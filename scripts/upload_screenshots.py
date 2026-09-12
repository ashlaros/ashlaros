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
import sys

import boto3


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


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
        # nobody would notice until someone pressed play
        if os.path.getsize(video) == 0:
            log(f"{video} is empty, refusing to publish it")
            return 1
        key = f"latest/video/{os.path.basename(video)}"
        s3.upload_file(video, bucket, key, ExtraArgs={"ContentType": "video/webm"})
        log(f"uploaded {key} ({os.path.getsize(video)} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
