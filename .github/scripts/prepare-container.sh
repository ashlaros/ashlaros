#!/usr/bin/env bash
# Make a stock Arch (or Arch Linux ARM) container able to build our packages.
#
# Two things it cannot do out of the box: makepkg refuses to run as root, and
# our own packages depend on each other - ashlaros-settings needs
# ashlaros-branding - so the repository being published has to be readable
# while it is being built.
set -euo pipefail

REPO_URL="${REPO_URL:-https://ashlaros.download/packages}"

# pacman 7 drops privileges to the 'alpm' user and confines downloads with
# Landlock. A container whose seccomp profile blocks the landlock syscalls
# fails the whole sync with "the Landlock ruleset could not be applied" -
# seen on the ARM runners. The isolation is worth having where the kernel
# allows it, so probe rather than switch it off unconditionally.
if ! pacman -Sy --noconfirm >/dev/null 2>&1; then
	echo "pacman's download sandbox is unavailable here; disabling it" >&2
	# into [options], not appended: a directive after the last repository
	# section belongs to THAT section, where pacman ignores it with
	# "directive 'DisableSandbox' in section 'aur' not recognized" - which
	# is what the ALARM image's trailing [aur] section made happen.
	sed -i '0,/^\[options\]/s//[options]\nDisableSandbox/' /etc/pacman.conf
fi

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

# Trust our own signing key before configuring the repository. A signed
# database whose key is unknown does not degrade to unsigned - pacman fails
# the whole sync with "invalid or corrupted database (PGP signature)", and
# every build after it cannot resolve so much as jq. SigLevel = Optional
# does not help: the check that fails happens before it applies.
if curl -fsSL "${REPO_URL}/ashlaros.gpg" -o /tmp/ashlaros.gpg &&
	gpg --show-keys /tmp/ashlaros.gpg >/dev/null 2>&1; then
	pacman-key --add /tmp/ashlaros.gpg
	gpg --show-keys --with-colons /tmp/ashlaros.gpg |
		awk -F: '/^fpr:/ {print $10}' |
		while read -r fingerprint; do pacman-key --lsign-key "$fingerprint"; done

	# Our own repository, so a package can depend on one published minutes
	# ago. DatabaseOptional, not DatabaseRequired: the very first run
	# publishes into an empty bucket, where no database exists at all.
	cat >>/etc/pacman.conf <<-EOF

		[ashlaros]
		SigLevel = Required DatabaseOptional
		Server = ${REPO_URL}/\$arch
	EOF
else
	echo "the ashlaros key is not published yet; building without the repository" >&2
fi

# a missing repository must not fail the sync: on the first ever run the
# bucket is empty and there is no database to fetch
pacman -Sy --noconfirm || true

# Stock OPTIONS carry `debug`, which makes a <name>-debug package beside
# every compiled one - detached symbols and /usr/src/debug sources. Those
# would enter the repository as first-class packages nobody asked for, and
# roughly double what a build leg uploads. OPTIONS is readonly inside
# makepkg and has no flag, so the config file is the only place to say it.
#
# Negate every bare `debug` and leave an existing `!debug` alone. The
# previous expression matched `debug` inside `!debug` too, so a config
# that already carried the negation became `!!debug` - which makepkg
# rejects outright with "OPTIONS array contains unknown option", failing
# the build before it starts. Requiring a space or paren on both sides is
# what distinguishes a bare `debug` from one already negated - and keeps
# it off `debuginfo`-style names that merely start the same way.
sed -i -E 's/([ (])debug([ )])/\1!debug\2/g' /etc/makepkg.conf

# Compile the way CachyOS compiles its x86_64_v3 repository, which is the
# stack every AshlarOS install runs: the flags below are CachyOS's own
# docker-makepkg-v3 makepkg.conf and rust.conf (github.com/CachyOS/
# docker-makepkg, 9b0259d), copied rather than approximated. Stock Arch
# builds for baseline x86-64 at -O2, so a vendored AUR package came out
# slower than the CachyOS package beside it.
#
# Not PACKAGECARCH=x86_64_v3 from the same file: that renames the output
# to *-x86_64_v3.pkg.tar.zst, and our repository and pacman's Architecture
# line are plain x86_64. The code inside is v3 either way, so these
# packages need a v3 CPU - which the installer already requires.
#
# A file in makepkg.conf.d rather than an edit: makepkg sources the
# directory after makepkg.conf in glob order, and zz- lands after the
# stock rust.conf whose RUSTFLAGS this replaces. x86_64 only: CachyOS has
# no aarch64 tree, and ARM keeps Arch Linux ARM's defaults.
if [[ $(uname -m) == x86_64 ]]; then
	cat >/etc/makepkg.conf.d/zz-cachyos-v3.conf <<-'EOF'
		CFLAGS="-march=x86-64-v3 -mtune=generic -O3 -pipe -fno-plt -fexceptions \
		        -Wp,-D_FORTIFY_SOURCE=3 -Wformat -Werror=format-security \
		        -fstack-clash-protection -fcf-protection -mpclmul"
		CXXFLAGS="$CFLAGS -Wp,-D_GLIBCXX_ASSERTIONS"
		LDFLAGS="-Wl,-O1 -Wl,--sort-common -Wl,--as-needed -Wl,-z,relro -Wl,-z,now \
		         -Wl,-z,pack-relative-relocs"
		LTOFLAGS="-flto=auto"
		RUSTFLAGS="-C opt-level=3 -C target-cpu=x86-64-v3 -Clink-arg=-z -Clink-arg=pack-relative-relocs"
		# CachyOS's OPTIONS: lto on, where stock Arch has it off. !debug
		# again, since this replaces the array the sed above fixed.
		OPTIONS=(strip docs !libtool !staticlibs emptydirs zipman purge !debug lto !autodeps)
		# CachyOS's file sets this bare; exported here, because stock
		# makepkg does not pass it to the build and go reads the environment
		export GOAMD64=v3
	EOF
fi

useradd -m -G wheel builder 2>/dev/null || true
echo 'builder ALL=(ALL) NOPASSWD: ALL' >/etc/sudoers.d/builder
chmod 440 /etc/sudoers.d/builder
