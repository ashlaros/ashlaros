"""The reactions themselves, drawn onto BGR frames.

Each effect is a short animation that draws itself onto the frame it is
handed and says when it is finished. They are drawn with OpenCV primitives
and the colour emoji font, nothing pre-rendered ships: the font is what
the rest of the desktop already draws emoji with.
"""

import math
import subprocess
from pathlib import Path

import cv2
import numpy as np

# Saturated, and distinct from each other and from skin tones
PALETTE = [
    (60, 76, 231), (34, 126, 230), (15, 196, 241), (113, 204, 46),
    (219, 152, 52), (182, 89, 155), (156, 92, 255), (255, 255, 255),
]


def emoji(char: str, size: int, cache: Path) -> np.ndarray:
    """One emoji as a BGRA sprite, size pixels tall, cropped to its ink.

    Rendered by pango-view in Noto Color Emoji once and cached: the
    bitmap strike is 136 px, so asking for more than that only upscales.
    """
    path = cache / f"{ord(char[0]):x}-{size}.png"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["pango-view", "--no-display", "--font=Noto Color Emoji 109",
             "--background=transparent", "--margin=0", f"--text={char}",
             f"--output={path}"],
            check=True, capture_output=True,
        )
        sprite = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        ys, xs = np.nonzero(sprite[:, :, 3])
        sprite = sprite[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        scale = size / sprite.shape[0]
        sprite = cv2.resize(sprite, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(path), sprite)
    return cv2.imread(str(path), cv2.IMREAD_UNCHANGED)


def blend(frame: np.ndarray, sprite: np.ndarray, cx: float, cy: float, alpha: float = 1.0):
    """Composites a BGRA sprite centred on (cx, cy), clipped to the frame."""
    h, w = sprite.shape[:2]
    x0, y0 = round(cx - w / 2), round(cy - h / 2)
    fx0, fy0 = max(x0, 0), max(y0, 0)
    fx1, fy1 = min(x0 + w, frame.shape[1]), min(y0 + h, frame.shape[0])
    if fx0 >= fx1 or fy0 >= fy1 or alpha <= 0:
        return
    part = sprite[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0]
    a = part[:, :, 3:4].astype(np.float32) * (alpha / 255)
    region = frame[fy0:fy1, fx0:fx1]
    region[:] = (part[:, :, :3] * a + region * (1 - a)).astype(np.uint8)


def scaled(sprite: np.ndarray, scale: float) -> np.ndarray:
    size = max(1, round(sprite.shape[1] * scale)), max(1, round(sprite.shape[0] * scale))
    return cv2.resize(sprite, size, interpolation=cv2.INTER_AREA)


def darken(frame: np.ndarray, amount: float, tint=(0, 0, 0)):
    """Dims the whole frame towards a colour - the stage the night effects
    play on."""
    if amount > 0:
        cv2.addWeighted(frame, 1 - amount, np.full_like(frame, tint), amount, 0, dst=frame)


def ramp(age: float, length: float, fade: float = 0.5) -> float:
    """0 to 1 over the first `fade` seconds, back to 0 over the last."""
    return max(0.0, min(1.0, age / fade, (length - age) / fade))


class Effect:
    length = 4.0

    def __init__(self, width: int, height: int, x: float, y: float):
        self.width, self.height = width, height
        # the hand that asked for it, in pixels; centre-screen for two hands
        self.x, self.y = x, y
        self.rng = np.random.default_rng()

    def draw(self, frame: np.ndarray, age: float):
        raise NotImplementedError


class Bubble(Effect):
    """One emoji in a bubble beside the hand, the way a reaction appears in
    a chat: it pops in, floats up a little, and fades."""

    length = 2.4

    def __init__(self, width, height, x, y, sprite):
        super().__init__(width, height, x, y)
        self.sprite = sprite
        self.radius = sprite.shape[0] * 0.75
        # beside the hand rather than on it, and kept inside the frame
        self.x = min(max(x + self.radius * 1.4, self.radius), width - self.radius)
        self.y = min(max(y - self.radius * 0.8, self.radius), height - self.radius)

    def draw(self, frame, age):
        # an overshoot on the way in: back-easing, 1.7 is the usual constant
        t = min(age / 0.3, 1.0) - 1
        pop = 1 + 2.7 * t**3 + 1.7 * t**2
        alpha = min(1.0, (self.length - age) / 0.4)
        y = self.y - 30 * age
        radius = max(1, round(self.radius * pop))

        overlay = frame.copy()
        cv2.circle(overlay, (round(self.x), round(y)), radius, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.85 * alpha, frame, 1 - 0.85 * alpha, 0, dst=frame)
        blend(frame, scaled(self.sprite, max(pop, 0.05)), self.x, y, alpha)


class Hearts(Effect):
    """Hearts streaming up out of the hand."""

    length = 3.2

    def __init__(self, width, height, x, y, sprite):
        super().__init__(width, height, x, y)
        n = 18
        self.sprites = [scaled(sprite, s) for s in self.rng.uniform(0.35, 0.8, n)]
        self.born = np.sort(self.rng.uniform(0, 1.4, n))
        self.speed = self.rng.uniform(140, 240, n)
        self.drift = self.rng.uniform(-60, 60, n)
        self.phase = self.rng.uniform(0, 2 * math.pi, n)

    def draw(self, frame, age):
        for i, sprite in enumerate(self.sprites):
            t = age - self.born[i]
            if t <= 0:
                continue
            x = self.x + self.drift[i] * t + 18 * math.sin(3 * t + self.phase[i])
            y = self.y - self.speed[i] * t
            blend(frame, sprite, x, y, max(0.0, min(1.0, 1.8 - t)))


class Sparkles(Effect):
    """Four-pointed stars twinkling out from the hand."""

    length = 2.8

    def __init__(self, width, height, x, y):
        super().__init__(width, height, x, y)
        n = 40
        angle = self.rng.uniform(0, 2 * math.pi, n)
        distance = self.rng.uniform(40, 260, n) * height / 720
        self.points = np.stack([x + np.cos(angle) * distance, y + np.sin(angle) * distance], 1)
        self.born = self.rng.uniform(0, 1.6, n)
        self.size = self.rng.uniform(8, 22, n) * height / 720
        self.colour = [PALETTE[i] for i in self.rng.choice([2, 7, 7, 6], n)]

    def draw(self, frame, age):
        for (x, y), born, size, colour in zip(self.points, self.born, self.size, self.colour,
                                             strict=True):
            t = age - born
            if not 0 < t < 1.0:
                continue
            # in and out again: a twinkle, not a fade
            s = size * math.sin(math.pi * t)
            arms = np.array([[0, -s], [s * 0.22, -s * 0.22], [s, 0], [s * 0.22, s * 0.22],
                             [0, s], [-s * 0.22, s * 0.22], [-s, 0], [-s * 0.22, -s * 0.22]])
            arms += (x, y)
            cv2.fillPoly(frame, [np.int32(arms)], colour, cv2.LINE_AA)


class Balloons(Effect):
    """Balloons rising from the bottom of the frame."""

    length = 5.5

    def __init__(self, width, height, x, y):
        super().__init__(width, height, x, y)
        n = 14
        self.x0 = self.rng.uniform(0.05, 0.95, n) * width
        self.y0 = height + self.rng.uniform(60, 400, n)
        self.speed = self.rng.uniform(180, 280, n) * height / 720
        self.size = self.rng.uniform(42, 64, n) * height / 720
        self.colour = [PALETTE[i % 7] for i in self.rng.permutation(n)]
        self.phase = self.rng.uniform(0, 2 * math.pi, n)

    def draw(self, frame, age):
        for i in range(len(self.x0)):
            r = self.size[i]
            x = self.x0[i] + 20 * math.sin(1.5 * age + self.phase[i])
            y = self.y0[i] - self.speed[i] * age
            if y < -3 * r:
                continue
            tail = [(round(x + 6 * math.sin(age * 4 + k + self.phase[i])),
                     round(y + r * 1.2 + k * r * 0.4)) for k in range(6)]
            cv2.polylines(frame, [np.int32(tail)], False, (230, 230, 230), 2, cv2.LINE_AA)
            centre = (round(x), round(y))
            cv2.ellipse(frame, centre, (round(r), round(r * 1.2)), 0, 0, 360,
                        self.colour[i], -1, cv2.LINE_AA)
            knot = np.int32([[x - 7, y + r * 1.25], [x + 7, y + r * 1.25], [x, y + r * 1.1]])
            cv2.fillPoly(frame, [knot], self.colour[i], cv2.LINE_AA)
            cv2.ellipse(frame, (round(x - r * 0.35), round(y - r * 0.45)),
                        (round(r * 0.18), round(r * 0.32)), 30, 0, 360,
                        (255, 255, 255), -1, cv2.LINE_AA)


class Confetti(Effect):
    """Confetti falling across the whole frame."""

    length = 5.0

    def __init__(self, width, height, x, y):
        super().__init__(width, height, x, y)
        n = 220
        self.x0 = self.rng.uniform(0, width, n)
        self.y0 = -self.rng.uniform(0, height, n)
        self.vy = self.rng.uniform(180, 320, n) * height / 720
        self.vx = self.rng.uniform(-40, 40, n)
        self.spin = self.rng.uniform(-8, 8, n)
        self.size = self.rng.uniform(5, 11, n) * height / 720
        self.colour = [PALETTE[i % 7] for i in self.rng.integers(0, 7, n)]

    def draw(self, frame, age):
        xs = self.x0 + self.vx * age + 25 * np.sin(2 * age + self.spin)
        ys = self.y0 + self.vy * age
        angles = self.spin * age
        for i in np.nonzero((ys > -20) & (ys < self.height + 20))[0]:
            s, a = self.size[i], angles[i]
            # a strip seen edge-on as it tumbles: the width breathes
            w, h = s * abs(math.cos(a * 1.3)) + 1, s * 0.5
            c, d = math.cos(a), math.sin(a)
            corners = np.array([[-w, -h], [w, -h], [w, h], [-w, h]]) @ [[c, d], [-d, c]]
            corners += (xs[i], ys[i])
            cv2.fillPoly(frame, [np.int32(corners)], self.colour[i], cv2.LINE_AA)


class Fireworks(Effect):
    """Bursts over a darkened frame."""

    length = 4.5

    def __init__(self, width, height, x, y):
        super().__init__(width, height, x, y)
        self.bursts = []
        for start in (0.2, 0.7, 1.2, 1.8, 2.4, 2.9):
            n = 70
            angle = self.rng.uniform(0, 2 * math.pi, n)
            speed = self.rng.uniform(120, 320, n) * height / 720
            self.bursts.append((
                start,
                self.rng.uniform(0.15, 0.85) * width,
                self.rng.uniform(0.12, 0.5) * height,
                np.cos(angle) * speed, np.sin(angle) * speed,
                PALETTE[self.rng.integers(0, 7)],
            ))

    def draw(self, frame, age):
        darken(frame, 0.55 * ramp(age, self.length, 0.4))
        for start, x, y, vx, vy, colour in self.bursts:
            t = age - start
            if not 0 < t < 1.5:
                continue
            fade = 1 - t / 1.5
            bright = tuple(round(c * fade + 255 * (1 - fade) * 0.2) for c in colour)
            px, py = x + vx * t, y + vy * t + 140 * t * t
            qx, qy = x + vx * (t - 0.08), y + vy * (t - 0.08) + 140 * (t - 0.08) ** 2
            for i in range(len(vx)):
                cv2.line(frame, (round(qx[i]), round(qy[i])), (round(px[i]), round(py[i])),
                         bright, 2, cv2.LINE_AA)


class Rain(Effect):
    """A grey-blue downpour."""

    length = 5.0

    def __init__(self, width, height, x, y):
        super().__init__(width, height, x, y)
        n = 260
        self.x0 = self.rng.uniform(-0.1, 1.1, n) * width
        self.y0 = self.rng.uniform(0, height, n)
        self.speed = self.rng.uniform(900, 1400, n) * height / 720
        self.length_px = self.rng.uniform(18, 40, n) * height / 720

    def draw(self, frame, age):
        level = ramp(age, self.length)
        darken(frame, 0.45 * level, tint=(60, 40, 30))
        overlay = frame.copy()
        ys = (self.y0 + self.speed * age) % (self.height + 60) - 30
        xs = self.x0 - 0.15 * ys
        for x, y, n in zip(xs, ys, self.length_px, strict=True):
            cv2.line(overlay, (round(x), round(y)), (round(x - 0.15 * n), round(y + n)),
                     (235, 215, 200), 1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.8 * level, frame, 1 - 0.8 * level, 0, dst=frame)


class Lasers(Effect):
    """Beams sweeping down from the top of the frame."""

    length = 4.5

    def __init__(self, width, height, x, y):
        super().__init__(width, height, x, y)
        n = 8
        self.origin = np.linspace(0.05, 0.95, n) * width
        self.phase = self.rng.uniform(0, 2 * math.pi, n)
        self.colour = [PALETTE[i] for i in (0, 3, 4, 5, 6, 0, 3, 4)]

    def draw(self, frame, age):
        level = ramp(age, self.length, 0.3)
        darken(frame, 0.6 * level)
        # the glow is drawn and blurred at a quarter of the size: a blur is
        # soft anyway, and full-size it cost most of a frame
        glow = np.zeros((self.height // 4, self.width // 4, 3), np.uint8)
        reach = 1.5 * self.height
        for i, x in enumerate(self.origin):
            angle = math.pi / 2 + 0.6 * math.sin(1.6 * age + self.phase[i])
            end = (round(x + reach * math.cos(angle)), round(reach * math.sin(angle)))
            cv2.line(glow, (round(x / 4), -2), (end[0] // 4, end[1] // 4), self.colour[i], 4,
                     cv2.LINE_AA)
            cv2.line(frame, (round(x), -5), end, (255, 255, 255), 2, cv2.LINE_AA)
        glow = cv2.GaussianBlur(glow, (0, 0), 1.5)
        glow = cv2.resize(glow, (self.width, self.height), interpolation=cv2.INTER_LINEAR)
        cv2.scaleAdd(glow, level, frame, dst=frame)


# What each gesture does: SINGLE for one hand, DOUBLE for both hands
# making the same gesture or one only two hands can make. Keys are
# gestures.py's names. An open palm, a fist or a raised finger trigger
# nothing: hands do those anyway while someone talks.
# Lasers take both hands, as FaceTime's do: one hand is a 🤘 bubble.
SINGLE = {
    "Thumb_Up": "thumbs-up", "Thumb_Down": "thumbs-down", "Victory": "balloons",
    "ILoveYou": "sparkles", "Horns": "horns", "OK": "ok", "Shaka": "shaka",
}
DOUBLE = {
    "Thumb_Up": "fireworks", "Thumb_Down": "rain", "Victory": "confetti",
    "ILoveYou": "lasers", "Horns": "lasers", "OK": "ok", "Shaka": "shaka",
    "Heart": "hearts",
}

# the emoji a bubble shows, by effect name
BUBBLES = {"thumbs-up": "\U0001f44d", "thumbs-down": "\U0001f44e", "ok": "\U0001f44c",
           "shaka": "\U0001f919", "horns": "\U0001f918"}


class Library:
    """Builds an effect by name, with the sprites it needs rendered once."""

    def __init__(self, cache: Path, height: int):
        size = round(height * 0.16)
        self.bubbles = {name: emoji(char, size, cache) for name, char in BUBBLES.items()}
        self.heart = emoji("\u2764\ufe0f", size, cache)

    def make(self, name: str, width: int, height: int, x: float, y: float) -> Effect:
        if name in self.bubbles:
            return Bubble(width, height, x, y, self.bubbles[name])
        if name == "hearts":
            return Hearts(width, height, x, y, self.heart)
        return {"balloons": Balloons, "confetti": Confetti, "fireworks": Fireworks,
                "rain": Rain, "lasers": Lasers, "sparkles": Sparkles}[name](width, height, x, y)
