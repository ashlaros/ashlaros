//! Courses: input, drawing, and juice for the falling-block game.
//!
//! Ported from `docs/game/play.js` and its `effects.js` calls. Nothing
//! here writes `courses::State` outside of `courses::State::apply` and
//! `step` - it reads the state, draws it, and turns keys into logged
//! actions exactly as the web page does.

use ashlaros_games::{courses, Event};
use raylib::prelude::*;

use crate::audio::Audio;
use crate::effects::Effects;
use crate::palette::{ACCENT, ARR_FRAMES, DAS_FRAMES, FG, PIECE_COLOURS};

const CELL: i32 = 28;
const BOARD_OX: i32 = 40;
const BOARD_OY: i32 = 50;
const SIDEBAR_OX: i32 = BOARD_OX + courses::WIDTH * CELL + 30;
const BOX_SIZE: i32 = 84;
const QUEUE_COUNT: u32 = 3;
const DANGER_ROWS: i32 = 4;
/// The window this view needs: the board, its sidebar, and a margin.
pub const WINDOW_W: i32 = SIDEBAR_OX + BOX_SIZE + 30;
pub const WINDOW_H: i32 = BOARD_OY + courses::HEIGHT * CELL + 60;

fn piece_colour(piece: u8) -> Color {
    PIECE_COLOURS[piece as usize % 7]
}

/// A little pitch variation on the cues that fire constantly, so holding
/// a key does not machine-gun one identical sample - the same reasoning
/// as the page's `detune()`.
fn detune(rng: &mut crate::rng::Rng) -> f32 {
    0.97 + rng.next_f32() * 0.06
}

/// Per-key autorepeat timing for held movement, since `is_key_pressed`
/// alone only fires once per physical press. `is_key_pressed_repeat`
/// exists on this raylib-rs but follows the OS's own key-repeat rate,
/// which is tuned for text entry rather than a ten-frame DAS; a per-key
/// counter gives Courses its own feel independent of the desktop's
/// settings.
#[derive(Default)]
struct Repeater {
    held_for: u32,
}

impl Repeater {
    /// True the frame this key should fire, given whether it is
    /// currently down: `DAS_FRAMES` delay before the first repeat, then
    /// an `ARR_FRAMES` repeat, so a held key moves at a steady rate
    /// instead of once per physical press.
    fn fire(&mut self, down: bool, just_pressed: bool) -> bool {
        if !down {
            self.held_for = 0;
            return false;
        }
        if just_pressed {
            self.held_for = 1;
            return true;
        }
        self.held_for += 1;
        if self.held_for <= DAS_FRAMES {
            return false;
        }
        (self.held_for - DAS_FRAMES).is_multiple_of(ARR_FRAMES)
    }
}

pub struct CoursesRun {
    pub state: courses::State,
    pub events: Vec<Event>,
    effects: Effects,
    left: Repeater,
    right: Repeater,
    down: Repeater,
    danger_armed: bool,
    last_lines: u32,
    last_level: u32,
    last_score: u32,
}

/// The falling piece as it was the instant before it locked, since
/// `lock_piece` rewrites the board in place and shifts whatever
/// survives it - afterwards there is no way to know where the piece was
/// or which rows went.
struct PieceSnapshot {
    piece: u8,
    rotation: u8,
    x: i32,
    y: i32,
    board: [u8; (courses::TOTAL_HEIGHT * courses::WIDTH) as usize],
    back_to_back: bool,
}

impl CoursesRun {
    pub fn new(seed: u32, effects_seed: u32) -> Self {
        let mut state = courses::State::new(seed);
        state.spawn();
        Self {
            state,
            events: Vec::new(),
            effects: Effects::new(effects_seed),
            left: Repeater::default(),
            right: Repeater::default(),
            down: Repeater::default(),
            danger_armed: true,
            last_lines: 0,
            last_level: 0,
            last_score: 0,
        }
    }

    /// How far the falling piece can go before it lands: a read-only
    /// mirror of the simulation's own collision check (`core/src/courses.rs`
    /// keeps it private), exactly like the page's `dropTarget()` calling
    /// the exported `collides()`.
    fn drop_target(&self) -> Option<i32> {
        if !self.state.has_piece {
            return None;
        }
        let mut y = self.state.y;
        while !collides(&self.state, self.state.piece, self.state.rotation, self.state.x, y + 1) {
            y += 1;
        }
        Some(y)
    }

    /// How high the settled stack reaches, in visible rows from the top.
    fn stack_top(&self) -> i32 {
        for row in 0..courses::HEIGHT {
            for col in 0..courses::WIDTH {
                if self.state.board[((row + courses::SPAWN_ROWS) * courses::WIDTH + col) as usize]
                    != 0
                {
                    return row;
                }
            }
        }
        courses::HEIGHT
    }

