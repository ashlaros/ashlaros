//! Quarry: input, drawing, and juice for the block breaker.
//!
//! Ported from `docs/game/quarry-play.js` and its `effects.js` calls.
//! Nothing here writes `quarry::State` outside of `quarry::State::apply`
//! and `step` - it reads the state, draws it, and turns keys and mouse
//! moves into logged actions exactly as the web page does.

use ashlaros_games::{quarry, Event};
use raylib::prelude::*;

use crate::audio::Audio;
use crate::effects::Effects;
use crate::palette::{ACCENT, FG, PIECE_COLOURS};

const OX: i32 = 40;
const OY: i32 = 50;
/// how far the aim must move before it is worth an event: the same
/// fraction of the field the web page samples at
const SAMPLE: i32 = quarry::FIELD_W / 40;

pub const WINDOW_W: i32 = OX + quarry::FIELD_W / quarry::SUB + OX;
pub const WINDOW_H: i32 = OY + quarry::FIELD_H / quarry::SUB + 60;

fn to_px(n: i32) -> i32 {
    n / quarry::SUB
}

fn capsule_letter(kind: u8) -> &'static str {
    match kind {
        quarry::CAPSULE_WIDEN => "W",
        quarry::CAPSULE_MULTI => "M",
        quarry::CAPSULE_SLOW => "S",
        _ => "C",
    }
}

fn capsule_label(kind: u8) -> &'static str {
    match kind {
        quarry::CAPSULE_WIDEN => "WIDE",
        quarry::CAPSULE_MULTI => "MULTI",
        quarry::CAPSULE_SLOW => "SLOW",
        _ => "CATCH",
    }
}

/// The ball warms as it speeds up: white at the run's starting pace and
/// hot by the time it is out of control - the only hue against a stone
/// palette, and barely that.
fn ball_tint(t: f32) -> Color {
    Color::new(
        (238.0 + 17.0 * t) as u8,
        (238.0 - 10.0 * t) as u8,
        (238.0 - 49.0 * t) as u8,
        255,
    )
}

pub struct QuarryRun {
    pub state: quarry::State,
    pub events: Vec<Event>,
    effects: Effects,
    left_down: bool,
    right_down: bool,
    /// Whether either arrow key was steering last tick, so the moment
    /// both are released is caught and logged once - without this the
    /// paddle would coast toward the wall it was aimed at forever.
    was_steering: bool,
    last_target: i32,
    /// bricks broken without the paddle touching the ball in between: the
    /// same combo the page's pitch ladder climbs on
    combo: u32,
    paddle_squash: f32,
    wall_before: [i8; quarry::CELLS],
}

impl QuarryRun {
    pub fn new(seed: u32, effects_seed: u32) -> Self {
        let state = quarry::State::new(seed);
        Self {
            wall_before: state.bricks,
            last_target: state.target,
            state,
            events: Vec::new(),
            effects: Effects::new(effects_seed),
            left_down: false,
            right_down: false,
            was_steering: false,
            combo: 0,
            paddle_squash: 0.0,
        }
    }

    /// How far the ball is from its starting pace to its ceiling, 0..1 -
    /// everything that says "faster" reads this one number so the tint,
    /// the trail and the meter cannot describe three different speeds.
    fn heat(&self) -> f32 {
        let span = (quarry::BALL_SPEED_MAX - quarry::BALL_SPEED) as f32;
        if span <= 0.0 {
            return 0.0;
        }
        ((self.state.speed - quarry::BALL_SPEED) as f32 / span).clamp(0.0, 1.0)
    }

    fn emit(&mut self, audio: &Audio, action: i32, value: i32) {
        let held_before = self.state.held;
        self.events.push(Event {
            action,
            tick: self.state.tick as i32,
            value,
        });
        self.state.apply(action, value);
        if action == quarry::ACTION_LAUNCH && held_before && !self.state.held {
            audio.play("launch");
        }
    }

