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

# --nocheck: several check() suites want a network or a display a sandboxed
# runner does not have, and a package that builds but cannot self-test is
# still the package we ship.
sudo -u builder --preserve-env=GPG_KEYID \
  makepkg -s --noconfirm --nocheck --sign --key "$GPG_KEYID"
