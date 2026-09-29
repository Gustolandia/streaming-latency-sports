# GitHub (registered source 4): issues/PRs and repository text of
# openmessaging/benchmark and its public forks (GitHub forks plus detached
# copies of the OMB code; see search_log.md). Result JSON files are in rows_4.

import ast
import json
import os
import re

R = "2026-09-28"
GH = "4 GitHub"
HERE = os.path.dirname(os.path.abspath(__file__))

REPORTS = []

# ------------------------------------------------ openmessaging/benchmark issues
_up = [
    (141, "2019-01-17", "Failed to benchmark pulsar", "publish latency only (console log)",
     "Pub Latency (ms) avg: 4726.2 - 50%: 5703.2 - 99%: 9423.6 - 99.9%: 9423.6"),
    (171, "2020-03-06", "Bookkeeper-driver doesn't support distributed mode", "publish latency only (console log)",
     "Pub Latency (ms) avg: 6.3 - 50%: 3.3 - 99%: 48.7 - 99.9%: 50.1 - Max: 50.3"),
    (275, "2022-07-28", "driver-kafka - Waiting for consumers to be ready never ending", "publish latency only (console log)",
     "Pub Latency (ms) avg: 53.9 - 50%: 35.6 - 99%: 375.2 - 99.9%: 375.2 - Max: 375.2"),
    (199, "2021-10-21", "comment on PR 199 (Pravega driver)", "publish latency only (console log)",
     "----- Aggregated Pub Latency (ms) avg: 4.2 - 50%: 3.8 - 95%: 6.1 - 99%: 9.4 - 99.9%: 97.1 - 99.99%: 150.9 - Max: 163.4"),
    (216, "2021-11-18", "Can the average publish latency be larger than end-to-end latency? (listed in already_read.txt)",
     "no numeric end-to-end percentile printed", "I observe that the calculated values of publishLatencyAvg are larger than endToEndLatencyAvg for the same test."),
    (452, "2026-03-26", "export serialized HDR Histogram (listed in already_read.txt)",
     "no OMB result: the numbers are a hypothetical example ('configuration B p99 = 14.6ms vs configuration A p99 = 14.1ms')",
     'A result showing "configuration B p99 = 14.6ms vs configuration A p99 = 14.1ms" looks like a meaningful difference'),
    (56, "2018-03-22", "Avoid adding negative metric values (listed in already_read.txt)", "no result numbers (code change: origin of the positivity filter)", ""),
    (247, "2022-03-01", "The load generation need to fix Coordinated Omission (listed in already_read.txt)", "no result numbers", ""),
    (398, "2023-12-06", "Grow buffer if histogram can't fit (listed in already_read.txt)", "no result numbers", ""),
]
for n, d, title, reason, q in _up:
    kind = "pull" if n in (56, 199, 398) else "issues"
    REPORTS.append(dict(
        id="gh_omb_%d" % n, source=GH + ": openmessaging/benchmark issues/PRs", url="https://github.com/openmessaging/benchmark/%s/%d" % (kind, n),
        date=d, retrieved=R, tool="OMB", src="gh/threads/openmessaging_benchmark_%d.txt" % n, included="no", reason=reason,
        configs=[dict(configuration=title, quote=q)]))

