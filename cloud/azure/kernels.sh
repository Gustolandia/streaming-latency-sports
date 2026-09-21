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
#     bash cloud/azure/kernels.sh boot 250           # boots it once, stock stays the default
#     bash cloud/azure/kernels.sh check 250          # after the reboot, before any run
#
# None of these is run under sudo: they call it where they need it, and running the script itself
# as root sends it looking for the checkout in /root.
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
#: The busy loop the tick is counted against, and the name it runs under. The name carries
#: this shell's pid so it cannot match anything else alive on the machine: the first version
#: searched for the loop's own text, and that matched the ssh command line of the operator
#: who had typed the same words to go looking for it.
SPINNER="while : ; do : ; done"
SPIN_TAG="sbl-tick-spinner-$$"
SPIN_CPU="${SPIN_CPU:-1}"
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
    # Only the tick changes. HRTICK is a scheduler feature rather than a config: v6.8 ships it
    # off (SCHED_FEAT(HRTICK, false)) and nothing here turns it on, so the check after each boot
    # confirms it rather than setting it. The tickless settings are left exactly as the running
    # kernel has them, and kernel_checks.py holds the three builds to each other.
    scripts/config --file .config --disable CONFIG_HZ_100 --disable CONFIG_HZ_250 \
      --disable CONFIG_HZ_300 --disable CONFIG_HZ_1000 || stop "the tick could not be cleared"
    scripts/config --file .config --enable "CONFIG_HZ_$hz" --set-val CONFIG_HZ "$hz" \
      || stop "HZ=$hz could not be set"
    scripts/config --file .config --disable CONFIG_DEBUG_INFO_BTF \
      --disable CONFIG_SYSTEM_TRUSTED_KEYS --disable CONFIG_SYSTEM_REVOCATION_KEYS
    # No "yes |" in front of it. olddefconfig takes the default for every new symbol and asks
    # nothing, and this kit runs under pipefail: make finishes first, yes dies of a broken pipe
    # with status 141, and the pipeline reports that -- so a configuration that worked perfectly
    # stopped the build. Its output is kept, because a stop rule that cannot say why is worth
    # little at three in the morning.
    make olddefconfig > "$WORK/olddefconfig-hz$hz.log" 2>&1 \
      || { tail -5 "$WORK/olddefconfig-hz$hz.log"
           stop "olddefconfig failed for HZ=$hz; see $WORK/olddefconfig-hz$hz.log"; }
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
  log "CAMPAIGN_COMPLETE: three kernels built in $WORK; boot each once with: bash cloud/azure/kernels.sh boot <hz>"
}

#: Keep the stock kernel as the one a plain restart comes back on.
#:
#: Installing a kernel we built ourselves quietly took that away. GRUB_DEFAULT=0 means the first
#: menu entry, which is whichever kernel sorts highest, and 6.8.12-sbl1000 sorts above
#: 6.8.0-1064-azure -- so from the moment the tick builds went on, every restart of the driver
#: came up on the HZ=1000 kernel. Silently, and including restarts with nothing to do with A2.
#:
#: That costs twice. This script's whole safety argument is that a kernel which does not come up
#: is gone on the next restart because the stock one is still the default, and that had stopped
#: being true. And A3, A5 and A7 all run on the stock kernel; they would have run on a 1000 Hz
#: build of a different source tree with nothing in the record saying so.
#:
#: Pinned by the entry's own id rather than by its position, because position is the bug.
pin_stock_default () {
  local stock sub ent
  stock=$(ls -1 /boot/vmlinuz-* 2>/dev/null | sed 's|/boot/vmlinuz-||' | grep -- '-azure$'             | sort -V | tail -1)
  [ -n "$stock" ] || stop "no stock -azure kernel in /boot to keep as the default"
  sub=$(sudo grep -oE "gnulinux-advanced-[a-f0-9-]+" /boot/grub/grub.cfg | head -1)
  ent=$(sudo grep -oE "gnulinux-$stock-advanced-[a-f0-9-]+" /boot/grub/grub.cfg | head -1)
  [ -n "$sub" ] && [ -n "$ent" ] || stop "the stock kernel has no menu entry to pin the default to"
  sudo cp -n /etc/default/grub /etc/default/grub.sbl-orig 2>/dev/null
  sudo sed -i "s|^GRUB_DEFAULT=.*|GRUB_DEFAULT=\"$sub>$ent\"|" /etc/default/grub     || stop "the default kernel could not be pinned"
  sudo update-grub >/dev/null 2>&1 || stop "update-grub failed while pinning the default"
  grep -q "^GRUB_DEFAULT=\"$sub>$ent\"$" /etc/default/grub     || stop "the default kernel did not stay pinned to $stock"
  log "a plain restart comes back on $stock"
}

