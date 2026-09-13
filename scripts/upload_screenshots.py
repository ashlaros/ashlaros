#!/usr/bin/env python3
"""Upload desktop screenshots and the tour video to the ISO bucket.

Only under `latest/screenshots/`, never under a version prefix. The shots
come from a container running whatever `ashlaros-settings` currently
publishes, which moves independently of the ISO: writing them under
`<version>/screenshots/` would say "this is what that ISO looked like" while
meaning "what the desktop looked like whenever this last ran". The ISO build
is welcome to publish its own versioned shots; this job does not pretend to.
"""

import argparse
import glob
import os
import subprocess
import sys

import boto3


# The tour is three scenes with holds, so a whole recording has hundreds
# of packets; a handful means it stopped early whatever the header claims.
MIN_FRAMES = 30


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def video_is_whole(path: str) -> tuple[bool, str]:
    """Whether the stream decodes to its end, and what was found.

    Not the container's duration: that is written in the header, so a file
    cut off mid-recording still claims the full length - a truncated tour
    missing 88% of its frames reported the same 34.285s as the whole one,
    and would have been published over a working video. Decoding is what
    knows the difference, and `-f null` throws the output away, so this
    costs a decode and no disk.
    """
    try:
        decode = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"could not run ffmpeg: {error}"
    if decode.returncode != 0:
        return False, f"ffmpeg exited {decode.returncode}"
    # ffmpeg reports a short file on stderr and still exits 0, so the exit
    # code alone would pass a truncated recording
    if decode.stderr.strip():
        return False, decode.stderr.strip().splitlines()[0]

    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-count_packets",
                "-select_streams", "v:0",
                "-show_entries", "stream=nb_read_packets",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"could not run ffprobe: {error}"
    try:
        frames = int(probe.stdout.strip())
    except ValueError:
        return False, "no video stream"
    if frames < MIN_FRAMES:
        return False, f"only {frames} frames"
    return True, f"{frames} frames"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shot-dir", required=True)
    args = parser.parse_args()

    shots = sorted(glob.glob(os.path.join(args.shot_dir, "*.png")))
    if not shots:
        log("no screenshots to upload")
        return 1

    # the tour, when the recording job produced one. Same prefix rule and
    # the same reason: it is what the desktop looked like whenever this
    # last ran, not what a given ISO contains.
    videos = sorted(glob.glob(os.path.join(args.shot_dir, "*.webm")))

    bucket = os.environ["R2_BUCKET"]
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )

    for shot in shots:
        key = f"latest/screenshots/{os.path.basename(shot)}"
        s3.upload_file(shot, bucket, key, ExtraArgs={"ContentType": "image/png"})
        log(f"uploaded {key} ({os.path.getsize(shot)} bytes)")

    for video in videos:
        # an empty or truncated file would publish over a working tour and
        # nobody would notice until someone pressed play. Size alone does
        # not catch a recording cut off mid-stream: that file is large and
        # looks fine. Only a decode does, so ffprobe has to agree the
        # container reports a duration before this overwrites a tour that
        # works.
        if os.path.getsize(video) == 0:
            log(f"{video} is empty, refusing to publish it")
            return 1
        whole, detail = video_is_whole(video)
        if not whole:
            log(f"{video} is not a whole video ({detail}), refusing to publish it")
            return 1
        log(f"{video} decodes to its end ({detail})")
        key = f"latest/video/{os.path.basename(video)}"
        s3.upload_file(video, bucket, key, ExtraArgs={"ContentType": "video/webm"})
        log(f"uploaded {key} ({os.path.getsize(video)} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
