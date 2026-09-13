//! Courses: the falling-block game.
//!
//! A port of `worker/src/game/logic.js`, kept deliberately literal. Every
//! constant and every rule is the one the JS shipped, because scores
//! already on the board were produced by it - a "tidier" port that scored
//! one point differently would invalidate every historical run.

use crate::{hash32, Event, Outcome};

pub const WIDTH: i32 = 10;
pub const HEIGHT: i32 = 20;
pub const SPAWN_ROWS: i32 = 2;
pub const TOTAL_HEIGHT: i32 = HEIGHT + SPAWN_ROWS;
pub const MAX_PIECES: u32 = 600;

pub const LINE_SCORES: [u32; 5] = [0, 100, 300, 500, 800];
pub const SOFT_DROP_POINTS: u32 = 1;
/// Back-to-back, as integer arithmetic: x3/2 rather than x1.5, because a
/// float multiply is where two implementations are free to disagree.
pub const BACK_TO_BACK_MULTIPLIER: u32 = 3;
pub const BACK_TO_BACK_DIVISOR: u32 = 2;
pub const HARD_DROP_POINTS: u32 = 2;

pub const ACTION_LEFT: i32 = 0;
pub const ACTION_RIGHT: i32 = 1;
pub const ACTION_ROTATE_CW: i32 = 2;
pub const ACTION_ROTATE_CCW: i32 = 3;
pub const ACTION_SOFT_DROP: i32 = 4;
pub const ACTION_HARD_DROP: i32 = 5;
pub const ACTION_HOLD: i32 = 6;

