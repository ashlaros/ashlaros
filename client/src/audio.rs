//! Playing the cues, and never being a reason the game fails to start.
//!
//! Silence is a first-class path here exactly as it is in
//! `docs/game/audio.js`: a machine with no sound card, a missing audio
//! directory, and a missing individual cue are all the same outcome -
//! nothing plays for that cue, and nothing else in the game waits on it
//! or panics over it.
//!
//! Nothing here may affect the simulation. This is told what happened;
//! it never decides anything.

use raylib::prelude::*;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// The cue basenames, exactly as `scripts/game-sfx.mjs` writes them and
/// `docs/game/audio.js`'s `CUES` lists them - one set of files serves the
/// web page and this client alike.
pub const CUES: &[&str] = &[
    "move",
    "rotate",
    "drop",
    "lock",
    "hold",
    "clear-1",
    "clear-2",
    "clear-3",
    "clear-4",
    "levelup",
    "gameover",
    "brick-1",
    "brick-2",
    "brick-3",
    "paddle",
    "wall",
    "solid",
    "capsule",
    "catch",
    "lost",
    "levelclear",
    "softdrop",
    "backtoback",
    "warning",
    "start",
    "launch",
    "speedup",
    "multi",
];

/// Where the WAVs live: an override for development, or the path the
/// package installs them to.
pub fn audio_dir() -> PathBuf {
    std::env::var("ASHLAROS_ARCADE_AUDIO")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/usr/share/ashlaros-arcade/audio"))
}

/// Every cue this run could find, keyed by name.
///
/// A missing directory means an empty map, not an error: `play` already
/// treats an absent name as silence, so a game with no sound files at all
/// takes the same path as one with all of them.
pub struct Audio<'aud> {
    sounds: HashMap<&'static str, Sound<'aud>>,
    muted: bool,
}

impl<'aud> Audio<'aud> {
    /// `device` is `None` when `init_audio_device` failed - a machine with
    /// no output, most likely - and the whole set loads silent rather
    /// than the game refusing to start.
    pub fn load(device: Option<&'aud RaylibAudio>, dir: &Path) -> Self {
        let mut sounds = HashMap::new();
        if let Some(device) = device {
            for name in CUES {
                let path = dir.join(format!("{name}.wav"));
                let Some(path) = path.to_str() else { continue };
                if let Ok(sound) = device.new_sound(path) {
                    sounds.insert(*name, sound);
                }
            }
        }
        Self {
            sounds,
            muted: false,
        }
    }

    pub fn play(&self, name: &str) {
        self.play_pitched(name, 1.0);
    }

    /// `pitch` is the same knob the page's `audio.play(name, gain, rate)`
    /// exposes as `rate`: presentation only, so two players hearing
    /// different detune on the same cue have logged the same run.
    pub fn play_pitched(&self, name: &str, pitch: f32) {
        if self.muted {
            return;
        }
        if let Some(sound) = self.sounds.get(name) {
            sound.set_pitch(pitch);
            sound.play();
        }
    }

    pub fn muted(&self) -> bool {
        self.muted
    }

    /// Not persisted across runs, unlike the page's `localStorage` flag -
    /// there is nowhere on this side worth writing it that the next
    /// launch would reliably find again.
    pub fn toggle_mute(&mut self) {
        self.muted = !self.muted;
    }
}
