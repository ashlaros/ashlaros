/**
 * Wall-clock effects, shared by both games.
 *
 * Particles, floating text, a banner, a flash and the screen shake - all
 * of it advanced by requestAnimationFrame elapsed time and none of it fed
 * by a simulation tick. The separation is deliberate rather than
 * convenient: the verifier replays ticks and must never owe a run anything
 * to do with a particle, so the effect clock and the tick clock stay apart
 * by construction rather than by care.
 *
 * Capped, and the cap is load-bearing. A hard drop throws a dozen streaks
 * and a four-line clear throws a hundred particles, and a two-minute run
 * does that hundreds of times - without a ceiling the arrays only grow and
 * the draw cost grows with them. With one, a frame is a few hundred fill
 * calls whatever the run has done.
 */

// A ceiling on every collection here. Generous for what the games throw
// at it, and small enough that the worst frame is bounded.
const MAX_BITS = 200;
const MAX_TEXT = 24;

// The banner is one thing at a time by design: two overlapping
// announcements are a crawl, and neither game has a moment where two
// should be read at once.
const BANNER_LIFE = 1.4;

const SQUARE = 0;
const DOT = 1;
const STREAK = 2;

const OFFSET = { x: 0, y: 0 };

export function createEffects() {
  const bits = [];
  const texts = [];
  let bannerText = null;
  let bannerAge = 0;
  let flashStrength = 0;
  let shakeAmount = 0;

  function add(bit) {
    bits.push(bit);
    // oldest out first: a burst that overflows is throwing away the
    // debris the player has already stopped looking at
    if (bits.length > MAX_BITS) bits.splice(0, bits.length - MAX_BITS);
  }

  return {
    /**
     * A cluster of small squares, the shape both games use for "something
     * broke here".
     */
    burst(x, y, colour, count, speed = 110) {
      for (let i = 0; i < count; i++) {
        // a fixed square spread rather than a uniform circle: two calls
        // to a source of randomness here are not worth a second sampler
        const angle = (i + 0.5) / count * Math.PI * 2 + x * 0.013 + y * 0.007;
        const force = speed * (0.55 + ((i * 7919) % 100) / 100);
        add({
          kind: SQUARE,
          x,
          y,
          vx: Math.cos(angle) * force,
          vy: Math.sin(angle) * force - speed * 0.35,
          gravity: 260,
          size: 3 + (i % 3),
          colour,
          age: 0,
          life: 0.42 + (i % 5) * 0.05,
        });
      }
    },

    /** A soft dot with no drift of its own: a ball's smear. */
    trail(x, y, colour, size, life = 0.18) {
      add({ kind: DOT, x, y, vx: 0, vy: 0, gravity: 0, size, colour, age: 0, life });
    },

    /** A fading rectangle, which is what a falling piece leaves behind. */
    streak(x, y, w, h, colour, life = 0.22) {
      add({ kind: STREAK, x, y, w, h, vx: 0, vy: 0, gravity: 0, size: 0, colour, age: 0, life });
    },

    /** Text that rises as it fades. */
    popup(text, x, y, colour = '#eeeeee', life = 0.9) {
      texts.push({ text, x, y, colour, age: 0, life });
      if (texts.length > MAX_TEXT) texts.splice(0, texts.length - MAX_TEXT);
    },

    /** A single announcement, centred and large, replacing any previous. */
    banner(text) {
      bannerText = text;
      bannerAge = 0;
    },

    /** A wash of light over the whole field, for the moment lines go. */
    flash(strength = 0.3) {
      flashStrength = Math.max(flashStrength, strength);
    },

    /** Kick the field by a few pixels. */
    shake(amount = 5) {
      shakeAmount = Math.max(shakeAmount, amount);
    },

    /**
     * Where the field is drawn this frame.
     *
     * A fresh direction every frame, because a fixed offset reads as a
     * board in the wrong place and a changing one reads as an impact.
     */
    shakeOffset() {
      OFFSET.x = 0;
      OFFSET.y = 0;
      if (shakeAmount > 0) {
        OFFSET.x = (Math.random() * 2 - 1) * shakeAmount;
        OFFSET.y = (Math.random() * 2 - 1) * shakeAmount;
      }
      return OFFSET;
    },

    /** Advance everything by real elapsed milliseconds. */
    update(elapsed) {
      const dt = Math.min(elapsed, 100) / 1000;
      // exponential decay, so a shake is gone the moment it is too small
      // to see rather than running out its timer on a frozen offset
      shakeAmount *= Math.exp(-dt * 14);
      if (shakeAmount < 0.15) shakeAmount = 0;
      flashStrength *= Math.exp(-dt * 9);
      if (flashStrength < 0.01) flashStrength = 0;

      for (let i = bits.length - 1; i >= 0; i--) {
        const bit = bits[i];
        bit.age += dt;
        if (bit.age >= bit.life) {
          bits[i] = bits[bits.length - 1];
          bits.pop();
          continue;
        }
        bit.x += bit.vx * dt;
        bit.y += bit.vy * dt;
        bit.vy += bit.gravity * dt;
      }

      for (let i = texts.length - 1; i >= 0; i--) {
        const text = texts[i];
        text.age += dt;
        if (text.age >= text.life) {
          texts[i] = texts[texts.length - 1];
          texts.pop();
          continue;
        }
        text.y -= 34 * dt;
      }

      if (bannerText) {
        bannerAge += dt;
        if (bannerAge >= BANNER_LIFE) bannerText = null;
      }
    },

    /** Paint over whatever the game has already drawn. */
    draw(ctx) {
      const w = ctx.canvas.width;
      const h = ctx.canvas.height;

      for (const bit of bits) {
        const left = 1 - bit.age / bit.life;
        ctx.globalAlpha = Math.max(0, left);
        ctx.fillStyle = bit.colour;
        if (bit.kind === STREAK) {
          ctx.fillRect(bit.x, bit.y, bit.w, bit.h);
        } else if (bit.kind === DOT) {
          ctx.beginPath();
          ctx.arc(bit.x, bit.y, bit.size * (0.45 + 0.55 * left), 0, Math.PI * 2);
          ctx.fill();
        } else {
          ctx.fillRect(bit.x - bit.size / 2, bit.y - bit.size / 2, bit.size, bit.size);
        }
      }
      ctx.globalAlpha = 1;

      // An outline rather than a shadow under the text: over a busy board
      // unreadable type is worse than none, and strokeText is the cheap
      // way to keep it readable at any background.
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.lineJoin = 'round';
      for (const text of texts) {
        const left = 1 - text.age / text.life;
        ctx.save();
        ctx.globalAlpha = Math.max(0, left);
        ctx.font = 'bold 18px monospace';
        ctx.lineWidth = 4;
        ctx.strokeStyle = '#141a1b';
        ctx.strokeText(text.text, text.x, text.y);
        ctx.fillStyle = text.colour;
        ctx.fillText(text.text, text.x, text.y);
        ctx.restore();
      }

      if (bannerText) {
        const t = bannerAge / BANNER_LIFE;
        ctx.save();
        // squared, so the banner holds and then leaves rather than fading
        // at a rate the eye reads as "dimming"
        ctx.globalAlpha = Math.max(0, 1 - t * t);
        ctx.font = 'bold 34px monospace';
        ctx.lineWidth = 6;
        ctx.strokeStyle = '#141a1b';
        ctx.strokeText(bannerText, w / 2, h * 0.32);
        ctx.fillStyle = '#eeeeee';
        ctx.fillText(bannerText, w / 2, h * 0.32);
        ctx.restore();
      }

      if (flashStrength > 0) {
        ctx.save();
        ctx.globalAlpha = Math.min(0.85, flashStrength);
        ctx.fillStyle = '#eeeeee';
        ctx.fillRect(0, 0, w, h);
        ctx.restore();
      }
    },

    /** Drop everything, for a run starting or ending. */
    clear() {
      bits.length = 0;
      texts.length = 0;
      bannerText = null;
      flashStrength = 0;
      shakeAmount = 0;
    },
  };
}