    /// Arrow-key aim: on press (or when the held direction changes) log
    /// one target at the field edge in that direction; on release, one
    /// target at wherever the paddle actually is, so it stops. The
    /// paddle's own `PADDLE_SPEED` cap is what turns two edge-events into
    /// the same motion continuous per-tick nudging would have produced,
    /// without paying a TARGET event for every one of those ticks - a
    /// held key logging 60 events/second would exhaust the server's
    /// event cap in under two minutes of ordinary steering.
    fn steer(&mut self, audio: &Audio) {
        let steering = self.left_down != self.right_down;
        let target = if self.left_down && !self.right_down {
            0
        } else if self.right_down && !self.left_down {
            quarry::FIELD_W - self.state.paddle_w
        } else if self.was_steering {
            self.state.paddle_x
        } else {
            return;
        };
        self.was_steering = steering;
        if (target - self.last_target).abs() >= SAMPLE {
            self.emit(audio, quarry::ACTION_TARGET, target);
            self.last_target = target;
        }
    }

    /// Once per frame: track which steering keys are held, let the mouse
    /// set the aim directly, and log a launch. The edge-triggered
    /// keyboard target happens in `tick`, alongside gravity.
    pub fn input(&mut self, handle: &RaylibHandle, audio: &Audio) {
        self.left_down = handle.is_key_down(KeyboardKey::KEY_LEFT);
        self.right_down = handle.is_key_down(KeyboardKey::KEY_RIGHT);

        // the mouse only logs when it actually moved, so it never fights
        // the keys by re-asserting the same position every frame
        let mouse_x = handle.get_mouse_x();
        if handle.get_mouse_delta().x != 0.0 && mouse_x >= OX && mouse_x <= OX + to_px(quarry::FIELD_W) {
            let target = ((mouse_x - OX) * quarry::SUB - self.state.paddle_w / 2)
                .max(0)
                .min(quarry::FIELD_W - self.state.paddle_w);
            if (target - self.last_target).abs() >= SAMPLE {
                self.emit(audio, quarry::ACTION_TARGET, target);
                self.last_target = target;
            }
        }

        if handle.is_key_pressed(KeyboardKey::KEY_SPACE) {
            self.emit(audio, quarry::ACTION_LAUNCH, 0);
        }
    }

    /// What the tick did, as sound and effect: read from what changed
    /// rather than the simulation announcing anything, exactly as
    /// `quarry-play.js`'s `announce()` does.
    fn announce(&mut self, audio: &Audio, before: &Before) {
        if self.state.speed > before.speed {
            audio.play("speedup");
        }

        if self.state.level > before.level {
            audio.play("levelclear");
            self.effects.banner(format!("LEVEL {}", self.state.level));
            return;
        }
        if self.state.lives < before.lives {
            audio.play("lost");
            self.effects.shake(9.0);
            return;
        }

        let caught = before.capsules[..before.capsule_count].iter().find(|c| {
            let y = c.y + quarry::CAPSULE_SPEED;
            y < quarry::FIELD_H
                && !self.state.capsules[..self.state.capsule_count]
                    .iter()
                    .any(|s| s.x == c.x && s.y == y && s.kind == c.kind)
        });
        if let Some(caught) = caught {
            let label = capsule_label(caught.kind);
            audio.play(if caught.kind == quarry::CAPSULE_MULTI {
                "multi"
            } else {
                "catch"
            });
            self.effects
                .popup(label, (OX + to_px(caught.x)) as f32, (OY + to_px(caught.y)) as f32, FG);
            if caught.kind == quarry::CAPSULE_MULTI {
                self.effects.shake(3.0);
            }
        }

        if self.state.bricks_broken > before.bricks_broken {
            let rung = self.broken_tier();
            self.combo += 1;
            let pitch = 2f32.powf(self.combo.min(12) as f32 / 12.0);
            audio.play_pitched(&format!("brick-{rung}"), pitch);
            self.brick_particles();
        } else if self.state.score > before.score && caught.is_none() {
            audio.play("brick-1");
        }

        if self.state.capsule_count > before.capsule_count {
            audio.play("capsule");
        }

        let bounced = (0..self.state.ball_count).any(|i| {
            before
                .velocities
                .get(i)
                .map(|&(_, vy)| vy > 0)
                .unwrap_or(false)
                && self.state.balls[i].vy < 0
        });
        if bounced {
            self.combo = 0;
            audio.play("paddle");
            self.paddle_squash = 1.0;
        }

        self.wall_sounds(audio, before);
    }

