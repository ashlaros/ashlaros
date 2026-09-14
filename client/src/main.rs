//! The native client.
//!
//! Renders and reads keys. It does not simulate anything: every rule
//! lives in `ashlaros-games`, which the worker's verifier runs as wasm
//! and this links as an rlib. A run played here and a run played in the
//! browser are the same run, scored the same way, and `ci/cross-target`
//! is what keeps that true.
//!
//! Deliberately small. A launcher, two games, and the event log a
//! submission is made of.

use ashlaros_games::{courses, quarry, Event};
use raylib::prelude::*;

const WINDOW_W: i32 = 480;
const WINDOW_H: i32 = 720;
const TICK_HZ: f32 = 60.0;

/// The palette the rest of the distribution uses. Named here rather than
/// imported because a client that pulled in a theme crate to draw seven
/// rectangles would be carrying more configuration than program.
const BG: Color = Color::new(0x14, 0x1a, 0x1b, 255);
const FG: Color = Color::new(0xc9, 0xcc, 0xd1, 255);
const ACCENT: Color = Color::new(0x3a, 0x40, 0x43, 255);
const PIECE_COLOURS: [Color; 7] = [
    Color::new(0x4e, 0x9a, 0xa6, 255),
    Color::new(0x5a, 0x7d, 0xa8, 255),
    Color::new(0xa8, 0x7d, 0x5a, 255),
    Color::new(0xa6, 0x9a, 0x4e, 255),
    Color::new(0x6f, 0xa6, 0x4e, 255),
    Color::new(0x8a, 0x6f, 0xa6, 255),
    Color::new(0xa6, 0x5a, 0x5a, 255),
];

enum Screen {
    Menu,
    Courses(CoursesRun),
    Quarry(QuarryRun),
}

/// Where a finished run goes, and what happened to it.
///
/// Three initials and nothing else, like the page: the board stores a
/// score and a seed, never a person.
struct Submission {
    initials: [u8; 3],
    cursor: usize,
    status: Option<String>,
    sent: bool,
}

impl Submission {
    fn new() -> Self {
        Self {
            initials: [b'A'; 3],
            cursor: 0,
            status: None,
            sent: false,
        }
    }

    fn text(&self) -> String {
        String::from_utf8_lossy(&self.initials).into_owned()
    }
}

/// The host the board lives on. Overridable so a run can be pointed at a
/// local worker while developing, which is also how this was tested.
fn endpoint() -> String {
    std::env::var("ASHLAROS_GAME_HOST")
        .unwrap_or_else(|_| "https://ashlaros.download".into())
}

/// POST the run, and return what the server said about it.
///
/// curl rather than an HTTP crate: this binary links raylib and a
/// simulation, and pulling in a TLS stack plus its dependency tree to
/// send one request a day would be more machinery than program. curl is
/// in `base`, so it is on every machine this package can be installed on.
///
/// No score is sent. The server replays the events against its own seed
/// and discards any number the client reports - which is the whole design
/// (R3.2), and means this cannot lie about a run even if it wanted to.
fn submit(game: &str, day: &str, player: &str, events: &[Event]) -> String {
    let log: Vec<String> = events
        .iter()
        .map(|e| {
            if game == "quarry" {
                format!("[{},{},{}]", e.action, e.tick, e.value)
            } else {
                format!("[{},{}]", e.action, e.tick)
            }
        })
        .collect();
    let body = format!(
        r#"{{"game":"{game}","day":"{day}","player":"{player}","events":[{}]}}"#,
        log.join(",")
    );

    let output = std::process::Command::new("curl")
        .arg("--silent")
        .arg("--show-error")
        .arg("--max-time")
        .arg("20")
        .arg("-H")
        .arg("content-type: application/json")
        .arg("--data-binary")
        .arg("@-")
        .arg(format!("{}/game/score", endpoint()))
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .and_then(|mut child| {
            use std::io::Write;
            child
                .stdin
                .take()
                .expect("stdin was piped")
                .write_all(body.as_bytes())?;
            child.wait_with_output()
        });

    let output = match output {
        Ok(output) => output,
        // a machine with no network is the ordinary case, not an error
        // worth a stack trace on a game over screen
        Err(error) => return format!("could not submit: {error}"),
    };

    let response = String::from_utf8_lossy(&output.stdout);
    // The response is small and its shape is fixed, so this reads the two
    // fields it needs rather than linking a JSON parser for them.
    if let Some(score) = field(&response, "\"score\":") {
        if response.contains("\"recorded\":true") {
            return format!("recorded {score}");
        }
    }
    if let Some(reason) = quoted(&response, "\"reason\":\"") {
        return reason;
    }
    if let Some(error) = quoted(&response, "\"error\":\"") {
        return error;
    }
    if response.trim().is_empty() {
        return "no answer from the board".into();
    }
    response.trim().chars().take(60).collect()
}

