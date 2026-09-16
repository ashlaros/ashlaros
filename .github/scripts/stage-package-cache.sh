#!/usr/bin/env bash
# Put the packages the installer will ask for into the ISO, so the install
# copies them from the medium instead of fetching them again.
#
# Seven packages are on the live ISO *and* in the installer's own list -
# firefox among them, 88 MB compressed - and today the install downloads
# every one of them a second time (#82).
#
# Not /var/cache/pacman/pkg: mkarchiso's _cleanup_pacstrap_dir deletes every
# file under exactly that path before packing the squashfs, which is why the
# published ISO ships an empty one. A cache anywhere else survives, and the
# installer names this path in the live pacman.conf it writes.
#
# Run against the profile directory before mkarchiso, so the staged files are
# copied in as ordinary airootfs content.
set -euo pipefail

profile=${1:?usage: stage-package-cache.sh <profile-dir>}
cache="$profile/airootfs/var/cache/ashlaros/pkg"

# The overlap, derived rather than listed: whatever appears both on the ISO
# and in the installer's DESKTOP_PACKAGES. A hardcoded list would drift the
# first time either side changed.
mapfile -t iso_packages < <(
  grep -vE '^\s*(#|$)' "$profile/packages.x86_64" | tr -d ' \t'
)
mapfile -t desktop_packages < <(
  python3 - <<'PY'
import ast
import pathlib

source = pathlib.Path("installer/orchestrator/phases_impl.py").read_text()
for node in ast.parse(source).body:
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "DESKTOP_PACKAGES":
        for name in ast.literal_eval(node.value):
            print(name)
PY
)

overlap=()
for package in "${iso_packages[@]}"; do
  for wanted in "${desktop_packages[@]}"; do
    [[ $package == "$wanted" ]] && overlap+=("$package") && break
  done
done

if ((${#overlap[@]} == 0)); then
  echo "no package is on both lists; nothing to stage"
  exit 0
fi

echo "staging ${#overlap[@]} packages the install would otherwise refetch:"
printf '  %s\n' "${overlap[@]}"

mkdir -p "$cache"
# The profile's repositories have their own databases; sync them before
# asking for a package, or every cachyos and ashlaros name is "target not
# found".
pacman -Sy --noconfirm --config "$profile/pacman.conf" >/dev/null

# --nodeps twice: these seven, not their dependency closure. Everything they
# depend on is already installed on the target by the time the installer
# asks for them - they are on the ISO's own package list - so caching the
# closure would add hundreds of megabytes for files nothing fetches.
# Measured: seven packages is ~125 MB, the closure is 550 MB.
pacman -Sw --noconfirm --nodeps --nodeps --config "$profile/pacman.conf" \
  --cachedir "$cache" "${overlap[@]}"

# Signatures are not needed on the medium: the installer verifies against
# the same repositories, and they double the file count for no benefit.
find "$cache" -name '*.sig' -delete

echo "staged $(find "$cache" -name '*.pkg.tar*' | wc -l) files, $(du -sh "$cache" | cut -f1)"