# ------------------------------------------------ fork issues / PR comments with printed e2e values
REPORTS += [
    dict(id="gh_pravega_18", source=GH + ": pravega/openmessaging-benchmark issue", url="https://github.com/pravega/openmessaging-benchmark/issues/18",
         date="2020-03-25", retrieved=R, tool="OMB (Pravega's fork, pravega/openmessaging-benchmark, a detached copy of OMB)",
         src="gh/threads/pravega_openmessaging-benchmark_18.txt", included="yes",
         notes="Console output of the Pravega fork (which prints E2E lines). Consumers received 20.8 msg/s, yet every end-to-end statistic prints 0.0: the median is 0.0, NOT 1 ms (unforeseen: an empty end-to-end histogram). The issue concerns a transactions-enabled driver default; no discard count is stated.",
         configs=[dict(broker="Pravega (enableTransaction default true)", configuration="workloads/1-topic-1-partition-100b.yaml, driver-pravega/pravega.yaml",
                       e2e_p50_ms="0.0", e2e_p99_ms="0.0", other="p95 0.0; p99.9 0.0; p99.99 0.0; max 0.0; avg 0.0",
                       quote="----- Aggregated E2E Latency (ms) avg:  0.0 - 50%:  0.0 - 95%:  0.0 - 99%:  0.0 - 99.9%:  0.0 - 99.99%:  0.0 - Max:  0.0")]),
    dict(id="gh_pravega_pr40", source=GH + ": pravega/openmessaging-benchmark PR comment", url="https://github.com/pravega/openmessaging-benchmark/pull/40#issuecomment-668017291",
         date="2020-08-03", retrieved=R, tool="OMB (Pravega's fork)", src="gh/threads/pravega_openmessaging-benchmark_40.txt", included="yes",
         configs=[dict(broker="Apache Kafka (AWS, driver-kafka/kafka.yaml)", configuration="'1 topic / 16 partition / 10kb / 50k' (producerRate 50000, 10 KB, 3 min)",
                       e2e_p50_ms="19.0", e2e_p99_ms="694.0", other="p95 504.0; p99.9 818.0; p99.99 904.0; max 955.0; avg 121.2",
                       quote="----- Aggregated E2E Latency (ms) avg: 121.2 - 50%: 19.0 - 95%: 504.0 - 99%: 694.0 - 99.9%: 818.0 - 99.99%: 904.0 - Max: 955.0")]),
    dict(id="gh_redpanda_pr58", source=GH + ": redpanda-data/openmessaging-benchmark PR comment", url="https://github.com/redpanda-data/openmessaging-benchmark/pull/58#issuecomment-1553953234",
         date="2023-05-19", retrieved=R, tool="OMB (Redpanda's fork)", src="gh/threads/redpanda-data_openmessaging-benchmark_58.txt", included="yes",
         notes="A single 10-second window printed during warm-up (not a final aggregate); pasted to show topic deletion works. Sub-millisecond digits: the Redpanda fork's end-to-end values are not whole milliseconds.",
         configs=[dict(broker="Redpanda (driver-redpanda/redpanda-ack-all-group-linger-10ms.yaml, swarm topology)", configuration="'1 topic / 1 partition / 1Kb' (warm-up window)",
                       e2e_p50_ms="9.574", e2e_p99_ms="15.356", other="p99.9 17.401; max 6015.871; avg 9.624",
                       quote="E2E Latency (ms) avg: 9.624 - 50%: 9.574 - 99%: 15.356 - 99.9%: 17.401 - Max: 6015.871")]),
    dict(id="gh_jeqo_1", source=GH + ": jeqo/openmessaging-benchmark issue comment (GitHub fork)", url="https://github.com/jeqo/openmessaging-benchmark/issues/1#issuecomment-1602081733",
         date="2023-06-22", retrieved=R, tool="OMB (jeqo's fork)", src="gh/threads/jeqo_openmessaging-benchmark_1.txt", included="yes",
         notes="'Initial results for business 4 cluster on gcp eu-central-1' (Aiven Kafka); the raw result JSON is attached as a zip (not examined: archive).",
         configs=[dict(broker="Apache Kafka (Aiven business-4 plan)", configuration="1-topic-16-partitions-1kb, driver-kafka/kafka-throughput.yaml",
                       e2e_p50_ms="660.003", e2e_p99_ms="2125.007", other="p75 1065.007; p95 1671.007; p99.9 2749.007; p99.99 3620.015; max 4167.007; avg 752.1609456",
                       quote="end-to-end-latency | 752.1609456 | 660.003 | 1065.007 | 1671.007 | 2125.007 | 2749.007 | 3620.015 | 4167.007")]),
    dict(id="gh_kaimingwan_2", source=GH + ": KaimingWan/openmessaging-benchmark issue comment (fork network of AutoMQ/openmessaging-benchmark)", url="https://github.com/KaimingWan/openmessaging-benchmark/issues/2#issuecomment-2143341981",
         date="2024-06-01", retrieved=R, tool="OMB (AutoMQ fork; issue titled 'AutoMQ OpenMessaging Benchmark Report')", src="gh/threads/KaimingWan_openmessaging-benchmark_2.txt", included="yes",
         notes="Automated report posted by github-actions[bot]. No median printed (average, P95, P99).",
         configs=[
             dict(broker="AutoMQ", configuration="1-topic-1000-partitions-4kb-4p4c-500m (producerRate 128000, 4 KB, 1 min)", e2e_p99_ms="802.37", other="P95 576.05; avg 303.23",
                  quote="| AutoMQ           | 303.23      | 576.05     | 802.37     | 278.46 | 18.0 | 296.46 |"),
             dict(broker="Apache Kafka", configuration="1-topic-1000-partitions-4kb-4p4c-500m (producerRate 128000, 4 KB, 1 min)", e2e_p99_ms="5797.44", other="P95 3517.53; avg 952.31",
                  quote="| Apache Kafka           | 952.31      | 3517.53     | 5797.44     | 737.46 | 0.0 | 737.46 |"),
         ]),
    dict(id="gh_automq_pr23", source=GH + ": AutoMQ/openmessaging-benchmark PR", url="https://github.com/AutoMQ/openmessaging-benchmark/pull/23",
         date="2023-06-07", retrieved=R, tool="OMB (AutoMQ fork)", src="gh/threads/AutoMQ_openmessaging-benchmark_23.txt", included="no",
         reason="no numbers (PR titled 'fix: fix E2E latency precision problem'; empty body)",
         configs=[dict(configuration="-", quote="fix: fix E2E latency precision problem; fix controller num for kafka",
                       notes="Context: AutoMQ changed its fork's end-to-end precision in June 2023.")]),
    dict(id="gh_redpanda_pr22", source=GH + ": redpanda-data/openmessaging-benchmark PR", url="https://github.com/redpanda-data/openmessaging-benchmark/pull/22",
         date="2022-07-27", retrieved=R, tool="OMB (Redpanda fork)", src="gh/threads/redpanda-data_openmessaging-benchmark_22.txt", included="no",
         reason="methodology change, no result numbers",
         configs=[dict(configuration="-", quote="a consume ignores records originated on different nodes and only measure e2e latency of the records written by the same node",
                       notes="Context: the Redpanda fork's SwarmWorker topology measures end-to-end latency on one node.")]),
]

