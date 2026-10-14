"""Gestures MediaPipe's classifier does not know, read off the landmarks.

The classifier's eight classes stop at a thumbs-up and a peace sign. Heart
hands, OK, a shaka and the horns are all a question of which fingers are
out and which touch, and the landmark model already answers that - so
these are geometry, not another model.

Every threshold was measured on HaGRID v2's test split: 10,450 images of
19 gesture classes, run through this pipeline. Each rule's docstring gives
its recall on its own class and how often it fired on all the others,
no_gesture included. A wave is a motion HaGRID cannot show, and Motion
follows it across frames instead.

Which fingers are out is read in world landmarks: metres, centred on the
hand, so neither distance from the camera nor a hand turned sideways
changes the answer. Contact between fingertips is read in pixels, where
"touching" is what the camera sees.
"""

import itertools
from collections import deque

import numpy as np

WRIST, THUMB_TIP = 0, 4
INDEX_MCP, INDEX_DIP, INDEX_TIP = 5, 7, 8
MIDDLE_MCP, MIDDLE_TIP = 9, 12
RING_MCP, RING_TIP = 13, 16
PINKY_MCP, PINKY_TIP = 17, 20

# A fingertip's distance from the wrist over its knuckle's: about 1.8 for
# a straight finger, under 1 for one folded into the palm. Between the two
# a finger is neither, and no rule counts it as either.
EXTENDED = 1.6
FOLDED = 1.35

# The classifier's own gestures that trigger anything; the rest - an open
# palm, a fist, a raised finger - are what hands do while someone talks.
CLASSIFIED = ("Thumb_Up", "Thumb_Down", "Victory", "ILoveYou")


def _reach(world: np.ndarray, tip: int, mcp: int) -> float:
    to_tip = np.linalg.norm(world[tip] - world[WRIST])
    return float(to_tip / np.linalg.norm(world[mcp] - world[WRIST]))


def _thumb_out(world: np.ndarray) -> float:
    """How far the thumb tip stands off the index knuckle, in palm widths."""
    palm = np.linalg.norm(world[INDEX_MCP] - world[PINKY_MCP])
    return float(np.linalg.norm(world[THUMB_TIP] - world[INDEX_MCP]) / palm)


def palm_pixels(hand) -> float:
    """The palm's width as the camera would see it facing square on.

    The on-screen width alone collapses when a hand turns edge-on, which
    would make every fingertip look close to every other. So the scale
    comes from the least foreshortened palm bone, in pixels per metre,
    applied to the palm's real width.
    """
    px, world = hand.pixels, hand.world
    per_metre = max(
        np.linalg.norm(px[a] - px[b]) / np.linalg.norm(world[a] - world[b])
        for a, b in ((WRIST, INDEX_MCP), (WRIST, PINKY_MCP), (INDEX_MCP, PINKY_MCP),
                     (WRIST, MIDDLE_MCP))
    )
    return float(per_metre * np.linalg.norm(world[INDEX_MCP] - world[PINKY_MCP]))


def upright(hand) -> bool:
    """Fingers pointing up, give or take 35 degrees."""
    v = hand.pixels[MIDDLE_MCP] - hand.pixels[WRIST]
    return bool(-v[1] / (np.linalg.norm(v) + 1e-9) > 0.8)


def open_palm(hand) -> bool:
    w = hand.world
    return min(_reach(w, INDEX_TIP, INDEX_MCP), _reach(w, MIDDLE_TIP, MIDDLE_MCP),
               _reach(w, RING_TIP, RING_MCP), _reach(w, PINKY_TIP, PINKY_MCP)) > EXTENDED


def horns(hand) -> bool:
    """🤘 index and pinky out, middle and ring down, thumb across them.
    HaGRID: 88% of `rock`; 0.04% of the rest. The tucked thumb is what
    tells it from 🤟, which the classifier already reports as ILoveYou."""
    w = hand.world
    return (_reach(w, INDEX_TIP, INDEX_MCP) > 1.5 and _reach(w, PINKY_TIP, PINKY_MCP) > 1.5
            and _reach(w, MIDDLE_TIP, MIDDLE_MCP) < FOLDED
            and _reach(w, RING_TIP, RING_MCP) < FOLDED
            and _thumb_out(w) < 1.2)


def shaka(hand) -> bool:
    """🤙 thumb and pinky out, the three between them folded.
    HaGRID: 64% of `call`; 0.05% of the rest. Most misses are a pinky the
    landmarks see as bent; loosening that let in curled heart hands."""
    w = hand.world
    return (_reach(w, PINKY_TIP, PINKY_MCP) > EXTENDED
            and max(_reach(w, INDEX_TIP, INDEX_MCP), _reach(w, MIDDLE_TIP, MIDDLE_MCP),
                    _reach(w, RING_TIP, RING_MCP)) < FOLDED
            and _thumb_out(w) > 0.8)


