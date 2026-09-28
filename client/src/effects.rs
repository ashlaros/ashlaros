//! Wall-clock effects, shared by both games and ported from
//! `docs/game/effects.js`: particles, floating text, a banner, a flash
//! and a screen shake, all advanced by frame time and none of it fed by
//! a simulation tick.
//!
//! Fixed-capacity rather than a growing `Vec`: a run that throws a
//! particle every frame for two minutes must cost the same to draw on
//! frame one as on the last, so the oldest bit is evicted rather than
//! the collection growing without bound.
//!
//! Nothing here reads or writes game state. Presentation randomness comes
//! from `rng::Rng`, never from anything the simulation could see.

use crate::rng::Rng;
use raylib::prelude::*;

const MAX_BITS: usize = 200;
const MAX_TEXT: usize = 24;
const BANNER_LIFE: f32 = 1.4;

#[derive(Clone, Copy)]
enum Kind {
    Square,
    Dot,
    Streak { w: f32, h: f32 },
}

#[derive(Clone, Copy)]
struct Bit {
    kind: Kind,
    x: f32,
    y: f32,
    vx: f32,
    vy: f32,
    gravity: f32,
    size: f32,
    colour: Color,
    age: f32,
    life: f32,
}

struct Text {
    text: String,
    x: f32,
    y: f32,
    colour: Color,
    age: f32,
    life: f32,
}

pub struct Effects {
    rng: Rng,
    bits: Vec<Bit>,
    texts: Vec<Text>,
    banner_text: Option<String>,
    banner_age: f32,
    flash_strength: f32,
    shake_amount: f32,
}

impl Effects {
    pub fn new(seed: u32) -> Self {
        Self {
            rng: Rng::new(seed),
            bits: Vec::with_capacity(MAX_BITS),
            texts: Vec::with_capacity(MAX_TEXT),
            banner_text: None,
            banner_age: 0.0,
            flash_strength: 0.0,
            shake_amount: 0.0,
        }
    }

    fn add(&mut self, bit: Bit) {
        if self.bits.len() >= MAX_BITS {
            // oldest out first: a burst that overflows is throwing away
            // the debris the player has already stopped looking at
            self.bits.remove(0);
        }
        self.bits.push(bit);
    }

    /// A cluster of small squares, the shape both games use for
    /// "something broke here".
    pub fn burst(&mut self, x: f32, y: f32, colour: Color, count: u32) {
        let speed = 110.0f32;
        for i in 0..count {
            let angle = (i as f32 + 0.5) / count as f32 * std::f32::consts::TAU
                + x * 0.013
                + y * 0.007;
            let force = speed * (0.55 + ((i * 7919) % 100) as f32 / 100.0);
            self.add(Bit {
                kind: Kind::Square,
                x,
                y,
                vx: angle.cos() * force,
                vy: angle.sin() * force - speed * 0.35,
                gravity: 260.0,
                size: 3.0 + (i % 3) as f32,
                colour,
                age: 0.0,
                life: 0.42 + (i % 5) as f32 * 0.05,
            });
        }
    }

    /// A soft dot with no drift of its own: a ball's smear.
    pub fn trail(&mut self, x: f32, y: f32, colour: Color, size: f32) {
        self.add(Bit {
            kind: Kind::Dot,
            x,
            y,
            vx: 0.0,
            vy: 0.0,
            gravity: 0.0,
            size,
            colour,
            age: 0.0,
            life: 0.18,
        });
    }

    /// A fading rectangle, which is what a falling piece leaves behind.
    pub fn streak(&mut self, x: f32, y: f32, w: f32, h: f32, colour: Color) {
        self.add(Bit {
            kind: Kind::Streak { w, h },
            x,
            y,
            vx: 0.0,
            vy: 0.0,
            gravity: 0.0,
            size: 0.0,
            colour,
            age: 0.0,
            life: 0.22,
        });
    }

    /// Text that rises as it fades.
    pub fn popup(&mut self, text: impl Into<String>, x: f32, y: f32, colour: Color) {
        if self.texts.len() >= MAX_TEXT {
            self.texts.remove(0);
        }
        self.texts.push(Text {
            text: text.into(),
            x,
            y,
            colour,
            age: 0.0,
            life: 0.9,
        });
    }

    /// A single announcement, centred and large, replacing any previous.
    pub fn banner(&mut self, text: impl Into<String>) {
        self.banner_text = Some(text.into());
        self.banner_age = 0.0;
    }

    /// A wash of light over the whole field, for the moment lines go.
    pub fn flash(&mut self, strength: f32) {
        self.flash_strength = self.flash_strength.max(strength);
    }

