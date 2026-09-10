#!/usr/bin/env bash
# Trust the keys iso/pacman.conf's repositories sign with.
#
# There is a bootstrap problem: cachyos-keyring lives in the CachyOS
# repository, whose database is signed with the key that package carries.
# Breaking the circle out of band is what lets iso/pacman.conf keep
# SigLevel = Required rather than being weakened to Never.
#
# The keyring PACKAGE, not a bare key URL: mirror.cachyos.org answers 200
# with an HTML fallback page for any path it does not have, so a wrong or
# moved key URL yields a valid-looking response that is not a key. A package
# is named by the database, which pins its exact version.
set -euo pipefail

CACHYOS_MIRROR="${CACHYOS_MIRROR:-https://mirror.cachyos.org/repo/x86_64}"
ASHLAROS_KEY_URL="${ASHLAROS_KEY_URL:-https://packages.ashlaros.download/ashlaros.gpg}"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

lsign_all() {
  local keyring="$1" fingerprint
  pacman-key --add "$keyring"
  while read -r fingerprint; do
    pacman-key --lsign-key "$fingerprint"
  done < <(gpg --show-keys --with-colons "$keyring" | awk -F: '/^fpr:/ {print $10}')
}

trust_cachyos() {
  # ask pacman where the package is rather than constructing the URL: only
  # the database knows the current version
  local conf="$work/pacman.conf" url
  cat >"$conf" <<-EOF
	[options]
	Architecture = auto
	SigLevel = Never
	DBPath = $work/db
	CacheDir = $work/cache

	[cachyos]
	Server = ${CACHYOS_MIRROR}/\$repo
	EOF
  mkdir -p "$work/db" "$work/cache"

  pacman --config "$conf" -Sy >/dev/null
  url=$(pacman --config "$conf" -Sp cachyos-keyring)
  [[ -n $url ]] || {
    echo "the cachyos database names no cachyos-keyring" >&2
    return 1
  }

  curl -fsSL "$url" -o "$work/cachyos-keyring.pkg.tar.zst"
  tar -xf "$work/cachyos-keyring.pkg.tar.zst" -C "$work" usr/share/pacman/keyrings/

  install -Dm644 "$work"/usr/share/pacman/keyrings/cachyos* -t /usr/share/pacman/keyrings/
  lsign_all "$work/usr/share/pacman/keyrings/cachyos.gpg"
}

trust_ashlaros() {
  curl -fsSL "$ASHLAROS_KEY_URL" -o "$work/ashlaros.gpg" || return 1
  # the mirror's HTML fallback is a 200 with a body that is not a key
  gpg --show-keys "$work/ashlaros.gpg" >/dev/null 2>&1 || {
    echo "$ASHLAROS_KEY_URL did not serve a key" >&2
    return 1
  }
  lsign_all "$work/ashlaros.gpg"
}

trust_cachyos
# not published before the first build-packages run, and the ISO cannot be
# built until the packages exist anyway - so name the cause rather than fail
# with a bare curl error
trust_ashlaros || echo "the ashlaros key is not published yet; run build-packages first" >&2