def ok_sign(hand) -> bool:
    """👌 thumb and index touching, the other three out.
    HaGRID: 90% of `ok`; 0.05% of the rest."""
    w, px = hand.world, hand.pixels
    # the joint below the index tip counts too: a ring made with the pad
    # of the finger is still a ring
    gap = min(np.linalg.norm(px[THUMB_TIP] - px[INDEX_TIP]),
              np.linalg.norm(px[THUMB_TIP] - px[INDEX_DIP]))
    return (gap / palm_pixels(hand) < 0.35
            and min(_reach(w, MIDDLE_TIP, MIDDLE_MCP), _reach(w, RING_TIP, RING_MCP),
                    _reach(w, PINKY_TIP, PINKY_MCP)) > EXTENDED)


def heart_hands(hands) -> bool:
    """🫶 two hands, index tips together over thumb tips together.
    HaGRID: 81% of `hand_heart` and `hand_heart2`, and 99% of those where
    both hands were found - fingers curled over each other sometimes hide
    one hand from the detector; 0.02% of the rest."""
    for a, b in itertools.combinations(hands, 2):
        scale = (palm_pixels(a) + palm_pixels(b)) / 2
        pa, pb = a.pixels, b.pixels
        if (np.linalg.norm(pa[INDEX_TIP] - pb[INDEX_TIP]) / scale < 0.9
                and np.linalg.norm(pa[THUMB_TIP] - pb[THUMB_TIP]) / scale < 1.3
                and pa[INDEX_TIP, 1] + pb[INDEX_TIP, 1] < pa[THUMB_TIP, 1] + pb[THUMB_TIP, 1]):
            return True
    return False


def raised_palms(hands, height: int) -> bool:
    """🙌 both palms open and upright, wrists in the upper 60% of the
    frame, and well apart: two palms together are a heart, or a prayer.
    HaGRID has no class for it; it fired on 0 of the 10,450 images."""
    up = [h for h in hands
          if open_palm(h) and upright(h) and h.pixels[WRIST, 1] < 0.6 * height]
    for a, b in itertools.combinations(up, 2):
        scale = (palm_pixels(a) + palm_pixels(b)) / 2
        if np.linalg.norm(a.pixels[MIDDLE_MCP] - b.pixels[MIDDLE_MCP]) / scale > 3.5:
            return True
    return False


def single(hand, min_score: float) -> str | None:
    """The one-hand gesture a hand makes, if any.

    The rules go first. The classifier calls a shaka a thumbs-up and the
    horns 🤟, confidently - on HaGRID's `call`, a third of the hands - so
    asking it first hid both, and fired a thumbs-up for every shaka. Rules
    first: shaka 22% -> 60%, horns 81% -> 88%, and thumbs-up firing on
    other classes 6.7% -> 0.6%."""
    for name, rule in (("Horns", horns), ("Shaka", shaka), ("OK", ok_sign)):
        if rule(hand):
            return name
    if hand.gesture in CLASSIFIED and hand.score >= min_score:
        return hand.gesture
    return None


def both(hands, height: int) -> str | None:
    """A gesture only two hands make together."""
    if heart_hands(hands):
        return "Heart"
    if raised_palms(hands, height):
        return "Raised_Palms"
    return None


class Motion:
    """Waves: a gesture that only exists across frames.

    One open, upright hand whose wrist turns back at least twice within
    WAVE_WINDOW, each swing at least half a palm wide.

    There is no clap. Measured on a real one, the palm detector found a
    hand in 47 of 336 frames and both hands in one: palms in motion blur
    and pressed together edge-on are not what it was trained to see, so
    there is nothing for a rule on landmarks to read.
    """

    WAVE_WINDOW = 1.2

    def __init__(self):
        self.wrists: deque[tuple[float, float, float]] = deque()  # time, x, palm

    def update(self, hands, now: float) -> str | None:
        waving = [h for h in hands if open_palm(h) and upright(h)]
        if len(hands) == 1 and waving:
            self.wrists.append((now, float(waving[0].pixels[WRIST, 0]), palm_pixels(waving[0])))
        else:
            self.wrists.clear()
        while self.wrists and now - self.wrists[0][0] > self.WAVE_WINDOW:
            self.wrists.popleft()

        if self._waved():
            self.wrists.clear()
            return "Wave"
        return None

    def _waved(self) -> bool:
        if len(self.wrists) < 6:
            return False
        palm = float(np.median([p for _, _, p in self.wrists]))
        turns, anchor, direction = 0, self.wrists[0][1], 0
        for _, x, _ in self.wrists:
            if abs(x - anchor) < 0.5 * palm:
                continue
            moving = 1 if x > anchor else -1
            if direction and moving != direction:
                turns += 1
            direction, anchor = moving, x
        return turns >= 2
