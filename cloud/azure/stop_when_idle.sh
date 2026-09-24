#!/usr/bin/env bash
# Deallocate this pair once its work has been gone for two looks in a row.
#
# Written on 24 September, after the PC that ran the watch was restarted. The watch's idle rule
# was what stopped a pair whose work had ended, and it went with the PC and with its Azure login.
# The queue could not stand in for it: a job that only holds the list gives up after twelve
# hours, and the Arm pair's A3 had sixteen left, so the list would have ended and the stop fired
# four hours before the campaign did. This waits as long as the work takes.
#
# It runs on the driver under setsid and nohup, so it survives anything that happens to whoever
# started it, and it stops the pair through the driver's own managed identity (stop_self.sh)
# rather than through anybody's login.
#
# Work is read from the process list the way queue.sh reads it, and the pattern arrives in the
# environment rather than on a command line, so there is nothing for it to match itself in.
# Two looks five minutes apart, because work hands over: a waiter sleeps a minute between its
# own looks, and a pair stopped in that gap loses the next piece of work with nobody to notice.
#
#     WORK='azure/(campaign|stage0|stage1|chain)[.]sh' \
#       setsid nohup bash ~/stop_when_idle.sh > ~/stop_when_idle.log 2>&1 < /dev/null &
set -euo pipefail
#: The checkout, wherever this copy of the script sits. A copy is started from outside the repo
#: on a pair that is mid-work, because an untracked file inside it is what made `git pull` abort
#: quietly on the second x86 pair for a day.
cd "$HOME/sbl" || exit 1
WORK="${WORK:?what counts as work, as an extended regular expression over the process list}"
LOOK_S="${LOOK_S:-300}"
LOOKS="${LOOKS:-2}"

log () { echo "$(date -u +%FT%TZ) $*"; }

busy () {
  ps -eo args --no-headers \
    | awk 'match($0, ENVIRON["WORK"]) && !/awk/ { n++ } END { exit !(n > 0) }'
}

export WORK
#: A pattern that matches its own spelling counts, as work, any command line that carries it --
#: the shell that started this, a colleague's pgrep, a note in a log being tailed -- and while one
#: exists the pair is never quiet and never stopped. Found in testing on 24 September: a plain
#: word such as run_t2_all matches itself, where azure/(campaign|chain)[.]sh does not. Write one
#: letter of each plain word in brackets, as run_t2_al[l], and the pattern stops matching its
#: own text while still matching the process.
if printf '%s\n' "$WORK" | awk 'match($0, ENVIRON["WORK"]) { f = 1 } END { exit !f }'; then
  log "REFUSED: '$WORK' matches its own spelling, so any command line carrying it would count" \
      "as work for ever; write one letter of each plain word in brackets, as run_t2_al[l]"
  exit 2
fi
quiet=0
log "watching for: $WORK"
while [ "$quiet" -lt "$LOOKS" ]; do
  if busy; then quiet=0; else quiet=$((quiet + 1)); fi
  log "quiet looks in a row: $quiet of $LOOKS"
  #: An if, not `[ ... ] && sleep`: on the last pass that list returns non-zero, the loop
  #: returns it, and under set -e the script can end there -- one line short of the only thing
  #: it exists to do.
  if [ "$quiet" -lt "$LOOKS" ]; then sleep "$LOOK_S"; fi
done
log "the work is done; stopping this pair"
bash cloud/azure/stop_self.sh
