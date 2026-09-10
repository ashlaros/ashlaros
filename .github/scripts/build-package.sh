#!/usr/bin/env bash
# Build and sign one package directory.
set -euo pipefail

pkg_dir="${1:?usage: build-package.sh <package directory>}"
: "${GPG_KEYID:?the key id must be provided}"

# the repository moves under us between the container's sync and this build;
# a makedepend resolved against a stale database installs a version the
# current one no longer has
pacman -Syu --noconfirm

# makepkg refuses to run as root, and the whole checkout has to be readable
# by the user it runs as instead
chown -R builder:builder .

cd "$pkg_dir"

# a PKGBUILD that verifies an upstream release signature needs that author's
# key in the builder keyring, or makepkg aborts before it starts building
keys=$(sed -n '/validpgpkeys=(/,/)/p' PKGBUILD | grep -oE '[0-9A-Fa-f]{40}' || true)
for key in $keys; do
  sudo -u builder gpg --keyserver keyserver.ubuntu.com --recv-keys "$key" ||
    echo "could not fetch $key; makepkg will report the failure"
done

# Record what this package was built from, so a later run can tell that
# rebuilding it would produce the same thing. PACKAGER is the only free-text
# field repo-add copies into the database that nothing else reads; the hash
# is over every file in the package directory, because a payload edit
# changes the package without touching pkgver. discover_packages.py reads
# it back out of the published database.
source_hash=$(python3 - "$PWD" <<'PYTHON'
import hashlib, pathlib, sys
directory = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
for path in sorted(p for p in directory.rglob("*") if p.is_file()):
    digest.update(path.relative_to(directory).as_posix().encode())
    digest.update(path.read_bytes())
print(digest.hexdigest()[:16])
PYTHON
)

# --nocheck: several check() suites want a network or a display a sandboxed
# runner does not have, and a package that builds but cannot self-test is
# still the package we ship.
sudo -u builder --preserve-env=GPG_KEYID \
  PACKAGER="AshlarOS <ashlaros-src:${source_hash}>" \
  makepkg -s --noconfirm --nocheck --sign --key "$GPG_KEYID"
