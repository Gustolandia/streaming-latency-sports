# The broker audit: what each broker tells a consumer about a message's time at the broker

Coded on 27 October 2026, under the protocol [`PROTOCOL.md`](PROTOCOL.md). The protocol was
registered by the push of `01fca148` before any record was coded. It reads documentation and source
code only; no machine is used, and nothing here reads a run of ours.

**The question.** A message's kernel-timed latency `W` holds a stretch where the message sat at the
broker because the consumer had not yet asked for it: its request, fetch or credit had not
arrived. Call that wait `S`. Only the broker sees both ends of `S`. So the split of `W` into the trip
and the consumer thread's part is exact only in two cases:
- the broker tells the consumer `S`, or the two times on its own clock that `S` is the difference of;
- the consumer keeps a request or credit waiting for every message, so that `S` is zero.

This audit asks, of every broker the industry's tools time and of the three largest clouds' own
message services, which of the two each allows. Its answers go to two groups: the people who
build brokers, and the people who build the tools that time them.

## The answer in brief

Across 23 brokers and 41 consumer interfaces:
- **None tells the consumer when the request or credit that took a message arrived.** So no
  broker delivers the wait `S` itself.
- **Eleven deliver a stay:** the message's whole time at the broker, from two stamps on the
  broker's clock. A stay bounds `S` from above, and it is close to `S` when the broker's own
  handling is short.
  - On by default: ActiveMQ Classic (ms), RocketMQ's pop consumption (ms), Azure Service Bus in
    peek-lock mode (ms, from the lock's end less the lock's length), and Azure Queue Storage
    (whole seconds).
  - When the consumer asks for it: Amazon SQS (ms, first receive only).
  - Off by default: RabbitMQ's queues, from version 4.2, with two settings (ms).
  - Only for messages whose publisher set an expiry, and only to the second: the MQTT 5.0
    standard, and EMQX.
- **The times the split needs already exist inside many brokers, unsent.**
  - Eight interfaces record each request's arrival, six of them in nanoseconds: Kafka's fetch
    and share groups, KoP, BookKeeper, Pravega and NATS JetStream's pull consumers. The other
    two are Redpanda and RocketMQ's pull.
  - Twelve record each send time and keep it, among them NATS, NSQ and Redis streams.
  - A broker could put these in the message without measuring anything new.
- **Twenty-three deliver only the arrival time.**
  - Its resolution is nanoseconds for NATS JetStream, NATS Streaming and NSQ. For Google Cloud
    Pub/Sub the documentation does not state it. Elsewhere it is milliseconds.
  - In eight of these interfaces it is sent only when a setting, or a choice the producer makes,
    asks for it.
- **Seven deliver no broker time at all.**
- **Requests that wait.**
  - In 32 of the 41 interfaces, a consumer can keep a request or credit waiting for each message.
    There the clients' own certificate of plans 47 and 49 applies.
  - In eight it cannot: Kafka's fetch and share groups, Redpanda, KoP, BookKeeper's
    DistributedLog reader, RocketMQ's pull, Kinesis's GetRecords and Azure Queue Storage.
  - One is not determined: Event Hubs' Kafka endpoint.
- **No delivered stay is finer than a millisecond.** A split of tens of microseconds needs finer
  stamps than any broker sends.

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

## The table

Computed by `python scripts/broker_audit.py table` from the records in this folder
(`batch_01.json` to `batch_04.json`). The verdicts are computed from the answers by the rules the
protocol registered, and are not stored in the records.

