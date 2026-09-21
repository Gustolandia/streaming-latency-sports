#!/usr/bin/env bash
# A5's core counts: ask for them at boot, because the machine will not give them any other way.
#
# A5 gives each core count its own session and P7 asks whether the cliff follows the count. The
# block was written to reach a count by switching CPUs off on a running machine, and that is
# wrong twice over:
#
#   the machine refuses      writing to /sys/devices/system/cpu/cpuN/online fails on both x86
#                            drivers -- "Device or resource busy" on one, "I/O error" on the
#                            other -- on an idle machine with nothing in dmesg. That is what a
#                            hypervisor that has pinned its channels to the CPUs looks like.
#
# The slice itself does follow the online count, immediately and in both directions -- measured
# on a machine where the CPUs had been hot-added and so could be taken away again: eight CPUs
# give 2800000 ns, four give 2100000, three give 1400000. So the original design would have read
# the right number had the machine allowed it. What is broken is the route, not the reading.
#
# So the count is asked for at boot, with nr_cpus=N on the kernel command line. Not maxcpus=N:
# that brings N up at boot and leaves the rest present, and Ubuntu ships a udev rule that onlines
# any CPU it finds offline, so the machine has all of them back within a second. A session that
# reached its count that way would run at eight CPUs, at the eight-CPU slice, in a directory
# named for two, and nothing would have failed. nr_cpus caps what the kernel knows exists, and
# there is nothing for udev to bring back.
#
#     bash cloud/azure/cpus.sh boot 2      # then reboot
#     bash cloud/azure/cpus.sh check 2     # after the reboot, before any run
#     bash cloud/azure/cpus.sh restore     # put the menu back as it was
#
# The entry is generated from the running boot's own /proc/cmdline, so the two boots differ in
# the core count and in nothing else; and it is selected with grub-reboot, so it applies to the
# next boot only and a boot that fails costs one restart. None of these is run under sudo: they
# call it where they need it.
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
set +e
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 1

DIR="runs/azure/cpus"
mkdir -p "$DIR"
CUSTOM="/etc/grub.d/40_custom"
KEEP="/etc/grub.d/40_custom.sbl-orig"
GRUBDEF="/etc/default/grub"
GRUBKEEP="/etc/default/grub.sbl-orig"
ENTRY_ID="sbl-cpus"

log () { echo "$(date -u +%FT%TZ) $*"; }
stop () { log "STOP_RULE: $*"; exit 1; }

#: The kernel a reduced-count session runs on. A5 belongs with A1, A3 and A7 on the stock kernel,
#: not on one of A2's tick builds, so the stock one is picked by name rather than by being newest.
stock_kernel () {
  ls -1 /boot/vmlinuz-* 2>/dev/null | sed 's|/boot/vmlinuz-||' | grep -- '-azure$' \
    | sort -V | tail -1
}

