//! Colours and input timing shared by both games' views.

use raylib::prelude::*;

pub const BG: Color = Color::new(0x14, 0x1a, 0x1b, 255);
pub const FG: Color = Color::new(0xc9, 0xcc, 0xd1, 255);
pub const ACCENT: Color = Color::new(0x3a, 0x40, 0x43, 255);
pub const PIECE_COLOURS: [Color; 7] = [
    Color::new(0x4e, 0x9a, 0xa6, 255),
    Color::new(0x5a, 0x7d, 0xa8, 255),
    Color::new(0xa8, 0x7d, 0x5a, 255),
    Color::new(0xa6, 0x9a, 0x4e, 255),
    Color::new(0x6f, 0xa6, 0x4e, 255),
    Color::new(0x8a, 0x6f, 0xa6, 255),
    Color::new(0xa6, 0x5a, 0x5a, 255),
];

/// Frames a directional key must be held before autorepeat begins, and
/// the frames between repeats after that: roughly 166ms delay and 33ms
/// repeat at 60fps, close to what a keyboard's own repeat feels like.
pub const DAS_FRAMES: u32 = 10;
pub const ARR_FRAMES: u32 = 2;