| Broker | Mode | Version | What the message carries | In the message | Kept at the broker only | Requests wait | Broker access |
|---|---|---|---|---|---|---|---|
| Apache Kafka | consumer groups (fetch) | 4.4.0 | arrival only | batch.maxTimestamp, timestampType = LogAppendTime (ms, arrival, by configuration) | Request.startTimeNanos (kept while the fetch waits in purgatory) (ns (System.nanoTime), request arrival) | no | yes |
| Apache Kafka | share groups (KIP-932, GA since 4.2) | 4.4.0 | arrival only | batch.maxTimestamp, timestampType = LogAppendTime (ms, arrival, by configuration) | Request.startTimeNanos (kept while the ShareFetch waits); also the acquisition-lock deadline of each acquired range (ns (System.nanoTime), request arrival) | no | yes |
| Redpanda | Kafka API (fetch) | 26.2.2 | arrival only | batch.maxTimestamp, timestampType = LogAppendTime (ms, arrival, by configuration) | in-flight request recv_time; per-request latency begin time (recv_time: Seastar lowres_clock (~task_quota); latency begin: std::chrono::high_resolution_clock, request arrival) | no | yes |
| Apache Pulsar | consumer (flow permits) | 5.0.1 | arrival only | BrokerEntryMetadata.broker_timestamp (ms, arrival, by configuration) | Consumer.lastConsumedTimestamp (latest dispatch to the consumer) (ms, send time) | yes | yes |
| Apache Pulsar | reader | 5.0.1 | arrival only | BrokerEntryMetadata.broker_timestamp (ms, arrival, by configuration) | Consumer.lastConsumedTimestamp (latest dispatch to the consumer) (ms, send time) | yes | yes |
| Apache Pulsar | Kafka protocol on Pulsar (KoP) | 5.0.1 | nothing | none | entry MessageMetadata.publish_time (Kafka-format entries) or BrokerEntryMetadata.broker_timestamp (ms, arrival, by configuration); startProcessRequestTimestamp (per request, kept until its response) (ns (MathUtils.nowInNano), request arrival) | no | yes |
| Apache BookKeeper | DistributedLog reader (as OMB driver-bookkeeper uses it) | 4.18.1 | nothing | none | PacketProcessorBaseV3.enqueueNanos (per request, kept while a long poll waits) (ns (System.nanoTime), request arrival) | no | yes |
| Pravega | reader groups | 0.13.0 | nothing | none | readSegment Timer start (per ReadSegment request) (ns (System.nanoTime), request arrival) | yes | yes |
| RabbitMQ | queues, AMQP 0-9-1 (basic.consume with prefetch) | 4.4.0 | stay in the message | timestamp_in_ms header (ms, arrival, by configuration); x-opt-rabbitmq-sent-time header (by configuration) (ms, send time) | none | yes | yes |
| RabbitMQ | queues, AMQP 1.0 | 4.4.0 | stay in the message | x-opt-rabbitmq-received-time message annotation (ms, arrival, by configuration); x-opt-rabbitmq-sent-time message annotation (by configuration) (ms, send time) | none | yes | yes |
| RabbitMQ | streams (stream protocol) | 4.4.0 | arrival only | chunk header Timestamp (ms, one value per chunk, arrival) | none | yes | no |
| NATS | core subscriptions | 2.15.2 | nothing | none | none | yes | yes |
| NATS | JetStream pull consumers | 2.15.2 | arrival only | stored timestamp (<timestamp> token of the ack subject) (ns, arrival) | pull request arrival (waitingRequest.received), not delivered (ns, request arrival) | yes | yes |
| NATS | JetStream push consumers | 2.15.2 | arrival only | stored timestamp (<timestamp> token of the ack subject) (ns, arrival) | delivery time (Pending.Timestamp), not delivered (ns, send time) | yes | yes |
| NATS Streaming | subscriptions | 0.25.6 | arrival only | MsgProto.timestamp (ns, arrival) | ack deadline (send time + AckWait), not delivered (ns, send time) | yes | yes |
| NSQ | channels (RDY credit) | 1.3.0 | arrival only | message timestamp (ns, arrival) | in-flight start (deliveryTS), not delivered (ns, send time) | yes | yes |
| Redis | streams (XREAD / XREADGROUP) | 8.10.3 | arrival only | entry ID time part (ms, arrival, by configuration) | PEL delivery_time (XREADGROUP), not delivered (ms, send time) | yes | yes |
| Redis | Pub/Sub | 8.10.3 | nothing | none | none | yes | yes |
| Redis | lists (BLPOP and kin) | 8.10.3 | nothing | none | none | yes | yes |
| Apache RocketMQ | pull and push consumers (long polling) | 5.5.1 | arrival only | storeTimestamp (ms, arrival) | suspendTimestamp of a pull request held by long polling (ms, request arrival) | no | yes |
| Apache RocketMQ | pop consumption | 5.5.1 | stay in the message | storeTimestamp (store_timestamp in gRPC) (ms, arrival); popTime (ms, send time) | none | yes | yes |
| Apache ActiveMQ Artemis | core protocol consumers (JMS) | 2.57.0 | arrival only | _AMQ_INGRESS_TIMESTAMP (ms, arrival, by configuration) | none | yes | yes |
| Apache ActiveMQ Artemis | AMQP 1.0 consumers | 2.57.0 | arrival only | x-opt-ingress-time (message annotation) (ms, arrival, by configuration) | none | yes | yes |
| Apache ActiveMQ Classic | OpenWire consumers (prefetch) | 6.4.0 | stay in the message | brokerInTime (JMSActiveMQBrokerInTime) (ms, arrival); brokerOutTime (JMSActiveMQBrokerOutTime) (ms, send time) | none | yes | yes |
| MQTT 5.0 (OASIS standard) | subscriptions, QoS 0 | 5.0 | stay in the message | a duration (s, derivable stay) | expiry deadline: arrival plus the Message Expiry Interval (no named stamp) (s, arrival, by configuration) | yes | no |
| MQTT 5.0 (OASIS standard) | subscriptions, QoS 1 and 2 | 5.0 | stay in the message | a duration (s, derivable stay) | expiry deadline: arrival plus the Message Expiry Interval (no named stamp) (s, arrival, by configuration) | yes | no |
| EMQX | MQTT subscriptions, QoS 0 | 6.3.2 | stay in the message | message timestamp, publish_received_at (reaches the subscriber only through a message transformation) (ms, arrival, by configuration); a duration (s, derivable stay) | none | yes | yes |
| EMQX | MQTT subscriptions, QoS 1 and 2 | 6.3.2 | stay in the message | message timestamp, publish_received_at (reaches the subscriber only through a message transformation) (ms, arrival, by configuration); a duration (s, derivable stay) | deliver_begin_at header; inflight insertion time (ms; ns, send time) | yes | yes |
| Google Cloud Pub/Sub | pull | v1 (google.pubsub.v1 API) | arrival only | publish_time (JSON publishTime) (Timestamp ns field; filled precision undocumented (examples: ms), arrival) | delivery time, kept as the ack deadline (delivery + ackDeadlineSeconds) (not documented (the deadline is set in whole seconds), send time) | yes | no |
| Google Cloud Pub/Sub | streaming pull | v1 (google.pubsub.v1 API) | arrival only | publish_time (JSON publishTime) (Timestamp ns field; filled precision undocumented (examples: ms), arrival) | delivery time, kept as the ack deadline (delivery + stream_ack_deadline_seconds) (not documented (the deadline is set in whole seconds), send time) | yes | no |
| Google Cloud Pub/Sub | push | v1 (google.pubsub.v1 API) | arrival only | publishTime (JSON body) or x-goog-pubsub-publish-time (unwrapped, with write_metadata) (Timestamp ns field; filled precision undocumented (examples: ms), arrival) | push request time, kept as the ack deadline (the push call's request timeout, ackDeadlineSeconds) (not documented (the deadline is set in whole seconds), send time) | yes | no |
| Google Cloud Pub/Sub Lite | Subscribe (streaming, flow-control tokens) | v1 (google.cloud.pubsublite.v1 API) | arrival only | publish_time (SequencedMessage) (Timestamp ns field; filled precision undocumented, arrival) | none | yes | no |
| Amazon SQS | ReceiveMessage (short and long polling) | API version 2012-11-05 | stay in the message | SentTimestamp (system attribute) (ms (epoch milliseconds), arrival); ApproximateFirstReceiveTimestamp (system attribute) (ms (epoch milliseconds), send time) | none | yes | yes |
| Azure Service Bus | receive, peek-lock | AMQP 1.0 (service protocol); SDK Azure.Messaging.ServiceBus 7.21.0 | stay in the message | EnqueuedTime / EnqueuedTimeUtc (AMQP message annotation x-opt-enqueued-time) (ms (AMQP timestamp), arrival); lock time (the message taken from the entity), kept as LockedUntil = lock time + LockDuration (x-opt-locked-until) (ms (AMQP timestamp), send time); a duration (ms, derivable stay) | none | yes | no |
| Azure Service Bus | receive, receive-and-delete | AMQP 1.0 (service protocol); SDK Azure.Messaging.ServiceBus 7.21.0 | arrival only | EnqueuedTime / EnqueuedTimeUtc (AMQP message annotation x-opt-enqueued-time) (ms (AMQP timestamp), arrival) | none | yes | no |
| Amazon Kinesis Data Streams | GetRecords | API version 2013-12-02 | arrival only | ApproximateArrivalTimestamp (ms, arrival) | time the response's NextShardIterator is returned, kept as the iterator's expiry (5 minutes later) (not documented, send time) | no | yes |
| Amazon Kinesis Data Streams | SubscribeToShard (enhanced fan-out) | API version 2013-12-02 | arrival only | ApproximateArrivalTimestamp (ms, arrival) | none | yes | yes |
| Azure Event Hubs | AMQP receive | AMQP 1.0 and Kafka protocol 1.0+ (service); SDK Azure.Messaging.EventHubs 5.12.2 | arrival only (unless Q3) | EnqueuedTime (AMQP message annotation x-opt-enqueued-time) (ms (AMQP timestamp), arrival) | none | yes | no |
| Azure Event Hubs | Kafka endpoint | AMQP 1.0 and Kafka protocol 1.0+ (service); SDK Azure.Messaging.EventHubs 5.12.2 | arrival only | the event's enqueue (log append) time; over Kafka, the record timestamp of type LOG_APPEND_TIME (batch MaxTimestamp) (ms, arrival) | none | not determined | no |
| Azure Queue Storage | Get Messages | Storage REST API version 2026-04-06 | stay in the message | InsertionTime (s (RFC 1123 date-time), arrival); dequeue time: the Date header of Get Messages, and TimeNextVisible = dequeue server time + visibilitytimeout (s (RFC 1123 date-time), send time); a duration (s, derivable stay) | none | no | yes |
| Azure Event Grid | namespace topics, pull delivery (receive) | namespace data-plane API version 2024-06-01 | nothing | none | publish time, kept as the event's time-to-live deadline (publish + eventTimeToLive) (not documented, arrival); receive time, kept as the lock deadline (receive + receiveLockDurationInSeconds) (not documented, send time) | yes | no |

## What we expected, and what we found

The protocol recorded what we expected before any record was coded.

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

## Readings applied to every record

Where the protocol left a reading open, one reading was chosen and applied to every record.
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

## How the records were made and checked

- **Coding.** Four auditors each coded a group of brokers from primary sources, following the
  protocol, without reading its section of expectations.
- **The fetch-back.** Every answer carries quotes from sources pinned to the version coded: 1,477
  quotes in all. On 27 October 2026, `scripts/broker_audit.py check` fetched every source back and
  found every quote exactly.
- **The read-backs.** Every rare answer was read back against its source in context, 72 in all,
  and all agree. These are each delivery stamp, each stamp kept only at the broker, each duration,
  and each "standing" or "credit or several". Each is recorded in its mode's `read_back`.
- **Not determined.** Two answers: what Event Hubs' retrieval time is (Q3), and whether its Kafka
  endpoint holds a fetch (Q7).

## How to check it

```bash
python scripts/broker_audit.py validate
python scripts/broker_audit.py table
python scripts/broker_audit.py check
```

`check` needs the network and takes a few minutes. It is not part of the test suite: its answer
depends on what other projects change.
