#!/usr/bin/env bash
# Build the nats.go consumer from its pinned library and compiler, and check what was built
# before it is used.
#
# 23 Oct 2026: nats.go v1.54.0 is the latest release of the official Go client of NATS, and
# go1.26.0 is the least toolchain it accepts: its go.mod says go 1.26.0, as do those of
# golang.org/x/crypto v0.57.0 and golang.org/x/sys v0.48.0, which it requires. go1.23.11, which
# builds harness/go, refuses them. natscli says go 1.26.0 too, at the commit cloud/azure/tools.sh
# pins for nats-latency and nats-bench (cc0a8e32): with no newer Go installed, go install switches
# to go1.26.0 for it, so the consumer and those audited tools are built by one compiler. go.sum
# holds the checksums the Go checksum database gives for each module, and a build that would need
# any other module stops.
#
# Usage: bash harness/go-nats/build.sh
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

NATS_GO_VERSION=v1.54.0
GO_TOOLCHAIN=go1.26.0

say () { echo "$(date -u +%H:%M:%S) $*"; }

# cloud/azure/tools.sh installs Go 1.22.5 at /usr/local/go (get_go) and puts it on the PATH of
# its own shell only.
command -v go >/dev/null 2>&1 || export PATH="/usr/local/go/bin:$PATH"
command -v go >/dev/null 2>&1 || {
  say "no go on PATH; cloud/azure/tools.sh installs Go 1.22.5 at /usr/local/go"; exit 1; }
mkdir -p out

# GOTOOLCHAIN names the compiler exactly: the go command fetches it once from the module proxy,
# checked against the checksum database, as it fetches the toolchain harness/go names. go.mod has
# no toolchain line, because its go line already implies go1.26.0. With -mod=readonly, a module
# that go.sum does not vouch for stops the build rather than being added.
export GOTOOLCHAIN="$GO_TOOLCHAIN" GOFLAGS=-mod=readonly CGO_ENABLED=0

say "checking the source with $(go version)"
go vet . || { say "STOP: go vet found a fault in main.go. Not building."; exit 1; }

say "compiling"
go build -o out/natsgo-consumer . || { say "the consumer did not build"; exit 1; }

say "checking what was built against the pins"
go version -m out/natsgo-consumer > out/BUILD_INFO.txt || {
  say "could not read the binary's build record"; exit 1; }
head -n 1 out/BUILD_INFO.txt | grep -q ": $GO_TOOLCHAIN\$" || {
  say "STOP: the binary was built by $(head -n 1 out/BUILD_INFO.txt | cut -d' ' -f2), not $GO_TOOLCHAIN"
  exit 1; }
grep -E -q "^[[:space:]]*dep[[:space:]]+github.com/nats-io/nats.go[[:space:]]+$NATS_GO_VERSION[[:space:]]" \
    out/BUILD_INFO.txt || {
  say "STOP: the binary is not built on nats.go $NATS_GO_VERSION; see out/BUILD_INFO.txt"; exit 1; }
sha256sum out/natsgo-consumer > out/SHA256SUM

say "built: harness/go-nats/out/natsgo-consumer, on nats.go $NATS_GO_VERSION by $GO_TOOLCHAIN"