/// The number following a key in the response, if it is there.
fn field(haystack: &str, key: &str) -> Option<String> {
    let rest = haystack.split(key).nth(1)?;
    let digits: String = rest
        .chars()
        .take_while(|c| c.is_ascii_digit())
        .collect();
    (!digits.is_empty()).then_some(digits)
}

/// The string following a key in the response, if it is there.
fn quoted(haystack: &str, key: &str) -> Option<String> {
    let rest = haystack.split(key).nth(1)?;
    Some(rest.split('"').next()?.to_string())
}

struct CoursesRun {
    state: courses::State,
    events: Vec<Event>,
    submission: Submission,
}

struct QuarryRun {
    state: quarry::State,
    events: Vec<Event>,
    submission: Submission,
    /// Where the mouse last put the paddle, in sub-pixels. Recorded only
    /// when it changes: the log is edges, not a sample per tick, or a
    /// two-minute run would be fourteen thousand numbers.
    last_target: i32,
}

/// Drive the three-initial entry and the submit key.
///
/// Shared by both games because the rules it implements are about the
/// board rather than the game - the same reason scores.js keeps the day,
/// the seed and the one-attempt rule outside the per-game modules.
///
/// Returns true when a run was just sent, so the caller can stop offering
/// to send it again.
fn handle_submission(
    handle: &RaylibHandle,
    submission: &mut Submission,
    game: &str,
    day: &str,
    events: &[Event],
) {
    if submission.sent {
        return;
    }

    for (key, letter) in [
        (KeyboardKey::KEY_A, b'A'),
        (KeyboardKey::KEY_B, b'B'),
        (KeyboardKey::KEY_C, b'C'),
        (KeyboardKey::KEY_D, b'D'),
        (KeyboardKey::KEY_E, b'E'),
        (KeyboardKey::KEY_F, b'F'),
        (KeyboardKey::KEY_G, b'G'),
        (KeyboardKey::KEY_H, b'H'),
        (KeyboardKey::KEY_I, b'I'),
        (KeyboardKey::KEY_J, b'J'),
        (KeyboardKey::KEY_K, b'K'),
        (KeyboardKey::KEY_L, b'L'),
        (KeyboardKey::KEY_M, b'M'),
        (KeyboardKey::KEY_N, b'N'),
        (KeyboardKey::KEY_O, b'O'),
        (KeyboardKey::KEY_P, b'P'),
        (KeyboardKey::KEY_Q, b'Q'),
        (KeyboardKey::KEY_R, b'R'),
        (KeyboardKey::KEY_S, b'S'),
        (KeyboardKey::KEY_T, b'T'),
        (KeyboardKey::KEY_U, b'U'),
        (KeyboardKey::KEY_V, b'V'),
        (KeyboardKey::KEY_W, b'W'),
        (KeyboardKey::KEY_X, b'X'),
        (KeyboardKey::KEY_Y, b'Y'),
        (KeyboardKey::KEY_Z, b'Z'),
    ] {
        if handle.is_key_pressed(key) {
            submission.initials[submission.cursor] = letter;
            submission.cursor = (submission.cursor + 1) % 3;
        }
    }
    if handle.is_key_pressed(KeyboardKey::KEY_BACKSPACE) {
        submission.cursor = (submission.cursor + 2) % 3;
        submission.initials[submission.cursor] = b'A';
    }

    if handle.is_key_pressed(KeyboardKey::KEY_ENTER) {
        submission.status = Some(submit(game, day, &submission.text(), events));
        // one attempt per seed is the server's rule; not offering to send
        // twice is this side agreeing with it rather than discovering it
        submission.sent = true;
    }
}

