"""Hands and their gestures, with the models MediaPipe's gesture recognizer ships.

The models are Google's gesture_recognizer.task, unpacked at build time: a
palm detector, a hand landmark model, a gesture embedder and a classifier.
The `mediapipe` wheel that normally drives them is not used - Arch does not
package it, and the current release kills its own process on Python 3.14 -
so the graph it would run is reproduced here from MediaPipe's calculators,
constant for constant: the SSD anchors, the weighted NMS, the rect
transformations, the landmark projection and the landmark normalisation the
embedder expects. OpenCV runs the two image networks; tflite.py runs the
two small ones.

Each step names the calculator it stands in for, so a disagreement with
MediaPipe can be traced to one function.
"""

import io
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import tflite

DETECTOR_SIZE = 192
LANDMARK_SIZE = 224
# GestureRecognizerOptions' defaults: detection, presence and tracking
MIN_DETECTION = 0.5
MIN_PRESENCE = 0.5
MIN_TRACKING_IOU = 0.5
# TensorsToLandmarksCalculator's normalize_z for this model
LANDMARK_Z_SCALE = 0.4
# HandLandmarksToRectCalculator only looks at the palm and the finger bases
RECT_LANDMARKS = [0, 1, 2, 3, 5, 6, 9, 10, 13, 14, 17, 18]


@dataclass
class Rect:
    """A NormalizedRect: centre and size as fractions of the image, radians."""

    x: float
    y: float
    w: float
    h: float
    rotation: float


@dataclass
class Hand:
    landmarks: np.ndarray  # (21, 3): x and y as fractions of the image
    gesture: str
    score: float
    next_rect: Rect  # where to look for this hand in the next frame


def _normalize_radians(angle: float) -> float:
    return angle - 2 * math.pi * math.floor((angle + math.pi) / (2 * math.pi))


def _anchors() -> np.ndarray:
    """SsdAnchorsCalculator for this detector: strides 8, 16, 16, 16 with
    two fixed-size anchors per layer, the three stride-16 layers sharing a
    grid - so 2 per cell on the 24x24 grid and 6 on the 12x12."""
    out = []
    for stride, per_cell in ((8, 2), (16, 6)):
        cells = DETECTOR_SIZE // stride
        ys, xs = np.mgrid[0:cells, 0:cells]
        centres = np.stack([(xs + 0.5) / cells, (ys + 0.5) / cells], -1).reshape(-1, 2)
        out.append(np.repeat(centres, per_cell, axis=0))
    return np.concatenate(out).astype(np.float32)


def _crop(image: np.ndarray, rect: Rect, size: int, border: int) -> np.ndarray:
    """ImageToTensorCalculator's OpenCV path: the rotated rect, warped to a
    square tensor, as a normalised RGB blob."""
    height, width = image.shape[:2]
    box = cv2.boxPoints(
        ((rect.x * width, rect.y * height), (rect.w * width, rect.h * height),
         math.degrees(rect.rotation))
    )
    corners = np.float32([[0, size], [0, 0], [size, 0], [size, size]])
    matrix = cv2.getPerspectiveTransform(box.astype(np.float32), corners)
    crop = cv2.warpPerspective(image, matrix, (size, size), flags=cv2.INTER_LINEAR,
                               borderMode=border)
    # NCHW: the classic engine only gets channels right in that order
    return cv2.dnn.blobFromImage(crop, 1 / 255, swapRB=True)


def _transform(rect: Rect, width: int, height: int, scale: float, shift_y: float) -> Rect:
    """RectTransformationCalculator with square_long, in image proportions."""
    sin, cos = math.sin(rect.rotation), math.cos(rect.rotation)
    x = rect.x - height * rect.h * shift_y * sin / width
    y = rect.y + rect.h * shift_y * cos
    side = max(rect.w * width, rect.h * height)
    return Rect(x, y, side / width * scale, side / height * scale, rect.rotation)


def _iou(a: Rect, b: Rect) -> float:
    """Axis-aligned overlap, which is what the association calculator uses."""
    left = max(a.x - a.w / 2, b.x - b.w / 2)
    right = min(a.x + a.w / 2, b.x + b.w / 2)
    top = max(a.y - a.h / 2, b.y - b.h / 2)
    bottom = min(a.y + a.h / 2, b.y + b.h / 2)
    inter = max(0.0, right - left) * max(0.0, bottom - top)
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union > 0 else 0.0


