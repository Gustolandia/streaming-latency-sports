#!/usr/bin/env bash
# A2's build campaign: three kernels from one source, differing in nothing but the tick.
#
# A2 asks whether the cliff's width follows the tick. The tick is fixed when a kernel is
# compiled, so it cannot be changed on a running machine and the block has to build its own. Our
# HZ=1000 build is the control, not Azure's stock kernel, so that the three differ in the tick
# and in nothing else; short bridge sessions on the stock kernel tie the results back to A1, A3
# and A5, which run on it.
#
# Run on the driver that will run A2, because the kernel has to be the driver's own:
#     nohup bash cloud/azure/kernels.sh build > kernels.log 2>&1 &
#     sudo bash cloud/azure/kernels.sh boot 250      # boots it once, stock stays the default
#     bash cloud/azure/kernels.sh check 250          # after the reboot, before any run
#
# Booting safely: a built kernel is booted once with grub-reboot, so a kernel that does not come
# up is gone on the next restart and the stock one takes over. Azure's serial console is the last
# resort. The broker keeps its kernel throughout: the helper that writes "got it" runs here.
# Like stage 0 and every campaign, this carries on past a failing command on purpose: a check
# that fails becomes a STOP_RULE with a reason a person can read, not a silent exit.
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
set +e
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 1
#: The build works inside $WORK, so anything written back to the repository needs its full path.
REPO="$(pwd)"

TICKS="${TICKS:-1000 250 100}"
WORK="${WORK:-$HOME/kernelbuild}"
DIR="runs/azure/kernels"
mkdir -p "$DIR"

log () { echo "$(date -u +%FT%TZ) $*"; }
stop () { log "STOP_RULE: $*"; exit 1; }

RELEASE="$(uname -r)"
FLAVOUR="${RELEASE#*-*-}"                      # azure
ABI="$(echo "$RELEASE" | cut -d- -f2)"         # 1064

