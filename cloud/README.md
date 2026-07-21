# Multi-host testbed (Oracle Cloud Always Free, uk-london-1)

Replaces the single-host Windows/WSL2 rig for the network-realism (RQ5) and cluster arms.
Provisioned entirely through the OCI CLI; see `provision.sh`.

## Why

The single-host testbed imposed two floors on every reported number
(`docs/results/platform/platform.json`):

* the Windows timer tick quantised event emission to ~15.6 ms, which supplied 53-78% of TTI;
* "loopback" traffic crossed Docker Desktop's port forwarder and the WSL2 virtual NIC.

Both are removed here (`docs/results/platform/platform_linux_crossvm.json`):

| metric | Windows/WSL2 "loopback" | Linux cross-VM | factor |
|---|---|---|---|
| `sleep(1ms)` median | 15.575 ms | **1.075 ms** | 14.5x finer |
| `sleep(10ms)` median | 15.793 ms | 10.092 ms | now correct |
| Redis TCP connect RTT | 5.572 ms | **0.303 ms** | 18.4x |
| Redis PING RTT (established) | 0.460 ms | **0.239 ms** | 1.9x |

Note the third and fourth rows: a genuine two-machine network is **faster** than the
original "co-located" path. The co-location claim was measured on a worse path than a LAN.

## Topology

| host | shape | role |
|---|---|---|
| `sbl-broker` | VM.Standard.E2.1.Micro | Kafka / Redis broker |
| `sbl-client` | VM.Standard.E2.1.Micro | producer + consumer |

Both in `uk-london-1` AD-3, VCN `10.0.0.0/16`, subnet `10.0.1.0/24`.
Broker ports are reachable **only** from inside the VCN (security list); no broker is
exposed to the internet. SSH is key-only.

`VM.Standard.A1.Flex` (ARM, 4 OCPU / 24 GB) is the preferred shape and is what the
3-node cluster arm needs, but London ARM capacity was exhausted at provisioning time
("Out of host capacity" in all ADs). `a1_retry.sh` polls for it.

## Caveat

`E2.1.Micro` is 1/8 OCPU burstable with 1 GB RAM. It is adequate for Redis and for the
round-trip-bound mechanism, but CPU throttling adds variance, and Kafka's JVM is tight at
1 GB. Treat micro-shape numbers as establishing the *mechanism*, not as capacity figures.
