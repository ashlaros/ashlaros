//! Quarry: the block breaker.
//!
//! A port of `worker/src/game/quarry.js`, as literal as Courses and for
//! the same reason - scores already on the board were produced by it.
//!
//! Integers matter more here than anywhere else in the crate. This has
//! ball physics: a position and a velocity advanced every tick and
//! reflected off surfaces, which is exactly where two compilers would
//! drift if either used floats. Positions are sub-pixels at a power of
//! two, so every divide is a shift and nothing rounds.

use crate::{hash32, Event, Outcome};

pub const SUB: i32 = 16;
const fn px(n: i32) -> i32 {
    n * SUB
}

pub const FIELD_W: i32 = px(240);
pub const FIELD_H: i32 = px(320);

pub const PADDLE_W: i32 = px(40);
pub const PADDLE_H: i32 = px(4);
pub const PADDLE_Y: i32 = FIELD_H - px(16);
/// Faster than the ball, and that is a measurement: the balance harness
/// found every skill band losing inside nine seconds with a slower
/// paddle, because the ball crosses the field in fewer ticks than the
/// paddle needs to follow it.
pub const PADDLE_SPEED: i32 = px(7);

pub const BALL_R: i32 = px(3);
pub const BALL_SPEED: i32 = px(3);

pub const BRICK_W: i32 = px(24);
pub const BRICK_H: i32 = px(10);
pub const BRICK_COLS: i32 = 8;
pub const BRICK_ROWS: i32 = 4;
pub const BRICK_TOP: i32 = px(40);
pub const CELLS: usize = (BRICK_COLS * BRICK_ROWS) as usize;

pub const TICKS_PER_SECOND: u32 = 60;
pub const MAX_TICKS: u32 = 120 * TICKS_PER_SECOND;
pub const MAX_BALLS: usize = 5;
pub const MAX_CAPSULES: usize = 16;
pub const START_LIVES: i32 = 3;

pub const EMPTY: i8 = 0;
pub const SOLID: i8 = -1;
pub const BRICK_SCORES: [u32; 4] = [0, 50, 100, 200];

pub const ACTION_TARGET: i32 = 0;
pub const ACTION_LAUNCH: i32 = 1;

pub const CAPSULE_WIDEN: u8 = 0;
pub const CAPSULE_MULTI: u8 = 1;
pub const CAPSULE_SLOW: u8 = 2;
pub const CAPSULE_CATCH: u8 = 3;
const CAPSULE_KINDS: u32 = 4;
pub const CAPSULE_SPEED: i32 = px(1);
pub const CAPSULE_SCORE: u32 = 100;
/// One brick in three drops something. A rate, not a flourish: a single
/// ball cannot clear a wall in a bounded round, so multi-ball is what
/// makes one clearable.
const CAPSULE_CHANCE: u32 = 3;

#[derive(Clone, Copy, Default)]
pub struct Ball {
    pub x: i32,
    pub y: i32,
    pub vx: i32,
    pub vy: i32,
}

#[derive(Clone, Copy, Default)]
pub struct Capsule {
    pub x: i32,
    pub y: i32,
    pub kind: u8,
}

/// The wall for a level: designed rather than uniform, and seeded so
/// every player faces the same one on the same day.
pub fn wall_at(seed: u32, level: u32) -> [i8; CELLS] {
    let mut bricks = [0i8; CELLS];
    for row in 0..BRICK_ROWS {
        for col in 0..BRICK_COLS {
            let key = (level.wrapping_mul(256).wrapping_add(row as u32))
                .wrapping_mul(16)
                .wrapping_add(col as u32);
            let roll = hash32(seed, key) % 100;
            let tier = if roll < 8 + level * 2 {
                // never on the bottom row: a solid brick there can wall
                // off the only approach to what is above it
                if row < BRICK_ROWS - 2 {
                    SOLID
                } else {
                    1
                }
            } else if roll < 34 {
                // a third of the wall is gaps - the cavities that let a
                // ball through to work on the top rows
                EMPTY
            } else if row == 0 {
                3
            } else if row == 1 {
                2
            } else {
                1
            };
            bricks[(row * BRICK_COLS + col) as usize] = tier;
        }
    }
    bricks
}