/// Today, as the server derives it. The seed follows from this, so a
/// client whose clock disagrees plays a different board and its
/// submission is refused - which is the right failure, since the
/// alternative is silently scoring it against the wrong wall.
fn today() -> String {
    // Days since the epoch, converted by the civil-from-days algorithm.
    // No date crate: this is the only date arithmetic in the binary.
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let days = (secs / 86400) as i64;

    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!("{y:04}-{m:02}-{d:02}")
}

fn main() {
    let (mut handle, thread) = raylib::init()
        .size(WINDOW_W, WINDOW_H)
        .title("AshlarOS Arcade")
        .vsync()
        .build();
    handle.set_target_fps(60);

    let day = today();
    let mut screen = Screen::Menu;
    let mut accumulator = 0.0f32;

    while !handle.window_should_close() {
        accumulator += handle.get_frame_time();

        match &mut screen {
            Screen::Menu => {
                if handle.is_key_pressed(KeyboardKey::KEY_ONE) {
                    let seed = ashlaros_games::seed_for("courses", &day);
                    let mut state = courses::State::new(seed);
                    state.spawn();
                    screen = Screen::Courses(CoursesRun {
                        state,
                        events: Vec::new(),
                        submission: Submission::new(),
                    });
                    accumulator = 0.0;
                } else if handle.is_key_pressed(KeyboardKey::KEY_TWO) {
                    let seed = ashlaros_games::seed_for("quarry", &day);
                    screen = Screen::Quarry(QuarryRun {
                        // seeded from the state's own target rather than
                        // a sentinel: the threshold below is a distance,
                        // so starting from -1 would mean the first small
                        // move near the left wall is never logged
                        last_target: quarry::State::new(seed).target,
                        state: quarry::State::new(seed),
                        events: Vec::new(),
                        submission: Submission::new(),
                    });
                    accumulator = 0.0;
                }
            }
            Screen::Courses(run) => {
                for (key, action) in [
                    (KeyboardKey::KEY_LEFT, courses::ACTION_LEFT),
                    (KeyboardKey::KEY_RIGHT, courses::ACTION_RIGHT),
                    (KeyboardKey::KEY_UP, courses::ACTION_ROTATE_CW),
                    (KeyboardKey::KEY_Z, courses::ACTION_ROTATE_CCW),
                    (KeyboardKey::KEY_DOWN, courses::ACTION_SOFT_DROP),
                    (KeyboardKey::KEY_SPACE, courses::ACTION_HARD_DROP),
                    (KeyboardKey::KEY_C, courses::ACTION_HOLD),
                ] {
                    if handle.is_key_pressed(key) && !run.state.over {
                        run.events.push(Event {
                            action,
                            tick: run.state.tick as i32,
                            value: 0,
                        });
                        run.state.apply(action, 0);
                    }
                }
                while accumulator >= 1.0 / TICK_HZ {
                    accumulator -= 1.0 / TICK_HZ;
                    run.state.step();
                }
                if run.state.over {
                    handle_submission(
                        &handle,
                        &mut run.submission,
                        "courses",
                        &day,
                        &run.events,
                    );
                }
                if handle.is_key_pressed(KeyboardKey::KEY_ESCAPE) {
                    screen = Screen::Menu;
                }
            }
            Screen::Quarry(run) => {
                let mouse = handle.get_mouse_x();
                let target = (mouse - 60).max(0) * quarry::SUB;
                // Only when the aim has moved far enough to be worth an
                // event. The page does the same (quarry-play.js:161) and
                // for a hard reason: quarry's log is capped at 4000
                // events, and logging every pixel of mouse travel spends
                // that in under a minute - the server then refuses an
                // honest run with "too many events". Measured: a scripted
                // run that logged every change was rejected; the same run
                // with this threshold is accepted.
                const SAMPLE: i32 = quarry::FIELD_W / 40;
                if (target - run.last_target).abs() >= SAMPLE && !run.state.over {
                    run.events.push(Event {
                        action: quarry::ACTION_TARGET,
                        tick: run.state.tick as i32,
                        value: target,
                    });
                    run.state.apply(quarry::ACTION_TARGET, target);
                    run.last_target = target;
                }
                if handle.is_key_pressed(KeyboardKey::KEY_SPACE) && !run.state.over {
                    run.events.push(Event {
                        action: quarry::ACTION_LAUNCH,
                        tick: run.state.tick as i32,
                        value: 0,
                    });
                    run.state.apply(quarry::ACTION_LAUNCH, 0);
                }
                while accumulator >= 1.0 / TICK_HZ {
                    accumulator -= 1.0 / TICK_HZ;
                    run.state.step();
                }
                if run.state.over {
                    handle_submission(
                        &handle,
                        &mut run.submission,
                        "quarry",
                        &day,
                        &run.events,
                    );
                }
                if handle.is_key_pressed(KeyboardKey::KEY_ESCAPE) {
                    screen = Screen::Menu;
                }
            }
        }

        let mut d = handle.begin_drawing(&thread);
        d.clear_background(BG);
        match &screen {
            Screen::Menu => draw_menu(&mut d, &day),
            Screen::Courses(run) => draw_courses(&mut d, run),
            Screen::Quarry(run) => draw_quarry(&mut d, run),
        }
    }
}

