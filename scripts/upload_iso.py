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
import re
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r2 import log, s3_client


VERSION_IN_NAME = re.compile(r"-(\d{4}\.\d{2}\.\d{2})-")


def version_of(names: list[str]) -> str:
    """The version the images themselves carry.

    Not a date computed here. profiledef.sh stamps the filename at build
    time and this runs after the VM tests, which take about an hour: a run
    that started before midnight UTC and published after it wrote
    `2026.09.17/ashlaros-2026.09.16-x86_64.iso`, and the worker builds the
    `latest/` redirect target from the prefix, so it pointed at a key that
    does not exist.
    """
    found = {m.group(1) for name in names if (m := VERSION_IN_NAME.search(name))}
    if not found:
        raise SystemExit(f"no version in any image name: {', '.join(names)}")
    if len(found) > 1:
        raise SystemExit(f"images disagree about the version: {', '.join(sorted(found))}")
    return found.pop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso-dir", required=True)
    args = parser.parse_args()

    # (glob, content type, the latest/ alias it repoints)
    ARTEFACTS = (
        ("*.iso", "application/x-iso9660-image", "latest/ashlaros.iso"),
        ("*.img.xz", "application/x-xz", "latest/ashlaros-rpi5.img.xz"),
    )

    # The Pi build writes its checksum as SHA256SUMS.<image>, which *.img.xz
    # also matches - uploaded as an artefact it would repoint latest/ at a
    # 90-byte text file. Checksums are handled separately below.
    found = [
        (path, content_type, alias)
        for pattern, content_type, alias in ARTEFACTS
        for path in sorted(glob.glob(os.path.join(args.iso_dir, pattern)))
        if not os.path.basename(path).startswith("SHA256SUMS")
    ]
    if not found:
        log("nothing to upload")
        return 1

    version = version_of([os.path.basename(path) for path, _, _ in found])
    log(f"publishing {version}, read from the image names")

    # The release tag and its notes URL have to name the same version the
    # bucket got, so the workflow reads it back from here rather than
    # computing a second date of its own.
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"version={version}\n")

    bucket = os.environ["R2_BUCKET"]
    s3 = s3_client()

    for path, content_type, _ in found:
        name = os.path.basename(path)
        key = f"{version}/{name}"
        s3.upload_file(path, bucket, key, ExtraArgs={"ContentType": content_type})
        log(f"uploaded {key} ({os.path.getsize(path)} bytes)")

    # SHA256SUMS from the ISO build, SHA256SUMS.<image> from the Pi one:
    # the two products publish under the same version prefix from separate
    # workflows, so the image cannot use the bare name without clobbering
    # the ISO's. Matching the prefix uploads whichever this build wrote,
    # rather than silently skipping the checksum that proves the image.
    checksums = sorted(glob.glob(os.path.join(args.iso_dir, "SHA256SUMS*")))
    if not checksums:
        raise SystemExit("no SHA256SUMS beside the artefact")
    for path in checksums:
        name = os.path.basename(path)
        s3.upload_file(
            path,
            bucket,
            f"{version}/{name}",
            ExtraArgs={"ContentType": "text/plain"},
        )
        log(f"uploaded {version}/{name}")

    # Last, and a pointer rather than a copy of the image. This used to be
    # a server-side copy: 1.7 GB duplicated per release, and worse than
    # wasteful. `latest/` is repointed every release, so a client resuming
    # a download across one asked for a byte range of an object that had
    # been replaced underneath it - serve.js honours If-Range to refuse
    # exactly that, and the refusal is a restarted download either way.
    #
    # The pointer holds the version string and nothing else. The worker
    # reads it and answers 302 to the versioned object, which is immutable,
    # so a resume targets a URL that cannot change under it. It also means
    # this key never needs pruning: it is the same dozen bytes forever.
    for path, _, alias in found:
        name = os.path.basename(path)
        s3.put_object(
            Bucket=bucket,
            Key=alias,
            Body=version.encode(),
            ContentType="text/plain",
            # the pointer changes every release and is tiny; a cache that
            # held it would pin the whole site to an old image
            CacheControl="no-cache",
        )
        log(f"{alias} -> {version}/{name}")

    prune_old_versions(s3, bucket, keep=5)

    return 0


def prune_old_versions(s3, bucket: str, keep: int) -> None:
    """Delete all but the newest `keep` release prefixes.

    Nothing removed these before, and a daily build publishes an image a
    day. Versions are YYYY.MM.DD, so lexical order is chronological and
    the newest `keep` are simply the tail.

    Whole prefixes, not just the images: a version's checksum and
    signature are worthless once its image is gone, and leaving them
    behind is how a bucket accumulates files nothing references.

    `latest/` is never a candidate - it is not a version prefix, and it
    points at the newest release, which is by definition kept.
    """
    versions = set()
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Delimiter="/"):
        for prefix in page.get("CommonPrefixes", []):
            name = prefix["Prefix"].rstrip("/")
            # a release prefix and nothing else: latest/, screenshots and
            # anything added later must not be swept up by this
            if re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", name):
                versions.add(name)

    doomed = sorted(versions)[:-keep] if len(versions) > keep else []
    if not doomed:
        log(f"{len(versions)} release(s) in the bucket; nothing to prune")
        return

    for version in doomed:
        for page in paginator.paginate(Bucket=bucket, Prefix=f"{version}/"):
            for obj in page.get("Contents", []):
                s3.delete_object(Bucket=bucket, Key=obj["Key"])
                log(f"pruned {obj['Key']}")


if __name__ == "__main__":
    sys.exit(main())