pub struct State {
    pub seed: u32,
    pub tick: u32,
    pub level: u32,
    pub score: u32,
    pub lives: i32,
    pub bricks: [i8; CELLS],
    pub paddle_x: i32,
    pub paddle_w: i32,
    pub target: i32,
    pub balls: [Ball; MAX_BALLS],
    pub ball_count: usize,
    pub capsules: [Capsule; MAX_CAPSULES],
    pub capsule_count: usize,
    pub held: bool,
    pub catching: bool,
    pub slow: u32,
    pub over: bool,
    pub bricks_broken: u32,
}

impl State {
    pub fn new(seed: u32) -> Self {
        Self {
            seed,
            tick: 0,
            level: 0,
            score: 0,
            lives: START_LIVES,
            bricks: wall_at(seed, 0),
            paddle_x: (FIELD_W - PADDLE_W) >> 1,
            paddle_w: PADDLE_W,
            target: (FIELD_W - PADDLE_W) >> 1,
            balls: [Ball::default(); MAX_BALLS],
            ball_count: 0,
            capsules: [Capsule::default(); MAX_CAPSULES],
            capsule_count: 0,
            held: true,
            catching: false,
            slow: 0,
            over: false,
            bricks_broken: 0,
        }
    }

    fn spawn_ball(&mut self, vx: i32) {
        if self.ball_count >= MAX_BALLS {
            return;
        }
        self.balls[self.ball_count] = Ball {
            x: self.paddle_x + (self.paddle_w >> 1),
            y: PADDLE_Y - BALL_R,
            vx,
            vy: -BALL_SPEED,
        };
        self.ball_count += 1;
    }

    fn brick_at(x: i32, y: i32) -> i32 {
        if y < BRICK_TOP {
            return -1;
        }
        let row = (y - BRICK_TOP) / BRICK_H;
        let col = x / BRICK_W;
        if row < 0 || row >= BRICK_ROWS || col < 0 || col >= BRICK_COLS {
            return -1;
        }
        row * BRICK_COLS + col
    }

    fn drop_capsule(&mut self, index: i32) {
        if self.capsule_count >= MAX_CAPSULES {
            return;
        }
        // seeded on the brick, not on a counter: which bricks drop is a
        // property of the wall, so two players who break the same brick
        // get the same capsule whatever order they got there in
        if hash32(self.seed, 0x5eed_0000u32.wrapping_add(index as u32)) % CAPSULE_CHANCE != 0 {
            return;
        }
        let row = index / BRICK_COLS;
        let col = index % BRICK_COLS;
        self.capsules[self.capsule_count] = Capsule {
            x: col * BRICK_W + (BRICK_W >> 1),
            y: BRICK_TOP + row * BRICK_H + (BRICK_H >> 1),
            kind: (hash32(self.seed, 0xca95_0000u32.wrapping_add(index as u32)) % CAPSULE_KINDS)
                as u8,
        };
        self.capsule_count += 1;
    }

    fn hit_brick(&mut self, index: i32) {
        let tier = self.bricks[index as usize];
        if tier == EMPTY || tier == SOLID {
            return;
        }
        let left = tier - 1;
        self.bricks[index as usize] = left;
        if left == EMPTY {
            self.score += BRICK_SCORES[(tier as usize).min(BRICK_SCORES.len() - 1)];
            self.bricks_broken += 1;
            self.drop_capsule(index);
        } else {
            // a partial hit still scores, or a three-tier brick pays
            // nothing for the two hits that did the work
            self.score += 10;
        }
    }

