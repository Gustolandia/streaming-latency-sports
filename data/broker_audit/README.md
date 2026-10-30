# The broker audit: what each broker tells a consumer, and a producer, about a message's time at the broker

Coded from 27 to 29 October 2026 under the protocol [`PROTOCOL.md`](PROTOCOL.md) and its first
amendment [`AMENDMENT_01.md`](AMENDMENT_01.md). Each rule was registered by a push before the work
it governs:
- the protocol, by `01fca148`, before any record was coded;
- the amendment, by `ac338d58`, before any search under it, with what we expected
  ([`AMENDMENT_01_EXPECTED.md`](AMENDMENT_01_EXPECTED.md));
- the rule for which of the products found are checked
  ([`AMENDMENT_01_SCOPE.md`](AMENDMENT_01_SCOPE.md)), by `48b1ee88`, before any of them was
  checked.

The audit reads documentation, specifications and source code only. No machine is used, and nothing
here reads a run of ours.

**The question.** A message's kernel-timed latency `W` holds a stretch where the message sat at the
broker because the consumer had not yet asked for it: its request, fetch or credit had not
arrived. Call that wait `S`. Only the broker sees both ends of `S`. So the split of `W` into the trip
and the consumer thread's part is exact only in two cases:
- the broker tells the consumer `S`, or the two times on its own clock that `S` is the difference of;
- the consumer keeps a request or credit waiting for every message, so that `S` is zero.

**The producer's side.** A producer can time the round trip of each publish, from its send to the
broker's acknowledgment. If the acknowledgment carries the time the broker received the publish and
the time it sent the acknowledgment, the producer can take the broker's hold out of the round trip
without sharing a clock with the broker. An NTP client does exactly this with a server's receive and
transmit times.

The audit asks, of every broker a documented search could find, which of these each allows. Its
answers go to two groups: the people who build brokers, and the people who build the tools that time
them.

**What the answers cover.** Three sets of brokers:
- the 23 brokers coded first: every broker a tool of the tools audit can time through, and the three
  largest clouds' own message services;
- the seed list, written before any search;
- the established products the search found: open-source projects with at least 1,000 GitHub stars
  and a push since 27 October 2023, commercial and cloud products with public documentation of what
  a consumer receives, and standards.

The search also found 188 smaller or inactive projects that were listed and not checked. One of them
might send a time that no checked broker sends. Every statement below is about the checked brokers.

## The answer in brief

Across 222 brokers, 418 consumer interfaces and 390 producer interfaces.

**What a consumer receives with each message.**
- **The wait itself: 2 interfaces, and neither is a production broker as it ships.**
  - Eclipse Zenoh 1.10, for queries answered by a storage. It sends the query's arrival only through
    a timestamp feature that its code marks unstable and that the querier must switch on. The wait is
    on one clock only when the router that holds the storage stamped the sample itself. The stamps
    are readings of the router's hybrid logical clock, in steps of about 4 ns.
  - Azurite, Microsoft's local emulator of Azure Queue Storage, to the whole second.
- **A stay: 79 interfaces in 53 brokers.** A stay is the message's whole time at the broker: the wait
  plus the broker's own handling. It bounds the wait from above.
  - 36 of the 79 come only from a duration counted in whole seconds. Most of these durations are an
    expiry that the broker shortens by the message's time there. MQTT 5.0 brokers do this, as the
    standard requires, for messages whose publisher set an expiry.
  - Only three brokers send a stay finer than a millisecond at both ends:
    - PGMQ, a queue that runs inside PostgreSQL, by default. It sends the enqueue time and the time a
      read took the message, in microseconds. A plain read answers at once, so the difference is the
      message's wait for the reader plus the read's own handling.
    - OPC UA subscriptions, under the industrial-automation standard. They carry the server's receive
      time and the notification's send time, in units of 100 ns. The receive time is sent only when
      the client asks for the server's timestamps.
    - Zenoh's subscribers, through the same unstable feature: the first router's stamp and each
      router's stamp as it sends the message on.
  - 60East AMPS's queue subscriptions send the arrival in microseconds, and a lease deadline whose
    resolution is not stated.
  - The stays of the most widely used brokers are all in milliseconds: ActiveMQ Classic, RocketMQ's
    pop consumption, Amazon SQS, Azure Service Bus in peek-lock mode, and RabbitMQ from 4.2 when a
    setting asks for it.
