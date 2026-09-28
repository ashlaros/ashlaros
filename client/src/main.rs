//! The native client.
//!
//! Renders and reads keys. It does not simulate anything: every rule
//! lives in `ashlaros-games`, which the worker's verifier runs as wasm
//! and this links as an rlib. A run played here and a run played in the
//! browser are the same run, scored the same way, and `ci/cross-target`
//! is what keeps that true.
//!
//! Music is out of scope here: it is rendered by `docs/game/music.js` on
//! the web page, and this client has nowhere equivalent to synthesize a
//! multi-minute loop without carrying that renderer over. The cue set
//! plays in full; only the background track does not.

mod audio;
mod courses_view;
mod effects;
mod palette;
mod quarry_view;
mod rng;

use ashlaros_games::Event;
use raylib::prelude::*;

use audio::Audio;
use courses_view::CoursesRun;
use palette::{ACCENT, BG, FG};
use quarry_view::QuarryRun;

const TICK_HZ: f32 = 60.0;

enum Screen {
    Menu,
    Courses(CoursesRun, Submission),
    Quarry(QuarryRun, Submission),
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
    gameover_played: bool,
}

impl Submission {
    fn new() -> Self {
        Self {
            initials: [b'A'; 3],
            cursor: 0,
            status: None,
            sent: false,
            gameover_played: false,
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

/// Drive the three-initial entry and the submit key.
///
/// Shared by both games because the rules it implements are about the
/// board rather than the game - the same reason scores.js keeps the day,
/// the seed and the one-attempt rule outside the per-game modules.
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

/// The window fits whichever game needs the most room - Courses' hold
/// and next-three sidebar is the wider requirement of the two.
fn window_size() -> (i32, i32) {
    (
        courses_view::WINDOW_W.max(quarry_view::WINDOW_W).max(480),
        courses_view::WINDOW_H.max(quarry_view::WINDOW_H).max(520),
    )
}

fn main() {
    let (window_w, window_h) = window_size();
    let (mut handle, thread) = raylib::init()
        .size(window_w, window_h)
        .title("AshlarOS Arcade")
        .vsync()
        .build();
    handle.set_target_fps(60);
    // Esc returns to the menu the way the on-screen text promises, rather
    // than raylib's default of closing the window outright - quitting is
    // still there, just at the window's own close button.
    handle.set_exit_key(None);

    // A device that fails to open is a silent game, never a panic or a
    // refusal to start: a machine with no sound card still plays.
    let device = RaylibAudio::init_audio_device().ok();
    let mut audio = Audio::load(device.as_ref(), &audio::audio_dir());

    let day = today();
    let mut screen = Screen::Menu;
    let mut accumulator = 0.0f32;
    let mut rng = rng::Rng::new(0x5eed_1234);

    while !handle.window_should_close() {
        let dt = handle.get_frame_time();
        accumulator += dt;

        let entering_initials = match &screen {
            Screen::Courses(run, submission) => run.state.over && !submission.sent,
            Screen::Quarry(run, submission) => run.state.over && !submission.sent,
            Screen::Menu => false,
        };
        if !entering_initials && handle.is_key_pressed(KeyboardKey::KEY_M) {
            audio.toggle_mute();
        }

        match &mut screen {
            Screen::Menu => {
                if handle.is_key_pressed(KeyboardKey::KEY_ONE) {
                    let seed = ashlaros_games::seed_for("courses", &day);
                    let mut run = CoursesRun::new(seed, seed ^ 0x9e37_79b9);
                    run.start_fanfare(&audio);
                    screen = Screen::Courses(run, Submission::new());
                    accumulator = 0.0;
                } else if handle.is_key_pressed(KeyboardKey::KEY_TWO) {
                    let seed = ashlaros_games::seed_for("quarry", &day);
                    let mut run = QuarryRun::new(seed, seed ^ 0x9e37_79b9);
                    run.start_fanfare(&audio);
                    screen = Screen::Quarry(run, Submission::new());
                    accumulator = 0.0;
                }
            }
            Screen::Courses(run, submission) => {
                if !run.state.over {
                    run.input(&handle, &audio, &mut rng);
                }
                while accumulator >= 1.0 / TICK_HZ {
                    accumulator -= 1.0 / TICK_HZ;
                    if !run.state.over {
                        run.tick(&audio, &mut rng);
                    }
                }
                run.update_effects(dt);
                if run.state.over {
                    if !submission.gameover_played {
                        submission.gameover_played = true;
                        audio.play("gameover");
                    }
                    handle_submission(&handle, submission, "courses", &day, &run.events);
                }
                if handle.is_key_pressed(KeyboardKey::KEY_ESCAPE) {
                    screen = Screen::Menu;
                }
            }
            Screen::Quarry(run, submission) => {
                if !run.state.over {
                    run.input(&handle, &audio);
                }
                while accumulator >= 1.0 / TICK_HZ {
                    accumulator -= 1.0 / TICK_HZ;
                    if !run.state.over {
                        run.tick(&audio);
                    }
                }
                run.update_effects(dt);
                if run.state.over {
                    if !submission.gameover_played {
                        submission.gameover_played = true;
                        audio.play("gameover");
                    }
                    handle_submission(&handle, submission, "quarry", &day, &run.events);
                }
                if handle.is_key_pressed(KeyboardKey::KEY_ESCAPE) {
                    screen = Screen::Menu;
                }
            }
        }

        let mut d = handle.begin_drawing(&thread);
        d.clear_background(BG);
        match &mut screen {
            Screen::Menu => draw_menu(&mut d, &day, &audio),
            Screen::Courses(run, submission) => {
                run.draw(&mut d);
                if run.state.over {
                    draw_gameover(&mut d, run.state.score, submission);
                }
            }
            Screen::Quarry(run, submission) => {
                run.draw(&mut d);
                if run.state.over {
                    draw_gameover(&mut d, run.state.score, submission);
                }
            }
        }
    }
}

fn draw_menu(d: &mut RaylibDrawHandle, day: &str, audio: &Audio) {
    d.draw_text("ASHLAROS ARCADE", 40, 80, 30, FG);
    d.draw_text(day, 40, 120, 20, ACCENT);
    d.draw_text("1  Courses", 40, 220, 24, FG);
    d.draw_text("2  Quarry", 40, 260, 24, FG);
    d.draw_text("Esc  back to this menu", 40, 340, 16, ACCENT);
    d.draw_text("M  mute", 40, 364, 16, ACCENT);
    d.draw_text("A run ends with three initials and enter.", 40, 388, 16, ACCENT);
    if audio.muted() {
        d.draw_text("Muted.", 40, 412, 16, ACCENT);
    }
    d.draw_text(
        "The same seed as the web board, the same rules.",
        40,
        d.get_screen_height() - 30,
        14,
        ACCENT,
    );
}

fn draw_gameover(d: &mut RaylibDrawHandle, score: u32, submission: &Submission) {
    let cx = d.get_screen_width() / 2 - 90;
    let cy = d.get_screen_height() / 2 - 40;
    d.draw_text(&format!("game over  {score}"), cx, cy, 24, FG);
    draw_submission(d, submission, cx, cy + 36);
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

