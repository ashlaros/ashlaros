"""The virtual camera: a v4l2loopback device this process writes frames to.

Plain ioctls through fcntl, because the two things needed beyond write()
have no Python binding anywhere Arch packages: setting the output format,
and v4l2loopback's own "client usage" event, which says when an
application starts or stops reading. That event is what keeps the real
camera - and its light - off while nobody is watching.

The struct layouts are linux/videodev2.h's on a 64-bit kernel and
v4l2loopback.h's, version 0.15; sizes are encoded in the ioctl numbers, so
a mismatch fails with EINVAL rather than corrupting anything.
"""

import fcntl
import os
import select
import struct
from pathlib import Path

VIDIOC_S_FMT = 0xC0D05605
VIDIOC_S_PARM = 0xC0CC5616
VIDIOC_SUBSCRIBE_EVENT = 0x4020565A
VIDIOC_DQEVENT = 0x80885659

V4L2_BUF_TYPE_VIDEO_OUTPUT = 2
V4L2_PIX_FMT_YUYV = 0x56595559
V4L2_FIELD_NONE = 1
V4L2_COLORSPACE_SRGB = 8
V4L2_EVENT_SUB_FL_SEND_INITIAL = 1
# V4L2_EVENT_PRIVATE_START + v4l2loopback's own offset + 1
V4L2_EVENT_PRI_CLIENT_USAGE = 0x08000000 + 0x08E00000 + 1

CARD_LABEL = "AshlarOS Camera"


def find_device() -> Path | None:
    """The loopback node the modprobe.d options name, by its label: the
    number is whatever was free when the module loaded."""
    for node in sorted(Path("/sys/class/video4linux").glob("video*")):
        try:
            if (node / "name").read_text().strip() == CARD_LABEL:
                return Path("/dev") / node.name
        except OSError:
            continue
    return None


class Loopback:
    def __init__(self, device: Path, width: int, height: int, fps: int):
        self.fd = os.open(device, os.O_RDWR | os.O_NONBLOCK)
        self.size = width * height * 2

        # struct v4l2_format: the type, padding to 8, then v4l2_pix_format
        pix = struct.pack("<12I", width, height, V4L2_PIX_FMT_YUYV, V4L2_FIELD_NONE,
                          width * 2, self.size, V4L2_COLORSPACE_SRGB, 0, 0, 0, 0, 0)
        fmt = struct.pack("<I4x", V4L2_BUF_TYPE_VIDEO_OUTPUT) + pix
        fcntl.ioctl(self.fd, VIDIOC_S_FMT, bytearray(fmt.ljust(208, b"\0")))

        # struct v4l2_streamparm with v4l2_outputparm: what readers are told
        # the frame rate is
        parm = struct.pack("<5I", V4L2_BUF_TYPE_VIDEO_OUTPUT, 0, 0, 1, fps)
        fcntl.ioctl(self.fd, VIDIOC_S_PARM, bytearray(parm.ljust(204, b"\0")))

        # struct v4l2_event_subscription: type, id, flags, reserved[5]
        sub = struct.pack("<3I20x", V4L2_EVENT_PRI_CLIENT_USAGE, 0,
                          V4L2_EVENT_SUB_FL_SEND_INITIAL)
        fcntl.ioctl(self.fd, VIDIOC_SUBSCRIBE_EVENT, bytearray(sub))
        self.poll = select.poll()
        self.poll.register(self.fd, select.POLLPRI)
        self.readers = 0

    def write(self, yuyv: bytes):
        os.write(self.fd, yuyv)

    def wait(self, timeout_ms: int | None) -> int:
        """Applies every pending usage event and returns whether anyone is
        reading; blocks up to timeout_ms for the first one (None: forever)."""
        while self.poll.poll(timeout_ms):
            event = bytearray(136)
            try:
                fcntl.ioctl(self.fd, VIDIOC_DQEVENT, event)
            except BlockingIOError:
                break
            # struct v4l2_event: type, then the payload union at offset 8,
            # whose first field is v4l2_event_client_usage.count
            if struct.unpack_from("<I", event, 0)[0] == V4L2_EVENT_PRI_CLIENT_USAGE:
                self.readers = struct.unpack_from("<I", event, 8)[0]
            timeout_ms = 0
        return self.readers

    def close(self):
        os.close(self.fd)