- **The arrival time only: 149 interfaces. No broker time: 188.** 86 brokers send a consumer no
  broker time in any of their interfaces.
- **The times the split needs exist inside many brokers, unsent.**
  - 20 interfaces in 19 brokers record when each request arrived and do not send it. 10 of these
    record it to the nanosecond: Kafka's fetch and share groups, KoP, BookKeeper, Pravega, NATS
    JetStream's pull consumers, AutoMQ, Tansu, KubeMQ's queues and Memphis.
  - 61 interfaces in 47 brokers keep each send time.
  - A broker could put these in the message without measuring anything new.
- **Requests that wait.** In 308 interfaces a consumer can keep a request or credit waiting for each
  message, so that `S` is zero. In 100 it cannot. 10 are not determined.

**What a producer receives when it publishes.**
- **A hold in the acknowledgment: 2 interfaces.**
  - Liftbridge, by default: the time the server received the message and the time it committed it
    and sent the acknowledgment, both in nanoseconds.
  - KubeMQ's queues (SendQueueMessage): the send time in nanoseconds; the receive time only through
    an expiry or a delay that the producer set.
- **One broker time: 42 interfaces.** 38 carry only a receive time, among them Kafka's log-append time
  (by configuration), Redis's stream ids and PubNub's timetoken. 4 carry only a send time.
- **No broker time: 248. No acknowledgment at all: 98.**

**What it means.** None of the 23 brokers that the industry's tools time sends the wait, or a stay
finer than a millisecond. The brokers that send finer times are a queue inside PostgreSQL, an
industrial-automation standard, and a feature of Zenoh that must be switched on. Yet many brokers
already record the times the split needs.

## Words used here

- **Arrival stamp:** the time the broker received or stored the message, by its own clock.
- **Delivery stamp:** either the time the request or credit that took the message arrived
  (*request arrival*), or the time the broker sent the message (*send time*).
- **Wait (`S`):** how long the message waited at the broker for a request or credit. It is zero
  when one was already waiting.
- **Stay:** the message's whole time at the broker, from arrival to send. It is the wait plus the
  broker's own handling.
- **Credit:** permission the consumer gives the broker to send it more messages without asking
  again (prefetch, link credit, permits, `RDY`).
- **Kept at the broker only:** a time the broker records but does not send with the message. It
  may be kept as a deadline computed from it, such as an acknowledgment deadline.
- **Broker access:** per-message or per-request timing that only someone with access to the
  broker can read: its logs at a named level, a monitoring command, or a tracing feature.
- **Acknowledgment:** the broker's reply to a publish, saying that it has the message.
- **Hold:** the time from the broker receiving a publish to its sending the acknowledgment.
- **Interface, or mode:** one way to consume or to publish whose answers differ from the others',
  such as pull against push, or MQTT's QoS 0 against QoS 1 and 2.
- **Groups.** A: the brokers a tool of the tools audit can time through. B: the three largest
  clouds' own message services. C: the brokers the amendment's seed list named or its search found.
- **Copy:** a hosted service or packaged distribution of a broker (Amazon MSK is a copy of Kafka).
- **Precedent:** a protocol outside the brokers that tells a client the far end's receive and send
  times, or its hold.
- **Not determined:** an answer the sources do not settle. A verdict marked "(unless …)" could
  change if that answer were settled.
- **Round 1, round 2:** words the notes in the records and in `candidates.json` use. Round 1 is the
  coding of the seed list on 27 October. Round 2 is the checking of the products the search found,
  begun on 27 October and finished on 29 October.

## The files

- `PROTOCOL.md` and the three `AMENDMENT_01` files: the registered rules, with their fingerprints.
- `batch_01.json` to `batch_04.json`: the first audit's 23 brokers, with their producers added
  under the amendment.
- `batch_05.json` to `batch_25.json`: the 199 brokers coded under the amendment.
- `precedents.json`: 42 precedents, each with the fields it sends and its evidence.
- `candidates.json`: the population. It has one entry for each of the 1,302 products found, with
  its decision and the reason for it. A coded product's entry names the file of its record. Every
  other entry has the class that it is counted under below.
- `search_log.json`: the 766 searches, each with its date, route, source and query and the products
  it surfaced. Then come route 2's 47 hits of the times themselves, and 14 feature requests.