    fn check_danger(&mut self, audio: &Audio) {
        let dangerous = self.stack_top() < DANGER_ROWS;
        if dangerous && self.danger_armed {
            self.danger_armed = false;
            audio.play("warning");
        } else if !dangerous {
            self.danger_armed = true;
        }
    }

    /// A piece locked: the clear ladder and the popups, or the dull tick
    /// of a plain placement. `before` is the piece and board as they were
    /// the instant before the lock, since afterwards the board no longer
    /// shows where the lines were.
    fn after_lock(&mut self, audio: &Audio, rng: &mut crate::rng::Rng, before: &PieceSnapshot) {
        let cleared = self.state.lines - self.last_lines;
        let delta = self.state.score - self.last_score;
        self.last_lines = self.state.lines;
        self.last_score = self.state.score;
        if cleared > 0 {
            audio.play(&format!("clear-{}", cleared.min(4)));
            self.clear_effects(before, cleared, delta);
        } else {
            audio.play_pitched("lock", detune(rng));
        }
        if cleared == 4 && before.back_to_back {
            audio.play("backtoback");
        }
        if self.state.level > self.last_level {
            self.last_level = self.state.level;
            audio.play("levelup");
            self.effects.banner(format!("LEVEL {}", self.state.level));
        }
        self.check_danger(audio);
    }

    fn clear_effects(&mut self, before: &PieceSnapshot, cleared: u32, delta: u32) {
        // the piece is stitched onto the pre-lock board copy, which is
        // what the board looked like the instant before the clear
        let mut joined = before.board;
        for (cx, cy) in courses::PIECES[before.piece as usize][(before.rotation & 3) as usize] {
            let (px, py) = (before.x + cx, before.y + cy);
            if (0..courses::WIDTH).contains(&px) && (0..courses::TOTAL_HEIGHT).contains(&py) {
                joined[(py * courses::WIDTH + px) as usize] = before.piece + 1;
            }
        }

        self.effects.flash(0.2 + cleared as f32 * 0.07);
        self.effects.shake(2.0 + cleared as f32 * 1.5);
        for row in 0..courses::TOTAL_HEIGHT {
            let full = (0..courses::WIDTH)
                .all(|col| joined[(row * courses::WIDTH + col) as usize] != 0);
            if !full {
                continue;
            }
            let visible = row - courses::SPAWN_ROWS;
            if !(0..courses::HEIGHT).contains(&visible) {
                continue;
            }
            for col in 0..courses::WIDTH {
                let cell = joined[(row * courses::WIDTH + col) as usize];
                if cell == 0 {
                    continue;
                }
                self.effects.burst(
                    (BOARD_OX + (col * CELL) + CELL / 2) as f32,
                    (BOARD_OY + (visible * CELL) + CELL / 2) as f32,
                    piece_colour(cell - 1),
                    2,
                );
            }
        }
        let cx = (BOARD_OX + courses::WIDTH * CELL / 2) as f32;
        let board_h = (courses::HEIGHT * CELL) as f32;
        self.effects
            .popup(format!("+{delta}"), cx, BOARD_OY as f32 + board_h * 0.58, FG);
        if cleared >= 4 {
            let label = if before.back_to_back {
                "BACK-TO-BACK"
            } else {
                "TETRIS"
            };
            self.effects
                .popup(label, cx, BOARD_OY as f32 + board_h * 0.48, FG);
        }
    }

    /// What a hard drop left on the way down: the ghost already showed
    /// where it would land, so this streak is how far it fell.
    fn hard_drop_trail(&mut self, before: &PieceSnapshot, land_y: Option<i32>) {
        let Some(land_y) = land_y else { return };
        if land_y <= before.y {
            return;
        }
        let colour = piece_colour(before.piece);
        for (cx, cy) in courses::PIECES[before.piece as usize][(before.rotation & 3) as usize] {
            let px = (BOARD_OX + (before.x + cx) * CELL + 1) as f32;
            let y0 = (BOARD_OY + (before.y + cy - courses::SPAWN_ROWS) * CELL) as f32;
            let y1 = (BOARD_OY + (land_y + cy - courses::SPAWN_ROWS) * CELL) as f32;
            self.effects
                .streak(px, y0, (CELL - 2) as f32, y1 + (CELL - 2) as f32 - y0, colour);
        }
    }

    fn snapshot(&self) -> PieceSnapshot {
        PieceSnapshot {
            piece: self.state.piece,
            rotation: self.state.rotation,
            x: self.state.x,
            y: self.state.y,
            board: self.state.board,
            back_to_back: self.state.back_to_back,
        }
    }

