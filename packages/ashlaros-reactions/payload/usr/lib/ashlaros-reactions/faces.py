"""Where the face is, for the gestures made relative to it.

A salute is a hand at the brow and a 👋👋 is palms either side of the
head, and neither can be told from a hand in the same shape elsewhere
without knowing where the head is. YuNet answers that: OpenCV's own face
detector, 227 KB, and FaceDetectorYN runs it with nothing else installed.
At a quarter of the 720p frame it takes about 2 ms.
"""

from pathlib import Path

import cv2
import numpy as np

# a quarter of each side: a face fills far more of a call's frame than the
# 10 px YuNet can still find, and the cost falls with the square
SCALE = 4


class Faces:
    def __init__(self, model: Path):
        self.detector = cv2.FaceDetectorYN.create(str(model), "", (320, 180), 0.6, 0.3, 5)
        self.size = (0, 0)

    def find(self, image: np.ndarray) -> list[np.ndarray]:
        """Face boxes in pixels of `image`: x, y, width, height."""
        height, width = image.shape[:2]
        size = (width // SCALE, height // SCALE)
        if size != self.size:
            self.detector.setInputSize(size)
            self.size = size
        _, found = self.detector.detect(cv2.resize(image, size, interpolation=cv2.INTER_AREA))
        return [] if found is None else [row[:4] * SCALE for row in found]