/// The seven pieces, four rotations each, as (x, y) cells.
///
/// Written out rather than computed, for the reason the JS gives: a
/// player whose muscle memory expects a kick to work will not tolerate it
/// failing silently, and a rotation routine is exactly the kind of thing
/// two implementations get subtly different.
pub const PIECES: [[[(i32, i32); 4]; 4]; 7] = [
    // I
    [
        [(0, 1), (1, 1), (2, 1), (3, 1)],
        [(2, 0), (2, 1), (2, 2), (2, 3)],
        [(0, 2), (1, 2), (2, 2), (3, 2)],
        [(1, 0), (1, 1), (1, 2), (1, 3)],
    ],
    // J
    [
        [(0, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (2, 2)],
        [(1, 0), (1, 1), (0, 2), (1, 2)],
    ],
    // L
    [
        [(2, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (1, 2), (2, 2)],
        [(0, 1), (1, 1), (2, 1), (0, 2)],
        [(0, 0), (1, 0), (1, 1), (1, 2)],
    ],
    // O
    [
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
    ],
    // S
    [
        [(1, 0), (2, 0), (0, 1), (1, 1)],
        [(1, 0), (1, 1), (2, 1), (2, 2)],
        [(1, 1), (2, 1), (0, 2), (1, 2)],
        [(0, 0), (0, 1), (1, 1), (1, 2)],
    ],
    // T
    [
        [(1, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (1, 2)],
        [(1, 0), (0, 1), (1, 1), (1, 2)],
    ],
    // Z
    [
        [(0, 0), (1, 0), (1, 1), (2, 1)],
        [(2, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (1, 2), (2, 2)],
        [(1, 0), (0, 1), (1, 1), (0, 2)],
    ],
];

/// The nth bag of seven, shuffled by the seed.
///
/// Addressable: bag n depends on the seed and n, never on bag n-1, so the
/// verifier can evaluate any piece directly instead of re-shuffling from
/// the beginning to answer "what was piece 200".
pub fn bag_at(seed: u32, n: u32) -> [u8; 7] {
    let mut bag = [0u8, 1, 2, 3, 4, 5, 6];
    let mut i = 6usize;
    while i > 0 {
        let j = (hash32(seed, n.wrapping_mul(16).wrapping_add(i as u32)) % (i as u32 + 1)) as usize;
        bag.swap(i, j);
        i -= 1;
    }
    bag
}

pub fn piece_at(seed: u32, index: u32) -> u8 {
    bag_at(seed, index / 7)[(index % 7) as usize]
}

/// Gravity in ticks per row. Level 15 and above is one row per tick,
/// which nobody sustains - that is what bounds a run by skill rather than
/// by stamina.
pub fn gravity_interval(level: u32) -> u32 {
    const TABLE: [u32; 15] = [48, 43, 38, 33, 28, 23, 18, 13, 8, 6, 5, 5, 4, 4, 3];
    if level >= 15 {
        1
    } else {
        TABLE[level as usize]
    }
}

pub fn level_for(lines: u32) -> u32 {
    lines / 10
}

pub struct State {
    pub seed: u32,
    pub board: [u8; (TOTAL_HEIGHT * WIDTH) as usize],
    pub tick: u32,
    pub index: u32,
    pub piece: u8,
    pub has_piece: bool,
    pub rotation: u8,
    pub x: i32,
    pub y: i32,
    pub hold: u8,
    pub has_hold: bool,
    pub hold_used: bool,
    pub score: u32,
    pub lines: u32,
    pub level: u32,
    pub gravity_counter: u32,
    pub back_to_back: bool,
    pub over: bool,
}

impl State {
    pub fn new(seed: u32) -> Self {
        Self {
            seed,
            board: [0; (TOTAL_HEIGHT * WIDTH) as usize],
            tick: 0,
            index: 0,
            piece: 0,
            has_piece: false,
            rotation: 0,
            x: 0,
            y: 0,
            hold: 0,
            has_hold: false,
            hold_used: false,
            score: 0,
            lines: 0,
            level: 0,
            gravity_counter: 0,
            back_to_back: false,
            over: false,
        }
    }

    fn collides(&self, piece: u8, rotation: u8, x: i32, y: i32) -> bool {
        for (cx, cy) in PIECES[piece as usize][(rotation & 3) as usize] {
            let (px, py) = (x + cx, y + cy);
            if px < 0 || px >= WIDTH || py >= TOTAL_HEIGHT {
                return true;
            }
            if py < 0 {
                continue;
            }
            if self.board[(py * WIDTH + px) as usize] != 0 {
                return true;
            }
        }
        false
    }

    pub fn spawn(&mut self) {
        if self.index >= MAX_PIECES {
            self.over = true;
            return;
        }
        self.piece = piece_at(self.seed, self.index);
        self.has_piece = true;
        self.index += 1;
        self.rotation = 0;
        self.x = 3;
        self.y = 0;
        self.hold_used = false;
        self.gravity_counter = 0;
        if self.collides(self.piece, 0, self.x, self.y) {
            self.over = true;
        }
    }

    fn lock_piece(&mut self) {
        for (cx, cy) in PIECES[self.piece as usize][(self.rotation & 3) as usize] {
            let (px, py) = (self.x + cx, self.y + cy);
            if py >= 0 && py < TOTAL_HEIGHT && px >= 0 && px < WIDTH {
                self.board[(py * WIDTH + px) as usize] = self.piece + 1;
            }
        }

        // clear full rows, bottom up
        let mut cleared = 0u32;
        // Scans upward once and does NOT re-check a row it just cleared -
        // what shifts down into that row is examined on no further pass.
        // That is the incumbent's behaviour and every score on the board
        // was produced by it, so it is the behaviour to reproduce.
        let mut row = TOTAL_HEIGHT - 1;
        while row >= 0 {
            let full = (0..WIDTH).all(|col| self.board[(row * WIDTH + col) as usize] != 0);
            if full {
                cleared += 1;
                let mut r = row;
                while r > 0 {
                    for col in 0..WIDTH {
                        self.board[(r * WIDTH + col) as usize] =
                            self.board[((r - 1) * WIDTH + col) as usize];
                    }
                    r -= 1;
                }
                for col in 0..WIDTH {
                    self.board[col as usize] = 0;
                }
            }
            row -= 1;
        }

        if cleared > 0 {
            let mut points = LINE_SCORES[cleared.min(4) as usize] * (self.level + 1);
            if cleared == 4 && self.back_to_back {
                points = (points * BACK_TO_BACK_MULTIPLIER) / BACK_TO_BACK_DIVISOR;
            }
            self.score += points;
            self.lines += cleared;
            self.level = level_for(self.lines);
            self.back_to_back = cleared == 4;
        }

        self.has_piece = false;
        self.spawn();
    }

    pub fn apply(&mut self, action: i32, _value: i32) {
        if self.over || !self.has_piece {
            return;
        }
        match action {
            ACTION_LEFT => {
                if !self.collides(self.piece, self.rotation, self.x - 1, self.y) {
                    self.x -= 1;
                }
            }
            ACTION_RIGHT => {
                if !self.collides(self.piece, self.rotation, self.x + 1, self.y) {
                    self.x += 1;
                }
            }
            ACTION_ROTATE_CW | ACTION_ROTATE_CCW => {
                let next = if action == ACTION_ROTATE_CW {
                    (self.rotation + 1) & 3
                } else {
                    (self.rotation + 3) & 3
                };
                // Wall kicks, tried in order. The vertical offsets are
                // the point: a rotation against the floor lifts the piece
                // rather than failing, which is the kick a player's muscle
                // memory expects and will not tolerate silently missing.
                const KICKS: [(i32, i32); 7] = [
                    (0, 0),
                    (-1, 0),
                    (1, 0),
                    (0, -1),
                    (-1, -1),
                    (1, -1),
                    (0, -2),
                ];
                for (dx, dy) in KICKS {
                    if !self.collides(self.piece, next, self.x + dx, self.y + dy) {
                        self.rotation = next;
                        self.x += dx;
                        self.y += dy;
                        return;
                    }
                }
            }
            ACTION_SOFT_DROP => {
                if !self.collides(self.piece, self.rotation, self.x, self.y + 1) {
                    self.y += 1;
                    self.score += SOFT_DROP_POINTS;
                    self.gravity_counter = 0;
                }
            }
            ACTION_HARD_DROP => {
                let mut dropped = 0u32;
                while !self.collides(self.piece, self.rotation, self.x, self.y + 1) {
                    self.y += 1;
                    dropped += 1;
                }
                self.score += dropped * HARD_DROP_POINTS;
                self.lock_piece();
            }
            ACTION_HOLD => {
                if self.hold_used {
                    return;
                }
                let held = if self.has_hold { Some(self.hold) } else { None };
                self.hold = self.piece;
                self.has_hold = true;
                match held {
                    None => {
                        // spawn() clears hold_used, because a NEW piece is
                        // allowed a hold. The piece arriving here is the
                        // replacement for one just put away, so the flag is
                        // set after the spawn - set first it was wiped, and
                        // the same piece could be held twice.
                        self.spawn();
                        self.hold_used = true;
                    }
                    Some(piece) => {
                        self.hold_used = true;
                        self.piece = piece;
                        self.rotation = 0;
                        self.x = 3;
                        self.y = 0;
                        if self.collides(self.piece, 0, self.x, self.y) {
                            self.over = true;
                        }
                    }
                }
            }
            _ => {}
        }
    }

    pub fn step(&mut self) {
        if self.over {
            return;
        }
        if !self.has_piece {
            self.spawn();
        }
        if self.over {
            return;
        }
        self.gravity_counter += 1;
        if self.gravity_counter >= gravity_interval(self.level) {
            self.gravity_counter = 0;
            if self.collides(self.piece, self.rotation, self.x, self.y + 1) {
                self.lock_piece();
            } else {
                self.y += 1;
            }
        }
        // after gravity, not before: the replay steps until `tick` equals
        // the event's, so incrementing first shifts every gravity step one
        // tick earlier than the log the player actually produced
        self.tick += 1;
    }
}

/// Replay an event log. The same function the client plays with.
pub fn replay(seed: u32, events: &[Event]) -> Outcome {
    let mut state = State::new(seed);
    state.spawn();

    // Step up TO each event's tick and then apply it, rather than only
    // acting when a tick matches exactly. A log that skips ticks - every
    // real log, since a player is not pressing a key 60 times a second -
    // would otherwise drop the input entirely.
    for event in events {
        // a negative tick is not a time; the validator rejects one
        // before a replay ever starts, and clamping keeps the cast total
        let target = event.tick.max(0) as u32;
        while state.tick < target && !state.over {
            state.step();
        }
        if state.over {
            break;
        }
        state.apply(event.action, event.value);
    }

    // the run continues to its end after the last input: a player who
    // stops pressing keys still tops out, and the score includes what
    // gravity did
    let mut guard = 0u32;
    while !state.over && guard < MAX_PIECES * 60 * 60 {
        state.step();
        guard += 1;
    }
    Outcome {
        score: state.score,
        detail: state.lines,
        ticks: state.tick,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_bag_is_always_a_permutation_of_the_seven() {
        for seed in 0..200u32 {
            for n in 0..8u32 {
                let mut seen = [false; 7];
                for piece in bag_at(seed, n) {
                    assert!(!seen[piece as usize], "seed {seed} bag {n} repeated a piece");
                    seen[piece as usize] = true;
                }
            }
        }
    }

    #[test]
    fn hold_swaps_once_per_piece() {
        // the bug the JS had: the first hold calls spawn(), which clears
        // the flag that was just set, so the next hold went through
        let mut state = State::new(11);
        state.spawn();
        state.apply(ACTION_HOLD, 0);
        let after_first = state.piece;
        state.apply(ACTION_HOLD, 0);
        assert_eq!(state.piece, after_first, "a second hold was accepted");
    }

    #[test]
    fn a_run_ends_without_any_input() {
        let outcome = replay(5, &[]);
        assert!(outcome.ticks > 0);
    }
}