boot () {
  local hz="${1:?which tick}"
  local deb
  # The underscore matters. Each build also produces a -dbg package of debug symbols, and
  # "linux-image-6.8.12-sbl1000-dbg_..." sorts before "linux-image-6.8.12-sbl1000_..." because a
  # hyphen comes before an underscore -- so a glob without it installs the symbols and points
  # grub at an entry that is not a kernel. The underscore also keeps HZ=100 from matching the
  # HZ=1000 package.
  deb=$(ls -1 "$WORK"/linux-image-*sbl"$hz"_*.deb 2>/dev/null | head -1)
  [ -n "$deb" ] || stop "no built kernel for HZ=$hz in $WORK"
  case "$deb" in *-dbg_*) stop "that is the debug-symbol package, not a kernel: $deb" ;; esac
  sudo dpkg -i "$deb" >/dev/null 2>&1 || stop "the HZ=$hz kernel could not be installed"
  pin_stock_default
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

  # Whether HRTICK is on decides whether A2 measures anything at all, and it is only legible to
  # root: /sys/kernel/debug is mounted 0700, so an unprivileged read returns nothing and the
  # check reports it could not be read -- a true statement that reads like a fault in the kernel.
  # Read it here, where this kit keeps its sudo, and hand the checker the file.
  local feats="$WORK/features-hz$hz.txt"
  mkdir -p "$WORK"
  sudo cat /sys/kernel/debug/sched/features > "$feats" 2>/dev/null
  [ -s "$feats" ] \
    || stop "the scheduler's feature list could not be read even with sudo; A2 is void if HRTICK is on and this cannot say"

  # The tick is counted from /proc/interrupts on the busiest CPU, and an idle machine has no busy
  # CPU: NO_HZ_IDLE stops the timer on every one of them, the count comes back 0 Hz, and the
  # check says the kernel is 100% out. That reads as a broken kernel and means "nothing was
  # running". So one CPU is held busy for as long as the count takes.
  #
  # The spinner is given three ways to die, because the last stray busy loop in this kit sat at
  # 99.7% of a CPU and quietly spoiled A3's measurements until somebody measured the idle
  # baseline and found it was not idle. `timeout` bounds it even if this shell is killed
  # outright, the trap covers the stop rules, and the kill covers the ordinary path. What is
  # checked afterwards is the loop itself and not the pid that was signalled: `timeout` does
  # forward the signal to its child, but this kit has been bitten by a surviving child before.
  # The loop runs under $SPIN_TAG so the search for survivors matches this invocation alone.
  timeout 120 taskset -c "$SPIN_CPU" sh -c "$SPINNER" "$SPIN_TAG" &
  local spin=$!
  # shellcheck disable=SC2064
  trap "kill $spin 2>/dev/null" EXIT INT TERM

  python3 scripts/kernel_checks.py check --hz "$hz" --features-from "$feats" $like \
    > "$DIR/check-hz$hz.json"
  local ok=$?

  kill "$spin" 2>/dev/null
  wait "$spin" 2>/dev/null
  trap - EXIT INT TERM
  local left
  left=$(pgrep -f "$SPIN_TAG" 2>/dev/null | tr '\n' ' ')
  [ -z "$left" ] || stop "a spinner survived the check (pids: $left); kill it before any run"

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
