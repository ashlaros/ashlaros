//! Play a run with the native crate and print the log as JSON, in the
//! shape the score endpoint accepts.
//!
//! This is how "the native client and the server agree" gets tested
//! against the live verifier rather than argued about: pipe the output
//! to `/game/score` and the recorded score must match the local one.

use ashlaros_games::{courses, quarry, Event};

fn main() {
    let mut args = std::env::args().skip(1);
    let game = args.next().unwrap_or_else(|| "courses".into());
    let day = args.next().unwrap_or_else(|| "2026-09-13".into());
    let player = args.next().unwrap_or_else(|| "RST".into());

    let seed = ashlaros_games::seed_for(&game, &day);
    let mut events: Vec<Event> = Vec::new();

    // A scripted player, not a random one: the point is a log the server
    // will accept and score identically, and randomness only makes a
    // disagreement harder to reproduce.
    let mut rng: u32 = 12345;
    let mut rand = |n: u32| {
        rng = rng.wrapping_mul(1103515245).wrapping_add(12345) & 0x7fff_ffff;
        rng % n
    };

    let outcome = if game == "quarry" {
        events.push(Event {
            action: quarry::ACTION_LAUNCH,
            tick: 0,
            value: 0,
        });
        let mut state = quarry::State::new(seed);
        let mut last = -1;
        while !state.over {
            // follow the lowest ball, which is what a player does
            let mut aim = state.paddle_x;
            let mut lowest = -1;
            for i in 0..state.ball_count {
                if state.balls[i].y > lowest {
                    lowest = state.balls[i].y;
                    aim = state.balls[i].x - (state.paddle_w / 2);
                }
            }
            let aim = aim.max(0).min(quarry::FIELD_W - state.paddle_w);
            if aim != last {
                let event = Event {
                    action: quarry::ACTION_TARGET,
                    tick: state.tick as i32,
                    value: aim,
                };
                // the same event the client would log, applied the same way
                state.apply(event.action, event.value);
                events.push(event);
                last = aim;
            }
            if state.held {
                let event = Event {
                    action: quarry::ACTION_LAUNCH,
                    tick: state.tick as i32,
                    value: 0,
                };
                state.apply(event.action, event.value);
                events.push(event);
            }
            state.step();
        }
        quarry::replay(seed, &events)
    } else {
        let mut state = courses::State::new(seed);
        state.spawn();
        while !state.over {
            if rand(6) == 0 {
                let action = match rand(4) {
                    0 => courses::ACTION_LEFT,
                    1 => courses::ACTION_RIGHT,
                    2 => courses::ACTION_ROTATE_CW,
                    _ => courses::ACTION_HARD_DROP,
                };
                let event = Event {
                    action,
                    tick: state.tick as i32,
                    value: 0,
                };
                state.apply(event.action, event.value);
                events.push(event);
            }
            state.step();
        }
        courses::replay(seed, &events)
    };

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

    eprintln!(
        "native: score={} detail={} ticks={} events={}",
        outcome.score,
        outcome.detail,
        outcome.ticks,
        events.len()
    );
    println!(
        r#"{{"game":"{game}","day":"{day}","player":"{player}","events":[{}]}}"#,
        log.join(",")
    );
}
