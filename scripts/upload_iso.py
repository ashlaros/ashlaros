#!/usr/bin/env python3
"""Upload a built image and its checksum to the release bucket.

Version-prefixed, so an older image stays fetchable while a newer one
publishes, and `latest/` is repointed only once the versioned copy is
complete - a download that starts mid-upload would otherwise get a truncated
image that still checksums as whatever arrived.

Two artefact types share this path: the x86_64 ISO and the Raspberry Pi
disk image. They are different products - different arch, different boot
mechanism, no installer on the Pi - so each has its own `latest/` alias
and neither can overwrite the other's.
"""

import argparse
import glob
import os
import sys

import boto3
from botocore.config import Config


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def s3_client():
    # R2 copies an object server-side, and a 1.7 GB image takes minutes -
    # well past botocore's 60s default, which failed the build after a
    # successful upload with "Read timeout on .../latest/ashlaros.iso".
    # The copy itself had started; only the client gave up waiting.
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(read_timeout=900, connect_timeout=60, retries={"max_attempts": 3}),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso-dir", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    # (glob, content type, the latest/ alias it repoints)
    ARTEFACTS = (
        ("*.iso", "application/x-iso9660-image", "latest/ashlaros.iso"),
        ("*.img.xz", "application/x-xz", "latest/ashlaros-rpi5.img.xz"),
    )

    found = [
        (path, content_type, alias)
        for pattern, content_type, alias in ARTEFACTS
        for path in sorted(glob.glob(os.path.join(args.iso_dir, pattern)))
    ]
    if not found:
        log("nothing to upload")
        return 1

    bucket = os.environ["R2_BUCKET"]
    s3 = s3_client()

    for path, content_type, _ in found:
        name = os.path.basename(path)
        key = f"{args.version}/{name}"
        s3.upload_file(path, bucket, key, ExtraArgs={"ContentType": content_type})
        log(f"uploaded {key} ({os.path.getsize(path)} bytes)")

    checksums = os.path.join(args.iso_dir, "SHA256SUMS")
    if os.path.exists(checksums):
        s3.upload_file(
            checksums,
            bucket,
            f"{args.version}/SHA256SUMS",
            ExtraArgs={"ContentType": "text/plain"},
        )
        log(f"uploaded {args.version}/SHA256SUMS")

    # last, and by server-side copy rather than a second upload of the same
    # bytes: until this points at the new image, latest/ still serves the
    # previous one whole
    for path, _, alias in found:
        name = os.path.basename(path)
        source = f"{args.version}/{name}"
        s3.copy_object(
            Bucket=bucket,
            Key=alias,
            CopySource={"Bucket": bucket, "Key": source},
        )
        # a copy that returned is not necessarily a copy that landed whole;
        # the size is the cheapest thing that would catch a truncated one
        expected = os.path.getsize(path)
        actual = s3.head_object(Bucket=bucket, Key=alias)["ContentLength"]
        if actual != expected:
            raise SystemExit(f"{alias} is {actual} bytes, expected {expected}")
        log(f"{alias} now points at {source} ({actual} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