fn draw_menu(d: &mut RaylibDrawHandle, day: &str) {
    d.draw_text("ASHLAROS ARCADE", 40, 80, 30, FG);
    d.draw_text(day, 40, 120, 20, ACCENT);
    d.draw_text("1  Courses", 40, 220, 24, FG);
    d.draw_text("2  Quarry", 40, 260, 24, FG);
    d.draw_text("Esc  back to this menu", 40, 340, 16, ACCENT);
    d.draw_text("A run ends with three initials and enter.", 40, 370, 16, ACCENT);
    d.draw_text(
        "The same seed as the web board, the same rules.",
        40,
        WINDOW_H - 60,
        14,
        ACCENT,
    );
}

fn draw_courses(d: &mut RaylibDrawHandle, run: &CoursesRun) {
    const CELL: i32 = 28;
    let ox = 60;
    let oy = 60;

    d.draw_rectangle_lines(
        ox - 2,
        oy - 2,
        courses::WIDTH * CELL + 4,
        courses::HEIGHT * CELL + 4,
        ACCENT,
    );

    // only the visible rows: the two spawn rows above the board are where
    // a piece enters, and showing them would move the floor
    for row in courses::SPAWN_ROWS..courses::TOTAL_HEIGHT {
        for col in 0..courses::WIDTH {
            let cell = run.state.board[(row * courses::WIDTH + col) as usize];
            if cell != 0 {
                d.draw_rectangle(
                    ox + col * CELL,
                    oy + (row - courses::SPAWN_ROWS) * CELL,
                    CELL - 1,
                    CELL - 1,
                    PIECE_COLOURS[(cell - 1) as usize % 7],
                );
            }
        }
    }

    if run.state.has_piece && !run.state.over {
        let cells = courses::PIECES[run.state.piece as usize][(run.state.rotation & 3) as usize];
        for (cx, cy) in cells {
            let (x, y) = (run.state.x + cx, run.state.y + cy - courses::SPAWN_ROWS);
            if y >= 0 {
                d.draw_rectangle(
                    ox + x * CELL,
                    oy + y * CELL,
                    CELL - 1,
                    CELL - 1,
                    PIECE_COLOURS[run.state.piece as usize],
                );
            }
        }
    }

    d.draw_text(&format!("score {}", run.state.score), ox, 20, 20, FG);
    d.draw_text(
        &format!("lines {}  level {}", run.state.lines, run.state.level),
        ox,
        oy + courses::HEIGHT * CELL + 16,
        18,
        ACCENT,
    );
    if run.state.over {
        d.draw_text("game over", ox, oy + courses::HEIGHT * CELL / 2, 28, FG);
        draw_submission(d, &run.submission, ox, oy + courses::HEIGHT * CELL / 2 + 40);
    }
}