    fn apply_capsule(&mut self, kind: u8) {
        self.score += CAPSULE_SCORE;
        match kind {
            CAPSULE_WIDEN => self.paddle_w = (self.paddle_w + px(8)).min(px(64)),
            CAPSULE_MULTI => {
                // every ball splits, not just the first: one plus one is a
                // slightly better single ball, where two plus two is the
                // pressure the genre is built on
                let existing = self.ball_count;
                for i in 0..existing {
                    if self.ball_count >= MAX_BALLS {
                        break;
                    }
                    let source = self.balls[i];
                    self.balls[self.ball_count] = Ball {
                        x: source.x,
                        y: source.y,
                        vx: -source.vx,
                        vy: source.vy,
                    };
                    self.ball_count += 1;
                }
            }
            CAPSULE_SLOW => self.slow = 10 * TICKS_PER_SECOND,
            _ => self.catching = true,
        }
    }

    pub fn apply(&mut self, action: i32, value: i32) {
        if self.over {
            return;
        }
        match action {
            ACTION_TARGET => {
                // clamped rather than trusted: a submission naming a
                // target off the field would drag the paddle somewhere
                // the game cannot put it
                self.target = value.max(0).min(FIELD_W - self.paddle_w);
            }
            ACTION_LAUNCH => {
                if self.held {
                    self.held = false;
                    self.spawn_ball(BALL_SPEED >> 1);
                }
            }
            _ => {}
        }
    }

    /// Reflect off the paddle. The centre must never return the ball
    /// straight up: a vertical return is a soft-lock and a stalling
    /// strategy.
    fn bounce(&mut self, index: usize) {
        let centre = self.paddle_x + (self.paddle_w >> 1);
        let offset = self.balls[index].x - centre;
        let mut vx = (offset * BALL_SPEED * 2) / (self.paddle_w >> 1);
        let floor = BALL_SPEED >> 2;
        if vx > -floor && vx < floor {
            vx = if offset < 0 { -floor } else { floor };
        }
        self.balls[index].vx = vx.max(-BALL_SPEED * 2).min(BALL_SPEED * 2);
        self.balls[index].vy = -BALL_SPEED;
        self.balls[index].y = PADDLE_Y - BALL_R;
    }

    fn step_ball(&mut self, index: usize) -> bool {
        let steps = if self.slow > 0 { 1 } else { 2 };
        for _ in 0..steps {
            self.balls[index].x += self.balls[index].vx;
            self.balls[index].y += self.balls[index].vy;

            if self.balls[index].x - BALL_R < 0 {
                self.balls[index].x = BALL_R;
                self.balls[index].vx = -self.balls[index].vx;
            } else if self.balls[index].x + BALL_R > FIELD_W {
                self.balls[index].x = FIELD_W - BALL_R;
                self.balls[index].vx = -self.balls[index].vx;
            }
            if self.balls[index].y - BALL_R < 0 {
                self.balls[index].y = BALL_R;
                self.balls[index].vy = -self.balls[index].vy;
            }

            let cell = Self::brick_at(self.balls[index].x, self.balls[index].y);
            if cell >= 0 && self.bricks[cell as usize] != EMPTY {
                self.hit_brick(cell);
                self.balls[index].vy = -self.balls[index].vy;
                self.balls[index].y += self.balls[index].vy;
            }

            let ball = self.balls[index];
            if ball.vy > 0
                && ball.y + BALL_R >= PADDLE_Y
                && ball.y - BALL_R <= PADDLE_Y + PADDLE_H
                && ball.x >= self.paddle_x
                && ball.x <= self.paddle_x + self.paddle_w
            {
                if self.catching {
                    self.held = true;
                    self.catching = false;
                    return true;
                }
                self.bounce(index);
            }
        }
        self.balls[index].y - BALL_R <= FIELD_H
    }

