#!/usr/bin/env bash
# Make a stock Arch (or Arch Linux ARM) container able to build our packages.
#
# Two things it cannot do out of the box: makepkg refuses to run as root, and
# our own packages depend on each other - ashlaros-settings needs
# ashlaros-branding - so the repository being published has to be readable
# while it is being built.
set -euo pipefail

REPO_URL="${REPO_URL:-https://packages.ashlaros.download}"

pacman-key --init
# Arch Linux ARM ships its own keyring name; populate whichever is present
for keyring in archlinux archlinuxarm; do
  pacman-key --populate "$keyring" 2>/dev/null || true
done

pacman -Syu --noconfirm --needed \
  base-devel git sudo python python-boto3 pacman-contrib

# x86_64 only: the v3 repositories have no ARM counterpart, and CachyOS
# publishes no aarch64 tree at all, so an ARM build resolves against Arch
# Linux ARM's own core/extra and nothing else.
if [[ $(uname -m) == x86_64 ]]; then
  cat >>/etc/pacman.conf <<-'EOF'

	[cachyos-core-v3]
	SigLevel = Never
	Server = https://mirror.cachyos.org/repo/x86_64_v3/$repo

	[cachyos-extra-v3]
	SigLevel = Never
	Server = https://mirror.cachyos.org/repo/x86_64_v3/$repo

	[cachyos]
	SigLevel = Never
	Server = https://mirror.cachyos.org/repo/x86_64/$repo
	EOF
fi

# Our own repository, so a package can depend on one published minutes ago.
# DatabaseOptional, not DatabaseRequired: the very first run publishes into
# an empty bucket, where no signed database exists yet.
cat >>/etc/pacman.conf <<-EOF

	[ashlaros]
	SigLevel = Optional TrustAll
	Server = ${REPO_URL}/\$arch
EOF

# a missing repository must not fail the sync: on the first ever run the
# bucket is empty and there is no database to fetch
pacman -Sy --noconfirm || true

useradd -m -G wheel builder 2>/dev/null || true
echo 'builder ALL=(ALL) NOPASSWD: ALL' >/etc/sudoers.d/builder
chmod 440 /etc/sudoers.d/builder