/// The entry prompt and whatever the board said back.
fn draw_submission(d: &mut RaylibDrawHandle, submission: &Submission, x: i32, y: i32) {
    if let Some(status) = &submission.status {
        d.draw_text(status, x, y, 18, FG);
        return;
    }
    d.draw_text(&format!("initials  {}", submission.text()), x, y, 20, FG);
    // the caret sits under the letter the next keypress replaces
    d.draw_text(
        "^",
        x + 9 * 11 + submission.cursor as i32 * 11,
        y + 20,
        20,
        ACCENT,
    );
    d.draw_text("A-Z to type, backspace, enter to submit", x, y + 44, 14, ACCENT);
}

fn draw_quarry(d: &mut RaylibDrawHandle, run: &QuarryRun) {
    let ox = 60;
    let oy = 60;
    // sub-pixels to pixels: a shift, because SUB is a power of two and
    // the simulation never has a fractional position to round
    let to_px = |n: i32| n / quarry::SUB;

    d.draw_rectangle_lines(
        ox - 2,
        oy - 2,
        to_px(quarry::FIELD_W) + 4,
        to_px(quarry::FIELD_H) + 4,
        ACCENT,
    );

    for row in 0..quarry::BRICK_ROWS {
        for col in 0..quarry::BRICK_COLS {
            let tier = run.state.bricks[(row * quarry::BRICK_COLS + col) as usize];
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

    d.draw_rectangle(
        ox + to_px(run.state.paddle_x),
        oy + to_px(quarry::PADDLE_Y),
        to_px(run.state.paddle_w),
        to_px(quarry::PADDLE_H).max(3),
        FG,
    );

    for i in 0..run.state.ball_count {
        let ball = run.state.balls[i];
        d.draw_circle(
            ox + to_px(ball.x),
            oy + to_px(ball.y),
            to_px(quarry::BALL_R) as f32,
            FG,
        );
    }

    for i in 0..run.state.capsule_count {
        let capsule = run.state.capsules[i];
        d.draw_rectangle(
            ox + to_px(capsule.x) - 5,
            oy + to_px(capsule.y) - 3,
            10,
            6,
            PIECE_COLOURS[(capsule.kind as usize) % 7],
        );
    }

    d.draw_text(&format!("score {}", run.state.score), ox, 20, 20, FG);
    d.draw_text(
        &format!("lives {}  bricks {}", run.state.lives, run.state.bricks_broken),
        ox,
        oy + to_px(quarry::FIELD_H) + 16,
        18,
        ACCENT,
    );
    if run.state.held {
        d.draw_text(
            "space to launch",
            ox,
            oy + to_px(quarry::FIELD_H) + 40,
            16,
            ACCENT,
        );
    }
    if run.state.over {
        d.draw_text("game over", ox, oy + to_px(quarry::FIELD_H) / 2, 28, FG);
        draw_submission(d, &run.submission, ox, oy + to_px(quarry::FIELD_H) / 2 + 40);
    }
}