def _weighted_nms(boxes: np.ndarray, keypoints: np.ndarray, scores: np.ndarray, limit: int):
    """NonMaxSuppressionCalculator, WEIGHTED, IoU 0.3: overlapping boxes are
    averaged by score rather than dropped, which steadies the palm box."""
    order = list(np.argsort(-scores))
    kept = []
    while order and len(kept) < limit:
        first = boxes[order[0]]
        group, rest = [], []
        for i in order:
            box = boxes[i]
            inter_w = min(first[2], box[2]) - max(first[0], box[0])
            inter_h = min(first[3], box[3]) - max(first[1], box[1])
            inter = max(0.0, inter_w) * max(0.0, inter_h)
            union = ((first[2] - first[0]) * (first[3] - first[1])
                     + (box[2] - box[0]) * (box[3] - box[1]) - inter)
            (group if union > 0 and inter / union > 0.3 else rest).append(i)
        weights = scores[group][:, None]
        kept.append((
            (boxes[group] * weights).sum(0) / weights.sum(),
            (keypoints[group] * weights[:, :, None]).sum(0) / weights.sum(),
        ))
        order = rest
    return kept


def _normalize_object(points: np.ndarray) -> np.ndarray:
    """LandmarksToMatrixCalculator's object normalisation, origin the wrist."""
    points = points - points[0]
    scale = max(np.ptp(points[:, 0]), np.ptp(points[:, 1])) + 1e-5
    return points / scale


