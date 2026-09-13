//! The simulations both games run.
//!
//! One crate, compiled twice: `wasm32-unknown-unknown` for the worker's
//! verifier, and natively for the raylib client. That is what makes "one
//! implementation" true rather than aspirational - the same source, the
//! same arithmetic, and a test in CI that proves the two targets agree.
//!
//! Pure: no I/O, no timers, no renderer, no allocation beyond the state
//! itself. Everything here is an integer state transition. That purity is
//! the actual requirement - with it, changing the front end is
//! mechanical; without it, every rendering choice is a rewrite.
//!
//! Integers only, and it matters more across two compilers than it did
//! across two JS engines: with floats, LLVM may contract operations
//! differently per target, so agreement would be a hope rather than a
//! property of the arithmetic. Every multiply is `wrapping_mul` on a u32,
//! which is defined identically everywhere.

// no_std on wasm only. The worker's module has no business carrying a
// standard library to step integers, but the native client links this as
// an ordinary rlib and the test harness needs std - so the attribute is
// scoped to the target that wants it rather than applied absolutely.
#![cfg_attr(target_arch = "wasm32", no_std)]

pub mod courses;
pub mod quarry;
pub mod wasm;

/// A 32-bit hash, the seeded generator both games draw from.
///
/// The JS original used `Math.imul` and `>>> 0` for exactly this: to stay
/// inside 32-bit integer semantics that two engines cannot disagree
/// about. `wrapping_mul` on a `u32` is the same operation, said plainly.
#[inline]
pub fn hash32(a: u32, b: u32) -> u32 {
    let mut x = a ^ b.wrapping_add(0x9e37_79b9).wrapping_mul(0x85eb_ca6b);
    x = (x ^ (x >> 16)).wrapping_mul(0x7feb_352d);
    x = (x ^ (x >> 15)).wrapping_mul(0x846c_a68b);
    x ^ (x >> 16)
}

/// The seed for a game on a day, derived rather than stored.
///
/// FNV-1a over `game:day`, so every player gets the same board on the
/// same day without a write, and the verifier recomputes it from the
/// run's own day rather than trusting the submission.
pub fn seed_for(game: &str, day: &str) -> u32 {
    let mut hash: u32 = 2166136261;
    for byte in game.bytes().chain(b":".iter().copied()).chain(day.bytes()) {
        hash = (hash ^ byte as u32).wrapping_mul(16777619);
    }
    hash
}

/// One event from a replay: what was done, when, and to what.
///
/// `tick` rather than a timestamp, because the simulation is discrete: a
/// wall clock would be a lossier way of naming the same integer, and a
/// suspended tab owes the simulation nothing.
// repr(C) and three same-width lanes: the caller writes this straight
// into linear memory, so the layout is part of the ABI rather than an
// implementation detail Rust may reorder.
#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Event {
    pub action: i32,
    pub tick: i32,
    pub value: i32,
}

/// What a replay produced. The client renders from the full state; the
/// verifier only needs this.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub struct Outcome {
    pub score: u32,
    /// lines for Courses, bricks for Quarry - whatever the board shows
    /// beside the score.
    pub detail: u32,
    pub ticks: u32,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hash_matches_the_javascript_it_replaces() {
        // taken from the JS implementation, which is the incumbent: if
        // these drift, every historical score becomes unverifiable
        assert_eq!(hash32(0, 0), 1_622_709_315);
        assert_eq!(hash32(1, 0), 677_952_471);
        assert_eq!(hash32(0, 1), 3_165_721_940);
    }

    #[test]
    fn seeds_match_the_javascript() {
        assert_eq!(seed_for("courses", "2026-09-13"), 2_948_530_700);
        assert_eq!(seed_for("quarry", "2026-09-13"), 3_201_124_988);
    }
}