boot () {
  local n="${1:?how many CPUs}"
  local rel="${KERNEL:-$(stock_kernel)}"
  [ -n "$rel" ] || stop "no stock -azure kernel found in /boot; name one with KERNEL="
  # Existence, not readability. Ubuntu ships the stock kernel as 0600 root -- the ones we built
  # ourselves are 0644, which is why this only shows up on the kernel A5 actually wants -- and
  # this script deliberately does not run as root. What has to be able to read the file is grub,
  # at boot, as root.
  [ -e "/boot/vmlinuz-$rel" ] || stop "no /boot/vmlinuz-$rel"
  [ -e "/boot/initrd.img-$rel" ] || stop "no /boot/initrd.img-$rel"

  local have
  have=$(ls -1d /sys/devices/system/cpu/cpu[0-9]* 2>/dev/null | wc -l)
  [ "$n" -ge 1 ] || stop "a session needs at least one CPU"
  [ "$n" -le "$have" ] || stop "asked for $n CPUs on a machine with $have"

  # The running boot's own arguments, minus the image it booted and minus any core count already
  # on them: this script's own previous boot leaves nr_cpus= there, and appending a second one
  # would leave the kernel to pick between them.
  local args
  args=$(sed -e 's|BOOT_IMAGE=[^ ]* *||' -e 's|nr_cpus=[0-9]*||g' -e 's|maxcpus=[0-9]*||g' \
             -e 's|  *| |g' -e 's|^ ||' -e 's| $||' /proc/cmdline)
  [ -n "$args" ] || stop "/proc/cmdline came back empty; refusing to write a boot entry from it"

  local uuid
  uuid=$(findmnt -no UUID /) || stop "the root filesystem's UUID could not be read"
  [ -n "$uuid" ] || stop "the root filesystem has no UUID to search for"

  sudo cp -n "$CUSTOM" "$KEEP" 2>/dev/null
  {
    echo "#!/bin/sh"
    echo "exec tail -n +3 \$0"
    echo "# Written by cloud/azure/cpus.sh. One entry, booted once through grub-reboot, carrying"
    echo "# the running boot's own command line plus the core count. Nothing else differs."
    echo "menuentry 'sbl: $rel, $n CPUs' --id $ENTRY_ID {"
    echo "  insmod part_gpt"
    echo "  insmod ext2"
    echo "  search --no-floppy --fs-uuid --set=root $uuid"
    echo "  linux /boot/vmlinuz-$rel $args nr_cpus=$n"
    echo "  initrd /boot/initrd.img-$rel"
    echo "}"
  } | sudo tee "$CUSTOM" >/dev/null || stop "the custom entry could not be written"
  sudo chmod +x "$CUSTOM"
  sudo update-grub >/dev/null 2>&1 || stop "update-grub failed; the menu may be half written"
  sudo grep -q "$ENTRY_ID" /boot/grub/grub.cfg || stop "the entry did not reach the menu"
  sudo grub-reboot "$ENTRY_ID" || stop "grub-reboot did not take; not rebooting"
  log "the next boot only will have $n CPUs, on $rel; the default is untouched"
  log "reboot now, then run: bash cloud/azure/cpus.sh check $n"
}

check () {
  local n="${1:?how many CPUs}"
  # Under sudo, as campaign.sh runs the same command: the base slice lives in debugfs, which is
  # mounted 0700 root, so an unprivileged read comes back empty and the check reports that the
  # slice could not be read on a machine that is perfectly willing to say.
  sudo python3 scripts/sched_settings.py check --cpus "$n" > "$DIR/check-cpu$n.json"
  local ok=$?
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1]));
print("\n".join("   " + p for p in d["problems"]) or "   nothing wrong");
s=d["settings"];
print("   %s CPUs online, base slice %s ns, scaling %s"
      % (s["online_cpus"], s["base_slice_ns"], s["tunable_scaling"]))' "$DIR/check-cpu$n.json"
  [ "$ok" = 0 ] || stop "the machine is not the $n-CPU machine A5 asked for; see $DIR/check-cpu$n.json"
  log "CAMPAIGN_COMPLETE: $n CPUs, and the slice the kernel's own rule gives for $n"
}

restore () {
  [ -r "$KEEP" ] && { sudo cp "$KEEP" "$CUSTOM" || stop "the original menu file could not be put back"; }
  [ -r "$GRUBKEEP" ] && { sudo cp "$GRUBKEEP" "$GRUBDEF" || stop "the original grub defaults could not be put back"; }
  sudo update-grub >/dev/null 2>&1 || stop "update-grub failed while restoring"
  sudo grep -q "$ENTRY_ID" /boot/grub/grub.cfg && stop "the entry is still in the menu after restoring"
  log "CAMPAIGN_COMPLETE: the menu is as it was; the next boot is the default one"
}

case "${1:-}" in
  boot) boot "${2:-}" ;;
  check) check "${2:-}" ;;
  restore) restore ;;
  *) echo "usage: bash cloud/azure/cpus.sh boot <n> | check <n> | restore" >&2; exit 2 ;;
esac
