#!/usr/bin/env bash
# Front end for the VM harness. Keeps the working directory, the image and
# the container name in one place so a session does not reinvent them.
#
#   run.sh fetch [version]   download an ISO into the workspace
#   run.sh install           boot the ISO and drive the installer
#   run.sh boot              boot the installed disk
#   run.sh shot <name>       screenshot the framebuffer, as PNG
#   run.sh run '<cmd>' <name>  type a command on the guest, screenshot it
#   run.sh de '<cmd>' <name>   the same, on an installed (de keymap) guest
#   run.sh stop              kill the VM
#   run.sh clean             remove the workspace entirely
#
# WORKSPACE defaults to /tmp/ashlaros-vm and holds the ISO, the target
# disk, the firmware vars and out/.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
workspace="${WORKSPACE:-/tmp/ashlaros-vm}"
image="${IMAGE:-ashlaros-vm}"
container="${CONTAINER:-ashlaros-vm}"
iso_url="${ISO_URL:-https://iso.ashlaros.download}"

ensure_image() {
  docker image inspect "$image" >/dev/null 2>&1 && return
  echo "## building $image"
  docker build -q -t "$image" "$here" >/dev/null
}

# the scripts are copied in rather than bind-mounted from the repository:
# the workspace is what the container sees as /vm, and a run must not be
# able to write to a checkout
sync_scripts() {
  mkdir -p "$workspace/out"
  cp "$here/boot.sh" "$here/qmp.py" "$here/install.py" "$workspace/"
}

start() {
  ensure_image
  sync_scripts
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker run -d --rm --name "$container" --platform linux/amd64 \
    --device /dev/kvm -v "$workspace:/vm" \
    ${TPM:+-e "TPM=$TPM"} ${CDROM:+-e "CDROM=$CDROM"} \
    "$image" bash /vm/boot.sh "${SECONDS_TO_RUN:-10800}" >/dev/null
  echo "## $container started, workspace $workspace"
}

# The ISO takes several minutes to reach the installer under TCG, and a
# driver started before it is up types into a void - the keystrokes are
# swallowed by the boot menu and the installer sits on screen 1 forever.
#
# "Something is on screen" is not enough, because the boot menu draws too.
# The installer's own logo is: it is the only screen with a large light
# grey block, and no boot menu or kernel log has one.
wait_for_installer() {
  local deadline=$((SECONDS + ${1:-900}))
  while ((SECONDS < deadline)); do
    sleep 20
    docker exec "$container" python3 /vm/qmp.py '' probe 1 >/dev/null 2>&1 || continue
    if docker exec "$container" python3 -c "
import sys
raw = open('/vm/out/probe.ppm','rb').read()
# the logo block, measured off a real installer screen. A run this
# long appears on no boot menu and in no kernel log.
sys.exit(0 if bytes([0xaa,0xaa,0xaa]) * 16 in raw else 1)
" 2>/dev/null; then
      echo "## installer is up"
      return 0
    fi
  done
  echo "## installer never appeared" >&2
  return 1
}

png() {
  docker exec "$container" python3 -c "
import struct, sys, zlib
name = sys.argv[1]
raw = open(f'/vm/out/{name}.ppm','rb').read()
# P6 <w> <h> <max>\n, whitespace-separated
parts, index = [], 2
while len(parts) < 3:
    while raw[index:index+1].isspace(): index += 1
    if raw[index:index+1] == b'#':
        while raw[index:index+1] != b'\n': index += 1
        continue
    start = index
    while not raw[index:index+1].isspace(): index += 1
    parts.append(int(raw[start:index]))
width, height, _ = parts
body = raw[index+1:]
rows = b''.join(b'\x00' + body[y*width*3:(y+1)*width*3] for y in range(height))
def chunk(tag, data):
    return (struct.pack('>I', len(data)) + tag + data
            + struct.pack('>I', zlib.crc32(tag + data)))
open(f'/vm/out/{name}.png','wb').write(
    b'\x89PNG\r\n\x1a\n'
    + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
    + chunk(b'IDAT', zlib.compress(rows))
    + chunk(b'IEND', b''))
print(f'/vm/out/{name}.png')
" "$1"
  echo "$workspace/out/$1.png"
}

case "${1:-}" in
fetch)
  version="${2:-latest}"
  mkdir -p "$workspace"
  if [[ $version == latest ]]; then
    url="$iso_url/latest/ashlaros.iso"
  else
    url="$iso_url/$version/ashlaros-$version-x86_64.iso"
  fi
  echo "## fetching $url"
  curl -fsSL --max-time 900 -o "$workspace/ashlaros.iso" "$url"
  ls -l "$workspace/ashlaros.iso"
  ;;
install)
  rm -f "$workspace/target.qcow2" "$workspace/ovmf_vars.fd" \
    "$workspace/qmp.sock" "$workspace"/out/*.ppm "$workspace"/out/*.png
  start
  wait_for_installer
  docker exec -d "$container" python3 /vm/install.py
  echo "## driving the installer; expect ~35 minutes under TCG"
  ;;
boot)
  CDROM=no start
  ;;
shot)
  docker exec "$container" python3 /vm/qmp.py '' "$2" 1 >/dev/null
  png "$2"
  ;;
run)
  docker exec "$container" python3 /vm/qmp.py "$2" "$3" "${4:-6}" >/dev/null
  png "$3"
  ;;
de)
  docker exec "$container" python3 -c "
import sys, time
sys.path.insert(0, '/vm')
from qmp import Qmp
q = Qmp()
q.type_de(sys.argv[1])
q.key('ret')
time.sleep(float(sys.argv[3]))
q.shot(sys.argv[2])
" "$2" "$3" "${4:-6}" >/dev/null
  png "$3"
  ;;
stop)
  docker rm -f "$container" >/dev/null 2>&1 || true
  echo "## stopped"
  ;;
clean)
  docker rm -f "$container" >/dev/null 2>&1 || true
  # the guest writes as root, so removal happens in a container
  docker run --rm -v "$(dirname "$workspace"):/parent" archlinux:base \
    rm -rf "/parent/$(basename "$workspace")" >/dev/null 2>&1 || true
  echo "## removed $workspace"
  ;;
*)
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 1
  ;;
esac