    /// One action, logged and applied - only what the simulation actually
    /// accepted goes in the log, since an entry the server refuses costs
    /// the whole run.
    fn press(&mut self, action: i32, audio: &Audio, rng: &mut crate::rng::Rng) {
        if self.state.over {
            return;
        }
        self.events.push(Event {
            action,
            tick: self.state.tick as i32,
            value: 0,
        });
        let held_before = self.state.hold;
        let locked_before = self.state.index;
        let before = self.snapshot();
        let land_y = self.drop_target();
        let y_before = self.state.y;
        self.state.apply(action, 0);
        if action == courses::ACTION_HARD_DROP {
            audio.play("drop");
            self.effects.shake(5.0);
            self.hard_drop_trail(&before, land_y);
        } else if action == courses::ACTION_SOFT_DROP && self.state.y > y_before {
            audio.play_pitched("softdrop", detune(rng));
        } else if action == courses::ACTION_HOLD && self.state.hold != held_before {
            audio.play("hold");
        } else if action == courses::ACTION_LEFT || action == courses::ACTION_RIGHT {
            audio.play_pitched("move", detune(rng));
        } else if action == courses::ACTION_ROTATE_CW || action == courses::ACTION_ROTATE_CCW {
            audio.play_pitched("rotate", detune(rng));
        }
        if self.state.index != locked_before {
            self.after_lock(audio, rng, &before);
        }
    }

    pub fn input(&mut self, handle: &RaylibHandle, audio: &Audio, rng: &mut crate::rng::Rng) {
        if handle.is_key_pressed(KeyboardKey::KEY_UP) {
            self.press(courses::ACTION_ROTATE_CW, audio, rng);
        }
        if handle.is_key_pressed(KeyboardKey::KEY_X) {
            self.press(courses::ACTION_ROTATE_CW, audio, rng);
        }
        if handle.is_key_pressed(KeyboardKey::KEY_Z) {
            self.press(courses::ACTION_ROTATE_CCW, audio, rng);
        }
        if handle.is_key_pressed(KeyboardKey::KEY_SPACE) {
            self.press(courses::ACTION_HARD_DROP, audio, rng);
        }
        if handle.is_key_pressed(KeyboardKey::KEY_C) {
            self.press(courses::ACTION_HOLD, audio, rng);
        }
        if self.left.fire(
            handle.is_key_down(KeyboardKey::KEY_LEFT),
            handle.is_key_pressed(KeyboardKey::KEY_LEFT),
        ) {
            self.press(courses::ACTION_LEFT, audio, rng);
        }
        if self.right.fire(
            handle.is_key_down(KeyboardKey::KEY_RIGHT),
            handle.is_key_pressed(KeyboardKey::KEY_RIGHT),
        ) {
            self.press(courses::ACTION_RIGHT, audio, rng);
        }
        if self.down.fire(
            handle.is_key_down(KeyboardKey::KEY_DOWN),
            handle.is_key_pressed(KeyboardKey::KEY_DOWN),
        ) {
            self.press(courses::ACTION_SOFT_DROP, audio, rng);
        }
    }

    pub fn tick(&mut self, audio: &Audio, rng: &mut crate::rng::Rng) {
        let locked_before = self.state.index;
        let before = self.snapshot();
        self.state.step();
        if self.state.index != locked_before {
            self.after_lock(audio, rng, &before);
        }
    }

    pub fn update_effects(&mut self, dt: f32) {
        self.effects.update(dt);
    }

    pub fn start_fanfare(&mut self, audio: &Audio) {
        audio.play("start");
        self.danger_armed = true;
        self.effects.clear();
    }

