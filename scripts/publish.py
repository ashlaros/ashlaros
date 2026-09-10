#!/usr/bin/env python3
"""Publish built packages into an architecture's repository tree on R2.

The bucket holds one tree per architecture:

    x86_64/ashlaros.db.tar.gz  + the packages it indexes
    aarch64/ashlaros.db.tar.gz + the packages it indexes

Order matters. Packages and their signatures upload first, the database
last, so a client that fetches the database mid-publish never sees an entry
whose package is not there yet.

`arch=any` packages are built once and registered in both databases -
pacman accepts an `any` package from either tree. The workflow hands the
same artifacts to both architecture legs rather than this script writing
two trees in one run, so a failure in one leg cannot leave the other's
database referencing packages it never uploaded.
"""

import argparse
import glob
import os
import subprocess
import sys

import boto3
from botocore.exceptions import ClientError

DB_NAME = "ashlaros"
# repo-add writes .db and .files as symlinks to the .tar.gz; both names are
# published because pacman fetches the short one and tooling reads the long
DB_SUFFIXES = (".db", ".db.tar.gz", ".files", ".files.tar.gz")


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


# Arch compresses packages with zstd; Arch Linux ARM still uses xz, and
# makepkg's PKGEXT follows whichever distribution built them.
PKG_SUFFIXES = (".pkg.tar.zst", ".pkg.tar.xz")


def packages_in(directory: str) -> list[str]:
    return sorted(
        path
        for suffix in PKG_SUFFIXES
        for path in glob.glob(os.path.join(directory, f"*{suffix}"))
    )


def pkgname_of(filename: str) -> str:
    """The package name out of a filename.

    A filename is name-version-release-arch.pkg.tar.<ext>, and a name may
    hold hyphens, so strip the three known trailing fields rather than split.
    """
    stem = filename.removesuffix(".sig")
    for suffix in PKG_SUFFIXES:
        stem = stem.removesuffix(suffix)
    return stem.rsplit("-", 3)[0]


def download_databases(s3, bucket: str, prefix: str, pkg_dir: str) -> None:
    """Fetch the existing databases so repo-add extends rather than replaces them.

    Both must come down: repo-add updates whichever files it finds and
    creates the rest from scratch, so publishing with only .db present
    rebuilds .files from this build alone and drops every other package's
    file list.
    """
    for suffix in (".db.tar.gz", ".files.tar.gz"):
        name = f"{DB_NAME}{suffix}"
        local = os.path.join(pkg_dir, name)
        try:
            s3.download_file(bucket, prefix + name, local)
            log(f"downloaded existing {name}")
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("NoSuchKey", "404"):
                raise
            log(f"no {name} yet; repo-add will create one")


def prune_superseded(s3, bucket: str, prefix: str, published: list[str]) -> None:
    """Drop older versions of the packages just published.

    The database only ever references the current version, so an older
    object is unreachable; leaving it would grow the bucket without end.
    """
    keep = set(published)
    names = {pkgname_of(name) for name in published}

    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            name = obj["Key"].removeprefix(prefix)
            if not name.endswith(PKG_SUFFIXES + tuple(s + ".sig" for s in PKG_SUFFIXES)):
                continue
            if name in keep or f"{name}.sig" in keep or name.removesuffix(".sig") in keep:
                continue
            if pkgname_of(name) in names:
                s3.delete_object(Bucket=bucket, Key=obj["Key"])
                log(f"pruned superseded {name}")


def publish(s3, bucket: str, arch: str, pkg_dir: str, packages: list[str], key: str | None) -> None:
    prefix = f"{arch}/"
    db_file = os.path.join(pkg_dir, f"{DB_NAME}.db.tar.gz")

    download_databases(s3, bucket, prefix, pkg_dir)

    # --include-sigs records each package's signature in the database, as
    # every Arch repository does: tooling expects the field, and pacman -Si
    # can then report a signer without fetching the package. --sign is
    # unrelated - it signs the database itself, without which the package
    # list is forgeable.
    repo_add = ["repo-add", "--include-sigs", db_file, *packages]
    if key:
        repo_add[1:1] = ["--sign", "--key", key]
    subprocess.run(repo_add, check=True)

    for package in packages:
        name = os.path.basename(package)
        s3.upload_file(package, bucket, prefix + name)
        log(f"{arch}: uploaded {name}")
        signature = package + ".sig"
        if os.path.exists(signature):
            s3.upload_file(signature, bucket, prefix + os.path.basename(signature))

    prune_superseded(s3, bucket, prefix, [os.path.basename(p) for p in packages])

    # the database goes last: until it names them, the objects above are
    # simply unreferenced, and a client mid-publish sees the old repository
    for suffix in DB_SUFFIXES:
        for name in (f"{DB_NAME}{suffix}", f"{DB_NAME}{suffix}.sig"):
            local = os.path.join(pkg_dir, name)
            # repo-add writes .db/.files as symlinks; upload the real bytes
            real = os.path.realpath(local)
            if not os.path.exists(real):
                continue
            s3.upload_file(real, bucket, prefix + name)
            log(f"{arch}: uploaded {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pkg-dir", required=True, help="directory of built packages")
    parser.add_argument("--arch", required=True, help="architecture tree to publish into")
    args = parser.parse_args()

    packages = packages_in(args.pkg_dir)
    if not packages:
        log("no packages to publish")
        return 1

    bucket = os.environ["R2_BUCKET"]
    key = os.environ.get("GPG_KEYID")
    s3 = s3_client()

    # a database left by an earlier run would be extended rather than
    # rebuilt from what this bucket actually holds
    for stale in glob.glob(os.path.join(args.pkg_dir, f"{DB_NAME}.*")):
        os.remove(stale)

    publish(s3, bucket, args.arch, args.pkg_dir, packages, key)

    log(f"published {len(packages)} package(s) to {args.arch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