# ------------------------------------------------ fork repository text
_NB = os.path.join(HERE, "gh", "fork_scan", "files", "rokinmaharjan_openmessaging__bin_scripts_LatencyGraph.ipynb")
_nbraw = open(_NB, encoding="utf-8").read()
_nb = json.loads(_nbraw)
_out = "\n".join("".join(o.get("text", [])) for o in _nb["cells"][2]["outputs"])
_line = [l for l in _out.splitlines() if l.startswith("{")][0]
_d = ast.literal_eval(_line)
_nbcfg = []
for rate in ("1MBps", "3MBps", "6MBps", "10MBps", "15MBps"):
    # exact printed substring for this rate, from its key to the end of its 99pct list
    i = _line.index("'%s': {" % rate)
    j = _line.index("'aggregatedEndToEndLatency99pct'", i)
    k = _line.index("]", j) + 1
    quote = _line[i:k]
    assert quote in _nbraw
    for broker in ("Redis", "RabbitMQ", "Artemis"):
        get = lambda key: [list(x.values())[0] for x in _d[rate][key] if broker in x][0]
        p50, p99 = get("aggregatedEndToEndLatency50pct"), get("aggregatedEndToEndLatency99pct")
        p75, p95, p999 = get("aggregatedEndToEndLatency75pct"), get("aggregatedEndToEndLatency95pct"), get("aggregatedEndToEndLatency999pct")
        _nbcfg.append(dict(
            broker={"Redis": "Redis 7.0.9 (pub/sub)", "RabbitMQ": "RabbitMQ 3.11.10", "Artemis": "ActiveMQ Artemis 2.28.0"}[broker],
            configuration="latency experiment at %s (32 KB messages, 5 min)" % rate,
            e2e_p50_ms=repr(p50), e2e_p99_ms=repr(p99), other="p75 %r; p95 %r; p99.9 %r" % (p75, p95, p999),
            quote=quote, check=True,
            notes=("PRIMARY: printed end-to-end median of exactly 1.0 ms; p99 2.0 (not the strong signature)." if (broker == "Redis" and p50 == 1.0) else "")))
