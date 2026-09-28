//! A tiny local generator for presentation randomness - particle spread,
//! screen-shake jitter, and nothing else. Never touches the simulation:
//! two players see different sparks off the same run and log the same
//! events, exactly as the web page's `Math.random()` calls in effects.js
//! do for the same reason.

pub struct Rng(u32);

impl Rng {
    pub fn new(seed: u32) -> Self {
        // xorshift dislikes a zero state, and a seed of exactly 0 is the
        // one value that would otherwise generate nothing but zeroes
        Self(seed | 1)
    }

    fn next_u32(&mut self) -> u32 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
        self.0 = x;
        x
    }

    /// A float in [0, 1).
    pub fn next_f32(&mut self) -> f32 {
        (self.next_u32() >> 8) as f32 / (1u32 << 24) as f32
    }

    /// A float in [-1, 1).
    pub fn signed_f32(&mut self) -> f32 {
        self.next_f32() * 2.0 - 1.0
    }
}