- [`TABLES.md`](TABLES.md): one row per consumer interface and per producer interface, with the
  verdict, the times in the message or the acknowledgment, the times kept at the broker only,
  whether requests wait, and broker access.

## How the brokers were found, and what each stage kept

**The searches: 766, all in `search_log.json`.**
- Route 1 lists brokers. It ran 421 searches of reference lists, code hosts and communities, and 189
  of the clouds' catalogs and of the copies' documentation.
- Route 2 looks for the times themselves. It ran 156 queries.

**The stages.** The searches returned 1,483 rows. Rows that name the same product were merged, and
the seed products that no search surfaced were added. That left 1,302 products, which go through the
stages below. Each product's entry in `candidates.json` gives its decision and reason.
- **Out on the amendment's grounds, from the product's own description: 689.**

  | Reason | Products |
  |---|---|
  | client library or framework | 235 |
  | keeps no messages for consumers (a tool, an application, a database, a vocabulary) | 210 |
  | stream processor or workflow engine | 115 |
  | proxy or router that holds no message | 40 |
  | brokerless messaging library | 30 |
  | notification service to devices or people | 28 |
  | documentation not public, or no longer online | 27 |
  | shut down by the coding date | 4 |
- **Copies: 68 listed, not coded.** The documentation of each was searched for a field it delivers
  that the broker it copies does not. Two copies had one and are coded as records of their own: the
  HTTP interfaces of Alibaba Cloud's ApsaraMQ for RocketMQ and of Tencent Cloud's TDMQ for
  RocketMQ. Two others name a header that a replication tool adds, not a time the broker sets on
  delivery: Confluent Replicator's provenance header and MSK Replicator's.
- **New products in scope: 411.** Under the scope rule, 223 of them were to be checked or screened.
  The other 188 were listed and not checked:

  | Why not checked | Products |
  |---|---|
  | under 1,000 stars (107 on GitHub, 8 on Gitee) | 115 |
  | archived or retired | 36 |
  | on another code host whose star count could not be read | 36 |
  | no push since 27 October 2023 | 1 |
- **Of the 223 checked or screened:** 87 were coded. 3 turned out to be other names of products
  already coded. 133 were screened out:

  | Why screened out | Products |
  |---|---|
  | not a broker, on a closer reading | 30 |
  | documentation not public, or no longer online | 28 |
  | a copy of another broker | 23 |
  | documentation not readable by the check | 22 |
  | below the scope rule once its page was read | 19 |
  | shut down by the coding date | 11 |
- **The seed list.** 111 seed products were coded. Of the others, the seed list's own copies are
  among the copies above. Eight are out: among them Chronicle Queue and Apache Ignite's messaging,
  which are brokerless, and Eclipse Hono, which holds no message. Three more are copies: SAP's
  advanced event mesh, Supabase Queues and StreamNative Ursa. One could not be read: webMethods
  Universal Messaging, whose documentation site refuses scripts.
- **Coded: 222 brokers.** These are the 23 coded first, 111 named by the seed list, and 88 found by
  the search alone.

## What we expected, and what we found

### Amendment 1

[`AMENDMENT_01_EXPECTED.md`](AMENDMENT_01_EXPECTED.md) was written before any search, and the
auditors did not read it while coding.

**Held:**
- **Many brokers keep a request's arrival or a send time and do not send it.** 20 interfaces in 19
  brokers keep the request's arrival, and 61 interfaces in 47 brokers keep a send time.
- **The stays we expected.**
  - Apache EventMesh: in each event's extensions, in ms.
  - IBM MQ: the put time in hundredths of a second, and an expiry that it shortens, in tenths.
  - Alibaba Cloud's Simple Message Queue and Yandex Message Queue: in ms, like SQS.
  - Oracle Cloud Infrastructure Queue: in ms, from the visibility deadline.
  - PGMQ: in µs. It sends the time of the read directly, not only the visibility deadline.
  - The AMQP 1.0 standard's ttl, in ms. Few brokers shorten it, as expected. Artemis (for messages
    stored in core form), ActiveMQ Classic, IBM MQ's AMQP channel and both Qpid brokers do.
    RabbitMQ, SwiftMQ and Alibaba Cloud's IoT Platform do not.
  - OPC UA subscriptions: in units of 100 ns.
  - Svix, Convoy and Hook0: the time of each delivery attempt, to the second, beside the event's
    own time.