class Hands:
    def __init__(self, models: Path, max_hands: int = 2):
        # by path, not from memory: readNetFromTFLite ignores the engine
        # argument for a buffer and picks the new engine, which runs these
        # two networks with their outputs fused into one
        def net(name):
            return cv2.dnn.readNetFromTFLite(str(models / name), engine=cv2.dnn.ENGINE_CLASSIC)

        self.detector = net("hand_detector.tflite")
        self.landmarker = net("hand_landmarks_detector.tflite")
        self.embedder = tflite.Model((models / "gesture_embedder.tflite").read_bytes())
        classifier = (models / "canned_gesture_classifier.tflite").read_bytes()
        self.classifier = tflite.Model(classifier)
        # the labels ride in a zip appended to the model, as TFLite metadata
        # does; read rather than restated, so a new model cannot shift them
        with zipfile.ZipFile(io.BytesIO(classifier)) as metadata:
            self.labels = metadata.read("labels.txt").decode().split()
        self.anchors = _anchors()
        self.max_hands = max_hands
        self.tracked: list[Rect] = []

    def process(self, image: np.ndarray) -> list[Hand]:
        """Hands in a BGR frame. Hands found in the last frame are followed
        from where they were; the detector only runs while fewer than
        max_hands are being followed, as MediaPipe's VIDEO mode does."""
        hands = [h for h in (self._hand(image, r) for r in self.tracked) if h]
        if len(hands) < self.max_hands:
            for rect in self._detect(image):
                if any(_iou(rect, h.next_rect) > MIN_TRACKING_IOU for h in hands):
                    continue
                hand = self._hand(image, rect)
                if hand and not any(_iou(hand.next_rect, h.next_rect) > MIN_TRACKING_IOU
                                    for h in hands):
                    hands.append(hand)
                if len(hands) == self.max_hands:
                    break
        self.tracked = [h.next_rect for h in hands]
        return hands

    def _detect(self, image: np.ndarray) -> list[Rect]:
        height, width = image.shape[:2]
        side = max(width, height)
        # letterboxed with zeros, as the hand detector graph asks for
        self.detector.setInput(_crop(image, Rect(0.5, 0.5, side / width, side / height, 0),
                                     DETECTOR_SIZE, cv2.BORDER_CONSTANT))
        raw, logits = self.detector.forward(["Identity", "Identity_1"])
        raw, logits = raw.reshape(-1, 18), logits.reshape(-1)

        scores = 1 / (1 + np.exp(-np.clip(logits, -100, 100)))
        keep = scores >= MIN_DETECTION
        if not keep.any():
            return []
        raw, scores, anchors = raw[keep] / DETECTOR_SIZE, scores[keep], self.anchors[keep]
        centre, size = raw[:, :2] + anchors, raw[:, 2:4]
        boxes = np.concatenate([centre - size / 2, centre + size / 2], 1)
        keypoints = raw[:, 4:].reshape(-1, 7, 2) + anchors[:, None, :]

        # DetectionLetterboxRemovalCalculator: back from the padded square
        pad = np.array([(1 - width / side) / 2, (1 - height / side) / 2])
        rects = []
        for padded_box, padded_points in _weighted_nms(boxes, keypoints, scores, self.max_hands):
            box = ((padded_box.reshape(2, 2) - pad) / (1 - 2 * pad)).reshape(-1)
            points = (padded_points - pad) / (1 - 2 * pad)
            # DetectionsToRectsCalculator: rotated so the wrist-to-middle-
            # finger line points up
            dx = (points[2, 0] - points[0, 0]) * width
            dy = (points[2, 1] - points[0, 1]) * height
            rotation = _normalize_radians(math.pi / 2 - math.atan2(-dy, dx))
            rect = Rect((box[0] + box[2]) / 2, (box[1] + box[3]) / 2,
                        box[2] - box[0], box[3] - box[1], rotation)
            rects.append(_transform(rect, width, height, scale=2.6, shift_y=-0.5))
        return rects

    def _hand(self, image: np.ndarray, rect: Rect) -> Hand | None:
        height, width = image.shape[:2]
        self.landmarker.setInput(_crop(image, rect, LANDMARK_SIZE, cv2.BORDER_REPLICATE))
        screen, presence, handedness, world = self.landmarker.forward(
            ["Identity", "Identity_1", "Identity_2", "Identity_3"])
        if presence.item() < MIN_PRESENCE:
            return None

        # LandmarkProjectionCalculator: from the rotated crop to the image
        local = screen.reshape(21, 3) / LANDMARK_SIZE
        sin, cos = math.sin(rect.rotation), math.cos(rect.rotation)
        x, y = local[:, 0] - 0.5, local[:, 1] - 0.5
        landmarks = np.stack([
            (cos * x - sin * y) * rect.w + rect.x,
            (sin * x + cos * y) * rect.h + rect.y,
            local[:, 2] / LANDMARK_Z_SCALE * rect.w,
        ], 1)
        # WorldLandmarkProjectionCalculator: the same rotation, in metres
        world = world.reshape(21, 3)
        world = np.stack([cos * world[:, 0] - sin * world[:, 1],
                          sin * world[:, 0] + cos * world[:, 1], world[:, 2]], 1)

        gesture, score = self._gesture(landmarks, world, handedness.item(), width, height)
        return Hand(landmarks, gesture, score, self._next_rect(landmarks, width, height))

    def _gesture(self, landmarks, world, right_score, width, height) -> tuple[str, float]:
        # LandmarksToMatrixCalculator: square pixels first, then the object
        # normalisation, for screen and world landmarks alike
        longest = max(width, height)
        screen = landmarks.copy()
        screen[:, 0] = (screen[:, 0] - 0.5) * width / longest + 0.5
        screen[:, 1] = (screen[:, 1] - 0.5) * height / longest + 0.5
        embedding = self.embedder(
            _normalize_object(screen)[None].astype(np.float32),
            # the model's binary handedness output is already P(right)
            np.array([[right_score]], np.float32),
            _normalize_object(world)[None].astype(np.float32),
        )[0]
        probabilities = self.classifier(embedding)[0][0]
        best = int(np.argmax(probabilities))
        return self.labels[best], float(probabilities[best])

    def _next_rect(self, landmarks: np.ndarray, width: int, height: int) -> Rect:
        """HandLandmarksToRectCalculator, then the tracking transformation."""
        points = landmarks[RECT_LANDMARKS, :2] * [width, height]
        # indices into the partial list: wrist, and the index, middle and
        # ring finger bases, whose blend is the direction the hand points
        tip = ((points[4] + points[8]) / 2 + points[6]) / 2
        rotation = _normalize_radians(
            math.pi / 2 - math.atan2(-(tip[1] - points[0, 1]), tip[0] - points[0, 0]))

        centre = (points.min(0) + points.max(0)) / 2
        sin, cos = math.sin(-rotation), math.cos(-rotation)
        offset = points - centre
        upright = np.stack([offset[:, 0] * cos - offset[:, 1] * sin,
                            offset[:, 0] * sin + offset[:, 1] * cos], 1)
        low, high = upright.min(0), upright.max(0)
        mid = (low + high) / 2
        sin, cos = math.sin(rotation), math.cos(rotation)
        x = mid[0] * cos - mid[1] * sin + centre[0]
        y = mid[0] * sin + mid[1] * cos + centre[1]
        rect = Rect(x / width, y / height, (high[0] - low[0]) / width,
                    (high[1] - low[1]) / height, rotation)
        return _transform(rect, width, height, scale=2.0, shift_y=-0.1)
