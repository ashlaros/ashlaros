//! The ABI the worker's verifier calls.
//!
//! Deliberately flat: integers in, integers out, one fixed buffer for the
//! event log. No allocator, no string marshalling, nothing that needs a
//! bindings generator - the surface is small enough that a generator
//! would be more machinery than the thing it wraps.
//!
//! The caller writes events into `EVENTS` via `events_ptr()`, then calls
//! `replay_*`. Single-threaded by construction: a worker isolate handles
//! one request at a time, and the module is instantiated per isolate.

use crate::{courses, quarry, Event, Outcome};

/// Bounded by what the games themselves accept: Courses ends after 600
/// pieces, Quarry after 120 seconds, and neither can produce more inputs
/// than this without the replay being rejected as over-dense anyway.
const MAX_EVENTS: usize = 8192;

static mut EVENTS: [Event; MAX_EVENTS] = [Event {
    action: 0,
    tick: 0,
    value: 0,
}; MAX_EVENTS];

static mut OUTCOME: Outcome = Outcome {
    score: 0,
    detail: 0,
    ticks: 0,
};

/// Where to write the event log. Three i32 lanes per event, laid out as
/// the struct is.
#[no_mangle]
pub extern "C" fn events_ptr() -> *mut Event {
    &raw mut EVENTS as *mut Event
}

#[no_mangle]
pub extern "C" fn max_events() -> u32 {
    MAX_EVENTS as u32
}

#[no_mangle]
pub extern "C" fn seed_for_day(game: u32, day_ptr: *const u8, day_len: u32) -> u32 {
    let day = unsafe { core::slice::from_raw_parts(day_ptr, day_len as usize) };
    let Ok(day) = core::str::from_utf8(day) else {
        return 0;
    };
    crate::seed_for(if game == 0 { "courses" } else { "quarry" }, day)
}

fn run(game: u32, seed: u32, count: u32) -> Outcome {
    let count = (count as usize).min(MAX_EVENTS);
    let events = unsafe { core::slice::from_raw_parts(&raw const EVENTS as *const Event, count) };
    if game == 0 {
        courses::replay(seed, events)
    } else {
        quarry::replay(seed, events)
    }
}

/// Replay `count` events already written at `events_ptr()`, returning the
/// score. `detail` and `ticks` follow from the accessors, so the common
/// case costs one call.
#[no_mangle]
pub extern "C" fn replay(game: u32, seed: u32, count: u32) -> u32 {
    let outcome = run(game, seed, count);
    unsafe {
        OUTCOME = outcome;
    }
    outcome.score
}

#[no_mangle]
pub extern "C" fn last_detail() -> u32 {
    unsafe { (*(&raw const OUTCOME)).detail }
}

#[no_mangle]
pub extern "C" fn last_ticks() -> u32 {
    unsafe { (*(&raw const OUTCOME)).ticks }
}

/// Aborting is the only sane response: there is no I/O to report through,
/// and a verifier that limped on after a panic would accept a score its
/// own simulation could not produce.
#[cfg(target_arch = "wasm32")]
#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! {
    core::arch::wasm32::unreachable()
}
