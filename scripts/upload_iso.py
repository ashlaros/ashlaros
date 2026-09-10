#!/usr/bin/env python3
"""Upload a built ISO and its checksum to the release bucket.

Version-prefixed, so an older image stays fetchable while a newer one
publishes, and `latest/` is repointed only once the versioned copy is
complete - a download that starts mid-upload would otherwise get a truncated
image that still checksums as whatever arrived.
"""

import argparse
import glob
import os
import sys

import boto3


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso-dir", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    isos = sorted(glob.glob(os.path.join(args.iso_dir, "*.iso")))
    if not isos:
        log("no ISO to upload")
        return 1

    bucket = os.environ["R2_BUCKET"]
    s3 = s3_client()

    for iso in isos:
        name = os.path.basename(iso)
        key = f"{args.version}/{name}"
        s3.upload_file(
            iso,
            bucket,
            key,
            ExtraArgs={"ContentType": "application/x-iso9660-image"},
        )
        log(f"uploaded {key} ({os.path.getsize(iso)} bytes)")

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
    for iso in isos:
        name = os.path.basename(iso)
        s3.copy_object(
            Bucket=bucket,
            Key="latest/ashlaros.iso",
            CopySource={"Bucket": bucket, "Key": f"{args.version}/{name}"},
        )
        log(f"latest/ashlaros.iso now points at {args.version}/{name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
