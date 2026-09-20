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
  mkdir -p "$WORK" && cd "$WORK" || stop "cannot use $WORK"
  if [ ! -d "linux-azure" ]; then
    sudo apt-get install -y -qq dpkg-dev || stop "dpkg-dev could not be installed"
    apt-get source "linux-image-unsigned-$RELEASE" 2>&1 | tail -3 \
      || stop "the source for $RELEASE could not be fetched; is deb-src enabled?"
    mv linux-azure-* linux-azure || stop "the source did not unpack as expected"
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
    cp .config "$OLDPWD/../config-hz$hz" 2>/dev/null || cp .config "$WORK/config-hz$hz"
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
  ls -1 "$WORK"/linux-image-*sbl*.deb 2>/dev/null | tee "$OLDPWD/$DIR/built.txt" \
    || stop "no kernel package was produced"
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