- **The arrival times we expected.** Apache Iggy (µs), PubNub (100 ns), Ably (ms), Nakadi (ms), Azure
  IoT Hub (ms), Oracle's Advanced Queuing and SQL Server Service Broker (the enqueue time), Amazon
  SNS, XMPP's delay stamp, Faktory, and the kdb+ tickerplant (ns).
- **No broker time beyond the standard's expiry.** Mosquitto and the other MQTT 5.0 brokers send
  none, though Mosquitto's example plugin can add an arrival time. Beanstalkd, Gearman, Pusher and
  Centrifugo send none either. Redis's relatives follow Redis.
- **BlazingMQ** sends no wall-clock time.
- **Requests that wait.** MQTT's subscriptions, AMPS's subscriptions and most real-time services
  wait as standing subscriptions or by credit. The cloud queues that long-poll accept several
  requests at once.
- **The producer's side.**
  - Times in the acknowledgment: Kafka's log-append time (by configuration), the id that Redis's
    XADD returns, PubNub's timetoken, and Queue Storage's insertion time, to the second.
  - No time in the acknowledgment: NATS JetStream, RabbitMQ, Pulsar, SQS, Pub/Sub, Kinesis, Service
    Bus, Event Hubs and MQTT.
- **How many coded:** 199 brokers under the amendment, within the 100 to 200 expected.
- **The precedents.** Every precedent we expected was found and recorded, among 42 in all: NTP; ICMP
  Timestamp; TWAMP and STAMP; RTCP's receiver reports; SIP's Timestamp header; QUIC's ACK Delay;
  Server-Timing; web routers' request-start header; Eurex's T7; CME's market data; and DDS and ROS 2.

**Wrong:**
- **"No broker the search finds delivers the time the request or credit that took a message
  arrived."** Two interfaces deliver it. Zenoh's storage queries do so through its unstable timestamp
  feature, and Azurite, an emulator, to the second.
- **"No broker puts both its receive time and its send time in a publish acknowledgment."** Liftbridge
  does, in nanoseconds, by default. KubeMQ's queues do when the producer sets an expiry or a delay.
- **"A few more brokers deliver a stay. All of them in milliseconds or coarser, except PGMQ."**
  - 79 interfaces in 53 brokers deliver a stay, most through MQTT 5.0's expiry.
  - Besides PGMQ, OPC UA and Zenoh's unstable stamps are finer than a millisecond.
- **"Between 150 and 300 products found."** The search found 1,302.
- **Tencent Cloud's CMQ** keeps its times in whole seconds, not milliseconds.
- **60East AMPS** also gives a stay, in its queue subscriptions, through the lease's deadline.
- **Zenoh** gives more than the first router's stamp. Its unstable feature gives subscribers a stay,
  and queries of a storage the wait.
- **MSMQ** also gives a stay, to the second. Besides the arrived time, it sends the time left on a
  message's time-to-be-received timer.
- **Salesforce's Platform Events:** the sources do not say whose clock sets the created date. The
  publishing examples set it from the publisher's clock.
- **Mercure** delivers an arrival time: the UUIDv7 in each update's id, when the hub makes the id.
- **Standard Webhooks:** the specification fixes only the time of each delivery attempt. The services
  add the event's own time (Svix, Convoy, Hook0), and Hookdeck sends no broker time.
- **IBM MQ's get with a wait** keeps one request at a time. It is its read-ahead that gives credit.

**What we did not expect at all.**
- **Asking for times.** Of the 14 feature requests found:
  - Four requests for an arrival stamp were met: in the Qpid C++ broker (0.14), ActiveMQ Apollo,
    Artemis (its ingress timestamp, 2.18) and Pulsar (its broker entry metadata).
  - Requests for a time in the queue, a delivery time or a time in the publish acknowledgment were
    closed with a pointer to logs, plugins or tracing, or are still open. NATS's request for a time
    in JetStream's publish acknowledgment has been open since 2023.
- **IBM WebSphere's service integration bus** computes each message's time in its engines,
  `MessageWaitTime` (a stay, in ms). It writes this into the delivered message for a connection that
  asks for it, and its own JMS client never asks.