    pub fn draw(&mut self, d: &mut RaylibDrawHandle) {
        d.draw_rectangle_lines(
            BOARD_OX - 2,
            BOARD_OY - 2,
            courses::WIDTH * CELL + 4,
            courses::HEIGHT * CELL + 4,
            ACCENT,
        );

        let (sx, sy) = self.effects.shake_offset();

        // only the visible rows: the two spawn rows above the board are
        // where a piece enters, and showing them would move the floor
        for row in courses::SPAWN_ROWS..courses::TOTAL_HEIGHT {
            for col in 0..courses::WIDTH {
                let cell = self.state.board[(row * courses::WIDTH + col) as usize];
                if cell != 0 {
                    d.draw_rectangle(
                        BOARD_OX + col * CELL + sx as i32,
                        BOARD_OY + (row - courses::SPAWN_ROWS) * CELL + sy as i32,
                        CELL - 1,
                        CELL - 1,
                        piece_colour(cell - 1),
                    );
                }
            }
        }

        if self.state.has_piece && !self.state.over {
            let cells = courses::PIECES[self.state.piece as usize][(self.state.rotation & 3) as usize];
            let colour = piece_colour(self.state.piece);
            let land = self.drop_target();

            // The landing preview, held faint so it reads as a marker
            // rather than a piece already down.
            if let Some(land) = land {
                if land != self.state.y {
                    for (cx, cy) in cells {
                        let y = land + cy - courses::SPAWN_ROWS;
                        if y >= 0 {
                            let ghost = Color::new(colour.r, colour.g, colour.b, 56);
                            d.draw_rectangle(
                                BOARD_OX + (self.state.x + cx) * CELL + sx as i32,
                                BOARD_OY + y * CELL + sy as i32,
                                CELL - 1,
                                CELL - 1,
                                ghost,
                            );
                        }
                    }
                }
            }

            // A piece sitting on the stack brightens as its lock
            // approaches, so the window the rules give it to nudge reads
            // as closing rather than as the game pausing.
            let heat = if courses::LOCK_DELAY > 0 {
                (self.state.lock_counter as f32 / courses::LOCK_DELAY as f32).min(1.0)
            } else {
                0.0
            };
            for (cx, cy) in cells {
                let x = self.state.x + cx;
                let y = self.state.y + cy - courses::SPAWN_ROWS;
                if y < 0 {
                    continue;
                }
                d.draw_rectangle(
                    BOARD_OX + x * CELL + sx as i32,
                    BOARD_OY + y * CELL + sy as i32,
                    CELL - 1,
                    CELL - 1,
                    colour,
                );
                if heat > 0.0 {
                    let bright = Color::new(255, 255, 255, (heat * 128.0) as u8);
                    d.draw_rectangle(
                        BOARD_OX + x * CELL + sx as i32,
                        BOARD_OY + y * CELL + sy as i32,
                        CELL - 1,
                        CELL - 1,
                        bright,
                    );
                }
            }
        }

        self.effects.draw(
            d,
            BOARD_OX,
            BOARD_OY,
            courses::WIDTH * CELL,
            courses::HEIGHT * CELL,
        );

        draw_piece_box(d, SIDEBAR_OX, BOARD_OY, "HOLD", if self.state.has_hold {
            Some(self.state.hold)
        } else {
            None
        });
        for k in 0..QUEUE_COUNT {
            let piece = courses::piece_at(self.state.seed, self.state.index + k);
            let label = if k == 0 { "NEXT" } else { "" };
            draw_piece_box(
                d,
                SIDEBAR_OX,
                BOARD_OY + BOX_SIZE + 16 + k as i32 * (BOX_SIZE + 8),
                label,
                Some(piece),
            );
        }

        d.draw_text(
            &format!("score {}", self.state.score),
            BOARD_OX,
            16,
            20,
            FG,
        );
        d.draw_text(
            &format!("lines {}  level {}", self.state.lines, self.state.level),
            BOARD_OX,
            BOARD_OY + courses::HEIGHT * CELL + 16,
            18,
            ACCENT,
        );
    }
}

/// One piece, centred in a labelled box: the hold and every queue slot
/// draw through this so the four read as one set of previews.
fn draw_piece_box(d: &mut RaylibDrawHandle, x: i32, y: i32, label: &str, piece: Option<u8>) {
    d.draw_rectangle_lines(x, y, BOX_SIZE, BOX_SIZE, ACCENT);
    if !label.is_empty() {
        d.draw_text(label, x, y - 18, 14, ACCENT);
    }
    let Some(piece) = piece else { return };
    let cells = courses::PIECES[piece as usize][0];
    let (mut min_x, mut max_x, mut min_y, mut max_y) = (i32::MAX, i32::MIN, i32::MAX, i32::MIN);
    for (cx, cy) in cells {
        min_x = min_x.min(cx);
        max_x = max_x.max(cx);
        min_y = min_y.min(cy);
        max_y = max_y.max(cy);
    }
    let size = 16;
    let ox = x + (BOX_SIZE - (max_x - min_x + 1) * size) / 2 - min_x * size;
    let oy = y + (BOX_SIZE - (max_y - min_y + 1) * size) / 2 - min_y * size;
    let colour = piece_colour(piece);
    for (cx, cy) in cells {
        d.draw_rectangle(ox + cx * size + 1, oy + cy * size + 1, size - 2, size - 2, colour);
    }
}


/// A read-only mirror of `courses::State`'s private collision check -
/// same cells table, same board, same rule - used only to preview where
/// a piece would land. It can never influence what the simulation does.
fn collides(state: &courses::State, piece: u8, rotation: u8, x: i32, y: i32) -> bool {
    for (cx, cy) in courses::PIECES[piece as usize][(rotation & 3) as usize] {
        let (px, py) = (x + cx, y + cy);
        if !(0..courses::WIDTH).contains(&px) || py >= courses::TOTAL_HEIGHT {
            return true;
        }
        if py < 0 {
            continue;
        }
        if state.board[(py * courses::WIDTH + px) as usize] != 0 {
            return true;
        }
    }
    false
}
