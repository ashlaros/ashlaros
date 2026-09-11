#!/usr/bin/env python3
"""Upload desktop screenshots to the ISO bucket.

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

    return 0


if __name__ == "__main__":
    sys.exit(main())
