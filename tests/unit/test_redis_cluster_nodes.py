"""Tests for scripts/redis_cluster_nodes.py - target >=95% branch coverage."""
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from redis_cluster_nodes import (  # noqa: E402
    parse_cluster_nodes,
    resolve_startup_nodes,
    build_cluster_client,
)


class TestParseClusterNodes:
    def test_host_port_pairs(self):
        assert parse_cluster_nodes("a:7000,b:7001") == [("a", 7000), ("b", 7001)]

    def test_bare_host_takes_default_port(self):
        assert parse_cluster_nodes("a,b", default_port=7000) == [("a", 7000), ("b", 7000)]

    def test_ipv6ish_uses_last_colon(self):
        assert parse_cluster_nodes("fd00::1:7000") == [("fd00::1", 7000)]

    @pytest.mark.parametrize("spec", ["", None])
    def test_empty(self, spec):
        assert parse_cluster_nodes(spec) == []

    def test_whitespace_and_trailing_commas_ignored(self):
        assert parse_cluster_nodes(" a:7000 , , b:7001 ,") == [("a", 7000), ("b", 7001)]


class TestResolveStartupNodes:
    def test_legacy_single_host_triple_and_remap(self):
        nodes, remap = resolve_startup_nodes("h")
        assert nodes == [("h", 7000), ("h", 7001), ("h", 7002)]
        assert remap is True, "single-host layout still needs the localhost remap"

    def test_explicit_nodes_disable_remap(self):
        # Remapping a genuinely distributed cluster to one host would break routing --
        # this is what confined the paper's cluster arm to a single machine.
        nodes, remap = resolve_startup_nodes("h", "10.0.1.1:7000,10.0.1.2:7000")
        assert nodes == [("10.0.1.1", 7000), ("10.0.1.2", 7000)]
        assert remap is False


class _Node:
    def __init__(self, host, port):
        self.host, self.port = host, port

    def __eq__(self, o):
        return (self.host, self.port) == (o.host, o.port)


class _Cluster:
    def __init__(self, startup_nodes, decode_responses=True, address_remap=None):
        self.startup_nodes = startup_nodes
        self.decode_responses = decode_responses
        self.address_remap = address_remap


class TestBuildClusterClient:
    def test_single_host_passes_remap(self):
        c = build_cluster_client(_Cluster, _Node, "h")
        assert c.address_remap is not None
        assert c.address_remap(("172.20.0.5", 7001)) == ("127.0.0.1", 7001)
        assert len(c.startup_nodes) == 3

    def test_multi_host_omits_remap(self):
        c = build_cluster_client(_Cluster, _Node, "ignored",
                                 "10.0.1.1:7000,10.0.1.2:7000,10.0.1.3:7000")
        assert c.address_remap is None
        assert [(n.host, n.port) for n in c.startup_nodes] == [
            ("10.0.1.1", 7000), ("10.0.1.2", 7000), ("10.0.1.3", 7000)]

    def test_decode_responses_forwarded(self):
        assert build_cluster_client(_Cluster, _Node, "h", decode_responses=False
                                    ).decode_responses is False
        assert build_cluster_client(_Cluster, _Node, "h", "a:1",
                                    decode_responses=False).decode_responses is False