    /// Kick the field by a few pixels.
    pub fn shake(&mut self, amount: f32) {
        self.shake_amount = self.shake_amount.max(amount);
    }

    /// Where the field is drawn this frame: a fresh direction every
    /// frame, because a fixed offset reads as a board in the wrong place
    /// and a changing one reads as an impact.
    pub fn shake_offset(&mut self) -> (f32, f32) {
        if self.shake_amount > 0.0 {
            (
                self.rng.signed_f32() * self.shake_amount,
                self.rng.signed_f32() * self.shake_amount,
            )
        } else {
            (0.0, 0.0)
        }
    }

    /// Advance everything by real elapsed seconds.
    pub fn update(&mut self, dt: f32) {
        let dt = dt.min(0.1);
        // exponential decay, so a shake is gone the moment it is too
        // small to see rather than running out its timer on a frozen
        // offset
        self.shake_amount *= (-dt * 14.0).exp();
        if self.shake_amount < 0.15 {
            self.shake_amount = 0.0;
        }
        self.flash_strength *= (-dt * 9.0).exp();
        if self.flash_strength < 0.01 {
            self.flash_strength = 0.0;
        }

        self.bits.retain_mut(|bit| {
            bit.age += dt;
            if bit.age >= bit.life {
                return false;
            }
            bit.x += bit.vx * dt;
            bit.y += bit.vy * dt;
            bit.vy += bit.gravity * dt;
            true
        });

        self.texts.retain_mut(|text| {
            text.age += dt;
            if text.age >= text.life {
                return false;
            }
            text.y -= 34.0 * dt;
            true
        });

        if self.banner_text.is_some() {
            self.banner_age += dt;
            if self.banner_age >= BANNER_LIFE {
                self.banner_text = None;
            }
        }
    }

    /// Paint over whatever the game has already drawn, inside the field
    /// box at `(ox, oy)` sized `(w, h)` - the banner and flash cover the
    /// box rather than the whole window, since the sidebar around it is
    /// not part of what shook or flashed.
    pub fn draw(&self, d: &mut RaylibDrawHandle, ox: i32, oy: i32, w: i32, h: i32) {
        for bit in &self.bits {
            let left = (1.0 - bit.age / bit.life).max(0.0);
            let colour = fade(bit.colour, left);
            match bit.kind {
                Kind::Streak { w, h } => {
                    d.draw_rectangle(bit.x as i32, bit.y as i32, w as i32, h as i32, colour);
                }
                Kind::Dot => {
                    d.draw_circle(
                        bit.x as i32,
                        bit.y as i32,
                        bit.size * (0.45 + 0.55 * left),
                        colour,
                    );
                }
                Kind::Square => {
                    d.draw_rectangle(
                        (bit.x - bit.size / 2.0) as i32,
                        (bit.y - bit.size / 2.0) as i32,
                        bit.size as i32,
                        bit.size as i32,
                        colour,
                    );
                }
            }
        }

        for text in &self.texts {
            let left = (1.0 - text.age / text.life).max(0.0);
            let colour = fade(text.colour, left);
            let size = 18;
            let width = d.measure_text(&text.text, size);
            d.draw_text(
                &text.text,
                text.x as i32 - width / 2,
                text.y as i32 - size / 2,
                size,
                colour,
            );
        }

        if let Some(banner) = &self.banner_text {
            let t = self.banner_age / BANNER_LIFE;
            // squared, so the banner holds and then leaves rather than
            // fading at a rate the eye reads as "dimming"
            let alpha = (1.0 - t * t).max(0.0);
            let size = 34;
            let width = d.measure_text(banner, size);
            let bx = ox + w / 2 - width / 2;
            let by = oy + (h as f32 * 0.32) as i32;
            d.draw_text(banner, bx, by, size, fade(Color::new(0xee, 0xee, 0xee, 255), alpha));
        }

        if self.flash_strength > 0.0 {
            let alpha = self.flash_strength.min(0.85);
            d.draw_rectangle(
                ox,
                oy,
                w,
                h,
                fade(Color::new(0xee, 0xee, 0xee, 255), alpha),
            );
        }
    }

    /// Drop everything, for a run starting or ending.
    pub fn clear(&mut self) {
        self.bits.clear();
        self.texts.clear();
        self.banner_text = None;
        self.flash_strength = 0.0;
        self.shake_amount = 0.0;
    }
}

fn fade(colour: Color, alpha: f32) -> Color {
    Color::new(
        colour.r,
        colour.g,
        colour.b,
        (alpha.clamp(0.0, 1.0) * 255.0) as u8,
    )
}