- **gmqtt** sends a message's expiry interval as the time already spent, against the MQTT standard.
  That is still a stay in the message.

### The first audit

The protocol recorded what we expected before any record was coded. This section reports the 23
brokers as the first audit found them on 27 October, before the corrections listed further down.

**Held:**
- **Kafka.** An arrival stamp by configuration only (`LogAppendTime`, in ms, per batch), delivered.
  No delivery stamp in the message. One fetch at a time per connection. Per-request timing,
  including a fetch's wait, in the broker's request log.
- **Redis streams.** The entry id's millisecond part, when the server makes the id, delivered. No
  delivery stamp in the message. Requests that wait.
- **NATS JetStream.** The stored time, in ns, delivered in the reply subject. No delivery stamp in
  the message. Several pull requests waiting at once.
- **RabbitMQ.** In queues, an arrival stamp by configuration only (ms); in streams, the chunk's
  timestamp (ms). Credit waits in both.
- **Pulsar.** The publish time is the producer's. A broker publish time by configuration (ms) is
  delivered: a second setting must also allow it to reach the consumer. Credit waits.
- **RocketMQ's pull.** The store timestamp (ms), always, delivered. A long-polling pull waits, one
  per queue.
- **ActiveMQ Classic.** Broker-in and broker-out times (ms), delivered: a stay in the message.
- **ActiveMQ Artemis.** An ingress timestamp by configuration (ms), delivered. Credit waits.
- **NSQ.** The message's timestamp, set by the broker in ns, delivered. Credit (`RDY`) waits.
- **Google Cloud Pub/Sub.** The publish time, set by the service, delivered. No delivery stamp in
  the message.
- **Amazon SQS.** `SentTimestamp` and `ApproximateFirstReceiveTimestamp` (ms), delivered when the
  consumer asks for them: a stay, for a message's first receive only. Long polls wait.
- **Amazon Kinesis Data Streams.** `ApproximateArrivalTimestamp` (ms), delivered. No delivery stamp
  in the message.
- **Azure Event Hubs and Service Bus.** The enqueued time (ms), delivered.
- **No broker delivers the time the request or credit that took a message arrived.** This held in
  all 41 interfaces.

**Wrong:**
- **"The only delivery stamps we expect are SQS's first-receive time and ActiveMQ Classic's
  broker-out time."** Five more interfaces deliver one:
  - RabbitMQ's queues, from version 4.2, stamp `x-opt-rabbitmq-sent-time` as each message goes
    to the consumer, when a setting asks for it. This is in both AMQP 0-9-1 and AMQP 1.0.
  - RocketMQ's pop consumption delivers `popTime`, the time the broker served the pop request.
  - Azure Service Bus, in peek-lock mode, delivers the lock's end, from which the documented lock
    length gives the time the message was taken.
  - Azure Queue Storage gives the time of each dequeue, to the second.

  Beyond stamps, the MQTT 5.0 standard makes every broker shorten a message's expiry by the time
  it waited, to the second. So a subscriber that knows the publisher's expiry learns the stay,
  for messages whose publisher set one.
- **"ActiveMQ Classic is the one self-hosted broker we expect to give a stay in the message."**
  RabbitMQ (by configuration), RocketMQ's pop consumption and the MQTT brokers give one too.
- **What we did not expect at all.** Many brokers record the times the split needs and keep them:
  - the arrival of each request: Kafka, Redpanda, KoP, BookKeeper, Pravega, NATS JetStream's pull
    consumers and RocketMQ's pull;
  - each send time: NATS, NATS Streaming, NSQ, Redis streams, Pulsar, EMQX, Pub/Sub and Event
    Grid, and, by a judgment call, Kinesis.

## Corrections to the first audit

The amendment keeps the first audit's answers unless an auditor finds one wrong. A wrong answer is
corrected in the open, never silently. Each correction is marked in its record, under
`corrected_in_amendment_1` or `added_in_amendment_1`.
- **Apache ActiveMQ Artemis, AMQP 1.0 consumers: arrival only becomes a stay.** Artemis stores most
  messages in its own core form. When it delivers one of these over AMQP 1.0, and the message has an
  expiration, it writes the header's ttl as the time left before that expiration, which it set from
  its own clock. It also writes the properties' absolute expiry time. So the expiry time less the ttl is the broker's clock at the send (Q3 and
  Q4), and the ttl is a derivable stay (Q5), in ms.
