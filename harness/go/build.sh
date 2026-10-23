#!/usr/bin/env bash
# Build the franz-go consumer from its pinned library and compiler, and check what was built
# before it is used.
#
# 23 Oct 2026: franz-go v1.19.5 is the release Redpanda's kgo-repeater, the audited tool built on
# franz-go, requires at the commit cloud/azure/tools.sh pins (6567f2f5, its go.mod), and go1.23.11
# is the toolchain that go.mod names. This module names the same two, so the consumer and the
# audited tool are one client library built by one compiler. go.sum holds the checksums the Go
# checksum database gives for each module, and a build that would need any other module stops.
#
# Usage: bash harness/go/build.sh
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

FRANZ_GO_VERSION=v1.19.5
GO_TOOLCHAIN=go1.23.11

say () { echo "$(date -u +%H:%M:%S) $*"; }

# cloud/azure/tools.sh installs Go 1.22.5 at /usr/local/go (get_go) and puts it on the PATH of
# its own shell only.
command -v go >/dev/null 2>&1 || export PATH="/usr/local/go/bin:$PATH"
command -v go >/dev/null 2>&1 || {
  say "no go on PATH; cloud/azure/tools.sh installs Go 1.22.5 at /usr/local/go"; exit 1; }
mkdir -p out

# GOTOOLCHAIN names the compiler exactly: the go command fetches it once from the module proxy,
# checked against the checksum database, as it fetched it for kgo-verifier on the driver. With
# -mod=readonly, a module that go.sum does not vouch for stops the build rather than being added.
export GOTOOLCHAIN="$GO_TOOLCHAIN" GOFLAGS=-mod=readonly CGO_ENABLED=0

say "checking the source with $(go version)"
go vet . || { say "STOP: go vet found a fault in main.go. Not building."; exit 1; }

say "compiling"
go build -o out/franz-consumer . || { say "the consumer did not build"; exit 1; }

say "checking what was built against the pins"
go version -m out/franz-consumer > out/BUILD_INFO.txt || {
  say "could not read the binary's build record"; exit 1; }
head -n 1 out/BUILD_INFO.txt | grep -q ": $GO_TOOLCHAIN\$" || {
  say "STOP: the binary was built by $(head -n 1 out/BUILD_INFO.txt | cut -d' ' -f2), not $GO_TOOLCHAIN"
  exit 1; }
grep -E -q "^[[:space:]]*dep[[:space:]]+github.com/twmb/franz-go[[:space:]]+$FRANZ_GO_VERSION[[:space:]]" \
    out/BUILD_INFO.txt || {
  say "STOP: the binary is not built on franz-go $FRANZ_GO_VERSION; see out/BUILD_INFO.txt"; exit 1; }
sha256sum out/franz-consumer > out/SHA256SUM

say "built: harness/go/out/franz-consumer, on franz-go $FRANZ_GO_VERSION by $GO_TOOLCHAIN"
