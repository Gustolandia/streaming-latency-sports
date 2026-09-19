#!/usr/bin/env bash
# Build the Java client for A8, from pinned jars, and check it before it is used.
#
# Which build of Kafka's client ran is part of what A8 reports, so the jars are pinned by
# fingerprint and a mismatch stops the build rather than quietly producing a different experiment.
# The self test needs no broker and runs last: it is the only place where a clock too coarse to
# measure with announces itself before a run rather than after.
#
# Usage: bash harness/java/build.sh
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

KAFKA_VERSION=3.9.0
SLF4J_VERSION=1.7.36
BASE=https://repo1.maven.org/maven2

say () { echo "$(date -u +%H:%M:%S) $*"; }

command -v javac >/dev/null 2>&1 || { say "no javac on PATH; install a JDK (17 or later)"; exit 1; }
mkdir -p lib out

fetch () {
  local url="$1" into="$2"
  [ -s "$into" ] && return 0
  say "fetching $(basename "$into")"
  curl -fsSL -o "$into" "$url" || { say "could not fetch $url"; return 1; }
}

fetch "$BASE/org/apache/kafka/kafka-clients/$KAFKA_VERSION/kafka-clients-$KAFKA_VERSION.jar" \
      lib/kafka-clients.jar || exit 1
fetch "$BASE/org/slf4j/slf4j-api/$SLF4J_VERSION/slf4j-api-$SLF4J_VERSION.jar" \
      lib/slf4j-api.jar || exit 1

say "checking the jars against DEPENDENCIES"
( cd lib && sha256sum -c ../DEPENDENCIES ) || {
  say "STOP: a jar does not match its pinned fingerprint. A8 reports which client ran, so a jar"
  say "      that changed under us is a different experiment. Not building."
  exit 1
}

# Windows keeps its classpath entries apart with a semicolon and everything else with a colon.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) SEP=";" ;;
  *) SEP=":" ;;
esac
CP="lib/kafka-clients.jar${SEP}lib/slf4j-api.jar"

say "compiling"
javac -Xlint:all -d out -cp "$CP" src/*.java || { say "the client did not compile"; exit 1; }

say "checking what needs no broker"
java -cp out LawSelfTest || {
  say "STOP: the self test failed. If it is the clock, this machine cannot run A8: the client"
  say "      refuses a clock that steps coarser than the effect being measured."
  exit 1
}

say "built: harness/java/out, against kafka-clients $KAFKA_VERSION"