- **Apache ActiveMQ Classic: an AMQP 1.0 consumers mode is added.** It delivers a stay.

So the first audit's 23 brokers now have 42 consumer interfaces: 13 deliver a stay, 22 the arrival
only and 7 nothing. Their producers were coded under the amendment.

## Readings applied to every record

Where the protocol left a reading open, one reading was chosen and applied to every record.

**From the first audit:**
- **What a broker records.**
  - A broker records a time when it keeps that time, or a deadline computed from it by a fixed
    length that the code or documentation states. Examples are an acknowledgment deadline (the
    send time plus the wait allowed), or a lock's end.
  - For a closed service, this needs a sentence of its documentation saying the length counts from
    that moment.
  - A stamp the broker keeps but does not send is answered under Q1 or Q3, with Q2 or Q4 `no`.
- **"By configuration."** This also covers a stamp the broker always records but sends only when
  a setting asks for it: RabbitMQ's received time, and EMQX's timestamp, which reaches a subscriber
  only through a message transformation. The note on each says so.
- **"Several" requests (Q7).** These are pending requests that can each take a *different*
  arriving message.
  - So KoP, which queues several fetches but refuses one past the log's end, waits one at a time.
    So does RocketMQ's pull.
  - Pravega accepts reads past a segment's end, at successive offsets. That makes "several"
    possible when event sizes are known; its own client keeps one read per segment.
  - Redis's answer rests on pipelining: a command pipelined behind a blocked one runs as soon as
    the blocked one is served. This works for `XREADGROUP ... >` and `BLPOP`, not for `XREAD $`.
- **Broker access (Q6).** It counts log lines at a named level (DEBUG, TRACE) that are written
  per message or per request, timed by the log line itself.
- **Modes.** Each interface is coded as its own row where its answers differ: Service Bus's
  peek-lock and receive-and-delete modes, and MQTT's QoS 0 against QoS 1 and 2.
- **Google Cloud Pub/Sub Lite is coded.** The protocol left it out only if it had been shut down
  by the coding date. It had not: its documentation says it keeps working until 31 January 2027.
- **Versions.**
  - **Redpanda** is coded at v26.2.2, the newest release with public source. Its release notes
    call it the last one published on GitHub; v26.2.3 to v26.2.5 have no public tag.
  - **ActiveMQ Artemis** has no GitHub releases, so it is coded at its highest stable tag.
  - **KoP** is archived. Its last release (January 2024) builds against Pulsar 3.1.1.
  - **EMQX 6.3.2** is under the Business Source License 1.1.
- **Judgment calls, flagged in their notes.**
  - Kinesis's GetRecords: the shard iterator's expiry is counted as a recorded send time.
  - Pulsar's `lastConsumedTimestamp` is kept only as the latest value.
  - Event Hubs' `runtime_info_retrieval_time_utc` is delivered with every event when the receiver
    asks. No source says it is a send time, so Q3 is `not determined`.
- **Changes after coding began, to presentation only.** No rule or answer changed.
  - A verdict is marked "(unless …)" only where a `not determined` answer could change it.
  - The table's stamps are split into what reaches the consumer and what the broker keeps.

**Settled while the amendment's records were coded and read back.** Each was then applied to every
record.
1. The HTTP `Date` header of a response is never a broker time.
2. A deadline (a lock, lease, visibility timeout or expiry) counts as a recorded time only if the
   source states both the moment it counts from and its length.
3. A time stamped by logic the user writes and the broker runs (a plugin, a rule or a handler) is
   "by configuration".
4. A time decoded from an id counts only if the source shows that the broker makes the id from its
   own clock.
5. An optional field is "always" only if the source says it is set on every message.
6. For a standard, only a MUST or a SHOULD counts.
7. A time kept only in a log or a trace counts under Q6 only.
8. A request's timeout deadline, set from its arrival, counts as a kept request arrival (Q3
   `request arrival`, Q4 `no`).
9. A duration (Q5) counts only if it covers the message's whole wait for the consumer. An expiry
   that the broker shortens before the message waits for credit does not.
10. A broker time that a choice of the producer's can replace is "by configuration", on by default.

