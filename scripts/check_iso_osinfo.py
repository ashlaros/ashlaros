#!/usr/bin/env python3
"""Fail if the built ISO no longer matches the osinfo entry we published.

Virtualisation tools recognise a medium by regex-matching four strings in
the ISO9660 primary volume descriptor against osinfo-db (#85). Those
strings come from `iso/profiledef.sh`, and the regexes live in
`packages/ashlaros-osinfo/ashlaros-rolling.xml.in` and in an entry
upstream that we cannot edit on our own schedule.

So renaming the volume label silently un-detects us, and nothing notices
until someone opens GNOME Boxes and gets "Operating System not found" -
with, worse, a BIOS VM that a UEFI-only ISO cannot boot.

The descriptor is 2 KiB at a fixed offset, so this costs a seek.
"""

import argparse
import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "packages/ashlaros-osinfo/ashlaros-rolling.xml.in"

# ISO9660: the primary volume descriptor is the first one, at sector 16,
# and every field below is a fixed offset into it.
PVD_OFFSET = 16 * 2048
FIELDS = {
    "system-id": (8, 40),
    "volume-id": (40, 72),
    "publisher-id": (318, 446),
    "application-id": (574, 702),
}


def read_pvd(iso: Path) -> dict[str, str]:
    with iso.open("rb") as handle:
        handle.seek(PVD_OFFSET)
        pvd = handle.read(2048)

    if pvd[1:6] != b"CD001" or pvd[0] != 1:
        raise SystemExit(f"{iso}: no primary volume descriptor at {PVD_OFFSET}")

    values = {
        name: pvd[start:end].decode("ascii", "replace").rstrip()
        for name, (start, end) in FIELDS.items()
    }
    # the size libosinfo compares against, in bytes
    values["volume-size"] = str(struct.unpack("<I", pvd[80:84])[0] * 2048)
    return values


def entry_patterns() -> dict[str, str]:
    """The regexes the published entry matches a medium with."""
    iso = ET.parse(ENTRY).getroot().find(".//media/iso")
    if iso is None:
        raise SystemExit(f"{ENTRY}: no <media><iso> element")
    return {child.tag: (child.text or "") for child in iso}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", type=Path, required=True, help="the built ISO")
    args = parser.parse_args()

    if not args.iso.is_file():
        print(f"no such ISO: {args.iso}", file=sys.stderr)
        return 2

    published = read_pvd(args.iso)
    patterns = entry_patterns()

    if not patterns:
        print(f"{ENTRY} matches on nothing, so it matches no medium", file=sys.stderr)
        return 1

    failures = []
    for field, pattern in patterns.items():
        value = published.get(field)
        if value is None:
            failures.append(f"{field}: the entry matches on it, the descriptor has no such field")
        # libosinfo anchors each regex against the whole field
        elif not re.fullmatch(pattern, value):
            failures.append(f"{field}: {value!r} does not match {pattern!r}")
        else:
            print(f"  {field}: {value!r} matches")

    for failure in failures:
        print(f"unmatched: {failure}", file=sys.stderr)

    if failures:
        print(
            "\nThe ISO no longer matches the osinfo entry, so GNOME Boxes and\n"
            "virt-manager will not recognise it - and Boxes hides its firmware\n"
            "selector for an unknown OS, leaving a BIOS VM this ISO cannot boot.\n"
            "Either revert the descriptor change in iso/profiledef.sh, or update\n"
            f"{ENTRY.relative_to(ROOT)} and the entry upstream in osinfo-db.",
            file=sys.stderr,
        )
        return 1

    print("the ISO still matches the osinfo entry")
    return 0


if __name__ == "__main__":
    sys.exit(main())