    /// Which rung of the ladder the strongest brick broken this tick was
    /// on, read from the wall as it was before the tick: a break takes
    /// the tier off, so afterwards there is nothing left to name it.
    fn broken_tier(&self) -> i8 {
        let mut rung = 1i8;
        for i in 0..quarry::CELLS {
            let was = self.wall_before[i];
            if was > rung && self.state.bricks[i] != was {
                rung = was;
            }
        }
        rung
    }

    fn brick_particles(&mut self) {
        for i in 0..quarry::CELLS {
            if self.wall_before[i] != quarry::EMPTY
                && self.wall_before[i] != quarry::SOLID
                && self.state.bricks[i] == quarry::EMPTY
            {
                let row = i as i32 / quarry::BRICK_COLS;
                let col = i as i32 % quarry::BRICK_COLS;
                let x = OX + to_px(col * quarry::BRICK_W + quarry::BRICK_W / 2);
                let y = OY + to_px(quarry::BRICK_TOP + row * quarry::BRICK_H + quarry::BRICK_H / 2);
                let colour = PIECE_COLOURS[(self.wall_before[i] as usize).min(6)];
                self.effects.burst(x as f32, y as f32, colour, 6);
            }
        }
    }

    /// The two sounds that are not about scoring: a wall/ceiling return
    /// is the point's rhythm and happens constantly, so it stays the
    /// quietest cue; an indestructible brick must not sound like a hit.
    fn wall_sounds(&mut self, audio: &Audio, before: &Before) {
        if self.state.ball_count != before.ball_count {
            return;
        }
        let scored = self.state.score != before.score;
        let band_top = quarry::BRICK_TOP - quarry::BALL_R;
        let band_bottom = quarry::BRICK_TOP + quarry::BRICK_ROWS * quarry::BRICK_H + quarry::BALL_R;
        let mut wall = false;
        let mut solid = false;
        for i in 0..self.state.ball_count {
            let ball = self.state.balls[i];
            let Some(&(vx, vy)) = before.velocities.get(i) else {
                continue;
            };
            if ball.vy.signum() != vy.signum() {
                if ball.y < quarry::BRICK_TOP {
                    wall = true;
                } else if !scored && ball.y > band_top && ball.y < band_bottom {
                    solid = true;
                }
            } else if ball.vx.signum() != vx.signum() {
                wall = true;
            }
        }
        if solid {
            audio.play("solid");
        } else if wall {
            audio.play("wall");
        }
    }

    pub fn tick(&mut self, audio: &Audio) {
        self.steer(audio);
        let mut velocities = [(0i32, 0i32); quarry::MAX_BALLS];
        for (slot, ball) in velocities.iter_mut().zip(&self.state.balls[..self.state.ball_count]) {
            *slot = (ball.vx, ball.vy);
        }
        let before = Before {
            score: self.state.score,
            bricks_broken: self.state.bricks_broken,
            lives: self.state.lives,
            level: self.state.level,
            ball_count: self.state.ball_count,
            capsule_count: self.state.capsule_count,
            capsules: self.state.capsules,
            speed: self.state.speed,
            velocities,
        };
        self.wall_before = self.state.bricks;
        self.state.step();
        self.announce(audio, &before);
    }

    pub fn update_effects(&mut self, dt: f32) {
        self.effects.update(dt);
        self.paddle_squash *= (-dt / 0.11).exp();
        if self.paddle_squash < 0.01 {
            self.paddle_squash = 0.0;
        }
        let warm = self.heat();
        let size = to_px(quarry::BALL_R) as f32 * (0.9 + warm * 0.6);
        let colour = ball_tint(warm);
        for i in 0..self.state.ball_count {
            let ball = self.state.balls[i];
            self.effects.trail(
                (OX + to_px(ball.x)) as f32,
                (OY + to_px(ball.y)) as f32,
                colour,
                size,
            );
        }
    }

    pub fn start_fanfare(&mut self, audio: &Audio) {
        self.effects.clear();
        self.combo = 0;
        self.paddle_squash = 0.0;
        self.last_target = self.state.target;
        self.emit(audio, quarry::ACTION_LAUNCH, 0);
    }