**One observation, used in the brief above.** When a poll returns at once, the request's arrival
and the send time differ only by the broker's handling of the poll. There, a stay is the wait plus
that handling.

## How the records were made and checked

- **Coding.**
  - **The first audit.** Four auditors each coded a group of the 23 brokers from primary sources,
    following the protocol, without reading its section of expectations.
  - **The seed list and the producers of the 23.** Under the amendment, on 27 October. Auditors each
    coded a group of the seed list, and one coded the producers of the 23 brokers.
  - **The products the search found.** On 29 October: 178 products, 8 in a trial and 170 in eight
    queues. Each source page was fetched once and kept, and each product's record was checked and
    saved as soon as it was written. A first pass on the evening of 27 October was stopped before it
    finished any record. Its screening decisions were kept, and they are in `candidates.json`.
- **The fetch-back.** Every answer carries quotes from sources pinned to the version coded: 14,069
  quotes on 2,152 pages, including the precedents' 194. On 30 October 2026 every source was fetched
  back afresh and every quote was found.
- **The read-backs.** Each rare answer was read back against its source in context. Under the
  amendment, an auditor other than the one who coded the answer did this. The rare answers are:
  - each delivery stamp, each stamp kept only at the broker, and each duration;
  - each "standing" or "credit or several";
  - each time in an acknowledgment;
  - each judgment call.

  There are 881 read-backs, each recorded in its interface's `read_back`. 866 agree. 50 answers were
  changed on reading back, each with its old answer and the reason, under `changed_on_read_back`.
  46 were changed by the auditors who read them back. Four were changed when the records were
  brought into this folder; each of these is marked with an `at` key:
  - Thingspeak's TalkBack queue: its duration becomes a stay, not the wait, because its delivery
    stamp's moment was found not determined.
  - ntfy's publish acknowledgment, Hook0's delivered arrival time and Zenoh's stored timestamp
    become "by configuration" under reading 10.
- **Doubts kept.** 15 read-backs record a doubt that the sources could not settle. The answer
  stands, and the doubt is noted beside it:
  - IBM MQ's read-ahead (Q5); WebSphere's service integration bus (Q7);
  - Solace PubSub+ Guaranteed messaging (Q5); MuleSoft Anypoint MQ (Q1);
  - Tencent Cloud's TDMQ for RocketMQ over HTTP (Q3, Q4); Thingspeak's TalkBack add command (P1);
  - Oracle Java CAPS JMS IQ Manager (Q2); SmoothMQ (Q3);
  - the FAA's NAS Enterprise Messaging Service (Q7); SuaveHooks (Q3, Q4); Vartiq (Q3);
  - Lightstreamer (Q7); Liveblocks (P1).
- **Not determined.** 333 answers across all the interfaces. The tables mark every verdict that one
  of them could change.

## Deviations from the amendment

- **Route 2's stopping rule** (ten new queries in a row with no new broker) fired at query 24 of
  156. The search went on, and everything it found was kept.
- **The scope rule** ([`AMENDMENT_01_SCOPE.md`](AMENDMENT_01_SCOPE.md)) replaced "every broker
  found is coded". It was registered before any product the search found was checked. 188 products
  found were listed and not checked.
- **Reddit** was read through the Arctic Shift archive. Reddit's own search needs a login, and the
  PullPush archive refuses automated use.
- **Searches that were not run.** Some site-restricted web searches of the communities were not run,
  because the search allowance ran out. The sites' own searches and archives were used instead.
- **Sources the check could not read.** These are pages built by JavaScript, and sites that answer
  scripts with HTTP 403, among them IBM Documentation and the rating sites G2 and Gartner. Products
  whose documentation could not be read are not coded. They are marked so in `candidates.json`
  (24 entries).
- **Reading 10 was settled late.** It was settled during the read-backs and applied to every record
  whose source or note shows that a producer's choice can replace the time. The read-backs do not
  cover arrival stamps, so an arrival stamp that a producer can replace could still be coded
  `always`.

## How to check it

```bash
python scripts/broker_audit.py validate
python scripts/broker_audit.py table
python scripts/broker_audit.py producers
python scripts/broker_audit.py check
```

`check` needs the network, and it fetches 2,152 pages one after another. It is not part of the
test suite, since its answer depends on what other projects change. The suite checks the records'
form, and it recomputes the main counts reported here from the committed files.