    fn step_capsules(&mut self) {
        let mut kept = 0usize;
        for i in 0..self.capsule_count {
            let mut capsule = self.capsules[i];
            capsule.y += CAPSULE_SPEED;
            let caught = capsule.y >= PADDLE_Y
                && capsule.y <= PADDLE_Y + PADDLE_H + CAPSULE_SPEED
                && capsule.x >= self.paddle_x
                && capsule.x <= self.paddle_x + self.paddle_w;
            if caught {
                self.apply_capsule(capsule.kind);
            } else if capsule.y < FIELD_H {
                self.capsules[kept] = capsule;
                kept += 1;
            }
        }
        self.capsule_count = kept;
    }

    pub fn cleared(&self) -> bool {
        self.bricks
            .iter()
            .all(|&tier| tier == EMPTY || tier == SOLID)
    }

    pub fn step(&mut self) {
        if self.over {
            return;
        }
        self.tick += 1;
        if self.slow > 0 {
            self.slow -= 1;
        }

        // The paddle closes on the target at a fixed speed. That is what
        // makes the replay verifiable: the client says where it aimed,
        // and the server works out where the paddle actually reached.
        let delta = self.target - self.paddle_x;
        if delta > PADDLE_SPEED {
            self.paddle_x += PADDLE_SPEED;
        } else if delta < -PADDLE_SPEED {
            self.paddle_x -= PADDLE_SPEED;
        } else {
            self.paddle_x = self.target;
        }
        self.paddle_x = self.paddle_x.max(0).min(FIELD_W - self.paddle_w);

        if self.held {
            self.step_capsules();
            if self.tick >= MAX_TICKS {
                self.over = true;
            }
            return;
        }

        let mut kept = 0usize;
        for i in 0..self.ball_count {
            let alive = self.step_ball(i);
            if alive && !self.held {
                self.balls[kept] = self.balls[i];
                kept += 1;
            }
        }
        self.ball_count = kept;

        self.step_capsules();

        if self.ball_count == 0 && !self.held {
            self.lives -= 1;
            // the paddle loses its widening with the life, or one good
            // run makes every later one easier
            self.paddle_w = PADDLE_W;
            self.catching = false;
            self.slow = 0;
            if self.lives <= 0 {
                self.over = true;
            } else {
                self.held = true;
            }
        }

        if self.cleared() {
            self.level += 1;
            self.score += 1000;
            self.bricks = wall_at(self.seed, self.level);
            self.ball_count = 0;
            self.capsule_count = 0;
            self.held = true;
            self.paddle_w = PADDLE_W;
        }

        if self.tick >= MAX_TICKS {
            self.over = true;
        }
    }
}

pub fn replay(seed: u32, events: &[Event]) -> Outcome {
    let mut state = State::new(seed);
    let mut index = 0usize;
    let mut guard = 0u32;
    while !state.over && guard < MAX_TICKS + 1 {
        guard += 1;
        while index < events.len() && events[index].tick.max(0) as u32 == state.tick {
            state.apply(events[index].action, events[index].value);
            index += 1;
        }
        state.step();
    }
    Outcome {
        score: state.score,
        detail: state.bricks_broken,
        ticks: state.tick,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_solid_brick_sits_on_the_bottom_row() {
        for level in 0..6u32 {
            let bricks = wall_at(7, level);
            for col in 0..BRICK_COLS {
                let index = ((BRICK_ROWS - 1) * BRICK_COLS + col) as usize;
                assert_ne!(bricks[index], SOLID, "solid on the bottom row of level {level}");
            }
        }
    }

    #[test]
    fn the_paddle_never_leaves_the_field() {
        let mut state = State::new(7);
        for target in [-99999, 99999, FIELD_W * 4] {
            state.apply(ACTION_TARGET, target);
            for _ in 0..200 {
                state.step();
            }
            assert!(state.paddle_x >= 0);
            assert!(state.paddle_x + state.paddle_w <= FIELD_W);
        }
    }

    #[test]
    fn a_run_ends_without_any_input() {
        let outcome = replay(5, &[]);
        assert!(outcome.ticks > 0);
    }
}