REPORTS.append(dict(
    id="gh_rokinmaharjan_notebook", source=GH + ": rokinmaharjan/openmessaging (GitHub fork of openmessaging/benchmark), repository text",
    url="https://github.com/rokinmaharjan/openmessaging/blob/master/bin/scripts/LatencyGraph.ipynb", date="2023-04-02", retrieved=R,
    tool="OMB (fork rokinmaharjan/openmessaging)", src="gh/fork_scan/files/rokinmaharjan_openmessaging__bin_scripts_LatencyGraph.ipynb", src_kind="json",
    included="yes",
    notes="Saved output of a Colab notebook prints the aggregated OMB fields read from the authors' result JSON (kept on Google Drive; the repository holds them only as results/Latency.zip). Data behind 'Benchmarking Message Queues' (Maharjan et al., Telecom 2023; methods: 32 KB messages, 5-minute runs, brokers installed locally). The same dict is printed twice (cells 2 and 3); coded once. Kafka is not in the printed dict.",
    configs=_nbcfg))

_SPEC = "gh/fork_scan/files/conduktor_openmessaging-benchmark__docs_superpowers_specs_2026-07-24-chop-throughput-verdict-design.md"
_LOG = "gh/fork_scan/files/conduktor_openmessaging-benchmark__docs_ramp-finder-trial-log.md"
REPORTS += [
    dict(id="gh_conduktor_spec", source=GH + ": conduktor/openmessaging-benchmark (GitHub fork), repository text",
         url="https://github.com/conduktor/openmessaging-benchmark/blob/conduktor-gateway/docs/superpowers/specs/2026-07-24-chop-throughput-verdict-design.md",
         date="2026-07-29 (committed; document dated 2026-07-24)", retrieved=R, tool="OMB (Conduktor fork with a ramp rate finder)", src=_SPEC, included="yes",
         notes="Design note in the fork's docs; AKS re-validation, 1 topic / 100 partitions / 100-byte messages.",
         configs=[dict(broker="Apache Kafka via Conduktor Gateway (AKS)", configuration="chop-ceiling, rampMaxBacklogSeconds 1.0, ~880,000 msg/s held 15 min",
                       e2e_p99_ms="326", quote="avg publish-delay 0.12 ms, e2e p99 326 ms")]),
    dict(id="gh_conduktor_triallog", source=GH + ": conduktor/openmessaging-benchmark (GitHub fork), repository text",
         url="https://github.com/conduktor/openmessaging-benchmark/blob/conduktor-gateway/docs/ramp-finder-trial-log.md",
         date="2026-07-29 (updated 2026-08-12)", retrieved=R, tool="OMB (Conduktor fork)", src=_LOG, included="yes",
         notes="Working notes; the value is a momentary windowed p99 spike read by the authors from their own plot during rate discovery, printed in text.",
         configs=[dict(broker="Apache Kafka via Conduktor Gateway (encrypt)", configuration="'encrypt' rate discovery, at the bracket's doubling overshoot",
                       e2e_p99_ms="~3 s (momentary)", converted=True, quote="messages and e2e p99 latency to ~3 seconds at the exact moment bracket's doubling overshoots past")]),
    dict(id="gh_vanlightly_custom", source=GH + ": Vanlightly/openmessaging-benchmark-custom (detached copy), repository text",
         url="https://github.com/Vanlightly/openmessaging-benchmark-custom/blob/main/charts/README.md", date="(repository)", retrieved=R, tool="OMB (custom)",
         src="gh/fork_scan/files/Vanlightly_openmessaging-benchmark-custom__charts_README.md", included="no",
         reason="chart axis ranges and dashboard titles, not results", configs=[dict(configuration="-", quote="Up to p99 percentile end-to-end latency chart has a range from 0 to 300ms.")]),
]
