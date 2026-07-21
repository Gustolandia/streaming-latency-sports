#!/usr/bin/env python3
"""
redis_cluster_nodes.py
Resolve the startup nodes for a Redis Cluster client.

Cluster support in this suite was originally written against a single-host docker-compose
layout that published three nodes on one machine as ports 7000/7001/7002, and it rewrote every
node address it discovered back to 127.0.0.1. That is correct for that layout and *impossible*
to use against a real cluster, where the three nodes sit on three different hosts sharing one
port. The paper's cluster arm was therefore confined to a single host by the client, not only
by the testbed.

This module keeps the legacy behaviour as the default so existing single-host runs are
unchanged, and adds an explicit multi-host form.
"""


def parse_cluster_nodes(spec, default_port=7000):
    """Parse "h1:7000,h2:7000,h3" into [(host, port), ...]; empty/None gives []."""
    nodes = []
    if not spec:
        return nodes
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            host, port = part.rsplit(":", 1)
            nodes.append((host, int(port)))
        else:
            nodes.append((part, int(default_port)))
    return nodes


def resolve_startup_nodes(host, cluster_nodes=None, default_port=7000):
    """Startup nodes plus whether addresses should be remapped to a single host.

    Returns (nodes, remap_to_localhost).

    With an explicit --cluster-nodes list the cluster is genuinely distributed, so the
    discovered addresses are already routable and remapping them would break routing. Without
    one we fall back to the historical single-host triple and keep the remap, because there the
    published ports really do all live on one machine.
    """
    explicit = parse_cluster_nodes(cluster_nodes, default_port)
    if explicit:
        return explicit, False
    return [(host, 7000), (host, 7001), (host, 7002)], True


def build_cluster_client(cluster_cls, node_cls, host, cluster_nodes=None, default_port=7000,
                         decode_responses=True):
    """Construct a RedisCluster for either topology.

    Kept separate from the callers so producer and consumer cannot drift apart: a mismatch
    between how the two connect is exactly the kind of asymmetry this project has been bitten
    by before.
    """
    nodes, remap = resolve_startup_nodes(host, cluster_nodes, default_port)
    startup = [node_cls(host=h, port=p) for h, p in nodes]
    if remap:
        return cluster_cls(startup_nodes=startup, decode_responses=decode_responses,
                           address_remap=lambda node: ("127.0.0.1", node[1]))
    return cluster_cls(startup_nodes=startup, decode_responses=decode_responses)