    pub fn draw(&mut self, d: &mut RaylibDrawHandle) {
        let field_w = to_px(quarry::FIELD_W);
        let field_h = to_px(quarry::FIELD_H);
        d.draw_rectangle_lines(OX - 2, OY - 2, field_w + 4, field_h + 4, ACCENT);

        let (sx, sy) = self.effects.shake_offset();
        let ox = OX + sx as i32;
        let oy = OY + sy as i32;

        for row in 0..quarry::BRICK_ROWS {
            for col in 0..quarry::BRICK_COLS {
                let tier = self.state.bricks[(row * quarry::BRICK_COLS + col) as usize];
                if tier == quarry::EMPTY {
                    continue;
                }
                let colour = if tier == quarry::SOLID {
                    ACCENT
                } else {
                    PIECE_COLOURS[(tier as usize).min(6)]
                };
                d.draw_rectangle(
                    ox + to_px(col * quarry::BRICK_W),
                    oy + to_px(quarry::BRICK_TOP + row * quarry::BRICK_H),
                    to_px(quarry::BRICK_W) - 2,
                    to_px(quarry::BRICK_H) - 2,
                    colour,
                );
            }
        }

        // the paddle squashes on contact: the one surface the player
        // owns, so it is also the one that gets to move
        let squash = self.paddle_squash;
        let pad_w = (to_px(self.state.paddle_w) as f32 * (1.0 + squash * 0.14)) as i32;
        let pad_h = (to_px(quarry::PADDLE_H).max(3) as f32 * (1.0 - squash * 0.35)) as i32;
        let pad_x = ox + to_px(self.state.paddle_x) - (pad_w - to_px(self.state.paddle_w)) / 2;
        let pad_y = oy + to_px(quarry::PADDLE_Y) + to_px(quarry::PADDLE_H).max(3) - pad_h;
        d.draw_rectangle(pad_x, pad_y, pad_w, pad_h, FG);
        if squash > 0.0 {
            let flash = Color::new(255, 255, 255, (squash * 0.45 * 255.0) as u8);
            d.draw_rectangle(pad_x, pad_y, pad_w, pad_h, flash);
        }

        let tint = ball_tint(self.heat());
        for i in 0..self.state.ball_count {
            let ball = self.state.balls[i];
            d.draw_circle(ox + to_px(ball.x), oy + to_px(ball.y), to_px(quarry::BALL_R) as f32, tint);
        }
        if self.state.held {
            let x = self.state.paddle_x + (self.state.paddle_w >> 1);
            d.draw_circle(
                ox + to_px(x),
                oy + to_px(quarry::PADDLE_Y - quarry::BALL_R),
                to_px(quarry::BALL_R) as f32,
                tint,
            );
        }

        for i in 0..self.state.capsule_count {
            let capsule = self.state.capsules[i];
            let cx = ox + to_px(capsule.x);
            let cy = oy + to_px(capsule.y);
            d.draw_rectangle(cx - 8, cy - 3, 16, 6, PIECE_COLOURS[(capsule.kind as usize) % 7]);
            d.draw_text(capsule_letter(capsule.kind), cx - 3, cy - 5, 10, Color::new(0x0d, 0x11, 0x12, 255));
        }

        self.effects.draw(d, OX, OY, field_w, field_h);

        d.draw_text(&format!("score {}", self.state.score), OX, 16, 20, FG);
        d.draw_text(
            &format!(
                "lives {}  bricks {}  level {}  ×{:.2}",
                self.state.lives.max(0),
                self.state.bricks_broken,
                self.state.level,
                self.state.speed as f32 / quarry::BALL_SPEED as f32,
            ),
            OX,
            OY + field_h + 16,
            18,
            ACCENT,
        );
        if self.state.held && !self.state.over {
            d.draw_text("space to launch", OX, OY + field_h + 40, 16, ACCENT);
        }
    }
}

struct Before {
    score: u32,
    bricks_broken: u32,
    lives: i32,
    level: u32,
    ball_count: usize,
    capsule_count: usize,
    capsules: [quarry::Capsule; quarry::MAX_CAPSULES],
    speed: i32,
    velocities: [(i32, i32); quarry::MAX_BALLS],
}