build () {
  command -v dpkg >/dev/null || stop "this is not a Debian machine; A2 builds Ubuntu's kernel"
  log "kernel running here: $RELEASE (abi $ABI, flavour $FLAVOUR)"

  log "== 1/4 the tools and the source"
  sudo apt-get update -qq || stop "apt-get update failed"
  sudo apt-get install -y -qq build-essential fakeroot libncurses-dev bison flex libssl-dev \
      libelf-dev dwarves rsync kernel-wedge gcc-12 \
    || stop "the build tools could not be installed"
  # Azure's Ubuntu image carries no deb-src line at all, so apt has no idea where the kernel's
  # source lives and `apt-get source` refuses before it starts. Every binary line is mirrored as
  # a source line, in a file of our own so the image's own list is left as it is. This adds a
  # place to fetch source from; it upgrades nothing, and nothing under a campaign changes.
  if ! grep -qs '^deb-src' /etc/apt/sources.list /etc/apt/sources.list.d/*.list; then
    log "   no deb-src line on this machine; mirroring the binary ones"
    sed -n 's/^deb \(.*\)$/deb-src \1/p' /etc/apt/sources.list 2>/dev/null \
      | sudo tee /etc/apt/sources.list.d/sbl-kernel-source.list >/dev/null
    [ -s /etc/apt/sources.list.d/sbl-kernel-source.list ] \
      || stop "no deb line could be mirrored into a deb-src one; this image lists its sources another way"
    sudo apt-get update -qq || stop "apt-get update failed after adding the source lines"
  fi

  mkdir -p "$WORK" && cd "$WORK" || stop "cannot use $WORK"
  if [ ! -d "linux-azure" ]; then
    sudo apt-get install -y -qq dpkg-dev || stop "dpkg-dev could not be installed"
    # The status has to be apt-get's own. Piping it into tail reports tail's, which is always
    # zero, and the build would carry on with no source to build.
    apt-get source "linux-image-unsigned-$RELEASE" > "$WORK/source.log" 2>&1
    if [ "$?" != 0 ]; then
      tail -3 "$WORK/source.log"
      stop "the source for $RELEASE could not be fetched; see $WORK/source.log"
    fi
    # apt leaves the package's tarball, diff and dsc beside the tree it unpacks, and all four
    # begin with the package's name -- linux-azure-6.8 here -- so a glob matches the lot and mv
    # reads the last one as the destination. The tree is picked out by being a directory.
    unpacked=$(find "$WORK" -maxdepth 1 -mindepth 1 -type d -name 'linux-*' | head -1)
    [ -n "$unpacked" ] || stop "the source did not unpack as expected; see $WORK/source.log"
    mv "$unpacked" linux-azure || stop "the source tree could not be renamed"
    # The archive serves whatever version it currently holds, which need not be the one running:
    # on 20 September the running kernel was 6.8.0-1064 and the archive offered 1067. The three
    # builds still differ in the tick and in nothing else, because all three come from this one
    # tree -- but which tree it was belongs beside the results, not in anybody's memory.
    basename "$unpacked" > "$REPO/$DIR/source_version.txt"
    log "   source tree: $(basename "$unpacked"); the kernel running here is $RELEASE"
  fi
  cd linux-azure || stop "no source folder"

  # The running kernel's own configuration, so the builds differ from it only where we say.
  [ -r "/boot/config-$RELEASE" ] || stop "no /boot/config-$RELEASE to copy"
  log "== 2/4 three configurations from the running kernel's own"
  for hz in $TICKS; do
    cp "/boot/config-$RELEASE" ".config" || stop "cannot copy the running config"
    # Only the tick changes. HRTICK is a scheduler feature rather than a config, and is switched
    # off at boot by cloud/azure/kernels.sh boot; the tickless settings are left exactly as the
    # running kernel has them, and kernel_checks.py holds the three builds to each other.
    scripts/config --file .config --disable CONFIG_HZ_100 --disable CONFIG_HZ_250 \
      --disable CONFIG_HZ_300 --disable CONFIG_HZ_1000 || stop "the tick could not be cleared"
    scripts/config --file .config --enable "CONFIG_HZ_$hz" --set-val CONFIG_HZ "$hz" \
      || stop "HZ=$hz could not be set"
    scripts/config --file .config --disable CONFIG_DEBUG_INFO_BTF \
      --disable CONFIG_SYSTEM_TRUSTED_KEYS --disable CONFIG_SYSTEM_REVOCATION_KEYS
    yes "" | make olddefconfig >/dev/null 2>&1 || stop "olddefconfig failed for HZ=$hz"
    got=$(grep '^CONFIG_HZ=' .config | cut -d= -f2)
    [ "$got" = "$hz" ] || stop "the config says HZ=$got after asking for $hz"
    cp .config "$WORK/config-hz$hz" || stop "the HZ=$hz config could not be kept"
    log "   HZ=$hz configured"
  done

  log "== 3/4 building, one kernel at a time, same machine and compiler"
  for hz in $TICKS; do
    cp "$WORK/config-hz$hz" .config || stop "the HZ=$hz config went missing"
    make -j"$(nproc)" LOCALVERSION="-sbl$hz" bindeb-pkg >"$WORK/build-hz$hz.log" 2>&1 \
      || stop "the HZ=$hz kernel did not build; see $WORK/build-hz$hz.log"
    log "   HZ=$hz built"
  done

  log "== 4/4 what was built"
  # Written with the repository's full path. The previous directory, at this point in the build,
  # is the build directory and not the repository, so writing built.txt relative to it fails --
  # and a failing tee is what the stop rule below would read, so three kernels that took six
  # hours to build would have reported that none was produced.
  ls -1 "$WORK"/linux-image-*sbl*.deb > "$REPO/$DIR/built.txt" 2>/dev/null
  [ -s "$REPO/$DIR/built.txt" ] || stop "no kernel package was produced"
  cat "$REPO/$DIR/built.txt"
  log "CAMPAIGN_COMPLETE: three kernels built in $WORK; boot each once with: sudo bash cloud/azure/kernels.sh boot <hz>"
}

boot () {
  local hz="${1:?which tick}"
  local deb
  deb=$(ls -1 "$WORK"/linux-image-*sbl"$hz"*.deb 2>/dev/null | head -1)
  [ -n "$deb" ] || stop "no built kernel for HZ=$hz in $WORK"
  sudo dpkg -i "$deb" >/dev/null 2>&1 || stop "the HZ=$hz kernel could not be installed"
  local entry
  entry=$(grep -E "^menuentry|^\s+menuentry" /boot/grub/grub.cfg | grep -c . || true)
  log "installed $deb; $entry menu entries"
  # Boot it ONCE. A kernel that does not come up is gone on the next restart, and the stock one
  # is still the default, so a failed boot costs a reboot rather than the machine.
  sudo grub-reboot "$(sudo grep -E "^menuentry|submenu" /boot/grub/grub.cfg | head -1 >/dev/null; \
      echo "Advanced options for Ubuntu>Ubuntu, with Linux $(basename "$deb" | \
      sed 's/linux-image-unsigned-//; s/linux-image-//; s/_.*//')")" \
    || stop "grub-reboot did not take; not rebooting"
  log "the next boot only will use HZ=$hz; the stock kernel stays the default"
  log "reboot now, then run: bash cloud/azure/kernels.sh check $hz"
}

check () {
  local hz="${1:?which tick}"
  local like=""
  [ -s "$DIR/nohz-hz1000.json" ] && [ "$hz" != 1000 ] && like="--nohz-like $DIR/nohz-hz1000.json"
  # shellcheck disable=SC2086
  python3 scripts/kernel_checks.py check --hz "$hz" $like > "$DIR/check-hz$hz.json"
  local ok=$?
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1]));
print("\n".join("   " + p for p in d["problems"]) or "   nothing wrong")' "$DIR/check-hz$hz.json"
  [ "$ok" = 0 ] || stop "HZ=$hz did not pass its checks; see $DIR/check-hz$hz.json"
  [ "$hz" = 1000 ] && cp "$DIR/check-hz$hz.json" "$DIR/nohz-hz1000.json"
  log "CAMPAIGN_COMPLETE: HZ=$hz passed its checks; see $DIR/check-hz$hz.json"
}

case "${1:-}" in
  build) build ;;
  boot) boot "${2:-}" ;;
  check) check "${2:-}" ;;
  *) echo "usage: bash cloud/azure/kernels.sh build | boot <hz> | check <hz>" >&2; exit 2 ;;
esac
