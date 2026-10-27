# The broker audit: what each broker tells a consumer about a message's time at the broker

Written 27 October 2026, before any record of this audit was coded. It reads documentation and
source code only. No machine is used, and nothing here reads a run of ours.

**Why.** The general method splits each message's kernel-timed latency `W` into two parts:
- the trip to a ready receiver, `F`;
- the part the consumer's thread adds by not having asked yet, `min(T_c, S)`.

The client times its own turnaround `T_c` exactly. `S` is the time the message waited at the broker
before the request or credit that took it arrived. Only the broker sees both ends of that wait. So
the split is exact in two cases:
- the broker tells the consumer `S`, or the two times on its own clock that `S` is the difference
  of;
- the consumer keeps a request or credit waiting for every message, so that `S` is zero. Plans 47
  and 49 showed that a client can certify this from its own timestamps.

This audit asks, for each broker, which of the two it allows. Its answers go to two groups: the
people who build brokers, and the people who build the tools that time them.

## The brokers

**Group A: the brokers the industry's tools time.** Every message broker that at least one tool in
the tools audit ([`data/tools_audit/`](../tools_audit/)) can time through, as that tool's own
repository names it at its audited version.

| Broker | Tools that time it (where the tool names it, at its audited commit) |
|---|---|
| Apache Kafka | OpenMessaging Benchmark `driver-kafka/`; SBK `drivers/kafka`; Kafka's EndToEndLatency, ProducerPerformance and Trogdor; librdkafka's rdkafka_performance; Xinfra Monitor; Strimzi Canary; Sarama's kafka-producer-performance; Pepper-Box; xk6-kafka; the Yahoo Streaming Benchmark |
| Redpanda | SBK `drivers/redpanda`; kgo-verifier |
| Apache Pulsar | OpenMessaging Benchmark `driver-pulsar/` and `driver-kop/` (Kafka's protocol on Pulsar); SBK `drivers/pulsar`; Pulsar's perf |
| RabbitMQ | OpenMessaging Benchmark `driver-rabbitmq/`; SBK `drivers/rabbitmq`; PerfTest (queues); Stream PerfTest (streams) |
| NATS | OpenMessaging Benchmark `driver-nats/`; SBK `drivers/nats`; the NATS CLI |
| NATS Streaming | OpenMessaging Benchmark `driver-nats-streaming/`; SBK `drivers/natsStream` |
| NSQ | OpenMessaging Benchmark `driver-nsq/`; SBK `drivers/nsq` |
| Apache RocketMQ | OpenMessaging Benchmark `driver-rocketmq/` and `driver-rocketmq5/`; SBK `drivers/rocketmq`; RocketMQ's benchmark |
| Apache ActiveMQ Artemis | OpenMessaging Benchmark `driver-artemis/` and `driver-jms/artemis-jms.yaml`; SBK `drivers/artemis`; `artemis perf`; Quiver |
| Apache ActiveMQ Classic | SBK `drivers/activemq` |
| Pravega | OpenMessaging Benchmark `driver-pravega/`; SBK `drivers/pravega`; Pravega's benchmark |
| Redis | OpenMessaging Benchmark `driver-redis/` (streams); SBK `drivers/redis` |
| MQTT brokers | OpenMessaging Benchmark `driver-mqtt5/`; emqtt-bench; mqtt-benchmark |
| Apache BookKeeper | OpenMessaging Benchmark `driver-bookkeeper/`; SBK `drivers/bookkeeper`; BookKeeper's benchmark |
| Google Cloud Pub/Sub | PerfKit Benchmarker's messaging benchmark (`gcp`); the Pub/Sub load test framework |
| Amazon SQS | PerfKit Benchmarker's messaging benchmark (`aws`) |
| Azure Service Bus | PerfKit Benchmarker's messaging benchmark (`azure`) |

The MQTT tools name no broker of their own, except emqtt-bench, which is EMQX's. So the MQTT row is
coded twice: once for the MQTT 5.0 standard, which fixes what any broker may put in a message to a
subscriber, and once for EMQX.

**Group B: the clouds' own message services.** The services of Amazon Web Services, Microsoft Azure
and Google Cloud that hold messages until a consumer asks for them or gives credit:
- Amazon SQS and Amazon Kinesis Data Streams;
- Azure Service Bus, Azure Event Hubs, Azure Queue Storage, and Azure Event Grid's namespace topics
  with pull delivery;
- Google Cloud Pub/Sub.

A hosted copy of a group A broker gives that broker's answers and is not coded twice (Amazon MSK
and Amazon MQ, Google Cloud's Managed Service for Apache Kafka).

**Left out, and why.**
- **In-process queues** (SBK's `atomicq`, `concurrentq`, `conqueue`, `linkedbq`, `syncq`): there is no
  broker; the queue is a library inside the tool.
- **Databases, key-value stores and file systems** that the tools time as storage.
- **Routers that hold no message** (Qpid Dispatch Router): a message is never stored, so there is
  no wait at a broker to report.
- **Push-only fan-out** (Amazon SNS): it holds no message for a consumer to ask for.
- **Retired services** (Google Cloud Pub/Sub Lite), if the provider has shut them down by the coding
  date.

**Modes.** Where a broker offers consumers more than one interface, and the answers can differ, each
interface is coded as its own row. Examples: Redis streams, Pub/Sub and lists; RabbitMQ queues and
streams; NATS core and JetStream; Kafka consumer groups and share groups; RocketMQ's pull and its
pop consumption; Pub/Sub pull, streaming pull and push; Kinesis GetRecords and SubscribeToShard.

## The version coded

- **Open-source brokers.** The latest stable release on the coding date: the release the project
  marks latest, or else its highest tag that is not a pre-release. Every source URL is pinned to
  that tag or to its commit.
- **Managed services.** The service's API reference and its official SDK source, as retrieved on the
  coding date. SDK URLs are pinned to a release tag. The API version string is recorded where the
  service has one.

## The questions

Asked of each broker and mode.

- **Q0. What the consumer receives.** The complete list of per-message fields that the broker's
  consumer protocol delivers, from the protocol's definition or the client's message class. The
  answers to Q1 to Q5 are read against this list.
- **Q1. Arrival stamp.** Does the broker record, for each message, the time it received or stored
  the message, on its own clock?
  - `always`;
  - `by configuration`: only when a broker or topic setting, or a choice the producer makes, asks
    for it (name the setting or the choice, and say whether it is off by default);
  - `no` (no stamp, or only a time the producer set).
  - Recorded with it: the field, its resolution, and where the broker sets it.
- **Q2. Arrival stamp delivered.** Is that stamp delivered to the consumer with the message?
  `yes` or `no`; `not applicable` when Q1 is `no`.
- **Q3. Delivery stamp.** Does the broker record, for each message or each delivery, one of these
  times?
  - `request arrival`: when the request or credit that took the message arrived;
  - `send time`: when the broker sent the message to the consumer;
  - `no`.
- **Q4. Delivery stamp delivered.** Is that stamp delivered with the message? `yes` or `no`;
  `not applicable` when Q3 is `no`.
- **Q5. A duration in the message.** Does the broker deliver, with each message, a duration it
  measured on its own clock that contains the message's wait for a request?
  - `wait`: the wait itself;
  - `stay`: the message's whole time at the broker;
  - `derivable wait` or `derivable stay`: computable, by a rule the documentation states, from
    delivered fields that the broker set on one clock;
  - `no`.
- **Q6. Out of band.** Per-message or per-request timing that the broker records where only someone
  with access to the broker can read it (its logs, a monitoring command, a tracing feature):
  - `per message`, `per request`, `aggregate only`, or `none`;
  - what it is, and its resolution.
- **Q7. Requests that wait.** Can a consumer keep a request or credit waiting at the broker, so that
  a message arriving finds one?
  - `standing`: a subscription receives every message as it arrives, with no credit to run out;
  - `credit or several`: the consumer grants credit, or keeps several requests pending at once;
  - `one at a time`: one pending request per connection, or per partition or queue;
  - `none`: a request returns at once, so the consumer polls.

Any question the sources do not settle is answered `not determined`, with what was searched.

## The evidence

- **Every answer carries evidence.** At least one item: a URL pinned to the version coded, and an
  exact quote from it. Only a `not applicable` answer may carry none. A quote is at most 300 characters and is copied from the fetched page or
  file, never written from memory. A line of code is quoted whole.
- **A "no" rests on the whole message.** A `no` on Q1 to Q5 rests on Q0's complete list of fields.
  Where the broker's source is open, it also cites the place where the broker builds the message it
  delivers.
- **Every quote is fetched back.** `scripts/broker_audit.py check` fetches every URL and confirms
  that each quote is in it, after collapsing white space. A quote it cannot find fails the record.
- **Nothing is filled in.** An answer the sources do not settle is `not determined`, never
  something plausible.
- **The rare answers are read back.** Every `yes` on Q3 to Q5, and every Q7 answer of `standing` or
  `credit or several`, is read back against its source before the audit is reported.

## The verdicts

`scripts/broker_audit.py` computes the verdicts from the answers. They are never stored.

**What the message carries:**
- **Wait in the message.** Q3 is `request arrival`, Q4 is `yes`, and Q1 and Q2 give the arrival
  stamp on the same clock. Or Q5 is `wait` or `derivable wait`. The consumer can compute `S`
  exactly, to the coarser of the two stamps' resolutions.
- **Stay in the message.** Q3 is `send time` and Q4 is `yes`, with Q1 and Q2. Or Q5 is `stay` or
  `derivable stay`. `S` then lies between the stay less the broker's own handling, and the stay.
- **Arrival only.** Q1 and Q2 only. The consumer learns when the message reached the broker, by the
  broker's clock. `S` needs a clock shared with the broker, and even then is only bounded.
- **Nothing.** None of the above.

**Two more verdicts, beside it:**
- **Requests can wait.** Q7 is `standing` or `credit or several`. The client's own certificate of
  plans 47 and 49 applies, and where it holds, the thread's part inside `W` is zero.
- **With access to the broker.** Q6 is `per message` or `per request`.

The resolution is reported beside each verdict. A millisecond stamp cannot split a wait of tens of
microseconds.

## What we expected, before any record was coded

- **Kafka.** An arrival stamp by configuration only (`LogAppendTime`, in ms, set per batch;
  `CreateTime`, the default, is the producer's), delivered. No delivery stamp. One fetch at a time
  per connection. Per-request timing, including a fetch's wait, in the broker's request log.
- **Redis streams.** The entry id's millisecond part is the arrival stamp when the server makes the
  id, and it is delivered. No delivery stamp. Blocking reads wait.
- **NATS JetStream.** The stored time, in ns, delivered in the reply subject. No delivery stamp.
  Pull requests wait, several at once.
- **RabbitMQ.** Queues: an arrival stamp by configuration only (a header, in ms), delivered.
  Streams: the chunk's timestamp, in ms, delivered. Credit waits in both.
- **Pulsar.** The publish time is the producer's. A broker publish time by configuration (ms),
  delivered. Credit (permits) waits.
- **RocketMQ.** The store timestamp (ms), always, delivered. A long-polling pull waits, one per
  queue.
- **ActiveMQ Classic.** Broker-in and broker-out times (ms), delivered: the one self-hosted broker
  we expect to give a stay in the message.
- **ActiveMQ Artemis.** An ingress timestamp by configuration (ms), delivered. Credit waits.
- **NSQ.** The message's timestamp, set by the broker in ns, delivered. Credit (`RDY`) waits.
- **Google Cloud Pub/Sub.** The publish time, set by the service, delivered. No delivery stamp.
- **Amazon SQS.** `SentTimestamp` and `ApproximateFirstReceiveTimestamp` (ms), delivered when the
  consumer asks for them: a stay, for a message's first receive only. Long polls wait.
- **Amazon Kinesis Data Streams.** `ApproximateArrivalTimestamp` (ms), delivered. No delivery stamp.
- **Azure Event Hubs and Service Bus.** The enqueued time (ms), delivered.
- **Overall.** No broker delivers the time the request or credit that took a message arrived. The
  only delivery stamps we expect are SQS's first-receive time and ActiveMQ Classic's broker-out
  time.

Where the audit finds otherwise, the expectation is reported as wrong, beside what was found.

## How the records are made

- **Coding.** Each broker is coded once, from primary sources, by an auditor working to this
  protocol. The records go to `data/broker_audit/batch_*.json`, in the form below.
- **Checking.** `scripts/broker_audit.py check` fetches every quote back. The read-backs above are
  recorded in each mode's `read_back`.
- **Deviations.** Any departure from this protocol is reported in the audit's README.

**The form of a record.**

```json
{"audited_utc": "2026-10-27",
 "brokers": [
  {"broker": "Apache Kafka", "group": "A", "version": "4.1.0",
   "version_evidence": [{"url": "...", "quote": "..."}],
   "modes": [
    {"mode": "consumer groups (fetch)",
     "Q0": {"fields": ["..."], "evidence": [{"url": "...", "quote": "..."}]},
     "Q1": {"answer": "by configuration", "field": "...", "resolution": "ms",
            "setting": "...", "default_on": false, "evidence": ["..."], "note": "..."},
     "Q2": {"answer": "yes", "evidence": ["..."]},
     "Q3": {"answer": "no", "evidence": ["..."]},
     "Q4": {"answer": "not applicable", "evidence": []},
     "Q5": {"answer": "no", "evidence": ["..."]},
     "Q6": {"answer": "per request", "what": "...", "resolution": "...", "evidence": ["..."]},
     "Q7": {"answer": "one at a time", "evidence": ["..."]},
     "not_determined": [],
     "read_back": []}]}]}
```

Each `"..."` in an `evidence` list stands for an item of the form `{"url": "...", "quote": "..."}`.
Every answer except `not applicable` carries at least one.
