//! The two targets must agree, and this is what proves it.
//!
//! The worker runs this crate as `wasm32-unknown-unknown`; the native
//! client links it directly. A leaderboard where a native player's run
//! scores differently under the verifier is worse than no leaderboard -
//! it rejects honest runs and cannot tell them from forged ones.
//!
//! This test runs a corpus natively, writes the results next to the
//! wasm build, and `ci/cross-target.mjs` replays the same corpus through
//! the wasm module and diffs. Both halves are needed: this one alone
//! proves nothing about wasm, and that is the target most likely to
//! differ, since it is the one whose arithmetic is emulated.

use ashlaros_games::{courses, quarry, Event};

/// A deterministic corpus. Not random: a test that generates fresh cases
/// each run reports different failures to different people, and a
/// cross-target disagreement must be reproducible to be fixable.
fn corpus() -> Vec<(u32, u32, Vec<Event>)> {
    let mut cases = Vec::new();
    let mut state: u32 = 12345;
    let mut rand = |n: u32| {
        state = state.wrapping_mul(1103515245).wrapping_add(12345) & 0x7fff_ffff;
        state % n
    };

    for run in 0..40u32 {
        let seed = 2_948_530_700u32.wrapping_add(run.wrapping_mul(7919));
        let mut events = Vec::new();
        let mut tick = 0i32;
        for _ in 0..300 {
            tick += 1 + rand(8) as i32;
            events.push(Event {
                action: rand(7) as i32,
                tick,
                value: 0,
            });
        }
        cases.push((0, seed, events));
    }

    for run in 0..40u32 {
        let seed = 3_201_124_988u32.wrapping_add(run.wrapping_mul(7919));
        let mut events = vec![Event {
            action: quarry::ACTION_LAUNCH,
            tick: 0,
            value: 0,
        }];
        let mut tick = 0i32;
        for _ in 0..300 {
            tick += 1 + rand(20) as i32;
            events.push(Event {
                action: quarry::ACTION_TARGET,
                tick,
                value: rand((quarry::FIELD_W) as u32) as i32,
            });
        }
        cases.push((1, seed, events));
    }

    cases
}

#[test]
fn native_results_are_recorded_for_the_wasm_side_to_check() {
    let mut lines = Vec::new();
    for (game, seed, events) in corpus() {
        let outcome = if game == 0 {
            courses::replay(seed, &events)
        } else {
            quarry::replay(seed, &events)
        };
        lines.push(format!(
            "{game} {seed} {} {} {}",
            outcome.score, outcome.detail, outcome.ticks
        ));
    }

    // A run that scores nothing anywhere would pass a diff while proving
    // nothing, so the corpus has to actually play.
    let scoring = lines.iter().filter(|l| !l.contains(" 0 0 ")).count();
    assert!(scoring > 60, "corpus barely plays: {scoring} scoring runs");

    std::fs::write(
        concat!(env!("CARGO_MANIFEST_DIR"), "/target/native-results.txt"),
        lines.join("\n") + "\n",
    )
    .expect("write native results");
}
