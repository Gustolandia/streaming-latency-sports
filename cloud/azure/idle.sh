#!/usr/bin/env bash
# Block I's boot (freeze 41): idle=poll on the kernel command line, so that an idle virtual
# processor spins instead of halting, and a woken thread does not wait for its processor to be
# woken first. Block I asks whether the mode of negative readings at -250 to -150 us is that wake
# (docs/results/order_scope/DESIGN.md).
#
# idle= is read once, as the kernel starts, so it is asked for at boot, as cpus.sh asks for a
# core count:
#
#     bash cloud/azure/idle.sh boot poll    # then reboot
#     bash cloud/azure/idle.sh status       # after the reboot, before any run: idle=poll on|off
#
# The rules are cpus.sh's. The entry is generated from the running boot's own /proc/cmdline, so
# the two boots differ in idle= and in nothing else; it is on the stock kernel, picked by name;
# and it is selected with grub-reboot, so it applies to the next boot only, a boot that fails
# costs one restart, and the restart after it comes back on the pinned default. None of these is
# run under sudo: they call it where they need it.
#
# The entry has a file of its own, /etc/grub.d/42_sbl_idle, and an id of its own, sbl-idle.
# cpus.sh writes the whole of 40_custom each time it asks for a core count, and puts its saved
# copy back to restore, so an entry kept in that file would be lost to either, and one written
# over it would take cpus.sh's away. Neither script writes the other's file.
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
set +e
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 1

#: The machine's own files. SBL_ROOT is empty on a driver; the tests point it at a fake tree, as
#: they point sched_settings.py's --root at one.
ROOT="${SBL_ROOT:-}"
CMDLINE="$ROOT/proc/cmdline"
CUSTOM="$ROOT/etc/grub.d/40_custom"
KEEP="$ROOT/etc/grub.d/40_custom.sbl-orig"
ENTRY="$ROOT/etc/grub.d/42_sbl_idle"
MENU="$ROOT/boot/grub/grub.cfg"
ENTRY_ID="sbl-idle"

log () { echo "$(date -u +%FT%TZ) $*"; }
stop () { log "STOP_RULE: $*"; exit 1; }

#: The kernel block I runs on: the stock one, picked by name as cpus.sh picks it, and not one of
#: A2's tick builds by being the newest.
stock_kernel () {
  local image
  for image in "$ROOT"/boot/vmlinuz-*; do echo "${image##*/vmlinuz-}"; done \
    | grep -- '-azure$' | sort -V | tail -1
}

#: Whether a command line holds idle=poll as an argument of its own: not idle=polling, and not
#: xidle=poll. campaign.sh reads /proc/cmdline the same way before each of block I's runs.
holds_idle_poll () {
  case " $1 " in *" idle=poll "*) return 0 ;; esac
  return 1
}

boot () {
  local mode="${1:-}"
  [ "$mode" = poll ] || stop "the one idle= this boots is poll, not \"$mode\""
  local rel="${KERNEL:-$(stock_kernel)}"
  [ -n "$rel" ] || stop "no stock -azure kernel found in /boot; name one with KERNEL="
  # Existence, not readability, as in cpus.sh: Ubuntu ships the stock kernel 0600 root, and what
  # has to read it is grub, at boot, as root.
  [ -e "$ROOT/boot/vmlinuz-$rel" ] || stop "no /boot/vmlinuz-$rel"
  [ -e "$ROOT/boot/initrd.img-$rel" ] || stop "no /boot/initrd.img-$rel"

  # The running boot's own arguments, minus the image it booted; minus any idle= already on them,
  # which this script's own previous boot leaves there, and two would leave the kernel to pick
  # between them; and minus a core count, which cpus.sh's boot leaves there, because block I runs
  # on all of the machine's CPUs. So the entry is the default boot plus idle=poll, whichever boot
  # asks for it. Each is taken out as a whole argument, so intel_idle.max_cstate= stays.
  local args
  args=$(sed -E -e 's/BOOT_IMAGE=[^ ]* *//' -e 's/(^| )(idle|nr_cpus|maxcpus)=[^ ]*/\1/g' \
             -e 's/  +/ /g' -e 's/^ //' -e 's/ $//' "$CMDLINE" 2>/dev/null)
  [ -n "$args" ] || stop "$CMDLINE came back empty; refusing to write a boot entry from it"

  local uuid
  uuid=$(findmnt -no UUID /) || stop "the root filesystem's UUID could not be read"
  [ -n "$uuid" ] || stop "the root filesystem has no UUID to search for"

  # The image's own menu file is kept aside once (-n), as cpus.sh keeps it, whichever of the two
  # scripts runs first on a machine. This one writes nothing into it.
  sudo cp -n "$CUSTOM" "$KEEP" 2>/dev/null
  {
    echo "#!/bin/sh"
    echo "exec tail -n +3 \$0"
    echo "# Written by cloud/azure/idle.sh. One entry, booted once through grub-reboot, carrying"
    echo "# the running boot's own command line, without a core count, plus idle=poll."
    echo "menuentry 'sbl: $rel, idle=poll' --id $ENTRY_ID {"
    echo "  insmod part_gpt"
    echo "  insmod ext2"
    echo "  search --no-floppy --fs-uuid --set=root $uuid"
    echo "  linux /boot/vmlinuz-$rel $args idle=poll"
    echo "  initrd /boot/initrd.img-$rel"
    echo "}"
  } | sudo tee "$ENTRY" >/dev/null || stop "the idle=poll entry could not be written"
  sudo chmod +x "$ENTRY"
  sudo update-grub >/dev/null 2>&1 || stop "update-grub failed; the menu may be half written"
  sudo grep -qF -- "--id $ENTRY_ID {" "$MENU" || stop "the entry did not reach the menu"
  sudo grub-reboot "$ENTRY_ID" || stop "grub-reboot did not take; not rebooting"
  log "the next boot only will have idle=poll, on $rel; the default is untouched"
  log "reboot now, then run: bash cloud/azure/idle.sh status"
}

#: One line, "idle=poll on" or "idle=poll off", which queue.sh's verify_boot reads word for word.
status () {
  [ -r "$CMDLINE" ] || stop "$CMDLINE could not be read"
  if holds_idle_poll "$(cat "$CMDLINE")"; then echo "idle=poll on"; else echo "idle=poll off"; fi
}

case "${1:-}" in
  boot) boot "${2:-}" ;;
  status) status ;;
  *) echo "usage: bash cloud/azure/idle.sh boot poll | status" >&2; exit 2 ;;
esac
