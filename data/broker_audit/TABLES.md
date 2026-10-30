# The broker audit's tables

Computed by `python scripts/broker_audit.py table` and `python scripts/broker_audit.py producers`
from the records in this folder (`batch_01.json` to `batch_25.json`). The verdicts are computed
from the answers by the rules that [`PROTOCOL.md`](PROTOCOL.md) and
[`AMENDMENT_01.md`](AMENDMENT_01.md) registered; they are not stored in the records. A test checks
that this file holds both tables exactly as the script prints them. [`README.md`](README.md) says
what the tables show and defines the words in their headings.

- **What the message carries:** the wait, a stay, the arrival time only, or nothing; "(unless …)"
  names the answers not determined that could change it.
- **In the message:** each broker time a consumer receives, with its resolution and kind.
- **Kept at the broker only:** each broker time the broker records and does not send.
- **Requests wait:** whether a consumer can keep a request or credit waiting for each message.
- **Broker access:** whether timing per message or per request can be read at the broker.
- **What the acknowledgment carries:** a hold (the broker's receive and send times, or a duration
  that contains its hold), one of the two times, nothing, or no acknowledgment at all.

## Consumer interfaces (418)

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
| Apache ActiveMQ Artemis | AMQP 1.0 consumers | 2.57.0 | stay in the message | x-opt-ingress-time (message annotation) (ms, arrival, by configuration); the broker's clock as a delivery converts a message stored in core form, sent as properties absolute-expiry-time less header ttl (only for such messages that carry an expiration) (ms, send time); header ttl, reduced at each delivery to the time left before an expiration the broker set from its own clock (ms, derivable stay) | none | yes | yes |
| Apache ActiveMQ Classic | OpenWire consumers (prefetch) | 6.4.0 | stay in the message | brokerInTime (JMSActiveMQBrokerInTime) (ms, arrival); brokerOutTime (JMSActiveMQBrokerOutTime) (ms, send time) | none | yes | yes |
| Apache ActiveMQ Classic | AMQP 1.0 consumers | 6.4.0 | stay in the message | properties creation-time, written from the message's timestamp, which is the broker's clock on arrival for a message published over MQTT, over STOMP without a timestamp header, or restamped by the TimeStampingBrokerPlugin (ms, arrival, by configuration); the broker's clock as each dispatch is converted, sent as properties absolute-expiry-time less header ttl (only for converted messages that carry an expiration) (ms, send time); header ttl, reduced at each dispatch to the time left before an expiration the broker set from its own clock (ms, derivable stay) | none | yes | yes |
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
| IBM MQ | MQI: MQGET with a wait, and asynchronous consumption (MQCB) | 10.0.0 (Long Term Support and Continuous Delivery documentation; product PDF manuals of 14 September 2026) | stay in the message | MQMD PutDate (YYYYMMDD) and PutTime (HHMMSSTH), GMT (10 ms (hundredths of a second), arrival, by configuration); MQMD Expiry: the remaining lifetime at MQGET (100 ms (tenths of a second); approximate, derivable stay) | none | no | yes |
| IBM MQ | MQI client with read ahead (nonpersistent messages) | 10.0.0 (Long Term Support and Continuous Delivery documentation; product PDF manuals of 14 September 2026) | stay in the message | MQMD PutDate (YYYYMMDD) and PutTime (HHMMSSTH), GMT (10 ms (hundredths of a second), arrival, by configuration); MQMD Expiry: the remaining lifetime (100 ms (tenths of a second); approximate, derivable stay) | none | yes | yes |
| IBM MQ | IBM MQ classes for JMS (receive and message listeners) | 10.0.0 (Long Term Support and Continuous Delivery documentation; product PDF manuals of 14 September 2026) | stay in the message | JMS_IBM_PutDate and JMS_IBM_PutTime (the MQMD PutDate and PutTime) (10 ms (hundredths of a second), arrival, by configuration); JMS_IBM_MQMD_Expiry, the remaining MQMD Expiry (only with MDREAD, off by default) (100 ms (tenths of a second); approximate, derivable stay) | none | no | yes |
| IBM MQ | messaging REST API (destructive get, HTTP DELETE with wait) | 10.0.0 (Long Term Support and Continuous Delivery documentation; product PDF manuals of 14 September 2026) | stay in the message | ibm-mq-md-expiry: the remaining expiry (header in ms; the queue manager's Expiry counts tenths of a second, approximately, derivable stay) | MQMD PutDate and PutTime (kept with the message, not sent over REST) (10 ms (hundredths of a second), arrival, by configuration) | no | not determined |
| IBM MQ | AMQP channel (AMQP 1.0 consumers) | 10.0.0 (Long Term Support and Continuous Delivery documentation; product PDF manuals of 14 September 2026) | stay in the message | MQMD PutDate and PutTime, delivered as properties creation-time for messages that did not come from AMQP (10 ms (hundredths of a second), arrival, by configuration); header ttl: the remaining MQMD Expiry, in milliseconds (100 ms (tenths of a second, in a millisecond field); approximate, derivable stay) | none | yes | not determined |
| WebSphere default messaging provider (service integration bus) | JMS consumers, read ahead off (the default for queue consumers) | Open Liberty 26.0.0.10 (tag gm-26.0.0.10): the default messaging provider's messaging engine (wasJmsServer) and JMS client (wasJmsClient) | nothing | none | CurrentMEArrivalTimestamp (message header field of the bus's internal message format, kept with the message item) (ms, arrival); messageWaitTime of the message item: the time of delivery to the consumer less the arrival stamp, plus the time spent at earlier engines; kept, not sent (ms, send time) | no | yes |
| WebSphere default messaging provider (service integration bus) | JMS consumers with read ahead (the default for non-durable topic subscribers and for durable subscribers outside a cloned environment) | Open Liberty 26.0.0.10 (tag gm-26.0.0.10): the default messaging provider's messaging engine (wasJmsServer) and JMS client (wasJmsClient) | nothing | none | CurrentMEArrivalTimestamp (kept with the message item) (ms, arrival); messageWaitTime of the message item (delivery less arrival), kept, not sent (ms, send time) | yes | yes |
| TIBCO Enterprise Message Service | Jakarta Messaging (JMS) consumers: receive and message listeners, with prefetch | 10.5.0 (User Guide, February 2026) | nothing | none | none | yes | yes |
| Solace PubSub+ event broker | SMF Direct messaging (topic subscriptions) | 10.26.8 (rolling release, October 2026; 10.26.0 LTS of June 2026); documentation as of 22 October 2026 | nothing | none | none | yes | not determined |
| Solace PubSub+ event broker | SMF Guaranteed messaging (flows bound to queues and topic endpoints) | 10.26.8 (rolling release, October 2026; 10.26.0 LTS of June 2026); documentation as of 22 October 2026 | stay in the message | time to live: the remaining TTL in the received message (ms field; the broker's counting step is not documented, derivable stay) | expiry deadline: arrival plus the remaining time to live, or plus the endpoint's max TTL (no named stamp) (ms (publisher TTL); s (endpoint max TTL), arrival, by configuration) | yes | yes |
| Solace PubSub+ event broker | MQTT 5.0 subscriptions, QoS 0 | 10.26.8 (rolling release, October 2026; 10.26.0 LTS of June 2026); documentation as of 22 October 2026 | nothing | none | none | yes | not determined |
| Solace PubSub+ event broker | MQTT 5.0 subscriptions, QoS 1 (QoS 2 requests are granted QoS 1) | 10.26.8 (rolling release, October 2026; 10.26.0 LTS of June 2026); documentation as of 22 October 2026 | stay in the message | Message Expiry Interval, reduced by the time waited at the broker (s, derivable stay) | expiry deadline: arrival plus the Message Expiry Interval (no named stamp) (s, arrival, by configuration) | yes | yes |
| Oracle WebLogic JMS | JMS asynchronous consumers (message listeners, message pipeline) | WebLogic Server 15.1.1.0.0 (JMS documentation of October 2025) | arrival only | JMSTimestamp (ms, arrival) | none | yes | yes |
| Oracle WebLogic JMS | JMS synchronous consumers (receive) | WebLogic Server 15.1.1.0.0 (JMS documentation of October 2025) | arrival only | JMSTimestamp (ms, arrival) | none | no | yes |
| Fiorano MQ | JMS consumers (receive and message listeners) | 11.0 (documentation as retrieved 27 October 2026) | nothing (unless Q2) | none | expiry time: arrival at the server plus the message's time to live (no named stamp) (not stated, arrival, by configuration) | not determined | no |
| MuleSoft Anypoint MQ | Broker API receive (GET messages, with pollingTime and a lock); used by the connector's consume and subscriber | Broker API (Courier Messaging API) 1.0.0; Anypoint MQ Connector 4.x; documentation as retrieved 27 October 2026 | arrival only (unless Q5) | created header (s (HTTP date in the documented example), arrival) | the lock's end: the time the message was handed to the consumer plus the lock's time to live (lockTtl, default 120000 ms); kept, not delivered (ms (lockTtl), send time) | no | no |
| Apache Qpid Broker-J | AMQP 0-8, 0-9 and 0-9-1 consumers (basic.consume with prefetch) | 10.1.1 | arrival only | arrival time (message metadata), delivered as the timestamp property of a message converted from AMQP 0-10 or 1.0 (ms, arrival, by configuration) | none | yes | yes |
| Apache Qpid Broker-J | AMQP 0-10 consumers (message.subscribe with message.flow credit) | 10.1.1 | arrival only | arrival time (message metadata), delivered as delivery-properties expiration less ttl, or as timestamp for a message converted from AMQP 1.0 (ms, arrival, by configuration) | none | yes | yes |
| Apache Qpid Broker-J | AMQP 1.0 consumers (link credit) | 10.1.1 | stay in the message | arrival time (message metadata), delivered as properties creation-time of a message converted from AMQP 0-8/0-9/0-9-1 or 0-10 (ms, arrival, by configuration); header ttl, reduced by the time since arrival (ms, derivable stay) | none | yes | yes |
| Apache Qpid C++ broker (qpidd) | AMQP 0-10 subscriptions (message.subscribe, message.flow credit) | 1.39.0 | stay in the message | delivery-properties timestamp (s, arrival, by configuration); delivery-properties ttl, the time left before the message expires (ms, derivable stay) | none | yes | yes |
| Apache Qpid C++ broker (qpidd) | AMQP 1.0 receiving links (link credit) | 1.39.0 | stay in the message | header ttl, the time left before the message expires (ms, derivable stay) | expiry deadline (receipt time plus the producer's ttl), kept with the message (ns (monotonic clock), arrival, by configuration) | yes | yes |
| JORAM | JMS consumers on queues (receive requests) | 5.24.1 | nothing (unless Q1, Q2, Q3) | none | none | yes | not determined |
| JORAM | JMS consumers on topic subscriptions | 5.24.1 | nothing | none | none | not determined | not determined |
| JORAM | AMQP 0-9-1 consumers (basic.consume with prefetch) | 5.24.1 | nothing | none | none | yes | not determined |
| Eclipse OpenMQ (Open Message Queue) | JMS consumers (OpenMQ protocol over TCP, TLS, the HTTP tunnel or WebSocket) | 6.9.0 | arrival only | packet timestamp (JMSTimestamp), set from the broker host's clock when a gateway the broker hosts builds the message (ms, arrival, by configuration) | ConsumerMessagePair timestamp, set when the message's state for the consumer becomes DELIVERED; not delivered (ms, send time) | yes | yes |
| Eclipse OpenMQ (Open Message Queue) | STOMP bridge service (STOMP over TCP or TLS) | 6.9.0 | arrival only | packet timestamp (JMSTimestamp, the timestamp header), set from the broker host's clock when a gateway the broker hosts builds the message (ms, arrival, by configuration) | ConsumerMessagePair timestamp, set when the broker delivers the message to the bridge's JMS consumer; not delivered (ms, send time) | yes | yes |
| Eclipse OpenMQ (Open Message Queue) | STOMP over WebSocket (mqstomp; mqjsonstomp carries the same frames as JSON) | 6.9.0 | arrival only | packet timestamp (the timestamp header), set from the broker's clock when the broker builds the message from a STOMP or JSON SEND frame (ms, arrival, by configuration) | ConsumerMessagePair timestamp, set when the broker hands the message to the WebSocket subscriber; not delivered (ms, send time) | yes | yes |
| SwiftMQ (Community Edition) | JMS consumers (SMQP, consumer cache) | 13.2.3 | arrival only | JMSExpiration (arrival on the broker's clock plus the producer's time-to-live); JMSTimestamp of messages published over MQTT or AMQP 0-9-1 without a timestamp; JMS_SWIFTMQ_AMQP_EXP_CURRENT_TIME_ADD of messages published over AMQP 1.0 with a ttl (ms, arrival, by configuration) | none | yes | yes |
| SwiftMQ (Community Edition) | AMQP 1.0 consumers (link credit, default JMS-mapping transformer) | 13.2.3 | arrival only | absolute-expiry-time (JMSExpiration: arrival on the broker's clock plus the ttl) and creation-time (JMSTimestamp, the broker's arrival time for MQTT and AMQP 0-9-1 publishes without a timestamp) (ms, arrival, by configuration) | none | yes | yes |
| SwiftMQ (Community Edition) | AMQP 0-9-1 consumers (basic.consume with prefetch) | 13.2.3 | arrival only | expiration property (JMSExpiration: arrival on the broker's clock plus the ttl) and timestamp property (JMSTimestamp, the broker's arrival time for MQTT publishes and AMQP 0-9-1 publishes without a timestamp) (ms, arrival, by configuration) | none | yes | yes |
| SwiftMQ (Community Edition) | AMQP 0-9-1 consumers (basic.get) | 13.2.3 | arrival only | expiration property (JMSExpiration: arrival on the broker's clock plus the ttl) and timestamp property (JMSTimestamp, the broker's arrival time for MQTT publishes and AMQP 0-9-1 publishes without a timestamp) (ms, arrival, by configuration) | none | no | yes |
| SwiftMQ (Community Edition) | MQTT 3.1.1 subscriptions, QoS 0 | 13.2.3 | nothing | none | StoreId entryTime of the subscription's queue entry (and JMSTimestamp of MQTT publishes), not delivered (ms, arrival) | yes | yes |
| SwiftMQ (Community Edition) | MQTT 3.1.1 subscriptions, QoS 1 and 2 | 13.2.3 | nothing | none | StoreId entryTime of the subscription's queue entry (and JMSTimestamp of MQTT publishes), not delivered (ms, arrival) | no | yes |
| LavinMQ | queues, AMQP 0-9-1 (basic.consume with prefetch) | 2.10.3 | arrival only | timestamp property (AMQP 0-9-1 basic properties) (s, arrival, by configuration) | delivered_at of the channel's Unack entry (RoughTime.instant, a monotonic instant), not delivered (100 ms (monotonic instant refreshed every 0.1 s), send time) | yes | yes |
| LavinMQ | queues, AMQP 0-9-1 (basic.get) | 2.10.3 | arrival only | timestamp property (AMQP 0-9-1 basic properties) (s, arrival, by configuration) | delivered_at of the channel's Unack entry (RoughTime.instant, a monotonic instant), not delivered (100 ms (monotonic instant refreshed every 0.1 s), send time) | no | yes |
| LavinMQ | streams, AMQP 0-9-1 (basic.consume with x-stream-offset) | 2.10.3 | arrival only | timestamp property (AMQP 0-9-1 basic properties) (s, arrival, by configuration) | delivered_at of the channel's Unack entry (RoughTime.instant, a monotonic instant), not delivered (100 ms (monotonic instant refreshed every 0.1 s), send time) | yes | yes |
| LavinMQ | MQTT 3.1 and 3.1.1 subscriptions, QoS 0 | 2.10.3 | nothing | none | stored message timestamp (RoughTime.unix_ms), not delivered (ms, floored to 100 ms, arrival) | yes | yes |
| LavinMQ | MQTT 3.1 and 3.1.1 subscriptions, QoS 1 (QoS 2 downgraded to 1) | 2.10.3 | nothing | none | stored message timestamp (RoughTime.unix_ms), not delivered (ms, floored to 100 ms, arrival) | yes | yes |
| IronMQ | pull queues: reserve (POST /queues/{name}/reservations, long poll up to 30 s) | IronMQ v3 REST API (documentation retrieved 27 October 2026; iron-io/docs commit d79110297313411408cd03362600c5204b3fa8bc) | nothing | none | the time a delayed message becomes available (post time plus delay), not delivered (s, arrival, by configuration); reservation deadline (the reservation plus its timeout), not delivered (s, send time) | not determined | not determined |
| IronMQ | push queues (POST to each subscriber URL) | IronMQ v3 REST API (documentation retrieved 27 October 2026; iron-io/docs commit d79110297313411408cd03362600c5204b3fa8bc) | nothing | none | the time a delayed message becomes available (post time plus delay), not delivered (s, arrival, by configuration); last_try_at, the latest push try to each subscriber, not delivered with the message (s, send time) | yes | yes |
| Oracle Database Advanced Queuing and Transactional Event Queues | PL/SQL DBMS_AQ.DEQUEUE and DEQUEUE_ARRAY (also the OCI dequeue) | Oracle AI Database 26ai (documentation G43539-02, retrieved 27 October 2026) | arrival only | enqueue_time (message_properties_t) (s (DATE; the queue table also keeps ENQ_TIMESTAMP, a TIMESTAMP), arrival) | DEQ_TIME / DEQ_TIMESTAMP (dequeue time) in the queue table, shown by the AQ$<queue_table> view (TIMESTAMP (fractional seconds), send time) | yes | yes |
| Oracle Database Advanced Queuing and Transactional Event Queues | Oracle JMS (AQ and TxEventQ) | Oracle AI Database 26ai (documentation G43539-02, retrieved 27 October 2026) | arrival only (unless Q4) | JMSTimestamp (the Advanced Queuing enqueue time) (ms, arrival) | DEQ_TIME / DEQ_TIMESTAMP (dequeue time) in the queue table, shown by the AQ$<queue_table> view (TIMESTAMP (fractional seconds), send time) | yes | yes |
| SQL Server Service Broker | RECEIVE (with WAITFOR) | SQL Server 2025 (17.x); documentation retrieved 27 October 2026 | arrival only | message_enqueue_time (datetime (rounded to .000, .003 or .007 s), arrival) | none | yes | yes |
| Microsoft Message Queuing (MSMQ) | MQReceiveMessage (synchronous and asynchronous) | Message Queuing of Windows 10 and Windows Server 2012 R2 and later (documentation retrieved 27 October 2026) | stay in the message | PROPID_M_ARRIVEDTIME (MSMQMessage.ArrivedTime) (s, arrival); PROPID_M_TIME_TO_BE_RECEIVED (time left in the time-to-be-received timer when the message is received) (s, derivable stay) | none | yes | yes |
| PGMQ | read and read_with_poll (visibility timeout; also read_grouped and its variants) | 1.13.1 | stay in the message | enqueued_at (µs (timestamptz), arrival); last_read_at = clock_timestamp() when the read takes the message (and vt = that instant plus the requested visibility timeout) (µs (timestamptz), send time) | none | yes | yes |
| PGMQ | pop (read and delete) | 1.13.1 | arrival only | enqueued_at (µs (timestamptz), arrival) | none | no | yes |
| Beanstalkd | reserve, reserve-with-timeout and reserve-job (TTR reservation) | 1.13 | nothing | none | created_at (job record) (µs (gettimeofday, kept in ns), arrival); deadline_at = reservation instant + TTR (job record) (µs (kept in ns), send time) | yes | yes |
| Faktory | FETCH (work units, reservation) | 1.10.0 | arrival only | enqueued_at (ns digits (RFC 3339 with fractional seconds), arrival) | reservation reserved_at, and expires_at = reserved_at + reserve_for (working set) (ns digits, send time) | yes | yes |
| Gearman (gearmand) | worker GRAB_JOB, GRAB_JOB_UNIQ and GRAB_JOB_ALL (JOB_ASSIGN packets) | 2.2.0 | nothing | none | job timeout timer armed at assignment (only for functions registered with CAN_DO_TIMEOUT) (ms (event-loop timer), send time) | no | yes |
| Svix | endpoint delivery (HTTP POST to the consumer's endpoint) | 1.103.0 (Svix server, open source; API 1.1.1) | stay in the message | message created_at (database), also encoded in the message id that svix-id carries (µs as kept; about 4 ms in the id (KsuidMs), arrival); attempt created_at (taken as each attempt is prepared), sent as svix-timestamp (s in the header; µs as kept, send time) | none | yes | yes |
| Hookdeck | destination delivery (HTTP request to the destination) | Event Gateway, API version 2026-09-01 (documentation retrieved 27 October 2026) | nothing | none | request ingested_at (and the event's created_at) (ms (documented examples), arrival); attempt delivered_at (and created_at) (ms (documented examples), send time) | yes | yes |
| Convoy | endpoint delivery (HTTP POST to the endpoint) | v26.9.2 | stay in the message | event id (a ULID made when the API received the event) sent as X-Convoy-Event-ID; the event also keeps acknowledged_at and created_at (ms (ULID), arrival, by configuration); signature timestamp t (taken as the signature is computed, just before the request), and each attempt's requested_at (kept) (s in the header; attempt times as stored, send time) | none | yes | yes |
| 60East AMPS | topic subscriptions (subscribe, sow_and_subscribe, bookmark replay) | AMPS server 5.3.5 (documentation as retrieved on 27 October 2026) | arrival only | timestamp header (ts, TransmissionTime): the time this instance of AMPS processed the publish command, ISO-8601 UTC (us, arrival) | none | yes | yes |
| 60East AMPS | queue subscriptions, at-least-once (leases) | AMPS server 5.3.5 (documentation as retrieved on 27 October 2026) | stay in the message | timestamp header (ts, TransmissionTime): the time this instance of AMPS processed the publish command, ISO-8601 UTC (us, arrival); leaseperiod header: the lease's expiry, the queue's LeasePeriod after AMPS sent the message (ISO-8601 datetime (resolution not stated), send time); leaseperiod less the queue's LeasePeriod (the send), less timestamp (the processing of the publish) (us (timestamp); leaseperiod's resolution not stated, derivable stay) | none | yes | yes |
| 60East AMPS | queue subscriptions, at-most-once | AMPS server 5.3.5 (documentation as retrieved on 27 October 2026) | arrival only (unless Q3, Q4, Q5) | timestamp header (ts, TransmissionTime): the time this instance of AMPS processed the publish command, ISO-8601 UTC (us, arrival) | none | yes | yes |
| 60East AMPS | SOW queries (sow) | AMPS server 5.3.5 (documentation as retrieved on 27 October 2026) | arrival only | timestamp header: the time AMPS processed the publish that stored the record (us, arrival) | none | no | yes |
| Bloomberg BlazingMQ | priority and fan-out queues (at least once, consumer flow control) | 0.95.20 | nothing | none | storage attributes: arrivalTimestamp (seconds since the epoch) and arrivalTimepoint (nanoseconds of a monotonic timer, meaningful only in the primary's process) (s (epoch); ns (monotonic, in process), arrival); time stamp of each unconfirmed delivery (UnconfirmedMessageInfo), taken as the queue handle delivers the message; not delivered (ns (monotonic), send time) | yes | yes |
| Bloomberg BlazingMQ | broadcast queues (at most once) | 0.95.20 | nothing | none | storage attributes: arrivalTimestamp (seconds since the epoch) and arrivalTimepoint (nanoseconds of a monotonic timer, meaningful only in the primary's process) (s (epoch); ns (monotonic, in process), arrival) | yes | yes |
| KX kdb+ tickerplant (tick.q) | subscriptions (.u.sub), real-time or batch mode | kdb+tick 2.8 (2014.03.12), KxSystems/kdb-tick at commit 85c08ff (13 August 2024; the repository has no tags) | arrival only | time column: the tickerplant's local time of day when .u.upd ran (timespan) (ns (timespan; the clock's precision depends on the platform), arrival, by configuration) | none | yes | no |
| Hazelcast (queues, topics, reliable topics) | IQueue (poll, take) | 5.7.0 | nothing | none | QueueItem creationTime (ms, arrival) | yes | no |
| Hazelcast (queues, topics, reliable topics) | ITopic (message listeners) | 5.7.0 | arrival only | publishTime (ms, arrival) | none | yes | no |
| Hazelcast (queues, topics, reliable topics) | reliable topic (ringbuffer reads) | 5.7.0 | nothing | none | ringbuffer expiration time of each item (arrival plus the ringbuffer's time-to-live) (ms, arrival, by configuration) | no | not determined |
| Oracle Coherence topics | subscribers (anonymous or in a subscriber group) | Coherence CE 15.1.1-0-6 | arrival only | element timestamp (ms (cluster time), arrival) | none | no | no |
| Aeron Archive | replay (startReplay), bounded or following a live recording | 1.53.3 | nothing | none | none | yes | yes |
| TIBCO FTL | subscribers through the persistence service (topics and queues, broker-based architecture) | 7.3.0 (Enterprise Edition; documentation as retrieved on 27 October 2026) | nothing | none | message_ttl timer of each message in a durable (arrival in the durable plus message_ttl) (s, arrival, by configuration) | yes | yes |
| LSEG Real-Time Distribution System | streaming item requests through the ADS (refresh, then update messages) | documentation as retrieved on 27 October 2026; delivered fields from LSEG Real-Time SDK 2.4.1.L1 (Enterprise Transport API, RWF) | nothing (unless Q1, Q2, Q3, Q4, Q5) | none | none | yes | not determined |
| Informatica Ultra Messaging (persistent Store) | persistent receivers: messages recovered from a Store | 6.17.2 (documentation as retrieved on 27 October 2026) | nothing | none | message age kept for repository-age-threshold (s, arrival, by configuration) | no | not determined |
| Eclipse Mosquitto | MQTT 5.0 subscriptions, QoS 0 | 2.1.2 | stay in the message | $timestamp user property (add-properties example plugin) (ms, arrival, by configuration); a duration (s, derivable stay) | none | yes | yes |
| Eclipse Mosquitto | MQTT 5.0 subscriptions, QoS 1 and 2 | 2.1.2 | stay in the message | $timestamp user property (add-properties example plugin) (ms, arrival, by configuration); a duration (s, derivable stay) | none | yes | yes |
| HiveMQ Community Edition | MQTT 5.0 subscriptions, QoS 0 | 2026.5 | stay in the message | a duration (s, derivable stay) | PUBLISH timestamp (arrival) (ms, arrival) | yes | yes |
| HiveMQ Community Edition | MQTT 5.0 subscriptions, QoS 1 and 2 | 2026.5 | stay in the message | a duration (s, derivable stay) | PUBLISH timestamp (arrival) (ms, arrival) | yes | yes |
| HiveMQ Enterprise | MQTT 5.0 subscriptions, QoS 0 | 4.56 (documentation as retrieved on 27 October 2026) | stay in the message | User Property set by a Data Hub data policy to ${timestamp} (ms, arrival, by configuration); a duration (s, derivable stay) | none | yes | yes |
| HiveMQ Enterprise | MQTT 5.0 subscriptions, QoS 1 and 2 | 4.56 (documentation as retrieved on 27 October 2026) | stay in the message | User Property set by a Data Hub data policy to ${timestamp} (ms, arrival, by configuration); a duration (s, derivable stay) | none | yes | yes |
| VerneMQ | MQTT 5.0 subscriptions, QoS 0 | 2.2.1 | stay in the message | a duration (s, derivable stay) | expiry_ts deadline (queue insertion plus the Message Expiry Interval) (s, arrival, by configuration) | yes | yes |
| VerneMQ | MQTT 5.0 subscriptions, QoS 1 and 2 | 2.2.1 | nothing | none | expiry_ts deadline (queue insertion plus the Message Expiry Interval) (s, arrival, by configuration) | yes | yes |
| NanoMQ | MQTT 5.0 subscriptions, QoS 0 | 0.25.7 | nothing | none | message timestamp (nng_clock at receipt) (ms, arrival) | yes | yes |
| NanoMQ | MQTT 5.0 subscriptions, QoS 1 and 2 | 0.25.7 | nothing | none | message timestamp (nng_clock at receipt) (ms, arrival) | yes | yes |
| Apache BifroMQ | MQTT 5.0 subscriptions, QoS 0 | 4.0.0-incubating | stay in the message | a duration (s, derivable stay) | Message.timestamp (HLC at arrival) (ms, arrival) | yes | yes |
| Apache BifroMQ | MQTT 5.0 subscriptions, QoS 1 and 2 | 4.0.0-incubating | stay in the message | a duration (s, derivable stay) | Message.timestamp (HLC at arrival) (ms, arrival); ConfirmingMessage.timestamp (send, monotonic), not delivered (ns, send time) | yes | yes |
| RMQTT | MQTT 5.0 subscriptions, QoS 0 | 0.24.0 | stay in the message | a duration (s, derivable stay) | create_time (ms, arrival) | yes | yes |
| RMQTT | MQTT 5.0 subscriptions, QoS 1 and 2 | 0.24.0 | stay in the message | a duration (s, derivable stay) | create_time (ms, arrival); OutInflightMessage.update_time (send), not delivered (ms, send time) | yes | yes |
| FlashMQ | MQTT 5.0 subscriptions, QoS 0 | 1.27.3 | stay in the message | a duration (s, derivable stay) | PublishExpireInfo.createdAt (monotonic), with the interval (s (used in whole seconds), arrival, by configuration) | yes | yes |
| FlashMQ | MQTT 5.0 subscriptions, QoS 1 and 2 | 1.27.3 | stay in the message | a duration (s, derivable stay) | PublishExpireInfo.createdAt (monotonic), with the interval (s (used in whole seconds), arrival, by configuration) | yes | yes |
| Moquette | MQTT 5.0 subscriptions, QoS 0 | 0.18.1 | stay in the message | a duration (s, derivable stay) | PublishedMessage.messageExpiry (deadline) (ms (rounded to seconds when forwarded), arrival, by configuration) | yes | yes |
| Moquette | MQTT 5.0 subscriptions, QoS 1 and 2 | 0.18.1 | stay in the message | a duration (s, derivable stay) | PublishedMessage.messageExpiry (deadline) (ms (rounded to seconds when forwarded), arrival, by configuration) | yes | yes |
| Aedes | MQTT 3.1 and 3.1.1 subscriptions, QoS 0, 1 and 2 | 1.2.0 | nothing | none | none | yes | no |
| Eclipse Amlen | MQTT 5.0 subscriptions, QoS 0 | 1.0.0.2 | stay in the message | a duration (s, derivable stay) | message header Expiry (deadline) (s, arrival, by configuration) | yes | yes |
| Eclipse Amlen | MQTT 5.0 subscriptions, QoS 1 and 2 | 1.0.0.2 | stay in the message | a duration (s, derivable stay) | message header Expiry (deadline) (s, arrival, by configuration) | yes | yes |
| Eclipse Amlen | JMS consumers (Amlen JMS client) | 1.0.0.2 | nothing | none | message header Expiry (deadline) (s, arrival, by configuration) | yes | yes |
| TBMQ | MQTT 5.0, non-persistent clients, QoS 0 | 2.4.1 | nothing | none | Kafka record timestamp of the message in tbmq.msg.all (ms, arrival) | yes | not determined |
| TBMQ | MQTT 5.0, non-persistent clients, QoS 1 and 2 | 2.4.1 | nothing | none | Kafka record timestamp of the message in tbmq.msg.all (ms, arrival) | yes | not determined |
| TBMQ | MQTT 5.0, persistent APPLICATION clients, QoS 1 and 2 | 2.4.1 | nothing | none | CREATED_TIME header of the copy in the application topic (and the Kafka record timestamp) (ms, arrival) | yes | not determined |
| TBMQ | MQTT 5.0, persistent DEVICE clients, QoS 1 and 2 | 2.4.1 | nothing | none | DevicePublishMsg.time (and the Kafka record timestamp) (ms, arrival) | yes | not determined |
| Waterstream | MQTT 5.0 subscriptions, QoS 0 | 1.7.0 (documentation as retrieved on 27 October 2026) | nothing (unless Q1, Q3, Q5) | none | none | yes | not determined |
| Waterstream | MQTT 5.0 subscriptions, QoS 1 and 2 | 1.7.0 (documentation as retrieved on 27 October 2026) | nothing (unless Q1, Q3, Q5) | none | none | yes | not determined |
| AWS IoT Core (message broker) | MQTT 5.0 subscriptions, QoS 0 | documentation as retrieved on 27 October 2026 | stay in the message | timestamp() set by a topic rule in the republished copy (user property or payload) (ms, arrival, by configuration); a duration (s, derivable stay) | none | yes | yes |
| AWS IoT Core (message broker) | MQTT 5.0 subscriptions, QoS 1 | documentation as retrieved on 27 October 2026 | stay in the message | timestamp() set by a topic rule in the republished copy (user property or payload) (ms, arrival, by configuration); a duration (s, derivable stay) | none | yes | yes |
| Azure IoT Hub | device-to-cloud, built-in Event Hubs-compatible endpoint (AMQP receive) | documentation as retrieved on 27 October 2026 (MicrosoftDocs/azure-docs at a33853236d24ee8adc979dc3924c7d4c4f79c43f) | arrival only (unless Q3) | iothub-enqueuedtime (and the Event Hub's x-opt-enqueued-time) (ms, arrival) | none | yes | not determined |
| Azure IoT Hub | cloud-to-device, device MQTT 3.1.1 subscription | documentation as retrieved on 27 October 2026 (MicrosoftDocs/azure-docs at a33853236d24ee8adc979dc3924c7d4c4f79c43f) | nothing | none | lock deadline (delivery plus one minute), not delivered (not documented, send time) | not determined | not determined |
| Azure Event Grid MQTT broker | MQTT 5.0 subscriptions, QoS 0 | documentation as retrieved on 27 October 2026 (MicrosoftDocs/azure-docs at a33853236d24ee8adc979dc3924c7d4c4f79c43f) | nothing (unless Q3, Q5) | none | expiry deadline: publication to the broker plus the Message Expiry Interval (s, arrival, by configuration) | yes | not determined |
| Azure Event Grid MQTT broker | MQTT 5.0 subscriptions, QoS 1 | documentation as retrieved on 27 October 2026 (MicrosoftDocs/azure-docs at a33853236d24ee8adc979dc3924c7d4c4f79c43f) | nothing (unless Q3, Q5) | none | expiry deadline: publication to the broker plus the Message Expiry Interval (s, arrival, by configuration) | yes | not determined |
| Azure Event Grid MQTT broker | routed to a namespace topic, pull delivery (CloudEvents) | documentation as retrieved on 27 October 2026 (MicrosoftDocs/azure-docs at a33853236d24ee8adc979dc3924c7d4c4f79c43f) | arrival only | CloudEvent time (when the service received the MQTT message) (100 ns (as in the documented example), arrival, by configuration) | receive time, kept as the lock deadline (receive + receiveLockDurationInSeconds) (not documented, send time) | yes | no |
| Apache Iggy | PollMessages (binary protocol over TCP, QUIC and WebSocket; the HTTP API's GET .../messages returns the same fields as JSON) | server-0.9.0 | arrival only | batch base_timestamp (each polled message's timestamp) (us, arrival) | none | no | yes |
| Fluvio | StreamFetch (consumer stream; what the client library's consumers use) | 0.18.1 | nothing | none | none | no | yes |
| Fluvio | Fetch (FileFetchRequest, one request, one response) | 0.18.1 | nothing | none | none | no | yes |
| Liftbridge | Subscribe (gRPC server stream) | v26.01.1 (API liftbridge-api v2.0.0) | arrival only | Message.timestamp (ns, arrival) | none | yes | yes |
| Gazette | Read (gRPC server stream of journal content; block = true waits for new content) | v0.103.0 | nothing | none | none | yes | yes |
| S2 (s2.dev) | read session (S2S protocol session, or an SSE response) | API v1 (OpenAPI 1.0.0, s2-specs commit 60dfbe3); documentation as retrieved 2026-10-27; SDK s2-sdk 0.35.2 | arrival only | SequencedRecord.timestamp (S2 arrival time when S2 assigns it) (ms, arrival, by configuration) | none | yes | no |
| S2 (s2.dev) | single-batch read (unary GET, optionally long polling at the tail with wait) | API v1 (OpenAPI 1.0.0, s2-specs commit 60dfbe3); documentation as retrieved 2026-10-27; SDK s2-sdk 0.35.2 | arrival only | SequencedRecord.timestamp (S2 arrival time when S2 assigns it) (ms, arrival, by configuration) | none | no | no |
| WarpStream | Kafka protocol fetch (consumer groups) | release v852 (21 October 2026); documentation as retrieved 2026-10-27 | arrival only | batch MaxTimestamp, timestamp type LogAppendTime (ms, arrival, by configuration) | none | no | no |
| WarpStream | HTTP fetch API (GET or POST /v1/kafka/fetch, optionally long_poll) | release v852 (21 October 2026); documentation as retrieved 2026-10-27 | arrival only | record timestamp (LogAppendTime) (ms, arrival, by configuration) | none | no | not determined |
| AutoMQ | consumer groups (Kafka fetch) | 1.7.4 (built on Apache Kafka 3.9.1) | arrival only | batch.maxTimestamp, timestampType = LogAppendTime (ms, arrival, by configuration) | Request.startTimeNanos (kept while the fetch waits in the delayed-fetch purgatory) (ns (System.nanoTime), request arrival) | no | yes |
| Tansu (Nisshi) | consumer groups (Kafka fetch) | v0.8.0 (released as Nisshi 0.8.0) | arrival only | batch base_timestamp and max_timestamp, set to the broker's time for a batch that carries the LogAppendTime bit (ms, arrival, by configuration) | fetch started_at, kept with the fetch's deadlines (started_at + max_wait) (ns (monotonic Instant), request arrival) | no | yes |
| Apache InLong TubeMQ | GetMessage RPC (pull consumer, and push consumer built on it) | 2.4.0 | nothing | none | receivedTime (stored message header and index entry) (ms, arrival); ConsumerNodeInfo.lastGetTime (latest successful GetMessage response, per consumer and partition), not delivered (ms, send time) | no | no |
| Apache EventMesh | TCP subscription (server push) | 1.12.0 | stay in the message | reqc2eventmeshtimestamp (event extension; reqeventmesh2mqtimestamp beside it) (ms, arrival, by configuration); reqeventmesh2ctimestamp (event extension) (ms, send time) | none | yes | yes |
| Apache EventMesh | HTTP subscription (webhook push) | 1.12.0 | stay in the message | reqc2eventmeshtimestamp (event extension; reqeventmesh2mqtimestamp beside it) (ms, arrival, by configuration); reqeventmesh2ctimestamp (in extFields) (ms, send time) | none | yes | yes |
| Apache EventMesh | gRPC stream subscription | 1.12.0 | stay in the message | reqc2eventmeshtimestamp (event extension; reqeventmesh2mqtimestamp beside it) (ms, arrival, by configuration); reqeventmesh2ctimestamp (attribute) (ms, send time) | none | yes | yes |
| Apache EventMesh | gRPC webhook subscription | 1.12.0 | arrival only | reqc2eventmeshtimestamp (event extension; reqeventmesh2mqtimestamp beside it) (ms, arrival, by configuration) | reqeventmesh2ctimestamp (lastPushTime), not delivered (ms, send time) | yes | yes |
| QMQ (Qunar) | pull (long polling), pull and push consumers | 1.1.3.5 | nothing | none | message log record timestamp (ms, arrival); PullEntry.pullBegin (and its deadline), not delivered (ms, request arrival) | yes | no |
| JoyQueue | JoyQueue protocol, FETCH_TOPIC_MESSAGE (long polling) | 4.2.7 | arrival only | storeTime (int, ms after the producer's sendTime); sendTime + storeTime is the broker's store time (ms, arrival) | LongPolling.expire (the fetch's arrival plus its longPollTimeout), not delivered (ms, request arrival) | no | no |
| DDMQ (Didi) | Thrift pull (consumer proxy) | commit 2f30b61a5741d55a5b515f3d8d19a8a35be8c9e2 (last commit, 17 April 2020; no release or tag) | nothing | none | RocketMQ storeTimestamp (kept by the store) (ms, arrival); UpstreamJob pullTimestamp (when a pull takes the message), not delivered (ms, send time) | yes | yes |
| DDMQ (Didi) | HTTP push (consumer proxy action) | commit 2f30b61a5741d55a5b515f3d8d19a8a35be8c9e2 (last commit, 17 April 2020; no release or tag) | nothing | none | RocketMQ storeTimestamp (kept by the store) (ms, arrival); CarreraAsyncRequest startTime, not delivered (ms, send time) | yes | yes |
| KubeMQ (community edition) | events (pub/sub, SubscribeToEvents) | 2.3.7 | nothing | none | none | yes | not determined |
| KubeMQ (community edition) | events store (SubscribeToEvents with a store type) | 2.3.7 | arrival only | Timestamp (the embedded store's received timestamp) (ns, arrival) | none | yes | not determined |
| KubeMQ (community edition) | queues (ReceiveQueueMessages) | 2.3.7 | arrival only | Attributes.Timestamp (the embedded store's received timestamp) (ns, arrival) | the receive request's wait deadline (waitCtx), not delivered (ns, request arrival) | yes | yes |
| RobustMQ | MQTT subscriptions, QoS 0 | 0.4.11 | nothing | none | StorageRecordMetadata.create_t (s, arrival) | yes | yes |
| RobustMQ | MQTT subscriptions, QoS 1 and 2 | 0.4.11 | nothing | none | StorageRecordMetadata.create_t (s, arrival); QosAckPacketInfo.create_time (while the acknowledgment is awaited), not delivered (ms, send time) | no | yes |
| Nakadi (Zalando) | subscription API (GET /subscriptions/{id}/events, streaming) | r3.3.9-2019-10-31 | arrival only | metadata.received_at (RFC 3339 string) (ms, arrival, by configuration) | PartitionData.lastSendMillis (latest batch sent, per partition), not delivered (ms, send time) | yes | no |
| Nakadi (Zalando) | low-level API (GET /event-types/{name}/events, streaming; deprecated) | r3.3.9-2019-10-31 | arrival only | metadata.received_at (RFC 3339 string) (ms, arrival, by configuration) | batchStartTimes (per partition, reset when a batch is sent), not delivered (ms, send time) | yes | no |
| Hermes (Allegro) | HTTP push, serial delivery | 2.22.2 | arrival only | __metadata.timestamp (Avro records; for JSON topics the same stamp is kept in Hermes's wrapper) (ms, arrival, by configuration) | none | yes | yes |
| Hermes (Allegro) | HTTP push, batch delivery | 2.22.2 | nothing | none | message timestamp (Hermes wrapper or Avro __metadata), kept (ms, arrival) | no | yes |
| Memphis | consumers (JetStream pull consumers, through the Memphis SDK) | 1.4.4 | arrival only | stored timestamp (<timestamp> token of the ack subject) (ns, arrival) | pull request arrival (waitingRequest.received), not delivered (ns, request arrival) | yes | yes |
| Amazon SNS | HTTP/S subscriptions, JSON notification (default) | API version 2010-03-31 (botocore 1.43.120 model; developer guide retrieved 2026-10-27) | arrival only | Timestamp (JSON body) (ms (ISO 8601 with milliseconds in the documented examples), arrival) | push request's send time, kept as its timeout (about 15 s); with delivery status logging, also the handoff that ends the logged dwell time (not documented (the timeout is about 15 s; logged dwell times are in ms), send time) | yes | yes |
| Amazon SNS | HTTP/S subscriptions, raw message delivery | API version 2010-03-31 (botocore 1.43.120 model; developer guide retrieved 2026-10-27) | nothing | none | publish timestamp (the Timestamp of the JSON format), not delivered (ms (ISO 8601 with milliseconds in the documented examples), arrival); push request's send time, kept as its timeout (about 15 s); with delivery status logging, also the handoff that ends the logged dwell time (not documented (the timeout is about 15 s; logged dwell times are in ms), send time) | yes | yes |
| Amazon EventBridge | event bus rules, API destination targets (HTTPS push) | API version 2015-10-07 (botocore 1.43.120 model; user guide retrieved 2026-10-27) | arrival only | time (the PutEvents call's time stamp when the entry gives no Time); aws.events.event.ingestion-time (input transformer variable, the time EventBridge received the event) (time: s in the documented examples; ingestion-time: ISO 8601, precision not documented, arrival, by configuration) | invocation attempt start (the request to the API destination), kept as its 5-second timeout; logged as INVOCATION_ATTEMPT_START with event bus logs at TRACE (ms (message_timestamp_ms of the log record); the timeout is 5 s, send time) | yes | yes |
| AWS AppSync Events | WebSocket subscriptions (data messages) | Event API, WebSocket subprotocol aws-appsync-event-ws (developer guide retrieved 2026-10-27); Amplify JS aws-amplify@6.22.2 for the HTTP publish result | arrival only | a timestamp that an onPublish handler writes into each event's payload from util.time (util.time.nowISO8601() in the documented example, or util.time.nowEpochMilliSeconds()) (ms (util.time.nowEpochMilliSeconds), arrival, by configuration) | none | yes | yes |
| Azure Web PubSub | WebSocket clients (simple, and PubSub subprotocols: JSON, reliable JSON, protobuf) | data-plane REST API version 2024-12-01; documentation at MicrosoftDocs/azure-docs a3385323 | nothing | none | expiry deadline of a message an MQTT 5.0 client published with a Message Expiry Interval: arrival plus the interval (no named stamp), kept, not delivered (s, arrival, by configuration) | yes | yes |
| Azure Web PubSub | MQTT 5.0 clients, QoS 0 | data-plane REST API version 2024-12-01; documentation at MicrosoftDocs/azure-docs a3385323 | stay in the message | a duration (s, derivable stay) | expiry deadline: arrival plus the Message Expiry Interval (no named stamp) (s, arrival, by configuration) | yes | yes |
| Azure Web PubSub | MQTT 5.0 clients, QoS 1 and 2 | data-plane REST API version 2024-12-01; documentation at MicrosoftDocs/azure-docs a3385323 | stay in the message | a duration (s, derivable stay) | expiry deadline: arrival plus the Message Expiry Interval (no named stamp) (s, arrival, by configuration) | yes | yes |
| Azure Web PubSub | event handler (CloudEvents over HTTP to the upstream webhook) | data-plane REST API version 2024-12-01; documentation at MicrosoftDocs/azure-docs a3385323 | nothing | ce-time (s (yyyy-MM-ddTHH:mm:ssZ), send time) | none | no | yes |
| Google Cloud Tasks | HTTP target tasks (push to the worker's URL) | v2 (google.cloud.tasks.v2 API; googleapis 933dd1be) | arrival only | schedule_time, set by the service to the current time when the task is created without one (or with one in the past), delivered as TaskETA; create_time is also kept (to the second), not delivered (s (TaskETA, seconds since 1970; the API keeps schedule_time to the microsecond), arrival, by configuration) | Attempt.dispatch_time (kept in the task's first_attempt and last_attempt), not delivered (us (truncated to the microsecond), send time) | yes | yes |
| Google Cloud Tasks | App Engine tasks (push to an App Engine handler) | v2 (google.cloud.tasks.v2 API; googleapis 933dd1be) | arrival only | schedule_time, set by the service to the current time when the task is created without one (or with one in the past), delivered as TaskETA; create_time is also kept (to the second), not delivered (s (TaskETA, seconds since 1970; the API keeps schedule_time to the microsecond), arrival, by configuration) | Attempt.dispatch_time (kept in the task's first_attempt and last_attempt), not delivered (us (truncated to the microsecond), send time) | yes | yes |
| Eventarc | Eventarc Standard triggers (CloudEvents over HTTP, through Pub/Sub push subscriptions) | Eventarc API v1 and Eventarc Publishing API v1 (googleapis 933dd1be); documentation retrieved 2026-10-27 | arrival only | ce-time = PUBLISH_TIME for Pub/Sub and Cloud Audit Logs events (system-generated); also message.publishTime in the body of Pub/Sub events (ms in the documented example (RFC 3339), arrival, by configuration) | push request time, kept as the request timeout (the push subscription's acknowledgment deadline) (not documented (the deadline is set in whole seconds), send time) | yes | no |
| Eventarc | Eventarc Advanced pipelines (CloudEvents over HTTP to a destination) | Eventarc API v1 and Eventarc Publishing API v1 (googleapis 933dd1be); documentation retrieved 2026-10-27 | nothing | none | none | yes | yes |
| Oracle Cloud Infrastructure Queue | GetMessages (short and long polling) | Queue API 20210201; OCI Python SDK 2.189.0 | stay in the message | createdAt (ms in the documented examples (RFC 3339), arrival); delivery time, kept and delivered as visibleAfter = delivery + the visibility timeout (the request's visibilityInSeconds, else the queue's) (ms in the documented examples (RFC 3339), send time); a duration (ms in the documented examples, derivable stay) | none | yes | no |
| Oracle Cloud Infrastructure Streaming | GetMessages (cursor) | Streaming API 20180418; OCI Python SDK 2.189.0 | arrival only | timestamp (not documented (RFC 3339 date-time), arrival) | none | no | no |
| Salesforce Platform Events (Pub/Sub API and Streaming API) | Pub/Sub API Subscribe (gRPC stream, num_requested flow control) | API version 68.0, Winter '27 (developer guides last updated 9 October 2026); Pub/Sub API version 1 (forcedotcom/pub-sub-api 20fb1382) | nothing (unless Q1) | none | none | yes | no |
| Salesforce Platform Events (Pub/Sub API and Streaming API) | Streaming API (CometD, Bayeux long polling) | API version 68.0, Winter '27 (developer guides last updated 9 October 2026); Pub/Sub API version 1 (forcedotcom/pub-sub-api 20fb1382) | nothing (unless Q1) | none | none | no | no |
| Momento Topics | gRPC Subscribe (server stream) | client-protos v0.138.3 (gRPC); HTTP API documentation at momentohq/public-dev-docs 385d5e2f | nothing | none | none | yes | no |
| Momento Topics | HTTP Subscribe (long poll) | client-protos v0.138.3 (gRPC); HTTP API documentation at momentohq/public-dev-docs 385d5e2f | nothing | none | none | no | no |
| Alibaba Cloud Simple Message Queue (formerly Message Service, MNS) | queues: ReceiveMessage and BatchReceiveMessage (long polling) | HTTP API version 2015-06-06 (documentation retrieved 2026-10-27); SDK aliyun-mns-java-sdk 2.0.0 | stay in the message | EnqueueTime (ms, arrival); FirstDequeueTime (first receive only); NextVisibleTime = receive time + the queue's VisibilityTimeout (every receive) (ms, send time); NextVisibleTime - VisibilityTimeout - EnqueueTime (ms, derivable stay) | none | yes | yes |
| Alibaba Cloud Simple Message Queue (formerly Message Service, MNS) | topics: push to an HTTP endpoint (XML, JSON or SIMPLIFIED format) | HTTP API version 2015-06-06 (documentation retrieved 2026-10-27); SDK aliyun-mns-java-sdk 2.0.0 | arrival only | PublishTime (ms, arrival) | push request's send time, kept as its 5-second response timeout (not documented (the timeout is 5 s), send time) | yes | yes |
| Alibaba Cloud EventBridge | event rules pushing to targets (HTTP and HTTPS endpoints, Function Compute, API destinations) | API version 2020-04-01 (documentation retrieved 2026-10-27); data-plane SDK alibabacloud-eventbridge-sdk at commit ccb377936d22 (no release tags) | stay in the message | aliyunpublishtime (ms (example 2020-11-19T21:04:42.179PRC), arrival); x-eventbridge-signature-timestamp (the time the push request was sent), delivered with every push to an HTTP/HTTPS target; NotifyTime is kept in the event trace (Q6) (ms, send time) | none | yes | yes |
| Alibaba Cloud DataHub | GetRecords by cursor (SDK protocol: protobuf, JSON or batch; and the OpenAPI's GetRecords) | OpenAPI version 2024-06-20 and the SDK protocol (documentation retrieved 2026-10-27); SDKs aliyun-datahub-sdk-go v1.2.1, aliyun-datahub-sdk-python v2.29.0 | arrival only (unless Q3, Q4) | system_time (SystemTime) (ms, arrival) | none | no | no |
| Alibaba Cloud DataHub | Kafka protocol endpoint (consumer groups) | OpenAPI version 2024-06-20 and the SDK protocol (documentation retrieved 2026-10-27); SDKs aliyun-datahub-sdk-go v1.2.1, aliyun-datahub-sdk-python v2.29.0 | nothing (unless Q2, Q3, Q4) | none | system_time (kept for every record) (ms, arrival) | not determined | no |
| Tencent Cloud TDMQ for CMQ | queues: ReceiveMessage and BatchReceiveMessage (HTTP data flow API, long polling) | HTTP data flow API (documentation retrieved 2026-10-27); TencentCloud API 3.0, tdmq 2020-02-17; SDKs tencentcloud-cmq-sdk-go v1.0.1, tencentcloud-sdk-go v1.3.201 | stay in the message | enqueueTime (s, arrival); nextVisibleTime = receive time + the queue's visibilityTimeout (s, send time); nextVisibleTime - visibilityTimeout - enqueueTime (s, derivable stay) | none | yes | yes |
| Tencent Cloud TDMQ for CMQ | topics: push to an HTTP endpoint (JSON or SIMPLIFIED format) | HTTP data flow API (documentation retrieved 2026-10-27); TencentCloud API 3.0, tdmq 2020-02-17; SDKs tencentcloud-cmq-sdk-go v1.0.1, tencentcloud-sdk-go v1.3.201 | arrival only | publishTime (not documented (an Int; the sample value is 11203432), arrival) | push request time, kept as the push's response timeout (about 15 s) (not documented, send time) | yes | yes |
| Yandex Message Queue | ReceiveMessage (short and long polling) | API version 2012-11-05 (SQS-compatible); yandex-cloud/docs at commit d6a30f68d4b5 (retrieved 2026-10-27) | stay in the message | SentTimestamp (attribute) (ms (epoch; example 1548347797419), arrival); ApproximateFirstReceiveTimestamp (attribute; first receive only); every receive is also kept as its visibility deadline (ms (epoch; example 1548348534956), send time) | none | yes | no |
| Yandex Data Streams | Kinesis-compatible HTTP API: GetRecords | yandex-cloud/docs at commit d6a30f68d4b5 (retrieved 2026-10-27); Kinesis-compatible HTTP API; Kafka API 3.4.0 and the YDB Topic API as YDB 26.2.1.14 implements them; SQS over Topics as YDB's main branch (commit 533b58f85b1f) documents it | arrival only | ApproximateArrivalTimestamp (not documented (a JSON number), arrival) | time each response's NextShardIterator is returned, kept as the iterator's expiry (5 minutes later) (not documented, send time) | no | no |
| Yandex Data Streams | Kafka API (fetch) | yandex-cloud/docs at commit d6a30f68d4b5 (retrieved 2026-10-27); Kinesis-compatible HTTP API; Kafka API 3.4.0 and the YDB Topic API as YDB 26.2.1.14 implements them; SQS over Topics as YDB's main branch (commit 533b58f85b1f) documents it | arrival only | record timestamp = the server's write time (WriteTimestampMS) (ms, arrival, by configuration) | the fetch's arrival, kept as its wait deadline (Now() in ms plus min(MaxWaitMs, 30 s)) in each partition's HasDataInfo request while the fetch waits; not sent (ms, request arrival) | no | no |
| Yandex Data Streams | SQS-compatible HTTP API (SQS over Topics, shared reader) | yandex-cloud/docs at commit d6a30f68d4b5 (retrieved 2026-10-27); Kinesis-compatible HTTP API; Kafka API 3.4.0 and the YDB Topic API as YDB 26.2.1.14 implements them; SQS over Topics as YDB's main branch (commit 533b58f85b1f) documents it | stay in the message | SentTimestamp (ms, arrival); ApproximateFirstReceiveTimestamp, which at this commit is the time the storage locks the message for this receive (TimeProvider->Now()), set on every receive (ms, send time) | none | yes | no |
| Yandex Data Streams | YDB Topic API (StreamRead) | yandex-cloud/docs at commit d6a30f68d4b5 (retrieved 2026-10-27); Kinesis-compatible HTTP API; Kafka API 3.4.0 and the YDB Topic API as YDB 26.2.1.14 implements them; SQS over Topics as YDB's main branch (commit 533b58f85b1f) documents it | arrival only (unless Q3, Q4) | written_at (per batch) (google.protobuf.Timestamp (ns field); fill precision not documented, arrival) | none | yes | no |
| Cloudflare Queues | Worker consumers (push, in batches) | REST API v4 and the Workers runtime API; cloudflare-docs at commit dc1a9c188094 (retrieved 2026-10-27); workerd v1.20261027.1; cloudflare-go v7.13.1 | arrival only | timestamp (Message.timestamp) (ms (JavaScript Date; timestamp_ms over HTTP), arrival) | start of each consumer invocation (the delivery of a batch), kept as its 15-minute wall-time limit; the analytics also record each ReadMessage operation (Q6) (not documented (the limit is 15 minutes), send time) | yes | no |
| Cloudflare Queues | HTTP pull consumers | REST API v4 and the Workers runtime API; cloudflare-docs at commit dc1a9c188094 (retrieved 2026-10-27); workerd v1.20261027.1; cloudflare-go v7.13.1 | arrival only | timestamp_ms (ms, arrival) | pull time, kept as the lease (visibility_timeout from the pull) (not documented (the timeout is set in ms), send time) | no | no |
| Upstash QStash | push to an HTTP endpoint (publish, enqueue, URL groups, schedules) | REST API v2 (OpenAPI 2.0.0); upstash/docs at commit e0359103ff03 (retrieved 2026-10-27); qstash-js v2.12.1 | nothing | iat of the Upstash-Signature JWT (the time the request's JWT was created); also the times of the ACTIVE and DELIVERED log entries (s (iat); ms (logs), send time) | createdAt (message record, logs and callbacks), not delivered (ms, arrival) | yes | yes |
| Vercel Queues | push mode (queue/v2beta trigger: Vercel invokes the consumer function) | Queues API v3 (beta; documentation retrieved 2026-10-27); SDK @vercel/queue 0.10.0 | arrival only (unless Q3, Q4) | createdAt (ce-vqscreatedat; Vqs-Timestamp) (ms (ISO 8601; documented examples to the millisecond), arrival) | none | yes | no |
| Vercel Queues | poll mode (ReceiveMessages, ReceiveMessageById) | Queues API v3 (beta; documentation retrieved 2026-10-27); SDK @vercel/queue 0.10.0 | arrival only | Vqs-Timestamp (timestamp) (ms (ISO 8601; documented examples to the millisecond), arrival) | receive time, kept as the lease's end (Vqs-Visibility-Timeout-Seconds, default 60 s) (not documented (the timeout is set in seconds), send time) | no | no |
| Valkey | streams (XREAD / XREADGROUP) | 9.1.3 | arrival only | entry ID time part (ms, arrival, by configuration) | PEL delivery_time (XREADGROUP), not delivered (ms, send time) | yes | yes |
| Valkey | Pub/Sub | 9.1.3 | nothing | none | none | yes | yes |
| Valkey | lists (BLPOP and kin) | 9.1.3 | nothing | none | none | yes | yes |
| KeyDB | streams (XREAD / XREADGROUP) | 6.3.4 | arrival only | entry ID time part (ms, arrival, by configuration) | PEL delivery_time (XREADGROUP), not delivered (ms, send time) | yes | yes |
| KeyDB | Pub/Sub | 6.3.4 | nothing | none | none | yes | yes |
| KeyDB | lists (BLPOP and kin) | 6.3.4 | nothing | none | none | yes | yes |
| Dragonfly | streams (XREAD / XREADGROUP) | 2.0.2 | arrival only | entry ID time part (ms, arrival, by configuration) | PEL delivery_time (XREADGROUP): the XREADGROUP transaction's time, taken when the command is dispatched and kept unchanged while it blocks; not delivered (ms, request arrival) | yes | yes |
| Dragonfly | Pub/Sub | 2.0.2 | nothing | none | none | yes | yes |
| Dragonfly | lists (BLPOP and kin) | 2.0.2 | nothing | none | none | yes | yes |
| Apache Kvrocks | streams (XREAD / XREADGROUP) | 2.17.0 | arrival only | entry ID time part (ms, arrival, by configuration) | pending entry last_delivery_time_ms (XREADGROUP), not delivered (ms, send time) | yes | yes |
| Apache Kvrocks | Pub/Sub | 2.17.0 | nothing | none | none | yes | yes |
| Apache Kvrocks | lists (BLPOP and kin) | 2.17.0 | nothing | none | none | yes | yes |
| Microsoft Garnet | Pub/Sub | 2.2.4 | nothing | none | none | yes | yes |
| Microsoft Garnet | lists (BLPOP and kin) | 2.2.4 | nothing | none | none | yes | yes |
| Centrifugo | subscriptions (bidirectional WebSocket, and the unidirectional WebSocket, SSE, HTTP-streaming and gRPC transports) | 6.10.2 | nothing | none | Publication.Time (Unix ms), not delivered (ms, arrival) | yes | yes |
| Centrifugo | history (client history command, and the server API's history) | 6.10.2 | nothing | none | Publication.Time (Unix ms), not delivered (ms, arrival) | no | yes |
| Mercure | subscription (server-sent events, GET on the hub) | 1.1.5 | arrival only | update ID (urn:uuid:<UUIDv7>): its 48-bit Unix ms part and 12-bit sub-ms fraction (1/4096 ms (48-bit ms field plus a 12-bit fraction), arrival, by configuration) | none | yes | yes |
| Nchan | long-polling | 1.3.8 | arrival only | message ID time (<time>:<tag>) (s, arrival) | none | no | yes |
| Nchan | interval-polling | 1.3.8 | arrival only | message ID time (<time>:<tag>) (s, arrival) | none | no | yes |
| Nchan | EventSource | 1.3.8 | arrival only | message ID time (<time>:<tag>) (s, arrival) | none | yes | yes |
| Nchan | WebSocket | 1.3.8 | arrival only | message ID time (<time>:<tag>) (s, arrival, by configuration) | none | yes | yes |
| Nchan | HTTP multipart/mixed | 1.3.8 | arrival only | message ID time (<time>:<tag>) (s, arrival) | none | yes | yes |
| Nchan | HTTP raw stream and chunked | 1.3.8 | nothing | none | message ID time (<time>:<tag>) (s, arrival) | yes | yes |
| Pushpin | HTTP streaming (Grip-Hold: stream) | 1.42.0 | nothing | none | none | yes | yes |
| Pushpin | HTTP long-polling (Grip-Hold: response) | 1.42.0 | nothing | none | none | no | yes |
| Pushpin | WebSocket (WebSocket-over-HTTP and GRIP WebSocket sessions) | 1.42.0 | nothing | none | none | yes | yes |
| Supabase Realtime | Broadcast (WebSocket channel) | 2.148.5 | nothing | none | realtime.messages.inserted_at, not delivered (us, arrival, by configuration) | yes | no |
| Supabase Realtime | Broadcast replay (on joining a private channel) | 2.148.5 | nothing | none | realtime.messages.inserted_at, not delivered (us, arrival) | no | no |
| Supabase Realtime | Postgres Changes (WebSocket channel) | 2.148.5 | arrival only | commit_timestamp (ms, arrival) | none | yes | no |
| Ably | realtime subscription (WebSocket or Comet realtime protocol) | specification 6.3.0, realtime protocol version 6 (ably-js 2.30.0); documentation retrieved 2026-10-27 | arrival only (unless Q3, Q4) | Message.timestamp (ms, arrival) | none | yes | no |
| Ably | SSE (server-sent events endpoint) | specification 6.3.0, realtime protocol version 6 (ably-js 2.30.0); documentation retrieved 2026-10-27 | arrival only | Message.timestamp (ms, arrival) | none | yes | no |
| Ably | REST history (GET /channels/{channelId}/messages) | specification 6.3.0, realtime protocol version 6 (ably-js 2.30.0); documentation retrieved 2026-10-27 | arrival only | Message.timestamp (ms, arrival) | none | no | no |
| PubNub | Subscribe V2 (long poll) | REST API (Subscribe V2, Publish, Message Persistence) documentation retrieved 2026-10-27; JavaScript SDK 13.1.3 | arrival only (unless Q3) | p.t (publish timetoken) (100 ns (timetoken unit), arrival) | none | no | not determined |
| PubNub | Message Persistence (fetch messages) | REST API (Subscribe V2, Publish, Message Persistence) documentation retrieved 2026-10-27; JavaScript SDK 13.1.3 | arrival only | timetoken (100 ns (timetoken unit), arrival) | none | no | not determined |
| Pusher Channels | channel subscriptions (WebSocket protocol) | protocol version 7; documentation retrieved 2026-10-27; pusher-js 8.6.0 | nothing | none | none | yes | yes |
| AMQP 1.0 (OASIS standard) | receiving link (link credit) | 1.0 (OASIS Standard, 29 October 2012) | stay in the message | a duration (ms, derivable stay) | message expiration time: arrival at the intermediary plus the header's ttl (no named stamp) (ms, arrival, by configuration) | yes | no |
| Jakarta Messaging 3.1 (JMS) | consumer, synchronous receive (receive, receive with a timeout, receiveNoWait) | 3.1 (Final Release, 25 February 2022) | nothing | none | none | no | no |
| Jakarta Messaging 3.1 (JMS) | consumer, asynchronous delivery (MessageListener) | 3.1 (Final Release, 25 February 2022) | nothing | none | none | yes | no |
| STOMP 1.2 | subscriptions (ack modes auto, client, client-individual) | 1.2 | nothing | none | none | yes | no |
| XMPP (XEP-0060 publish-subscribe, XEP-0203 delayed delivery, XEP-0313 message archive) | pubsub event notifications (XEP-0060) | XEP-0060 1.30.0 (2025-11-11); XEP-0203 2.0 (2009-09-15); XEP-0313 1.1.3 (2025-04-09); XEP-0160 1.0.1 (2016-10-07) | nothing | none | none | yes | no |
| XMPP (XEP-0060 publish-subscribe, XEP-0203 delayed delivery, XEP-0313 message archive) | pubsub last published item, sent on subscribing (XEP-0060 6.1.7) | XEP-0060 1.30.0 (2025-11-11); XEP-0203 2.0 (2009-09-15); XEP-0313 1.1.3 (2025-04-09); XEP-0160 1.0.1 (2016-10-07) | arrival only | delay stamp: the time the item's notification was originally sent (s (XEP-0082 DateTime; fractions of a second optional), arrival) | none | yes | no |
| XMPP (XEP-0060 publish-subscribe, XEP-0203 delayed delivery, XEP-0313 message archive) | pubsub item retrieval (XEP-0060 6.5) | XEP-0060 1.30.0 (2025-11-11); XEP-0203 2.0 (2009-09-15); XEP-0313 1.1.3 (2025-04-09); XEP-0160 1.0.1 (2016-10-07) | nothing | none | none | no | no |
| XMPP (XEP-0060 publish-subscribe, XEP-0203 delayed delivery, XEP-0313 message archive) | messages stored offline (XEP-0160), delivered with a delay stamp (XEP-0203) | XEP-0060 1.30.0 (2025-11-11); XEP-0203 2.0 (2009-09-15); XEP-0313 1.1.3 (2025-04-09); XEP-0160 1.0.1 (2016-10-07) | arrival only | delay stamp added by the recipient's server to a message it stored offline (s (XEP-0082 DateTime; fractions of a second optional), arrival) | none | yes | no |
| XMPP (XEP-0060 publish-subscribe, XEP-0203 delayed delivery, XEP-0313 message archive) | archive queries (XEP-0313) | XEP-0060 1.30.0 (2025-11-11); XEP-0203 2.0 (2009-09-15); XEP-0313 1.1.3 (2025-04-09); XEP-0160 1.0.1 (2016-10-07) | arrival only | archive timestamp: the time the archiving entity received the message (s (XEP-0082 DateTime; fractions of a second optional), arrival) | none | no | no |
| OPC UA (Part 4 subscriptions, Part 14 PubSub) | subscriptions, data change notifications (Publish service) | 1.05.07 (Parts 4 and 6, 2026-04-15); 1.05.06 (Parts 5 and 14, 2025-10-22) | stay in the message | DataValue serverTimestamp (with serverPicoSeconds): the time the Server received the value, or last knew it accurate (100 ns (UtcTime, DateTime encoding); 10 ps with serverPicoSeconds, arrival, by configuration); ResponseHeader.timestamp of the Publish response (the time the Server sent it); NotificationMessage.publishTime (the time the message was first sent) (100 ns (UtcTime, DateTime encoding), send time) | none | yes | no |
| OPC UA (Part 4 subscriptions, Part 14 PubSub) | subscriptions, event notifications (Publish service) | 1.05.07 (Parts 4 and 6, 2026-04-15); 1.05.06 (Parts 5 and 14, 2025-10-22) | stay in the message | ReceiveTime (BaseEventType property): the time the Server received the Event (100 ns (UtcTime, DateTime encoding), arrival, by configuration); ResponseHeader.timestamp of the Publish response (the time the Server sent it); NotificationMessage.publishTime (the time the message was first sent) (100 ns (UtcTime, DateTime encoding), send time) | none | yes | no |
| OPC UA (Part 4 subscriptions, Part 14 PubSub) | PubSub through an MQTT broker (Part 14) | 1.05.07 (Parts 4 and 6, 2026-04-15); 1.05.06 (Parts 5 and 14, 2025-10-22) | stay in the message | a duration (s, derivable stay) | none | yes | no |
| DDS (OMG Data Distribution Service), with RTI Connext's Persistence and Queuing Services | DataReader, samples kept by the durability service (TRANSIENT or PERSISTENT; OMG DDS 1.4) | DDS 1.4 (OMG formal/15-04-10, March 2015); RTI Connext 7.7.0 (Queuing Service User's Manual 6.0.1, its last) | nothing | none | none | yes | no |
| DDS (OMG Data Distribution Service), with RTI Connext's Persistence and Queuing Services | RTI Persistence Service, DataReader of the samples it publishes (Connext 7.7.0) | DDS 1.4 (OMG formal/15-04-10, March 2015); RTI Connext 7.7.0 (Queuing Service User's Manual 6.0.1, its last) | arrival only | SampleInfo.source_timestamp of a sample the service's PRSTDataWriter publishes: the service's own write time (ns field (Time_t: sec, nanosec), arrival, by configuration) | none | yes | not determined |
| DDS (OMG Data Distribution Service), with RTI Connext's Persistence and Queuing Services | RTI Queuing Service, QueueConsumer (Queuing API 7.7.0; User's Manual 6.0.1) | DDS 1.4 (OMG formal/15-04-10, March 2015); RTI Connext 7.7.0 (Queuing Service User's Manual 6.0.1, its last) | nothing (unless Q2, Q4) | none | expiration time of each sample, set when it is first added to the SharedReaderQueue (arrival plus the sample lifespan), kept at the service (not documented, arrival, by configuration); time each sample was sent to its QueueConsumer, kept as the acknowledgment timeout's deadline (only when response_timeout is set; default UNLIMITED) (not documented, send time) | yes | no |
| Eclipse Zenoh | subscribers, publications routed through a router | 1.10.1 | stay in the message | Sample.timestamp: the hybrid-logical-clock timestamp added by the first router that routes a data message arriving without one (NTP64 on the router's system clock: a 32-bit fraction of a second whose last 4 bits hold the HLC counter (2^-28 s, about 3.7 ns), arrival, by configuration); ROUTE record in the message's timestamp stack, pushed by each forwarding router just before it sends the message on (by configuration: the publisher's timestamp instrumentation, unstable API) (NTP64 on the router's system clock: a 32-bit fraction of a second whose last 4 bits hold the HLC counter (2^-28 s, about 3.7 ns), or a user-defined format, send time) | none | yes | yes |
| Eclipse Zenoh | queries answered by a storage (storage manager plugin on a router) | 1.10.1 | wait in the message | stored sample's timestamp: the router's arrival stamp, or the storage's own when the sample arrived without one (NTP64 on the router's system clock: a 32-bit fraction of a second whose last 4 bits hold the HLC counter (2^-28 s, about 3.7 ns), arrival, by configuration); RECEIVE record of the query, pushed by the node that hosts the storage when the query arrives, carried in the reply's timestamp stack (by configuration: the querier's timestamp instrumentation, unstable API); the storage's SEND record follows it (NTP64 on the router's system clock: a 32-bit fraction of a second whose last 4 bits hold the HLC counter (2^-28 s, about 3.7 ns), or a user-defined format, request arrival) | none | no | yes |
| WebSub (W3C Recommendation) | content distribution to a subscriber's callback (HTTP POST) | W3C Recommendation 23 January 2018 | nothing | none | none | yes | no |
| CloudEvents (CNCF) | events delivered over HTTP (HTTP protocol binding; HTTP 1.1 Web Hooks for Event Delivery) | 1.0.2 | nothing | none | none | yes | no |
| Standard Webhooks | webhook delivery to the consumer's endpoint (HTTP POST) | 1.0.0 (specification), repository release v1.0.2 | nothing | webhook-timestamp header: the time of the delivery attempt, updated on each retry (s (integer Unix time), send time) | none | yes | no |
| Alibaba Cloud ApsaraMQ for RocketMQ (4.x series, HTTP interface) | HTTP ConsumeMessage (long polling), non-ordered messages | HTTP API 2015-06-06 (documentation retrieved 2026-10-27); SDKs mq-http-java-sdk 1.0.3.2 and mq-http-go-sdk 1.0.3; OpenAPI Ons 2019-02-14 | nothing (unless Q2) | a stamp (?, send time) | StoreTimestamp (kept; returned by the message query API, not in the consumed message) (ms, arrival) | yes | yes |
| Alibaba Cloud ApsaraMQ for RocketMQ (4.x series, HTTP interface) | HTTP ConsumeMessageOrderly (trans=order, long polling), ordered messages | HTTP API 2015-06-06 (documentation retrieved 2026-10-27); SDKs mq-http-java-sdk 1.0.3.2 and mq-http-go-sdk 1.0.3; OpenAPI Ons 2019-02-14 | nothing (unless Q2, Q3, Q4) | none | StoreTimestamp (kept; returned by the message query API, not in the consumed message) (ms, arrival) | yes | yes |
| Tencent Cloud TDMQ for RocketMQ (HTTP interface) | HTTP consumeMessage (long polling) | HTTP access compatible with the community HTTP SDK (documentation retrieved 2026-10-27); SDK mq-http-php-sdk 1.0.4 (HTTP API 2015-06-06); TencentCloud API tdmq 2020-02-17 (tencentcloud-sdk-go v1.3.202) | nothing (unless Q2) | NextConsumeTime less the 5-minute retry interval (every delivery); FirstConsumeTime (first delivery, by the SDK's name) (ms (as the SDKs parse it; Tencent states no unit), send time) | StoreTimestamp (kept; returned by ExportRocketMQMessageDetail, not in the consumed message) (not stated (int64 timestamp), arrival) | yes | yes |
| Alibaba Cloud ApsaraMQ for MQTT | MQTT 3.1.1 subscriptions, QoS 0, 1 and 2 | MQTT 3.1.1 and 5.0 (documentation of the upgraded series retrieved 2026-10-27); OpenAPI OnsMqtt 2020-04-20; mqtt-server-sdk at commit 5dfe7ee71c078db7755411806c63b5864df54a1b | nothing | none | none | yes | yes |
| Alibaba Cloud ApsaraMQ for MQTT | MQTT 5.0 subscriptions, QoS 0 | MQTT 3.1.1 and 5.0 (documentation of the upgraded series retrieved 2026-10-27); OpenAPI OnsMqtt 2020-04-20; mqtt-server-sdk at commit 5dfe7ee71c078db7755411806c63b5864df54a1b | nothing (unless Q5) | none | none | yes | yes |
| Alibaba Cloud ApsaraMQ for MQTT | MQTT 5.0 subscriptions, QoS 1 and 2 | MQTT 3.1.1 and 5.0 (documentation of the upgraded series retrieved 2026-10-27); OpenAPI OnsMqtt 2020-04-20; mqtt-server-sdk at commit 5dfe7ee71c078db7755411806c63b5864df54a1b | nothing (unless Q5) | none | none | yes | yes |
| Alibaba Cloud ApsaraMQ for MQTT | server application subscription (mqtt-server-sdk, Go, over AMQP 0-9-1) | MQTT 3.1.1 and 5.0 (documentation of the upgraded series retrieved 2026-10-27); OpenAPI OnsMqtt 2020-04-20; mqtt-server-sdk at commit 5dfe7ee71c078db7755411806c63b5864df54a1b | nothing | none | none | yes | yes |
| Azure IoT Operations MQTT broker | MQTT v5 subscription, QoS 0 | documentation last updated 2026-07-31 | stay in the message | a duration (s, derivable stay) | expiry deadline of the queued message (internal, not named in the documentation) (s, arrival, by configuration) | yes | not determined |
| Azure IoT Operations MQTT broker | MQTT v5 subscription, QoS 1 | documentation last updated 2026-07-31 | stay in the message | a duration (s, derivable stay) | expiry deadline of the queued message (internal, not named in the documentation) (s, arrival, by configuration) | yes | not determined |
| Azure IoT Operations MQTT broker | MQTT v3.1.1 subscription, QoS 0 and 1 | documentation last updated 2026-07-31 | nothing | none | expiry deadline of the queued message (internal, not named in the documentation) (s, arrival, by configuration) | yes | not determined |
| comqtt | MQTT 5.0 subscription, QoS 0 | v2.6.7 | stay in the message | a duration (s, derivable stay) | Created (packet received on the server) (s, arrival) | yes | not determined |
| comqtt | MQTT 5.0 subscription, QoS 1 and 2 | v2.6.7 | nothing | none | Created (packet received on the server) (s, arrival) | yes | not determined |
| comqtt | MQTT 3.0 and 3.1.1 subscription, all QoS | v2.6.7 | nothing | none | Created (packet received on the server) (s, arrival) | yes | not determined |
| ElasticMQ | ReceiveMessage over the SQS-compatible HTTP API (long or short polling) | v1.7.1 | stay in the message | created (ms, arrival); a stamp (?, send time); a duration (ms, derivable stay) | none | yes | not determined |
| Emitter | MQTT subscription over TCP or WebSocket | v3.1 | nothing | none | time component of the message ID (s, arrival) | yes | not determined |
| gmqtt | MQTT 5.0 subscription, QoS 0 | v0.5.0 | stay in the message | a duration (s, stay) | At (entry time in the subscriber's queue) (ns, arrival) | yes | not determined |
| gmqtt | MQTT 5.0 subscription, QoS 1 and 2 | v0.5.0 | stay in the message | a duration (s, stay) | At (entry time in the subscriber's queue) (ns, arrival) | yes | not determined |
| gmqtt | MQTT 3.1.1 subscription, all QoS | v0.5.0 | nothing | none | At (entry time in the subscriber's queue) (ns, arrival) | yes | not determined |
| Adafruit IO | MQTT subscription to a feed or group topic | documentation as read on 2026-10-29 | nothing | none | none | yes | not determined |
| Alibaba Cloud IoT Platform | AMQP 1.0 server-side subscription (consumer group) | documentation as read on 2026-10-29 (AMQP page last updated 5 August 2025) | nothing (unless Q1) | none | none | yes | not determined |
| Losant | MQTT 3.1.1 subscription (QoS 0 only) | documentation as read on 2026-10-29 (Losant MQTT broker, MQTT 3.1.1) | nothing | none | none | yes | not determined |
| Huawei Cloud IoTDA | AMQP server-side subscription (push to an AMQP client) | documentation as read on 2026-10-29 (API pages updated 2026-09-30) | arrival only | event_time (s, arrival) | none | yes | not determined |
| flespi | MQTT 5.0 subscription | documentation as read on 2026-10-29 (flespi MQTT broker page) | nothing (unless Q5) | none | none | yes | not determined |
| flespi | MQTT 3.1 and 3.1.1 subscription | documentation as read on 2026-10-29 (flespi MQTT broker page) | nothing | none | none | yes | not determined |
| OpenRemote | MQTT subscriptions to attribute and asset events (event JSON) | 1.33.0 | arrival only | timestamp (ms, arrival, by configuration) | none | yes | not determined |
| OpenRemote | MQTT subscriptions to attribute values (value only) | 1.33.0 | nothing | none | timestamp (ms, arrival, by configuration) | yes | not determined |
| Tencent Cloud TDMQ for MQTT | MQTT subscriptions (3.1, 3.1.1 and 5.0) | documentation as retrieved on 29 October 2026 | nothing (unless Q5) | none | Message Timestamp (server-side message storage time) (not stated, arrival) | yes | yes |
| ThingLinks | data bridge to sinks (the event collector's JSON for a distributed message) | v1.4.0 | arrival only | timestamp (ms, arrival) | none | not determined | not determined |
| ThingLinks | MQTT subscriptions through BifroMQ | v1.4.0 | stay in the message | a duration (s, derivable stay) | timestamp (ms, arrival) | yes | not determined |
| ThingsBoard | WebSocket API subscriptions (entity data and telemetry updates) | v4.4.0.1 | arrival only | ts (ms, arrival, by configuration) | none | yes | not determined |
| ThingsBoard | MQTT device subscriptions (shared attribute updates and server-side RPC requests) | v4.4.0.1 | nothing | none | none | yes | not determined |
| Thingspeak | MQTT subscriptions to a channel feed (QoS 0) | documentation as archived by the Wayback Machine in 2025 and 2026 | arrival only | created_at (s, arrival, by configuration) | none | yes | not determined |
| Thingspeak | TalkBack command queue, execute call with a JSON or XML response (pull) | documentation as archived by the Wayback Machine in 2025 and 2026 | stay in the message (unless Q3) | created_at (s, arrival); a duration (s, derivable stay) | none | no | not determined |
| Thingspeak | TalkBack command queue, execute call with a text response (the default) | documentation as archived by the Wayback Machine in 2025 and 2026 | nothing | none | created_at (s, arrival) | no | not determined |
| Bevywise CrystalMQ (MQTTRoute) | MQTT subscriptions (3.1, 3.1.1 and 5) | documentation as retrieved on 29 October 2026 | nothing (unless Q1, Q3, Q5) | none | none | yes | not determined |
| Coreflux | MQTT subscriptions (MQTT 3.1.1 and 5) | documentation v2.22 as retrieved on 29 October 2026 | arrival only (unless Q3, Q5) | a LoT model field declared WITH TIMESTAMP (UTC or ISO) (s, arrival, by configuration) | none | yes | not determined |
| Crossbar.io | WAMP subscriptions (EVENT messages) | v26_10_1 | nothing | none | time_ns (ns, arrival, by configuration) | yes | not determined |
| Crossbar.io | event history call (wamp.subscription.get_events) | v26_10_1 | arrival only | time_ns (ns, arrival, by configuration) | none | no | not determined |
| ejabberd | XMPP messages stored offline and delivered at login (mod_offline) | 26.09 | arrival only | offline message timestamp (the delay stamp) (us, arrival, by configuration) | none | yes | not determined |
| ejabberd | XMPP archive queries (mod_mam, XEP-0313) | 26.09 | arrival only | archive timestamp (forwarded delay stamp) and archive id (us, arrival, by configuration) | none | no | not determined |
| ejabberd | MQTT subscriptions (mod_mqtt, MQTT 3.1.1 and 5.0) | 26.09 | stay in the message | a duration (s, derivable stay) | expiry deadline: the second of arrival plus the publisher's message expiry interval (s, arrival, by configuration) | yes | not determined |
| FairCom Edge | MQ API getMessagesFromMqTopic and getMessagesFromMqApiSession (JSON API, pull) | documentation last updated 27 October 2026 | arrival only | create_ts of the integration table record, returned as the message's timestamp (ms, arrival) | none | no | not determined |
| FairCom Edge | MQTT subscriptions (MQTT 3.1, 3.1.1 and 5) | documentation last updated 27 October 2026 | nothing (unless Q3, Q5) | none | create_ts of the integration table record (ms, arrival) | yes | not determined |
| hmq | MQTT subscriptions at QoS 0 | v1.5.10 | nothing | none | ts of the bridge element (Unix seconds) (s, arrival, by configuration) | yes | not determined |
| hmq | MQTT subscriptions at QoS 1 and 2 | v1.5.10 | nothing | none | ts of the bridge element (Unix seconds) (s, arrival, by configuration); a stamp (?, send time) | yes | not determined |
| hmq | Kafka bridge (plugin kafka: JSON elements the broker sends to Kafka) | v1.5.10 | arrival only | ts (s, arrival, by configuration) | none | not determined | not determined |
| Mochi MQTT | MQTT 5.0 subscription | v2.7.9 | stay in the message | a duration (s, derivable stay) | Created (s, arrival) | yes | not determined |
| Mochi MQTT | MQTT 3.1 and 3.1.1 subscription | v2.7.9 | nothing | none | Created (s, arrival) | yes | not determined |
| Mochi MQTT | inline subscription (Go callback, needs Options.InlineClient) | v2.7.9 | arrival only | Created (s, arrival) | none | yes | not determined |
| MongooseIM | live delivery to a connected client (one-to-one chat), with the message archive on | 6.10.0 | arrival only | stanza-id (us, arrival, by configuration) | none | yes | not determined |
| MongooseIM | offline messages delivered when the recipient logs in, with offline storage on | 6.10.0 | arrival only | delay stamp (us, arrival, by configuration) | none | yes | not determined |
| MongooseIM | archive query result (XEP-0313), with the message archive on | 6.10.0 | arrival only | delay stamp (us, arrival, by configuration) | none | no | not determined |
| MQTTnet | MQTT subscription (3.1, 3.1.1 and 5.0) | v5.2.0 | nothing | none | none | yes | not determined |
| Openfire | live delivery to a connected client (one-to-one chat) | v5.1.2 | nothing | none | none | yes | not determined |
| Openfire | offline messages delivered when the recipient logs in | v5.1.2 | arrival only | delay stamp (creation date) (ms, arrival) | none | yes | not determined |
| Openfire | multi-user chat room history sent to an occupant who joins | v5.1.2 | arrival only | delay stamp (ms, arrival, by configuration) | none | yes | not determined |
| Oracle Java CAPS JMS IQ Manager | queue receivers (JMS receive) | Java CAPS 6 documentation (JMS Reference 820-2239) | nothing | none | enqueue time (s, arrival) | yes | no |
| Oracle Java CAPS JMS IQ Manager | topic subscribers (JMS, durable subscription) | Java CAPS 6 documentation (JMS Reference 820-2239) | nothing | none | enqueue time (s, arrival) | yes | no |
| Oracle Tuxedo /Q | tpdequeue without TPQWAIT (an empty queue returns an error at once) | Oracle Tuxedo 12c Release 2 (12.2.2) | nothing | none | expiration time (arrival plus relative expiration) (s, arrival, by configuration) | no | not determined |
| Oracle Tuxedo /Q | tpdequeue with TPQWAIT (the request waits for a message) | Oracle Tuxedo 12c Release 2 (12.2.2) | nothing | none | expiration time (arrival plus relative expiration) (s, arrival, by configuration) | yes | not determined |
| rocketmq-rust | pull consumption (long polling) | v1.0.0 | arrival only | store timestamp (ms, arrival) | a stamp (?, request arrival) | no | not determined |
| rocketmq-rust | pop consumption | v1.0.0 | stay in the message | store timestamp (ms, arrival); a stamp (?, send time); a duration (ms, derivable stay) | none | yes | not determined |
| Rumqttd | MQTT 5.0 subscription | rumqttd-0.20.0 | stay in the message | a duration (s, derivable stay) | timestamp (monotonic Instant taken when the publish enters the commit log) (ns, arrival) | yes | not determined |
| Rumqttd | MQTT 3.1.1 subscription | rumqttd-0.20.0 | nothing | none | timestamp (monotonic Instant taken when the publish enters the commit log) (ns, arrival) | yes | not determined |
| SAP NetWeaver JMS provider | queue receivers (JMS) | SAP NetWeaver AS Java 7.4 (SAP Library saphelp_nw74, 7.4.16) | nothing | none | none | yes | not determined |
| SAP NetWeaver JMS provider | topic subscribers (JMS) | SAP NetWeaver AS Java 7.4 (SAP Library saphelp_nw74, 7.4.16) | nothing | none | none | yes | not determined |
| Semantik | subscription stream (server-sent events, POST /v1/subscribe) | hosted service, documentation and Go SDK commit 24d4313a376ac35fe30b89fb7125a2d9c6740e24 as read on 2026-10-29 | nothing | none | none | yes | not determined |
| Semantik | one-shot search (POST /v1/search) | hosted service, documentation and Go SDK commit 24d4313a376ac35fe30b89fb7125a2d9c6740e24 as read on 2026-10-29 | nothing | none | none | no | not determined |
| SmoothMQ | SQS ReceiveMessage (long polling with WaitTimeSeconds) | v0.2.3 | arrival only | message id (snowflake: milliseconds since 2010-11-04 01:42:54.657 UTC in the upper bits) (ms, arrival) | a stamp (?, send time) | yes | not determined |
| ZeroC IceStorm | subscriber proxy (oneway, twoway or batch delivery) | v3.8.3 | nothing | none | none | yes | no |
| Azurite | Get Messages (dequeue) | v3.37.0 | wait in the message | InsertionTime (s, arrival); a stamp (?, request arrival); a duration (s, derivable stay) | none | no | not determined |
| Azurite | Peek Messages | v3.37.0 | arrival only | InsertionTime (s, arrival) | none | no | not determined |
| Backendless | REST Retrieve Messages (poll a subscription) | service documentation as retrieved 2026-10-29; JavaScript SDK v7.4.8 | arrival only | publishedAt (ms, arrival) | none | no | not determined |
| Backendless | Real-time channel listeners (push) | service documentation as retrieved 2026-10-29; JavaScript SDK v7.4.8 | nothing (unless Q1, Q2, Q3, Q4, Q5) | none | none | yes | not determined |
| FAA NAS Enterprise Messaging Service (NEMS) | JMS subscription (SWIM consumer) | SWIM Timestamp and Message Sequence Number Policy, version 1.0 (29 September 2025) | nothing (unless Q1, Q2, Q3, Q4, Q5) | none | none | yes | not determined |
| Google App Engine Task Queue | Push queue (HTTP request to the task handler) | documentation last updated 2026-10-26 UTC | nothing | none | none | yes | not determined |
| Google App Engine Task Queue | Pull queue (lease_tasks) | documentation last updated 2026-10-26 UTC | nothing | none | none | no | not determined |
| MyQttHub | REST API pull (POST /pull) | ReactiveMyQtt v6.7.764 (REST API documentation, retrieved 2026-10-29) | nothing | none | none | no | yes |
| MyQttHub | MQTT 3.1 and 3.1.1 subscription (QoS 0, 1 and 2) | ReactiveMyQtt v6.7.764 (REST API documentation, retrieved 2026-10-29) | nothing | none | none | yes | yes |
| OCI Notifications | HTTPS (Custom URL) subscription | service documentation as retrieved 2026-10-29; OCI Go SDK v65.128.0 | nothing (unless Q1, Q2, Q3, Q4) | none | none | yes | not determined |
| Oracle Messaging Cloud Service | REST receive request (POST /consumers/{consumerName}/messages) | Using Oracle Messaging Cloud Service, E37257-26, May 2020 (Cloud Classic Infrastructure documentation) | nothing (unless Q1, Q2) | none | a stamp (?, request arrival) | not determined | not determined |
| Oracle Messaging Cloud Service | Message push listener (HTTP request to the listener's endpoint) | Using Oracle Messaging Cloud Service, E37257-26, May 2020 (Cloud Classic Infrastructure documentation) | nothing (unless Q1, Q2) | none | none | yes | not determined |
| ROMA Connect | RESTful consumption API | documentation updated 2025-07-21 | nothing | none | a stamp (?, request arrival) | no | not determined |
| Simple Message Notification (SMN) | HTTP/HTTPS subscription (notification message) | documentation updated 2025-04-02 | nothing | timestamp (s, send time) | none | yes | not determined |
| Xiaomi Galaxy EMQ | ReceiveMessage (long polling optional) | EMQ SDK 1.3.6 (galaxy-sdk-java commit 97952feb, 2020-01-09) | nothing (unless Q1, Q5) | none | a stamp (?, request arrival) | no | not determined |
| Zapier Trigger Inbox | lease API (poll) | Trigger Inbox API 1.0.0 (OpenAPI spec) | stay in the message | created_at (ms, arrival); a duration (ms, derivable stay) | leased_until (ms, send time) | no | not determined |
| AnyHook | webhook delivery to a destination endpoint | API v1 (documentation read 2026-10-29) | nothing | AnyHook-Signature t= (s, send time) | created_at (event log and API) (not stated, arrival) | yes | yes |
| Hook0 | endpoint delivery (HTTP request to the subscription target) | API 1.0.2 (tag api/v1.0.2) and output worker 1.0.7 (tag output-worker/v1.0.7) | stay in the message | the time in X-Event-Id, a UUIDv7 the database makes with uuidv7() when the producer leaves out event_id; received_at (statement_timestamp() of the INSERT that stores the event) is kept for every event and not sent (ms (the UUIDv7 delivered); us (received_at, kept), arrival, by configuration); X-Hook0-Signature t (Utc::now() when each attempt is signed, just before the request) (s, send time) | none | yes | yes |
| Hookdeck Outpost | webhook destination (default mode) | v1.7.0 | nothing | x-outpost-timestamp (time.Now() when each request is formatted) (s, send time) | event time (time, set to the server's clock when the publisher omits it) (us, arrival, by configuration) | yes | yes |
| HookDeploy | forward to a destination (HTTPS URL or private destination) | API v1 (documentation read 2026-10-29) | nothing | none | captured_at (request record, API) (s, arrival); forwarded_at (forward result, API) (s, send time) | yes | yes |
| Posthook | webhook deliveries (push to the project's endpoint) | hosted service, API v1 (documentation read 2026-10-29) | stay in the message | createdAt (s, arrival); postedAt (ms, send time); a duration (s, derivable stay) | none | yes | not determined |
| SuaveHooks | poll API (pull of captured events) | hosted service, REST API v1 (documentation read 2026-10-29) | arrival only | receivedAt (s, arrival) | none | no | not determined |
| SuaveHooks | forwards to HTTP, S3, SQS, Kafka and Pub/Sub targets (push) | hosted service, REST API v1 (documentation read 2026-10-29) | nothing (unless Q2, Q5) | X-SuaveHooks-Timestamp (and deliveredAt in the forward delivery log) (s, send time) | receivedAt (s, arrival) | yes | yes |
| Vartiq | webhook deliveries (push to the webhook URL) | hosted service (documentation read 2026-10-29) | nothing | none | createdAt (webhook message record) (not stated, arrival); webhookMessageAttempt.createdAt (not stated, send time) | yes | not determined |
| Webhook Studio | event list API (pull of captured events) | hosted service, /v1 API (documentation read 2026-10-29) | arrival only | received_at (ms, arrival) | none | no | not determined |
| Webhook Studio | long poll (events/wait, pull) | hosted service, /v1 API (documentation read 2026-10-29) | arrival only | received_at (ms, arrival) | none | no | not determined |
| Webhook Studio | forwards to destination URLs (push) | hosted service, /v1 API (documentation read 2026-10-29) | nothing | none | received_at (ms, arrival) | yes | yes |
| Zeplo | requests executed against the target URL (push) | Zeplo v2 (documentation read 2026-10-29) | nothing | none | queuedAt in the enqueue reply; created and the pending timestamp of the request's timeline (s, arrival); timeline timestamp of the processing status (sub-second, send time) | yes | yes |
| Amazon Chime SDK (messaging) | messaging WebSocket session (push to channel members) | hosted service (API reference and developer guide read 2026-10-29) | nothing (unless Q1, Q2) | none | none | yes | not determined |
| Amazon Chime SDK (messaging) | ListChannelMessages (pull) | hosted service (API reference and developer guide read 2026-10-29) | nothing (unless Q1, Q2) | none | none | no | not determined |
| AnyCable | WebSocket subscriptions (extended Action Cable protocol) | v1.6.20 | nothing | none | timestamp of the broker's history entry (s, arrival, by configuration) | yes | not determined |
| AnyCable | Durable Streams read over HTTP (catch-up and long-poll) | v1.6.20 | nothing | none | timestamp of the broker's history entry (s, arrival, by configuration) | no | not determined |
| AnyCable | Durable Streams read over HTTP (Server-Sent Events) | v1.6.20 | nothing | none | timestamp of the broker's history entry (s, arrival, by configuration) | yes | not determined |
| Azure Communication Services (chat) | real-time notifications (chatMessageReceived event, push to thread participants) | hosted service, Chat REST API version 2025-03-15 (documentation read 2026-10-29) | arrival only | createdOn (sub-second (seven fractional digits in the REST example), arrival) | none | yes | not determined |
| Azure Communication Services (chat) | ListChatMessages (pull, REST) | hosted service, Chat REST API version 2025-03-15 (documentation read 2026-10-29) | arrival only | createdOn (sub-second (seven fractional digits in the REST example), arrival) | none | no | not determined |
| Azure Fluid Relay | op events to connected clients (push over the delta connection) | hosted service; protocol definitions of FluidFramework client_v3.7.0 | arrival only (unless Q3, Q4, Q5) | timestamp (not stated, arrival) | none | yes | not determined |
| Azure Fluid Relay | delta storage fetch (pull of stored operations) | hosted service; protocol definitions of FluidFramework client_v3.7.0 | arrival only (unless Q3, Q4, Q5) | timestamp (not stated, arrival) | none | no | not determined |
| Beaver | WebSocket clients subscribed to channels (push) | v1.5.0 | nothing | none | none | yes | not determined |
| deepstream.io | event subscriptions over WebSocket (text protocol) | v10.2.4 | nothing | none | none | yes | not determined |
| Faye | HTTP long-polling transports (messages returned on /meta/connect) | 1.4.3 | nothing | none | none | no | not determined |
| Faye | WebSocket and EventSource transports (push) | 1.4.3 | nothing | none | none | yes | not determined |
| Gotify | WebSocket stream (push to the user's clients) | v3.1.1 | arrival only | date (ns (the documented example has seven fractional digits), arrival) | none | yes | not determined |
| Gotify | GET /message (pull, paged) | v3.1.1 | arrival only | date (ns (the documented example has seven fractional digits), arrival) | none | no | not determined |
| Kuzzle | realtime subscriptions (document notifications pushed to subscribers) | v2.60.1 | arrival only | timestamp (the notification's request.timestamp) (ms, arrival) | none | yes | not determined |
| Lightstreamer | subscription (streaming or polling session) | v7.4.9 | nothing | none | none | yes | not determined |
| Liveblocks | broadcast events over the room WebSocket | v3.24.5 | nothing | none | none | yes | not determined |
| Liveblocks | feed messages pushed over the room WebSocket | v3.24.5 | arrival only | createdAt (ms, arrival, by configuration) | none | yes | not determined |
| Liveblocks | feed messages read over the REST API (list) | v3.24.5 | arrival only | createdAt (ms, arrival, by configuration) | none | no | not determined |
| MigratoryData | subscription (client API) | 6.0.24 | nothing | none | none | yes | not determined |
| ntfy | JSON, SSE or WebSocket stream | v2.34.0 | arrival only | time (s, arrival) | none | yes | not determined |
| ntfy | raw stream | v2.34.0 | nothing | none | time (s, arrival) | yes | not determined |
| ntfy | poll (poll=1) | v2.34.0 | arrival only | time (s, arrival) | none | no | not determined |
| Poxa | WebSocket subscription (Pusher protocol) | v1.3.0 | nothing | none | none | yes | not determined |
| Soketi | WebSocket subscription (Pusher protocol) | 1.6.1 | nothing | none | none | yes | not determined |
| Apache Fluss | log scanner (LogScanner.poll) | v1.0.0 | arrival only | timestamp (batch commit timestamp) (ms, arrival) | none | no | not determined |
| Cloudflare K2 | subscription consume (POST /subscriptions/{id}/consume, five-minute lease per batch) | public beta, documentation read on 29 October 2026 | stay in the message | records[].timestamp_ms (ms, arrival); a stamp (?, send time); a duration (ms, derivable stay) | none | no | not determined |
| Data Ingestion Service (DIS) | download records (GET /v2/{project_id}/records) | API v2, documentation read on 29 October 2026 | arrival only | timestamp (ms, arrival) | none | no | not determined |
| Jocko | fetch (Kafka protocol) | 0.0.1 | nothing | none | none | no | not determined |
| Vanus | event log read (client library Read, gateway GetEvent) | v0.9.0 | arrival only | xvanusstime (ms, arrival) | none | no | not determined |
| Vanus | trigger push to an HTTP sink (subscription) | v0.9.0 | arrival only | xvanusstime (ms, arrival) | none | yes | not determined |
| Walrus | GET over the TCP client protocol (shared cursor) | v0.3.0 | nothing | none | none | no | not determined |
| KurrentDB (EventStoreDB) | catch-up subscription (Streams.Read with the subscription option) | v26.2.3 | arrival only | metadata "created" (ticks since the epoch) (100 ns, arrival) | none | yes | not determined |
| KurrentDB (EventStoreDB) | persistent subscription (PersistentSubscriptions.Read) | v26.2.3 | arrival only | metadata "created" (ticks since the epoch) (100 ns, arrival) | none | yes | not determined |
| KurrentDB (EventStoreDB) | read of a stream or $all (Streams.Read without the subscription option) | v26.2.3 | arrival only | metadata "created" (ticks since the epoch) (100 ns, arrival) | none | no | not determined |
| Message DB | read functions (get_stream_messages, get_category_messages) | v1.3.0 | arrival only | time (us, arrival) | none | no | not determined |
| MongoDB change streams | change stream (watch, getMore on a tailable cursor) | r9.0.4 | arrival only | wallTime (ms, arrival) | none | no | not determined |
| PgQue | receive (pgque.receive, a batch per call) | v0.2.2 | arrival only | created_at (us, arrival) | none | no | not determined |
| PostgreSQL LISTEN/NOTIFY | LISTEN subscription | REL_18_6 | nothing | none | none | yes | not determined |
| Hatchet | worker stream, task by task (START_STEP_RUN) | v0.114.2 | nothing | none | inserted_at (us, arrival); a stamp (?, send time) | yes | yes |
| Hatchet | worker stream, batch start (START_BATCH) | v0.114.2 | nothing (unless Q2, Q5) | a stamp (?, send time) | inserted_at (us, arrival) | yes | yes |
| AMQP 0-9-1 | basic.consume (pushed basic.deliver) | 0-9-1 | nothing | none | none | yes | not determined |
| AMQP 0-9-1 | basic.get (synchronous poll) | 0-9-1 | nothing | none | none | no | not determined |
| Durable Streams | catch-up read (GET offset) | v0.3.0 (protocol draft 1.0) | nothing | none | none | no | not determined |
| Durable Streams | long-poll read (GET live=long-poll) | v0.3.0 (protocol draft 1.0) | nothing | none | none | no | not determined |
| Durable Streams | SSE read (GET live=sse) | v0.3.0 (protocol draft 1.0) | nothing | none | none | yes | not determined |
| MQTT-SN | subscription (PUBLISH from the gateway) | 1.2 | nothing | none | none | yes | not determined |
| MQTT-SN | sleeping client wake-up (PINGREQ) | 1.2 | nothing | none | none | no | not determined |
| OpenMessaging | push consumer (MessageListener) | 2.1.0-pubsub | nothing | none | none | yes | not determined |
| OpenMessaging | pull consumer (PullConsumer.poll) | 2.1.0-pubsub | nothing | none | none | not determined | not determined |
| WAMP | subscription (EVENT) | Internet-Draft published 3 July 2026 | nothing | none | timestamp (ms, arrival, by configuration) | yes | not determined |
| WAMP | event history retrieval (wamp.subscription.get_events) | Internet-Draft published 3 July 2026 | arrival only | timestamp (ms, arrival, by configuration) | none | no | not determined |
| WS-Notification (WS-BrokeredNotification) | push (Notify to a NotificationConsumer) | 1.3 (OASIS Standard, 1 October 2006) | nothing | none | none | yes | not determined |
| WS-Notification (WS-BrokeredNotification) | pull point (GetMessages) | 1.3 (OASIS Standard, 1 October 2006) | nothing | none | none | no | not determined |
| Fireworq | HTTP push to a worker | v1.5.0 | nothing | none | created_at (ms, arrival) | yes | yes |

## Producer interfaces (390)

| Broker | Producer interface | Version | What the acknowledgment carries | Times in it |
|---|---|---|---|---|
| Apache Kafka | produce request, acks=1 or acks=-1 (all) | 4.4.0 | receive time only | LogAppendTimeMs (per partition) (ms, store time, by configuration) |
| Apache Kafka | produce request, acks=0 | 4.4.0 | no acknowledgment | none |
| Redpanda | Kafka API produce request, acks=1 or acks=-1 (all) | 26.2.2 | receive time only | LogAppendTimeMs (per partition) (ms, store time, by configuration) |
| Redpanda | Kafka API produce request, acks=0 | 26.2.2 | no acknowledgment | none |
| Apache Pulsar | producer (binary protocol: CommandSend, answered by CommandSendReceipt or CommandSendError) | 5.0.1 | nothing | none |
| Apache Pulsar | REST produce and WebSocket producer (ProducerAck) | 5.0.1 | nothing | none |
| Apache Pulsar | Kafka protocol on Pulsar (KoP): produce request, acks=1 or acks=-1 (all) | 5.0.1 | nothing | none |
| Apache Pulsar | Kafka protocol on Pulsar (KoP): produce request, acks=0 | 5.0.1 | no acknowledgment | none |
| Apache BookKeeper | add entry (bookie protocol v3 or v2), as the DistributedLog writer of OMB's driver uses it | 4.18.1 | nothing | none |
| Pravega | event writer (appends to a segment, answered by DataAppended) | 0.13.0 | nothing | none |
| RabbitMQ | AMQP 0-9-1 basic.publish, channel not in confirm mode | 4.4.0 | no acknowledgment | none |
| RabbitMQ | AMQP 0-9-1 publisher confirms (confirm.select) | 4.4.0 | nothing | none |
| RabbitMQ | AMQP 1.0, unsettled transfers (disposition) | 4.4.0 | nothing | none |
| RabbitMQ | AMQP 1.0, pre-settled transfers | 4.4.0 | no acknowledgment | none |
| RabbitMQ | streams (stream protocol Publish) | 4.4.0 | nothing | none |
| NATS | core publish (PUB, HPUB), verbose false | 2.15.2 | no acknowledgment | none |
| NATS | core publish (PUB, HPUB), verbose true | 2.15.2 | nothing | none |
| NATS | JetStream publish with a reply subject (PubAck) | 2.15.2 | nothing | none |
| NATS | JetStream publish without a reply subject, or to a stream with no_ack | 2.15.2 | no acknowledgment | none |
| NATS Streaming | publish (PubMsg, answered by PubAck) | 0.25.6 | nothing | none |
| NSQ | PUB, MPUB and DPUB over TCP (also /pub and /mpub over HTTP) | 1.3.0 | nothing | none |
| Redis | XADD (streams) | 8.10.3 | receive time only | the reply's entry ID, its milliseconds part (ms, store time, by configuration) |
| Redis | PUBLISH and SPUBLISH (Pub/Sub) | 8.10.3 | nothing | none |
| Redis | LPUSH and RPUSH (lists) | 8.10.3 | nothing | none |
| Apache RocketMQ | remoting send, synchronous or asynchronous (SEND_MESSAGE, SEND_MESSAGE_V2, SEND_BATCH_MESSAGE) | 5.5.1 | receive time only | recallHandle: Base64 of 'v1 topic brokerName timestamp messageId', whose timestamp is the timer message's delivery time plus 1 ms (the timer precision, timerPrecisionMs (default 1000 ms; 100, 200 or 500 ms by setting), receive time, by configuration) |
| Apache RocketMQ | remoting send, oneway | 5.5.1 | no acknowledgment | none |
| Apache RocketMQ | gRPC SendMessage (proxy) | 5.5.1 | nothing | none |
| Apache ActiveMQ Artemis | core protocol send, acknowledged (blocking send, or asynchronous send with a confirmation window) | 2.57.0 | nothing | none |
| Apache ActiveMQ Artemis | core protocol send, asynchronous without a confirmation window | 2.57.0 | no acknowledgment | none |
| Apache ActiveMQ Artemis | AMQP 1.0, unsettled transfers (disposition) | 2.57.0 | nothing | none |
| Apache ActiveMQ Artemis | AMQP 1.0, pre-settled transfers | 2.57.0 | no acknowledgment | none |
| Apache ActiveMQ Classic | OpenWire synchronous send (responseRequired: Response) | 6.4.0 | nothing | none |
| Apache ActiveMQ Classic | OpenWire asynchronous send with a producer window (ProducerAck) | 6.4.0 | nothing | none |
| Apache ActiveMQ Classic | OpenWire asynchronous send without a producer window | 6.4.0 | no acknowledgment | none |
| MQTT 5.0 (OASIS standard) | PUBLISH, QoS 0 | 5.0 | no acknowledgment | none |
| MQTT 5.0 (OASIS standard) | PUBLISH, QoS 1 (PUBACK) | 5.0 | nothing | none |
| MQTT 5.0 (OASIS standard) | PUBLISH, QoS 2 (PUBREC, then PUBCOMP after the publisher's PUBREL) | 5.0 | nothing | none |
| EMQX | MQTT PUBLISH, QoS 0 | 6.3.2 | no acknowledgment | none |
| EMQX | MQTT PUBLISH, QoS 1 (PUBACK) | 6.3.2 | nothing | none |
| EMQX | MQTT PUBLISH, QoS 2 (PUBREC, then PUBCOMP) | 6.3.2 | nothing | none |
| EMQX | HTTP API POST /publish and /publish/bulk | 6.3.2 | receive time only | id: its first 64 bits are the GUID's timestamp, erlang:system_time in microseconds when the API built the message (us, receive time, by configuration) |
| Google Cloud Pub/Sub | Publish (gRPC and REST) | v1 (google.pubsub.v1 API) | nothing | none |
| Google Cloud Pub/Sub Lite | Publish (streaming: PublishRequest, answered by PublishResponse) | v1 (google.cloud.pubsublite.v1 API) | nothing | none |
| Amazon SQS | SendMessage and SendMessageBatch | API version 2012-11-05 | nothing | none |
| Azure Service Bus | send over AMQP 1.0, unsettled transfer (disposition) | AMQP 1.0 (service protocol); SDK Azure.Messaging.ServiceBus 7.21.0 | nothing | none |
| Azure Service Bus | send over AMQP 1.0, pre-settled transfer | AMQP 1.0 (service protocol); SDK Azure.Messaging.ServiceBus 7.21.0 | no acknowledgment | none |
| Amazon Kinesis Data Streams | PutRecord and PutRecords | API version 2013-12-02 | nothing | none |
| Azure Event Hubs | AMQP send (disposition) | AMQP 1.0 and Kafka protocol 1.0+ (service); SDK Azure.Messaging.EventHubs 5.12.2 | nothing | none |
| Azure Event Hubs | Kafka endpoint: produce request, acks=1 or all | AMQP 1.0 and Kafka protocol 1.0+ (service); SDK Azure.Messaging.EventHubs 5.12.2 | nothing (unless P1) | none |
| Azure Queue Storage | Put Message (Messages_Enqueue) | Storage REST API version 2026-04-06 | receive time only | InsertionTime (s (RFC 1123 date-time), store time) |
| Azure Event Grid | namespace topic publish (PublishCloudEvent, PublishCloudEvents) | namespace data-plane API version 2024-06-01 | nothing | none |
| IBM MQ | MQI: MQPUT and MQPUT1, synchronous response | 10.0.0 (Long Term Support and Continuous Delivery documentation; product PDF manuals of 14 September 2026) | receive time only | MQMD PutDate and PutTime returned on output (10 ms (hundredths of a second), receive time, by configuration) |
| IBM MQ | MQI: MQPUT and MQPUT1 with asynchronous put response | 10.0.0 (Long Term Support and Continuous Delivery documentation; product PDF manuals of 14 September 2026) | no acknowledgment | none |
| IBM MQ | IBM MQ classes for JMS: send (synchronous put) | 10.0.0 (Long Term Support and Continuous Delivery documentation; product PDF manuals of 14 September 2026) | receive time only | JMS_IBM_PutDate and JMS_IBM_PutTime on the sent message (10 ms (hundredths of a second), receive time, by configuration) |
| IBM MQ | IBM MQ classes for JMS: send with asynchronous put | 10.0.0 (Long Term Support and Continuous Delivery documentation; product PDF manuals of 14 September 2026) | no acknowledgment | none |
| IBM MQ | messaging REST API: POST message | 10.0.0 (Long Term Support and Continuous Delivery documentation; product PDF manuals of 14 September 2026) | nothing | none |
| WebSphere default messaging provider (service integration bus) | JMS send, reliable nonpersistent, reliable persistent or assured persistent (the client awaits the engine's reply) | Open Liberty 26.0.0.10 (tag gm-26.0.0.10): the default messaging provider's messaging engine (wasJmsServer) and JMS client (wasJmsClient) | nothing | none |
| WebSphere default messaging provider (service integration bus) | JMS send, best-effort or express nonpersistent (no reply) | Open Liberty 26.0.0.10 (tag gm-26.0.0.10): the default messaging provider's messaging engine (wasJmsServer) and JMS client (wasJmsClient) | no acknowledgment | none |
| TIBCO Enterprise Message Service | synchronous send: PERSISTENT, and NON_PERSISTENT when the server confirms (authorization enabled, or as npsend_check_mode says) | 10.5.0 (User Guide, February 2026) | nothing | none |
| TIBCO Enterprise Message Service | asynchronous send with a completion listener | 10.5.0 (User Guide, February 2026) | nothing | none |
| TIBCO Enterprise Message Service | RELIABLE_DELIVERY, and NON_PERSISTENT without confirmation | 10.5.0 (User Guide, February 2026) | no acknowledgment | none |
| Solace PubSub+ event broker | SMF Direct publish | 10.26.8 (rolling release, October 2026; 10.26.0 LTS of June 2026); documentation as of 22 October 2026 | no acknowledgment | none |
| Solace PubSub+ event broker | SMF Guaranteed publish (publisher acknowledgment) | 10.26.8 (rolling release, October 2026; 10.26.0 LTS of June 2026); documentation as of 22 October 2026 | nothing | none |
| Solace PubSub+ event broker | MQTT 5.0 publish, QoS 0 | 10.26.8 (rolling release, October 2026; 10.26.0 LTS of June 2026); documentation as of 22 October 2026 | no acknowledgment | none |
| Solace PubSub+ event broker | MQTT 5.0 publish, QoS 1 (PUBACK), and QoS 2 (answered with PUBREC and PUBCOMP) | 10.26.8 (rolling release, October 2026; 10.26.0 LTS of June 2026); documentation as of 22 October 2026 | nothing | none |
| Oracle WebLogic JMS | JMS send (synchronous) | WebLogic Server 15.1.1.0.0 (JMS documentation of October 2025) | nothing (unless P1) | none |
| Oracle WebLogic JMS | JMS asynchronous send (CompletionListener) | WebLogic Server 15.1.1.0.0 (JMS documentation of October 2025) | nothing (unless P1) | none |
| Fiorano MQ | JMS send (synchronous) | 11.0 (documentation as retrieved 27 October 2026) | nothing | none |
| Fiorano MQ | JMS asynchronous send (CompletionListener) | 11.0 (documentation as retrieved 27 October 2026) | nothing | none |
| MuleSoft Anypoint MQ | Broker API send (PUT message, or a batch of 1 to 10); connector publish | Broker API (Courier Messaging API) 1.0.0; Anypoint MQ Connector 4.x; documentation as retrieved 27 October 2026 | nothing | none |
| Apache Qpid Broker-J | AMQP 0-9-1 basic.publish with publisher confirms (confirm.select) | 10.1.1 | nothing | none |
| Apache Qpid Broker-J | AMQP 0-8, 0-9 and 0-9-1 basic.publish without confirms | 10.1.1 | no acknowledgment | none |
| Apache Qpid Broker-J | AMQP 0-10 message.transfer (completion by session.completed) | 10.1.1 | nothing | none |
| Apache Qpid Broker-J | AMQP 1.0 transfer, unsettled (disposition) | 10.1.1 | nothing | none |
| Apache Qpid Broker-J | AMQP 1.0 transfer, sent settled | 10.1.1 | no acknowledgment | none |
| Apache Qpid C++ broker (qpidd) | AMQP 0-10 message.transfer (session.completed) | 1.39.0 | nothing | none |
| Apache Qpid C++ broker (qpidd) | AMQP 1.0 transfer, unsettled (disposition) | 1.39.0 | nothing | none |
| Apache Qpid C++ broker (qpidd) | AMQP 1.0 transfer, pre-settled | 1.39.0 | no acknowledgment | none |
| JORAM | JMS send, blocking (the default for persistent messages) | 5.24.1 | nothing (unless P1, P2, P3) | none |
| JORAM | JMS send, non-blocking (non-persistent messages, or asyncSend) | 5.24.1 | no acknowledgment | none |
| JORAM | AMQP 0-9-1 basic.publish | 5.24.1 | no acknowledgment | none |
| JORAM | AMQP 0-9-1 basic.publish in a transaction (tx.commit) | 5.24.1 | nothing | none |
| Eclipse OpenMQ (Open Message Queue) | JMS send acknowledged by the broker (SEND_REPLY): persistent messages by default, every message with imqAckOnProduce=true, and asynchronous sends | 6.9.0 | send time only | SEND_REPLY packet timestamp (in the reply's system message ID) (ms, send time) |
| Eclipse OpenMQ (Open Message Queue) | JMS send without acknowledgment: non-persistent messages by default, or any message with imqAckOnProduce=false | 6.9.0 | no acknowledgment | none |
| Eclipse OpenMQ (Open Message Queue) | STOMP SEND with a receipt header (STOMP bridge service and STOMP over WebSocket) | 6.9.0 | nothing | none |
| Eclipse OpenMQ (Open Message Queue) | STOMP SEND without a receipt header (STOMP bridge service and STOMP over WebSocket) | 6.9.0 | no acknowledgment | none |
| SwiftMQ (Community Edition) | JMS send answered by ProduceMessageReply (persistent messages, every replyThreshold-th send; a transacted session's commit is answered by CommitReply) | 13.2.3 | nothing | none |
| SwiftMQ (Community Edition) | JMS send without reply (non-persistent sends between replies, or persistent with asynchronous sends) | 13.2.3 | no acknowledgment | none |
| SwiftMQ (Community Edition) | AMQP 1.0 transfer, unsettled (disposition) | 13.2.3 | nothing | none |
| SwiftMQ (Community Edition) | AMQP 1.0 transfer, pre-settled | 13.2.3 | no acknowledgment | none |
| SwiftMQ (Community Edition) | AMQP 0-9-1 basic.publish (no publisher confirms; tx not implemented) | 13.2.3 | no acknowledgment | none |
| SwiftMQ (Community Edition) | MQTT 3.1.1 PUBLISH, QoS 0 | 13.2.3 | no acknowledgment | none |
| SwiftMQ (Community Edition) | MQTT 3.1.1 PUBLISH, QoS 1 and 2 (PUBACK; PUBREC, then PUBCOMP) | 13.2.3 | nothing | none |
| LavinMQ | AMQP 0-9-1 basic.publish with publisher confirms (basic.ack) | 2.10.3 | nothing | none |
| LavinMQ | AMQP 0-9-1 basic.publish without confirms | 2.10.3 | no acknowledgment | none |
| LavinMQ | AMQP 0-9-1 basic.publish in a transaction (tx.commit-ok) | 2.10.3 | nothing | none |
| LavinMQ | MQTT 3.1 and 3.1.1 PUBLISH, QoS 0 | 2.10.3 | no acknowledgment | none |
| LavinMQ | MQTT 3.1 and 3.1.1 PUBLISH, QoS 1 (PUBACK; QoS 2 downgraded to 1) | 2.10.3 | nothing | none |
| IronMQ | POST /queues/{name}/messages (201 Created) | IronMQ v3 REST API (documentation retrieved 27 October 2026; iron-io/docs commit d79110297313411408cd03362600c5204b3fa8bc) | nothing | none |
| Oracle Database Advanced Queuing and Transactional Event Queues | PL/SQL DBMS_AQ.ENQUEUE and ENQUEUE_ARRAY | Oracle AI Database 26ai (documentation G43539-02, retrieved 27 October 2026) | nothing | none |
| Oracle Database Advanced Queuing and Transactional Event Queues | Oracle JMS send and publish | Oracle AI Database 26ai (documentation G43539-02, retrieved 27 October 2026) | nothing (unless P1) | none |
| SQL Server Service Broker | SEND ON CONVERSATION | SQL Server 2025 (17.x); documentation retrieved 27 October 2026 | nothing | none |
| Microsoft Message Queuing (MSMQ) | MQSendMessage (return value) | Message Queuing of Windows 10 and Windows Server 2012 R2 and later (documentation retrieved 27 October 2026) | nothing | none |
| Microsoft Message Queuing (MSMQ) | acknowledgment messages (PROPID_M_ACKNOWLEDGE, to an administration queue) | Message Queuing of Windows 10 and Windows Server 2012 R2 and later (documentation retrieved 27 October 2026) | nothing (unless P1, P2) | none |
| PGMQ | send and send_batch (also send_topic) | 1.13.1 | nothing | none |
| Beanstalkd | put | 1.13 | nothing | none |
| Faktory | PUSH and PUSHB | 1.10.0 | nothing | none |
| Gearman (gearmand) | SUBMIT_JOB and its variants (background, high and low priority, epoch) | 2.2.0 | nothing | none |
| Svix | create message (POST /api/v1/app/{app_id}/msg) | 1.103.0 (Svix server, open source; API 1.1.1) | receive time only | timestamp (the message's created_at; the id encodes the same instant) (µs (as stored), receive time) |
| Hookdeck | source URL and Publish API (synchronous HTTP response) | Event Gateway, API version 2026-09-01 (documentation retrieved 27 October 2026) | nothing (unless P1, P2, P3) | none |
| Convoy | create event (POST /api/v1/projects/{projectID}/events) | v26.9.2 | receive time only | data.uid: a ULID made as the request was handled; its first 48 bits are the Unix time in milliseconds (ms, receive time) |
| 60East AMPS | publish and delta_publish (received, processed, persisted acknowledgments) | AMPS server 5.3.5 (documentation as retrieved on 27 October 2026) | nothing | none |
| Bloomberg BlazingMQ | PUT with acknowledgment requested | 0.95.20 | nothing | none |
| KX kdb+ tickerplant (tick.q) | asynchronous .u.upd (neg h) | kdb+tick 2.8 (2014.03.12), KxSystems/kdb-tick at commit 85c08ff (13 August 2024; the repository has no tags) | no acknowledgment | none |
| KX kdb+ tickerplant (tick.q) | synchronous .u.upd (h) | kdb+tick 2.8 (2014.03.12), KxSystems/kdb-tick at commit 85c08ff (13 August 2024; the repository has no tags) | nothing | none |
| Hazelcast (queues, topics, reliable topics) | IQueue offer | 5.7.0 | nothing | none |
| Hazelcast (queues, topics, reliable topics) | ITopic publish | 5.7.0 | nothing | none |
| Hazelcast (queues, topics, reliable topics) | reliable topic publish (ringbuffer add) | 5.7.0 | nothing | none |
| Oracle Coherence topics | Publisher.publish (CompletableFuture<Status>) | Coherence CE 15.1.1-0-6 | nothing | none |
| Aeron Archive | publication recorded by the archive (startRecording) | 1.53.3 | no acknowledgment | none |
| TIBCO FTL | tibPublisher_Send, store publisher mode store_confirm_send | 7.3.0 (Enterprise Edition; documentation as retrieved on 27 October 2026) | nothing | none |
| TIBCO FTL | tibPublisher_Send, store publisher mode store_send_noconfirm | 7.3.0 (Enterprise Edition; documentation as retrieved on 27 October 2026) | no acknowledgment | none |
| LSEG Real-Time Distribution System | post messages through the ADS (acknowledgment requested) | documentation as retrieved on 27 October 2026; delivered fields from LSEG Real-Time SDK 2.4.1.L1 (Enterprise Transport API, RWF) | nothing | none |
| Informatica Ultra Messaging (persistent Store) | persistent source (stability acknowledgments from Stores) | 6.17.2 (documentation as retrieved on 27 October 2026) | nothing | none |
| Eclipse Mosquitto | MQTT PUBLISH, QoS 0 | 2.1.2 | no acknowledgment | none |
| Eclipse Mosquitto | MQTT PUBLISH, QoS 1 (PUBACK) and QoS 2 (PUBREC, PUBCOMP) | 2.1.2 | nothing | none |
| HiveMQ Community Edition | MQTT PUBLISH, QoS 0 | 2026.5 | no acknowledgment | none |
| HiveMQ Community Edition | MQTT PUBLISH, QoS 1 (PUBACK) and QoS 2 (PUBREC, PUBCOMP) | 2026.5 | nothing | none |
| HiveMQ Enterprise | MQTT PUBLISH, QoS 0 | 4.56 (documentation as retrieved on 27 October 2026) | no acknowledgment | none |
| HiveMQ Enterprise | MQTT PUBLISH, QoS 1 (PUBACK) and QoS 2 (PUBREC, PUBCOMP) | 4.56 (documentation as retrieved on 27 October 2026) | nothing | none |
| VerneMQ | MQTT PUBLISH, QoS 0 | 2.2.1 | no acknowledgment | none |
| VerneMQ | MQTT PUBLISH, QoS 1 (PUBACK) and QoS 2 (PUBREC, PUBCOMP) | 2.2.1 | nothing | none |
| NanoMQ | MQTT PUBLISH, QoS 0 | 0.25.7 | no acknowledgment | none |
| NanoMQ | MQTT PUBLISH, QoS 1 (PUBACK) and QoS 2 (PUBREC, PUBCOMP) | 0.25.7 | nothing | none |
| Apache BifroMQ | MQTT PUBLISH, QoS 0 | 4.0.0-incubating | no acknowledgment | none |
| Apache BifroMQ | MQTT PUBLISH, QoS 1 (PUBACK) and QoS 2 (PUBREC, PUBCOMP) | 4.0.0-incubating | nothing | none |
| RMQTT | MQTT PUBLISH, QoS 0 | 0.24.0 | no acknowledgment | none |
| RMQTT | MQTT PUBLISH, QoS 1 (PUBACK) and QoS 2 (PUBREC, PUBCOMP) | 0.24.0 | nothing | none |
| FlashMQ | MQTT PUBLISH, QoS 0 | 1.27.3 | no acknowledgment | none |
| FlashMQ | MQTT PUBLISH, QoS 1 (PUBACK) and QoS 2 (PUBREC, PUBCOMP) | 1.27.3 | nothing | none |
| Moquette | MQTT PUBLISH, QoS 0 | 0.18.1 | no acknowledgment | none |
| Moquette | MQTT PUBLISH, QoS 1 (PUBACK) and QoS 2 (PUBREC, PUBCOMP) | 0.18.1 | nothing | none |
| Aedes | MQTT PUBLISH, QoS 0 | 1.2.0 | no acknowledgment | none |
| Aedes | MQTT PUBLISH, QoS 1 (PUBACK) and QoS 2 (PUBREC, PUBCOMP) | 1.2.0 | nothing | none |
| Eclipse Amlen | MQTT PUBLISH, QoS 0 | 1.0.0.2 | no acknowledgment | none |
| Eclipse Amlen | MQTT PUBLISH, QoS 1 (PUBACK) and QoS 2 (PUBREC, PUBCOMP) | 1.0.0.2 | nothing | none |
| TBMQ | MQTT PUBLISH, QoS 0 | 2.4.1 | no acknowledgment | none |
| TBMQ | MQTT PUBLISH, QoS 1 (PUBACK) and QoS 2 (PUBREC, PUBCOMP) | 2.4.1 | nothing | none |
| Waterstream | MQTT PUBLISH, QoS 0 | 1.7.0 (documentation as retrieved on 27 October 2026) | no acknowledgment | none |
| Waterstream | MQTT PUBLISH, QoS 1 (PUBACK) and QoS 2 (PUBREC, PUBCOMP) | 1.7.0 (documentation as retrieved on 27 October 2026) | nothing | none |
| AWS IoT Core (message broker) | MQTT PUBLISH, QoS 0 | documentation as retrieved on 27 October 2026 | no acknowledgment | none |
| AWS IoT Core (message broker) | MQTT PUBLISH, QoS 1 (PUBACK) | documentation as retrieved on 27 October 2026 | nothing | none |
| AWS IoT Core (message broker) | HTTPS Publish (IoT Data Plane) | documentation as retrieved on 27 October 2026 | nothing | none |
| Azure IoT Hub | device-to-cloud MQTT 3.1.1 PUBLISH, QoS 0 | documentation as retrieved on 27 October 2026 (MicrosoftDocs/azure-docs at a33853236d24ee8adc979dc3924c7d4c4f79c43f) | no acknowledgment | none |
| Azure IoT Hub | device-to-cloud MQTT 3.1.1 PUBLISH, QoS 1 (PUBACK) | documentation as retrieved on 27 October 2026 (MicrosoftDocs/azure-docs at a33853236d24ee8adc979dc3924c7d4c4f79c43f) | nothing | none |
| Azure Event Grid MQTT broker | MQTT PUBLISH, QoS 0 | documentation as retrieved on 27 October 2026 (MicrosoftDocs/azure-docs at a33853236d24ee8adc979dc3924c7d4c4f79c43f) | no acknowledgment | none |
| Azure Event Grid MQTT broker | MQTT PUBLISH, QoS 1 (PUBACK) | documentation as retrieved on 27 October 2026 (MicrosoftDocs/azure-docs at a33853236d24ee8adc979dc3924c7d4c4f79c43f) | nothing | none |
| Apache Iggy | SendMessages (binary protocol over TCP, QUIC and WebSocket) | server-0.9.0 | receive time only | reply header timestamp (the prepare timestamp, the same value as the batch's base_timestamp) (us, receive time) |
| Apache Iggy | HTTP POST /streams/{stream_id}/topics/{topic_id}/messages | server-0.9.0 | nothing | none |
| Fluvio | ProduceRequest | 0.18.1 | nothing | none |
| Liftbridge | Publish and PublishAsync (gRPC), or an envelope published over NATS with an ack inbox; AckPolicy LEADER or ALL | v26.01.1 (API liftbridge-api v2.0.0) | hold in the acknowledgment | Ack.receptionTimestamp (ns, receive time); Ack.commitTimestamp (set as the leader publishes the ack) (ns, send time) |
| Liftbridge | Publish, PublishAsync or a NATS envelope with AckPolicy NONE (or a unary Publish without a deadline) | v26.01.1 (API liftbridge-api v2.0.0) | no acknowledgment | none |
| Gazette | Append (gRPC client stream) | v0.103.0 | nothing | none |
| S2 (s2.dev) | append (unary POST, or an append session over S2S) | API v1 (OpenAPI 1.0.0, s2-specs commit 60dfbe3); documentation as retrieved 2026-10-27; SDK s2-sdk 0.35.2 | receive time only | AppendAck start.timestamp and end.timestamp (S2 arrival time when S2 assigns the records' timestamps) (ms, receive time, by configuration) |
| WarpStream | Kafka produce request | release v852 (21 October 2026); documentation as retrieved 2026-10-27 | nothing (unless P1) | none |
| WarpStream | HTTP produce, WarpStream-native (POST /v1/kafka/produce) | release v852 (21 October 2026); documentation as retrieved 2026-10-27 | nothing (unless P1) | none |
| WarpStream | HTTP produce, Confluent REST Proxy v2-compatible (POST /topics/{topic} and /topics/{topic}/partitions/{partition}) | release v852 (21 October 2026); documentation as retrieved 2026-10-27 | nothing | none |
| AutoMQ | Kafka produce request | 1.7.4 (built on Apache Kafka 3.9.1) | receive time only | LogAppendTimeMs (ms, store time, by configuration) |
| Tansu (Nisshi) | Kafka produce request | v0.8.0 (released as Nisshi 0.8.0) | nothing | none |
| Apache InLong TubeMQ | SendMessage RPC (synchronous and asynchronous send) | 2.4.0 | receive time only | appendTime (ms, store time) |
| Apache EventMesh | TCP asynchronous publish (ASYNC_MESSAGE_TO_SERVER) | 1.12.0 | nothing (unless P1) | none |
| Apache EventMesh | HTTP asynchronous publish, EventMesh message format | 1.12.0 | send time only | resTime (ms, send time) |
| Apache EventMesh | HTTP publish of a CloudEvent | 1.12.0 | nothing | none |
| Apache EventMesh | gRPC publish | 1.12.0 | send time only | time (attribute, protobuf Timestamp) (protobuf Timestamp (s and ns) filled from the Java clock, send time) |
| QMQ (Qunar) | send message (synchronous and asynchronous) | 1.1.3.5 | nothing | none |
| JoyQueue | JoyQueue protocol, PRODUCE_MESSAGE | 4.2.7 | nothing | none |
| DDMQ (Didi) | Thrift send (producer proxy: sendSync, sendAsync, sendBatchSync) | commit 2f30b61a5741d55a5b515f3d8d19a8a35be8c9e2 (last commit, 17 April 2020; no release or tag) | nothing | none |
| KubeMQ (community edition) | SendEvent (events and events store) | 2.3.7 | nothing | none |
| KubeMQ (community edition) | SendQueueMessage | 2.3.7 | hold in the acknowledgment | ExpirationAt and DelayedTo (deadlines computed from the receipt time) (ns, receive time, by configuration); SentAt (ns, send time) |
| RobustMQ | MQTT PUBLISH, QoS 1 and 2 | 0.4.11 | nothing | none |
| RobustMQ | MQTT PUBLISH, QoS 0 | 0.4.11 | no acknowledgment | none |
| Nakadi (Zalando) | publish (POST /event-types/{name}/events) | r3.3.9-2019-10-31 | nothing | none |
| Hermes (Allegro) | HTTP publish (POST /topics/{topic}) | 2.22.2 | nothing | none |
| Memphis | produce (JetStream publish through the Memphis SDK) | 1.4.4 | nothing | none |
| Amazon SNS | Publish and PublishBatch (Query API) | API version 2010-03-31 (botocore 1.43.120 model; developer guide retrieved 2026-10-27) | nothing | none |
| Amazon EventBridge | PutEvents | API version 2015-10-07 (botocore 1.43.120 model; user guide retrieved 2026-10-27) | nothing | none |
| AWS AppSync Events | publish (HTTP POST /event, and the WebSocket publish message) | Event API, WebSocket subprotocol aws-appsync-event-ws (developer guide retrieved 2026-10-27); Amplify JS aws-amplify@6.22.2 for the HTTP publish result | nothing | none |
| Azure Web PubSub | REST API send (to all, a group, a user or a connection) | data-plane REST API version 2024-12-01; documentation at MicrosoftDocs/azure-docs a3385323 | nothing | none |
| Azure Web PubSub | PubSub WebSocket client sendToGroup or event, with ackId | data-plane REST API version 2024-12-01; documentation at MicrosoftDocs/azure-docs a3385323 | nothing | none |
| Azure Web PubSub | MQTT 5.0 PUBLISH at QoS 1 and 2 (PUBACK; PUBREC and PUBCOMP) | data-plane REST API version 2024-12-01; documentation at MicrosoftDocs/azure-docs a3385323 | nothing | none |
| Azure Web PubSub | MQTT PUBLISH at QoS 0 | data-plane REST API version 2024-12-01; documentation at MicrosoftDocs/azure-docs a3385323 | no acknowledgment | none |
| Google Cloud Tasks | CreateTask | v2 (google.cloud.tasks.v2 API; googleapis 933dd1be) | receive time only | create_time; also schedule_time when the service set it to the current time (s (create_time, truncated to the second); us (schedule_time), store time) |
| Google Cloud Tasks | BatchCreateTasks (long-running operation) | v2 (google.cloud.tasks.v2 API; googleapis 933dd1be) | receive time only | metadata.start_time (the batch create's start); each created task's create_time in the final response (not documented (Timestamp); create_time to the second, receive time) |
| Eventarc | Publish (to a message bus, Eventarc Advanced) | Eventarc API v1 and Eventarc Publishing API v1 (googleapis 933dd1be); documentation retrieved 2026-10-27 | nothing | none |
| Eventarc | PublishEvents and PublishChannelConnectionEvents (channels for third-party providers, Eventarc Standard) | Eventarc API v1 and Eventarc Publishing API v1 (googleapis 933dd1be); documentation retrieved 2026-10-27 | nothing | none |
| Oracle Cloud Infrastructure Queue | PutMessages | Queue API 20210201; OCI Python SDK 2.189.0 | nothing (unless P1) | none |
| Oracle Cloud Infrastructure Streaming | PutMessages | Streaming API 20180418; OCI Python SDK 2.189.0 | receive time only | entries[].timestamp (not documented (RFC 3339 date-time), store time) |
| Salesforce Platform Events (Pub/Sub API and Streaming API) | Pub/Sub API Publish and PublishStream | API version 68.0, Winter '27 (developer guides last updated 9 October 2026); Pub/Sub API version 1 (forcedotcom/pub-sub-api 20fb1382) | nothing | none |
| Salesforce Platform Events (Pub/Sub API and Streaming API) | REST API (POST to the event's sObject resource) | API version 68.0, Winter '27 (developer guides last updated 9 October 2026); Pub/Sub API version 1 (forcedotcom/pub-sub-api 20fb1382) | nothing | none |
| Momento Topics | Publish (gRPC Publish; HTTP POST /topics/{cacheName}/{topicName}) | client-protos v0.138.3 (gRPC); HTTP API documentation at momentohq/public-dev-docs 385d5e2f | nothing | none |
| Alibaba Cloud Simple Message Queue (formerly Message Service, MNS) | queues: SendMessage and BatchSendMessage | HTTP API version 2015-06-06 (documentation retrieved 2026-10-27); SDK aliyun-mns-java-sdk 2.0.0 | nothing | none |
| Alibaba Cloud Simple Message Queue (formerly Message Service, MNS) | topics: PublishMessage | HTTP API version 2015-06-06 (documentation retrieved 2026-10-27); SDK aliyun-mns-java-sdk 2.0.0 | nothing | none |
| Alibaba Cloud EventBridge | PutEvents (API 2020-04-01, and the data-plane SDK's putEvents) | API version 2020-04-01 (documentation retrieved 2026-10-27); data-plane SDK alibabacloud-eventbridge-sdk at commit ccb377936d22 (no release tags) | nothing | none |
| Alibaba Cloud EventBridge | custom event source of type HTTP/HTTPS (webhook URL) | API version 2020-04-01 (documentation retrieved 2026-10-27); data-plane SDK alibabacloud-eventbridge-sdk at commit ccb377936d22 (no release tags) | nothing (unless P1, P2, P3) | none |
| Alibaba Cloud DataHub | PutRecords and PutRecordsByShard (SDK protocol) | OpenAPI version 2024-06-20 and the SDK protocol (documentation retrieved 2026-10-27); SDKs aliyun-datahub-sdk-go v1.2.1, aliyun-datahub-sdk-python v2.29.0 | nothing | none |
| Alibaba Cloud DataHub | Kafka protocol endpoint (produce) | OpenAPI version 2024-06-20 and the SDK protocol (documentation retrieved 2026-10-27); SDKs aliyun-datahub-sdk-go v1.2.1, aliyun-datahub-sdk-python v2.29.0 | nothing (unless P1, P3) | none |
| Tencent Cloud TDMQ for CMQ | HTTP data flow API: SendMessage, BatchSendMessage, PublishMessage, BatchPublishMessage | HTTP data flow API (documentation retrieved 2026-10-27); TencentCloud API 3.0, tdmq 2020-02-17; SDKs tencentcloud-cmq-sdk-go v1.0.1, tencentcloud-sdk-go v1.3.201 | nothing | none |
| Tencent Cloud TDMQ for CMQ | TencentCloud API 3.0: SendCmqMsg and PublishCmqMsg (for testing) | HTTP data flow API (documentation retrieved 2026-10-27); TencentCloud API 3.0, tdmq 2020-02-17; SDKs tencentcloud-cmq-sdk-go v1.0.1, tencentcloud-sdk-go v1.3.201 | nothing | none |
| Yandex Message Queue | SendMessage and SendMessageBatch | API version 2012-11-05 (SQS-compatible); yandex-cloud/docs at commit d6a30f68d4b5 (retrieved 2026-10-27) | nothing | none |
| Yandex Data Streams | Kinesis-compatible HTTP API: PutRecord and PutRecords | yandex-cloud/docs at commit d6a30f68d4b5 (retrieved 2026-10-27); Kinesis-compatible HTTP API; Kafka API 3.4.0 and the YDB Topic API as YDB 26.2.1.14 implements them; SQS over Topics as YDB's main branch (commit 533b58f85b1f) documents it | nothing | none |
| Yandex Data Streams | Kafka API (produce) | yandex-cloud/docs at commit d6a30f68d4b5 (retrieved 2026-10-27); Kinesis-compatible HTTP API; Kafka API 3.4.0 and the YDB Topic API as YDB 26.2.1.14 implements them; SQS over Topics as YDB's main branch (commit 533b58f85b1f) documents it | receive time only | LogAppendTimeMs (log_append_time_ms) (ms, store time) |
| Yandex Data Streams | SQS-compatible HTTP API: SendMessage and SendMessageBatch | yandex-cloud/docs at commit d6a30f68d4b5 (retrieved 2026-10-27); Kinesis-compatible HTTP API; Kafka API 3.4.0 and the YDB Topic API as YDB 26.2.1.14 implements them; SQS over Topics as YDB's main branch (commit 533b58f85b1f) documents it | nothing | none |
| Yandex Data Streams | YDB Topic API (StreamWrite) | yandex-cloud/docs at commit d6a30f68d4b5 (retrieved 2026-10-27); Kinesis-compatible HTTP API; Kafka API 3.4.0 and the YDB Topic API as YDB 26.2.1.14 implements them; SQS over Topics as YDB's main branch (commit 533b58f85b1f) documents it | nothing | none |
| Cloudflare Queues | Worker binding: send() and sendBatch() | REST API v4 and the Workers runtime API; cloudflare-docs at commit dc1a9c188094 (retrieved 2026-10-27); workerd v1.20261027.1; cloudflare-go v7.13.1 | nothing | none |
| Cloudflare Queues | HTTP API: POST .../queues/{queue_id}/messages and .../messages/batch | REST API v4 and the Workers runtime API; cloudflare-docs at commit dc1a9c188094 (retrieved 2026-10-27); workerd v1.20261027.1; cloudflare-go v7.13.1 | nothing | none |
| Upstash QStash | REST API v2: publish, enqueue and batch | REST API v2 (OpenAPI 2.0.0); upstash/docs at commit e0359103ff03 (retrieved 2026-10-27); qstash-js v2.12.1 | nothing | none |
| Vercel Queues | SendMessage (POST /api/v3/topic/{topic}) and the SDK's send() | Queues API v3 (beta; documentation retrieved 2026-10-27); SDK @vercel/queue 0.10.0 | nothing | none |
| Valkey | XADD | 9.1.3 | receive time only | entry ID time part (ms, store time, by configuration) |
| Valkey | PUBLISH / SPUBLISH | 9.1.3 | nothing | none |
| Valkey | LPUSH / RPUSH (and kin) | 9.1.3 | nothing | none |
| KeyDB | XADD | 6.3.4 | receive time only | entry ID time part (ms, store time, by configuration) |
| KeyDB | PUBLISH | 6.3.4 | nothing | none |
| KeyDB | LPUSH / RPUSH (and kin) | 6.3.4 | nothing | none |
| Dragonfly | XADD | 2.0.2 | receive time only | entry ID time part (ms, store time, by configuration) |
| Dragonfly | PUBLISH / SPUBLISH | 2.0.2 | nothing | none |
| Dragonfly | LPUSH / RPUSH (and kin) | 2.0.2 | nothing | none |
| Apache Kvrocks | XADD | 2.17.0 | receive time only | entry ID time part (ms, store time, by configuration) |
| Apache Kvrocks | PUBLISH / MPUBLISH | 2.17.0 | nothing | none |
| Apache Kvrocks | LPUSH / RPUSH (and kin) | 2.17.0 | nothing | none |
| Microsoft Garnet | PUBLISH | 2.2.4 | nothing | none |
| Microsoft Garnet | LPUSH / RPUSH (and kin) | 2.2.4 | nothing | none |
| Centrifugo | server API publish (HTTP or gRPC; broadcast likewise per channel) | 6.10.2 | nothing | none |
| Centrifugo | client-side publish (client protocol) | 6.10.2 | nothing | none |
| Mercure | publish (POST to the hub) | 1.1.5 | receive time only | update ID (urn:uuid:<UUIDv7>): its 48-bit Unix ms part and 12-bit sub-ms fraction (1/4096 ms (48-bit ms field plus a 12-bit fraction), store time, by configuration) |
| Nchan | publisher location (HTTP POST or PUT, or a message on a publisher WebSocket) | 1.3.8 | receive time only | last message id (<time>:<tag>), its time part (s, store time, by configuration) |
| Pushpin | control API publish (HTTP POST /publish/) | 1.42.0 | nothing | none |
| Pushpin | ZeroMQ publish sockets (PULL and SUB) | 1.42.0 | no acknowledgment | none |
| Supabase Realtime | WebSocket broadcast, ack off (the default) | 2.148.5 | no acknowledgment | none |
| Supabase Realtime | WebSocket broadcast, broadcast.ack true | 2.148.5 | nothing | none |
| Supabase Realtime | REST broadcast API (batch and single) | 2.148.5 | nothing | none |
| Supabase Realtime | database (realtime.send) | 2.148.5 | no acknowledgment | none |
| Ably | REST publish (POST /channels/{channelId}/messages; batch publish likewise per channel) | specification 6.3.0, realtime protocol version 6 (ably-js 2.30.0); documentation retrieved 2026-10-27 | nothing | none |
| Ably | realtime publish (ACK on the realtime connection) | specification 6.3.0, realtime protocol version 6 (ably-js 2.30.0); documentation retrieved 2026-10-27 | nothing (unless P2) | none |
| PubNub | Publish and Signal (REST) | REST API (Subscribe V2, Publish, Message Persistence) documentation retrieved 2026-10-27; JavaScript SDK 13.1.3 | receive time only | timetoken (the message's publish timetoken) (100 ns (timetoken unit), receive time) |
| Pusher Channels | HTTP API trigger (POST /apps/{app_id}/events and /batch_events) | protocol version 7; documentation retrieved 2026-10-27; pusher-js 8.6.0 | nothing | none |
| Pusher Channels | client events (WebSocket) | protocol version 7; documentation retrieved 2026-10-27; pusher-js 8.6.0 | no acknowledgment | none |
| AMQP 1.0 (OASIS standard) | sending link, unsettled deliveries (at-least-once) | 1.0 (OASIS Standard, 29 October 2012) | nothing | none |
| AMQP 1.0 (OASIS standard) | sending link, pre-settled deliveries (at-most-once) | 1.0 (OASIS Standard, 29 October 2012) | no acknowledgment | none |
| Jakarta Messaging 3.1 (JMS) | send (synchronous, or asynchronous with a CompletionListener) | 3.1 (Final Release, 25 February 2022) | nothing | none |
| STOMP 1.2 | SEND without a receipt header | 1.2 | no acknowledgment | none |
| STOMP 1.2 | SEND with a receipt header | 1.2 | nothing | none |
| XMPP (XEP-0060 publish-subscribe, XEP-0203 delayed delivery, XEP-0313 message archive) | pubsub publish (XEP-0060 7.1) | XEP-0060 1.30.0 (2025-11-11); XEP-0203 2.0 (2009-09-15); XEP-0313 1.1.3 (2025-04-09); XEP-0160 1.0.1 (2016-10-07) | nothing | none |
| XMPP (XEP-0060 publish-subscribe, XEP-0203 delayed delivery, XEP-0313 message archive) | message stanza (RFC 6120), stored offline or archived | XEP-0060 1.30.0 (2025-11-11); XEP-0203 2.0 (2009-09-15); XEP-0313 1.1.3 (2025-04-09); XEP-0160 1.0.1 (2016-10-07) | no acknowledgment | none |
| XMPP (XEP-0060 publish-subscribe, XEP-0203 delayed delivery, XEP-0313 message archive) | message stanza with stream management acknowledgments (XEP-0198) | XEP-0060 1.30.0 (2025-11-11); XEP-0203 2.0 (2009-09-15); XEP-0313 1.1.3 (2025-04-09); XEP-0160 1.0.1 (2016-10-07) | nothing | none |
| OPC UA (Part 4 subscriptions, Part 14 PubSub) | Write service (client and server) | 1.05.07 (Parts 4 and 6, 2026-04-15); 1.05.06 (Parts 5 and 14, 2025-10-22) | send time only | ResponseHeader.timestamp (100 ns (UtcTime, DateTime encoding), send time) |
| OPC UA (Part 4 subscriptions, Part 14 PubSub) | PubSub Publisher through MQTT, QoS 0 (BestEffort, AtMostOnce) | 1.05.07 (Parts 4 and 6, 2026-04-15); 1.05.06 (Parts 5 and 14, 2025-10-22) | no acknowledgment | none |
| OPC UA (Part 4 subscriptions, Part 14 PubSub) | PubSub Publisher through MQTT, QoS 1 or 2 (AtLeastOnce, ExactlyOnce) | 1.05.07 (Parts 4 and 6, 2026-04-15); 1.05.06 (Parts 5 and 14, 2025-10-22) | nothing | none |
| DDS (OMG Data Distribution Service), with RTI Connext's Persistence and Queuing Services | DataWriter write, RELIABLE (OMG DDS 1.4; RTI Connext 7.7.0) | DDS 1.4 (OMG formal/15-04-10, March 2015); RTI Connext 7.7.0 (Queuing Service User's Manual 6.0.1, its last) | nothing | none |
| DDS (OMG Data Distribution Service), with RTI Connext's Persistence and Queuing Services | QueueProducer send_sample (RTI Queuing Service) | DDS 1.4 (OMG formal/15-04-10, March 2015); RTI Connext 7.7.0 (Queuing Service User's Manual 6.0.1, its last) | nothing | none |
| Eclipse Zenoh | put (publisher or session) | 1.10.1 | no acknowledgment | none |
| WebSub (W3C Recommendation) | publisher notifies the hub (mechanism not specified) | W3C Recommendation 23 January 2018 | no acknowledgment | none |
| CloudEvents (CNCF) | HTTP request carrying an event to an intermediary | 1.0.2 | nothing | none |
| Standard Webhooks | event handed to the sender (not defined by the standard) | 1.0.0 (specification), repository release v1.0.2 | no acknowledgment | none |
| Alibaba Cloud ApsaraMQ for RocketMQ (4.x series, HTTP interface) | HTTP PublishMessage (normal, ordered, scheduled, delayed and transactional half messages) | HTTP API 2015-06-06 (documentation retrieved 2026-10-27); SDKs mq-http-java-sdk 1.0.3.2 and mq-http-go-sdk 1.0.3; OpenAPI Ons 2019-02-14 | nothing | none |
| Tencent Cloud TDMQ for RocketMQ (HTTP interface) | HTTP publishMessage | HTTP access compatible with the community HTTP SDK (documentation retrieved 2026-10-27); SDK mq-http-php-sdk 1.0.4 (HTTP API 2015-06-06); TencentCloud API tdmq 2020-02-17 (tencentcloud-sdk-go v1.3.202) | nothing | none |
| Alibaba Cloud ApsaraMQ for MQTT | MQTT PUBLISH, QoS 0 | MQTT 3.1.1 and 5.0 (documentation of the upgraded series retrieved 2026-10-27); OpenAPI OnsMqtt 2020-04-20; mqtt-server-sdk at commit 5dfe7ee71c078db7755411806c63b5864df54a1b | no acknowledgment | none |
| Alibaba Cloud ApsaraMQ for MQTT | MQTT PUBLISH, QoS 1 (PUBACK) and QoS 2 (PUBREC, PUBCOMP) | MQTT 3.1.1 and 5.0 (documentation of the upgraded series retrieved 2026-10-27); OpenAPI OnsMqtt 2020-04-20; mqtt-server-sdk at commit 5dfe7ee71c078db7755411806c63b5864df54a1b | nothing | none |
| Alibaba Cloud ApsaraMQ for MQTT | OpenAPI SendMessage (server application) | MQTT 3.1.1 and 5.0 (documentation of the upgraded series retrieved 2026-10-27); OpenAPI OnsMqtt 2020-04-20; mqtt-server-sdk at commit 5dfe7ee71c078db7755411806c63b5864df54a1b | nothing | none |
| Alibaba Cloud ApsaraMQ for MQTT | server SDK SendMessage (mqtt-server-sdk, AMQP 0-9-1 publisher confirms) | MQTT 3.1.1 and 5.0 (documentation of the upgraded series retrieved 2026-10-27); OpenAPI OnsMqtt 2020-04-20; mqtt-server-sdk at commit 5dfe7ee71c078db7755411806c63b5864df54a1b | nothing | none |
| Azure IoT Operations MQTT broker | publish at QoS 0 | documentation last updated 2026-07-31 | no acknowledgment | none |
| Azure IoT Operations MQTT broker | publish at QoS 1 | documentation last updated 2026-07-31 | nothing | none |
| comqtt | publish at QoS 0 | v2.6.7 | no acknowledgment | none |
| comqtt | publish at QoS 1 and 2 | v2.6.7 | nothing | none |
| ElasticMQ | SendMessage over the SQS-compatible HTTP API | v1.7.1 | nothing | none |
| Emitter | MQTT publish at QoS 0 | v3.1 | no acknowledgment | none |
| Emitter | MQTT publish at QoS 1 | v3.1 | nothing | none |
| gmqtt | publish at QoS 0 | v0.5.0 | no acknowledgment | none |
| gmqtt | publish at QoS 1 and 2 | v0.5.0 | nothing | none |
| Adafruit IO | MQTT publish at QoS 0 | documentation as read on 2026-10-29 | no acknowledgment | none |
| Adafruit IO | MQTT publish at QoS 1 | documentation as read on 2026-10-29 | nothing | none |
| Alibaba Cloud IoT Platform | device MQTT publish at QoS 0 or QoS 1 | documentation as read on 2026-10-29 (AMQP page last updated 5 August 2025) | nothing (unless P1, P2, P3) | none |
| Losant | MQTT publish at QoS 0 | documentation as read on 2026-10-29 (Losant MQTT broker, MQTT 3.1.1) | no acknowledgment | none |
| Losant | MQTT publish at QoS 1 (PUBACK) | documentation as read on 2026-10-29 (Losant MQTT broker, MQTT 3.1.1) | nothing | none |
| Huawei Cloud IoTDA | device HTTPS API, POST /v5/devices/{device_id}/sys/messages/up | documentation as read on 2026-10-29 (API pages updated 2026-09-30) | nothing | none |
| flespi | MQTT publish at QoS 0 | documentation as read on 2026-10-29 (flespi MQTT broker page) | no acknowledgment | none |
| flespi | MQTT publish at QoS 1 (PUBACK) | documentation as read on 2026-10-29 (flespi MQTT broker page) | nothing | none |
| OpenRemote | MQTT publish to writeattribute and writeattributevalue topics (QoS 1) | 1.33.0 | nothing | none |
| Tencent Cloud TDMQ for MQTT | MQTT publish, QoS 1 (PUBACK) | documentation as retrieved on 29 October 2026 | nothing | none |
| Tencent Cloud TDMQ for MQTT | HTTP POST publish | documentation as retrieved on 29 October 2026 | nothing | none |
| ThingLinks | MQTT PUBLISH through BifroMQ (QoS 1 and 2) | v1.4.0 | nothing | none |
| ThingLinks | downlink command published by the platform to the broker | v1.4.0 | nothing | none |
| ThingsBoard | MQTT publish of telemetry and attributes (QoS 1) | v4.4.0.1 | nothing | none |
| Thingspeak | MQTT publish to a channel (QoS 0 only) | documentation as archived by the Wayback Machine in 2025 and 2026 | no acknowledgment | none |
| Thingspeak | TalkBack add command (HTTP POST) | documentation as archived by the Wayback Machine in 2025 and 2026 | receive time only | a time (s, receive time) |
| Bevywise CrystalMQ (MQTTRoute) | MQTT publish (QoS 1 and 2) | documentation as retrieved on 29 October 2026 | nothing | none |
| Coreflux | MQTT publish, QoS 1 and 2 | documentation v2.22 as retrieved on 29 October 2026 | nothing | none |
| Coreflux | MQTT publish, QoS 0 | documentation v2.22 as retrieved on 29 October 2026 | no acknowledgment | none |
| Crossbar.io | WAMP PUBLISH with acknowledgment requested | v26_10_1 | nothing | none |
| ejabberd | MQTT PUBLISH, QoS 1 and 2 | 26.09 | nothing | none |
| ejabberd | XMPP message with stream management (XEP-0198) | 26.09 | nothing | none |
| FairCom Edge | MQTT PUBLISH, QoS 1 and 2 | documentation last updated 27 October 2026 | nothing | none |
| FairCom Edge | MQ API publishMessagesToMq (JSON API) | documentation last updated 27 October 2026 | nothing | none |
| hmq | MQTT PUBLISH, QoS 1 | v1.5.10 | nothing | none |
| hmq | MQTT PUBLISH, QoS 0 | v1.5.10 | no acknowledgment | none |
| Mochi MQTT | MQTT publish, QoS 1 and 2 | v2.7.9 | nothing | none |
| Mochi MQTT | MQTT publish, QoS 0 | v2.7.9 | no acknowledgment | none |
| Mochi MQTT | inline publish (Go call, needs Options.InlineClient) | v2.7.9 | no acknowledgment | none |
| MongooseIM | XMPP message stanza sent by a client, stream management off | 6.10.0 | no acknowledgment | none |
| MongooseIM | XMPP message stanza sent by a client, stream management on (mod_stream_management) | 6.10.0 | nothing | none |
| MQTTnet | MQTT publish, QoS 1 and 2 | v5.2.0 | nothing | none |
| MQTTnet | MQTT publish, QoS 0 | v5.2.0 | no acknowledgment | none |
| MQTTnet | in-process injection (InjectApplicationMessage) | v5.2.0 | no acknowledgment | none |
| Openfire | XMPP message stanza sent by a client, stream management off | v5.1.2 | no acknowledgment | none |
| Openfire | XMPP message stanza sent by a client, stream management on (XEP-0198) | v5.1.2 | nothing | none |
| Oracle Java CAPS JMS IQ Manager | JMS send (queue sender or topic publisher) | Java CAPS 6 documentation (JMS Reference 820-2239) | no acknowledgment | none |
| Oracle Tuxedo /Q | tpenqueue | Oracle Tuxedo 12c Release 2 (12.2.2) | nothing | none |
| rocketmq-rust | send message (synchronous and asynchronous) | v1.0.0 | nothing | none |
| Rumqttd | MQTT publish, QoS 1 and 2 | rumqttd-0.20.0 | nothing | none |
| Rumqttd | MQTT publish, QoS 0 | rumqttd-0.20.0 | no acknowledgment | none |
| SAP NetWeaver JMS provider | JMS send (queue sender or topic publisher) | SAP NetWeaver AS Java 7.4 (SAP Library saphelp_nw74, 7.4.16) | no acknowledgment | none |
| Semantik | publish (POST /v1/publish) | hosted service, documentation and Go SDK commit 24d4313a376ac35fe30b89fb7125a2d9c6740e24 as read on 2026-10-29 | nothing | none |
| SmoothMQ | SQS SendMessage and SendMessageBatch | v0.2.3 | receive time only | a time (ms, receive time) |
| ZeroC IceStorm | publisher proxy (invoke a void operation on the topic's publisher object) | v3.8.3 | nothing | none |
| Azurite | Put Message | v3.37.0 | receive time only | InsertionTime (s, receive time) |
| Backendless | Messaging.publish (REST POST to the channel) | service documentation as retrieved 2026-10-29; JavaScript SDK v7.4.8 | nothing | none |
| FAA NAS Enterprise Messaging Service (NEMS) | JMS publish by a SWIM producer | SWIM Timestamp and Message Sequence Number Policy, version 1.0 (29 September 2025) | nothing (unless P1, P2, P3) | none |
| Google App Engine Task Queue | Queue.add (task added by the application) | documentation last updated 2026-10-26 UTC | nothing | none |
| MyQttHub | REST API publish (POST /publish) | ReactiveMyQtt v6.7.764 (REST API documentation, retrieved 2026-10-29) | nothing | none |
| MyQttHub | MQTT publish, QoS 1 and 2 | ReactiveMyQtt v6.7.764 (REST API documentation, retrieved 2026-10-29) | nothing | none |
| MyQttHub | MQTT publish, QoS 0 | ReactiveMyQtt v6.7.764 (REST API documentation, retrieved 2026-10-29) | no acknowledgment | none |
| OCI Notifications | PublishMessage (REST API and SDKs) | service documentation as retrieved 2026-10-29; OCI Go SDK v65.128.0 | nothing (unless P1) | none |
| Oracle Messaging Cloud Service | REST send (POST /producers/{producerName}/messages) | Using Oracle Messaging Cloud Service, E37257-26, May 2020 (Cloud Classic Infrastructure documentation) | nothing (unless P1) | none |
| ROMA Connect | RESTful production API | documentation updated 2025-07-21 | nothing | none |
| Simple Message Notification (SMN) | publish message API | documentation updated 2025-04-02 | nothing | none |
| Xiaomi Galaxy EMQ | SendMessage | EMQ SDK 1.3.6 (galaxy-sdk-java commit 97952feb, 2020-01-09) | nothing (unless P1) | none |
| Zapier Trigger Inbox | event from a connected app (no publish call) | Trigger Inbox API 1.0.0 (OpenAPI spec) | no acknowledgment | none |
| AnyHook | inbound URL (POST from the sender) | API v1 (documentation read 2026-10-29) | nothing | none |
| Hook0 | ingest an event (POST /event) | API 1.0.2 (tag api/v1.0.2) and output worker 1.0.7 (tag output-worker/v1.0.7) | receive time only | received_at (us, store time) |
| Hookdeck Outpost | publish API (POST /publish) | v1.7.0 | nothing | none |
| HookDeploy | capture endpoint (POST from the sender) | API v1 (documentation read 2026-10-29) | nothing | none |
| Posthook | schedule hook (POST /v1/hooks) | hosted service, API v1 (documentation read 2026-10-29) | receive time only | createdAt (s, receive time) |
| SuaveHooks | capture endpoint (POST to the endpoint URL on ingest.suavehooks.com) | hosted service, REST API v1 (documentation read 2026-10-29) | nothing | none |
| Vartiq | send message (webhook message create, API) | hosted service (documentation read 2026-10-29) | receive time only (unless P2) | data.webhookMessage.createdAt (not stated, receive time) |
| Webhook Studio | capture endpoint (any HTTP request to /e/<slug>) | hosted service, /v1 API (documentation read 2026-10-29) | nothing | none |
| Zeplo | enqueue (POST /queues/enqueue) | Zeplo v2 (documentation read 2026-10-29) | receive time only | queuedAt (s, store time) |
| Amazon Chime SDK (messaging) | SendChannelMessage | hosted service (API reference and developer guide read 2026-10-29) | nothing | none |
| AnyCable | HTTP broadcast (POST /_broadcast) | v1.6.20 | nothing | none |
| Azure Communication Services (chat) | SendChatMessage (REST) | hosted service, Chat REST API version 2025-03-15 (documentation read 2026-10-29) | nothing | none |
| Azure Fluid Relay | op submission (submit on the delta connection) | hosted service; protocol definitions of FluidFramework client_v3.7.0 | receive time only (unless P2) | timestamp (not stated, receive time) |
| Beaver | HTTP publish and broadcast actions | v1.5.0 | nothing | none |
| deepstream.io | event emit | v10.2.4 | no acknowledgment | none |
| Faye | publish (Bayeux message on a non-meta channel) | 1.4.3 | nothing | none |
| Gotify | POST /message | v3.1.1 | receive time only | date (ns (the documented example has seven fractional digits), receive time) |
| Kuzzle | realtime:publish | v2.60.1 | nothing | none |
| Lightstreamer | data adapter update (in-process adapter SDK) | v7.4.9 | no acknowledgment | none |
| Lightstreamer | client upstream message (MSG request) | v7.4.9 | nothing | none |
| Liveblocks | broadcast event (REST API and Node SDK) | v3.24.5 | no acknowledgment | none |
| Liveblocks | create feed message (REST API and Node SDK) | v3.24.5 | receive time only | createdAt (ms, receive time, by configuration) |
| MigratoryData | publish (client API) | 6.0.24 | nothing | none |
| ntfy | publish (HTTP PUT or POST, or JSON publish) | v2.34.0 | receive time only | time (s, receive time, by configuration) |
| Poxa | REST API (POST /apps/:app_id/events) | v1.3.0 | nothing | none |
| Poxa | client event over the WebSocket | v1.3.0 | no acknowledgment | none |
| Soketi | REST API (POST /apps/{appId}/events) | 1.6.1 | nothing | none |
| Soketi | client event over the WebSocket | 1.6.1 | no acknowledgment | none |
| Apache Fluss | append writer (AppendWriter.append) | v1.0.0 | nothing | none |
| Cloudflare K2 | HTTP produce (POST /produce on the stream endpoint) | public beta, documentation read on 29 October 2026 | nothing | none |
| Cloudflare K2 | Workers binding send() | public beta, documentation read on 29 October 2026 | nothing | none |
| Data Ingestion Service (DIS) | upload records (POST /v2/{project_id}/records) | API v2, documentation read on 29 October 2026 | nothing | none |
| Jocko | produce (Kafka protocol) | 0.0.1 | receive time only | Timestamp (s, store time) |
| Vanus | publish (gateway gRPC Publish or CloudEvents HTTP) | v0.9.0 | nothing | none |
| Walrus | PUT over the TCP client protocol | v0.3.0 | nothing | none |
| KurrentDB (EventStoreDB) | append (Streams.Append) | v26.2.3 | nothing | none |
| Message DB | write_message (SQL function) | v1.3.0 | nothing | none |
| MongoDB change streams | insert (write command with a write concern) | r9.0.4 | nothing (unless P1, P2) | none |
| PgQue | send (pgque.send SQL function) | v0.2.2 | nothing | none |
| PostgreSQL LISTEN/NOTIFY | NOTIFY command | REL_18_6 | nothing | none |
| PostgreSQL LISTEN/NOTIFY | pg_notify function | REL_18_6 | nothing | none |
| Hatchet | gRPC TriggerWorkflowRun | v0.114.2 | nothing | none |
| Hatchet | gRPC EventsService.Push | v0.114.2 | receive time only | a time (ns, receive time) |
| AMQP 0-9-1 | basic.publish | 0-9-1 | no acknowledgment | none |
| AMQP 0-9-1 | publish in a transaction (tx.commit) | 0-9-1 | nothing | none |
| Durable Streams | append (POST) | v0.3.0 (protocol draft 1.0) | nothing | none |
| MQTT-SN | PUBLISH with QoS 0 or -1 | 1.2 | no acknowledgment | none |
| MQTT-SN | PUBLISH with QoS 1 or 2 (PUBACK) | 1.2 | nothing | none |
| OpenMessaging | Producer.send | 2.1.0-pubsub | nothing | none |
| OpenMessaging | Producer.sendOneway | 2.1.0-pubsub | no acknowledgment | none |
| WAMP | PUBLISH (unacknowledged, the default) | Internet-Draft published 3 July 2026 | no acknowledgment | none |
| WAMP | PUBLISH with acknowledge = true (PUBLISHED) | Internet-Draft published 3 July 2026 | nothing | none |
| WS-Notification (WS-BrokeredNotification) | Notify to a NotificationBroker (one way) | 1.3 (OASIS Standard, 1 October 2006) | no acknowledgment | none |
| Fireworq | POST /job/{category} | v1.5.0 | nothing | none |
