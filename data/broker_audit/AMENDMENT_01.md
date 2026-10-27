# Amendment 1 to the broker audit: a wide search for brokers, and the producer's side

Written 27 October 2026, after the first 23 brokers were coded, and before any search or record
under this amendment. [`PROTOCOL.md`](PROTOCOL.md) is unchanged. Everything it says holds here
unless this amendment says otherwise. Like the protocol, this amendment reads documentation,
specifications and source code only. No machine is used.

**Why.** The protocol coded the brokers the industry's tools time and the three largest clouds' own
message services: 23 brokers and 41 consumer interfaces. A broker that no tool times may still send
the times the split needs. This amendment widens the audit in two ways.
- **Every broker a documented search can find.** The search runs two routes. One lists brokers. The
  other looks for the times themselves.
- **The producer's side.** A producer can time the round trip of each publish, from its send to the
  broker's acknowledgment. Suppose the acknowledgment carries the time the broker received the
  request and the time it sent the acknowledgment. Then the producer can take the broker's hold out
  of the round trip without sharing a clock with the broker. An NTP client does exactly this with a
  server's receive and transmit times.

## Words used here

- **Acknowledgment:** the broker's reply to a publish, saying that it has the message.
- **Hold:** the time from the broker receiving a publish request to its sending the acknowledgment.
- **Copy:** a hosted service or packaged distribution of a broker that is coded on its own (Amazon
  MSK is a copy of Apache Kafka).
- **Precedent:** a protocol outside the brokers that tells a client the far end's receive and send
  times, or its hold.

## What counts as a broker

**In.** A product or project, open or closed, that keeps messages from producers and delivers them
to consumers, and documents what a consumer receives. It may be a service of its own or a documented
feature of a database server. This covers:
- message brokers and queue servers, among them JMS providers and MQTT, AMQP and STOMP brokers;
- log and streaming platforms;
- the queue, publish-subscribe, event-bus, task and streaming services of any cloud;
- real-time publish-subscribe services and hubs (WebSocket, long polling, server-sent events);
- webhook delivery services, which hold an event and push it to a consumer's endpoint;
- job-queue servers;
- queues built into database servers;
- IoT and industrial hubs that hold messages for consumers.

**Standards.** A standard that fixes what a message may carry is coded as a broker of its own, as
MQTT 5.0 was. A broker that implements a coded standard is still coded, since it may add fields.

**Copies.** A copy is listed, and its own documentation is searched for a field it delivers that the
broker it copies does not. It is coded only if it has one.

**Archived projects.** An archived open-source broker whose source is still public is in. It is coded
at its last release and marked archived.

**Out.** Each is recorded with its reason.
- Client libraries and frameworks that run over a broker or a database (Celery, Sidekiq, BullMQ,
  pg-boss, Spring Cloud Stream, MassTransit).
- Brokerless messaging libraries (ZeroMQ, NNG, Aeron's transport, the LMAX Disruptor). One that
  gives a reader a receive or send time is recorded among the precedents.
- Proxies and routers that hold no message.
- Notification services that deliver to a device's operating system (Apple's push notification
  service, Firebase Cloud Messaging, Web Push).
- Stream processors and workflow engines.
- Services shut down by the coding date.
- Products whose documentation of the delivered fields is not public, or is behind a login or a
  paywall.

**Modes and producers.** Each consumer interface is coded as a mode, as before. Each producer
interface is coded as a producer, under the questions below. Examples: Kafka's produce request;
RabbitMQ's publisher confirms; a JetStream publish; an MQTT publish at QoS 0, 1 or 2.

## How brokers are found

**Route 1: listing brokers.** Every source below is searched.
1. **The seed list** in this amendment, written from what the author knew before any search.
2. **Reference lists.**
   - Wikipedia's articles on message-oriented middleware, message brokers, message queues, AMQP,
     MQTT and its comparison of implementations, STOMP, Jakarta Messaging, DDS and XMPP.
   - mqtt.org's list of software, and the STOMP implementations page.
   - The CNCF landscape's streaming and messaging category, and the Apache Software Foundation's
     projects in messaging.
   - GitHub awesome lists on messaging, streaming, MQTT, Kafka and queues.
3. **Code hosts.** The GitHub topics `message-broker`, `message-queue`, `mqtt-broker`, `pubsub`,
   `event-streaming`, `streaming-platform` and `job-queue`, each read down to 500 stars.
4. **Catalogs.**
   - The product catalogs of Amazon Web Services, Microsoft Azure, Google Cloud, Alibaba Cloud,
     Tencent Cloud, Huawei Cloud, Oracle Cloud, IBM Cloud, Yandex Cloud and Cloudflare.
   - Review and analyst categories: G2's message queue software, Gartner Peer Insights' event
     stream processing and message-oriented middleware, and StackShare's message queues.
5. **Communities.** Reddit, Hacker News and Stack Overflow, by site-restricted web searches and by
   each site's own search: threads that compare, recommend or announce brokers.

**Route 2: looking for the times.** These searches look for the times themselves, in documentation,
specifications, issue trackers and forums.
- **Terms.** Among them: dequeue time, delivery time or timestamp, sent time, first receive, time in
  queue, queue time, dwell time, residence time, sojourn time, request received time, broker-out
  time, and acknowledgment timestamp. Each is searched with broker, queue, message, publish or
  subscribe.
- **Requests.** What users have asked brokers to add: Kafka's KIPs, Pulsar's PIPs, and the issue
  trackers and discussions of the brokers coded.
- **What a hit adds.** Each broker a hit names joins the population if it meets the rule above.

**Community sources find brokers. They never answer a question.** Every answer rests on the broker's
own documentation, specification or source code, under the protocol's evidence rules.

**The search's record.** Each search records its date, route, source and query, and the brokers it
surfaced. The audit reports how many brokers each stage kept: found, duplicates, out (by reason),
copies, and coded.

**When the search stops.**
- Route 1 stops when every source above has been read.
- Route 2 stops when ten new queries in a row surface no broker that is not already listed.

## The seed list

Written before any search. Brokers already coded are not repeated.
- **Enterprise and JMS.** IBM MQ; WebSphere's default messaging provider (the service integration
  bus); TIBCO Enterprise Message Service; Solace PubSub+; webMethods Universal Messaging; Oracle
  WebLogic JMS; Apache Qpid Broker-J; the Apache Qpid C++ broker; JORAM; Eclipse OpenMQ; SwiftMQ;
  LavinMQ; Fiorano MQ; Aurea SonicMQ; MuleSoft Anypoint MQ; SAP Event Mesh and SAP Integration
  Suite's advanced event mesh; IronMQ.
- **Queues in databases, job-queue servers, and webhook services.** Oracle Advanced Queuing and
  Transactional Event Queues; SQL Server Service Broker; Microsoft Message Queuing (MSMQ); PGMQ and
  Supabase Queues; Beanstalkd; Faktory; Gearman; Svix; Hookdeck; Convoy.
- **Finance, low latency and data grids.** 60East AMPS; Informatica Ultra Messaging; Bloomberg's
  BlazingMQ; Aeron Archive and Aeron Cluster; Chronicle Queue; the KX kdb+ tickerplant; TIBCO FTL;
  TIBCO Rendezvous; the LSEG Real-Time Distribution System; Hazelcast; Oracle Coherence's topics;
  Apache Ignite's messaging.
- **MQTT brokers and IoT hubs.** Eclipse Mosquitto; HiveMQ; VerneMQ; NanoMQ; Apache BifroMQ; RMQTT;
  FlashMQ; Moquette; Aedes; Eclipse Amlen; TBMQ; Waterstream; AWS IoT Core; Azure IoT Hub; Azure
  Event Grid's MQTT broker; Alibaba Cloud's ApsaraMQ for MQTT; Eclipse Hono.
- **Logs and streaming.** Apache Iggy; Fluvio; Liftbridge; Gazette; S2; WarpStream; AutoMQ;
  Bufstream; Tansu; StreamNative Ursa; Apache InLong's TubeMQ; Apache EventMesh; QMQ; JoyQueue;
  DDMQ; KubeMQ; RobustMQ; Nakadi; Hermes; Memphis.
- **Cloud services.**
  - Amazon SNS; Amazon EventBridge; AWS AppSync Events.
  - Azure Web PubSub.
  - Google Cloud Tasks; Eventarc.
  - Oracle Cloud Infrastructure's Queue and Streaming.
  - Salesforce's Platform Events and Pub/Sub API; Momento Topics.
  - Alibaba Cloud's Simple Message Queue (formerly MNS), EventBridge and DataHub.
  - Tencent Cloud's TDMQ, CMQ edition.
  - Yandex Message Queue and Yandex Data Streams.
  - Cloudflare Queues; Upstash QStash; Vercel Queues.
- **Real-time services and Redis's relatives.** Ably; PubNub; Pusher Channels; Centrifugo; Mercure;
  Nchan; Pushpin; Supabase Realtime; Valkey; KeyDB; Dragonfly; Apache Kvrocks; Microsoft Garnet.
- **Standards and routed systems.** AMQP 1.0; Jakarta Messaging; STOMP 1.2; XMPP (XEP-0060,
  XEP-0203, XEP-0313); OPC UA (subscriptions in Part 4, PubSub in Part 14); DDS, with RTI Connext's
  queuing, persistence and routing services; Eclipse Zenoh; WebSub; CloudEvents; Standard Webhooks.
- **Copies, to be searched for extra fields.** Confluent Platform and Confluent Cloud; Amazon MSK;
  Amazon MQ; Aiven; Instaclustr; IBM Event Streams; Google Cloud's Managed Service for Apache Kafka;
  CloudAMQP; Synadia Cloud; StreamNative Cloud; DataStax Astra Streaming; Redis Cloud; EMQX Cloud;
  HiveMQ Cloud; Tencent Cloud's CKafka; Huawei Cloud's DMS; Alibaba Cloud's ApsaraMQ for Kafka,
  RocketMQ and RabbitMQ.

## The producer's questions

Asked of each producer interface of every broker, the 23 already coded included.
- **The 23 brokers' answers to Q0 to Q7 stand.** An answer an auditor finds wrong is reported as a
  correction, with its evidence. It is never changed silently.

The questions:
- **P0. What the producer receives.** Whether the interface acknowledges a publish at all, and the
  complete list of fields in the acknowledgment, from the protocol's definition or the client's
  result class.
- **P1. Receive time.** Does the acknowledgment carry the time the broker received the publish
  request, or stored the message, by its own clock?
  - `always`;
  - `by configuration`: name the setting, and say whether it is off by default;
  - `no`;
  - `not applicable`: the interface has no acknowledgment.
  - Recorded with it: the field, its resolution, and which of the two times it is.
- **P2. Send time.** Does the acknowledgment carry the time the broker sent it? The same answers.
- **P3. A duration.** Does the acknowledgment carry a duration the broker measured on its own clock
  that contains its hold of the request?
  - `hold`;
  - `derivable hold`: computable, by a rule the documentation states, from fields in the
    acknowledgment that the broker set on one clock;
  - `no`;
  - `not applicable`: the interface has no acknowledgment.

Any of P1 to P3 the sources do not settle is `not determined`, with what was searched.

**The producer's verdict.** It is computed by `scripts/broker_audit.py` and never stored.
- **Hold in the acknowledgment.** P1 and P2 both give a time, or P3 is `hold` or `derivable hold`.
  The producer can take the broker's hold out of its round trip without a shared clock.
- **Receive time only**, or **send time only.** One time on the broker's clock. The split needs a
  clock shared with the broker.
- **Nothing.** The acknowledgment carries no broker time.
- **No acknowledgment.**

## Depth for the new brokers

Every question, Q0 to Q7 and P0 to P3, is asked of every new broker.
- Q0 and P0 must be complete.
- Q6 and Q7 may be `not determined` after a search of the broker's own documentation. The answer
  records what was searched.

## Read-backs

The protocol's read-backs extend to the producer's rare answers: every P1 or P2 that gives a time,
and every P3 of `hold` or `derivable hold`. Each rare answer of a broker coded under this amendment
is read back by an auditor other than the one who coded it.

## The precedents

Some protocols outside the brokers tell a client the far end's receive and send times, or its hold.
With them, the far end's part can be taken out of a round trip.
- **How they are recorded.** Under the protocol's evidence rules, as context for what brokers could
  do. They are not counted among the brokers.
- **The seed.** NTP; ICMP Timestamp; RTCP's receiver reports; SIP's Timestamp header; TWAMP and
  STAMP; QUIC's ACK Delay; HTTP's Server-Timing; the request-start header of web routers; the
  order-entry and market-data timestamps of trading venues; the source and receive timestamps that
  DDS and ROS 2 give a reader.

## The records

- **New brokers** go to `data/broker_audit/batch_05.json` onward, in the protocol's form, with three
  more keys:
  - `"group": "C"`;
  - `kind`, one of: `broker`, `streaming platform`, `cloud service`, `real-time service`, `webhook
    service`, `job-queue server`, `database queue`, `IoT hub`, `standard`;
  - `found_by`, a list of the searches that surfaced it, each with `route`, `source` and `query`.
- **The 23 brokers already coded** get their producers in their existing batch files. Nothing else
  in those records changes, except a correction reported as one.
- **Every broker** has a `producers` list. A producer has this form:

```json
{"interface": "produce request",
 "P0": {"acknowledgment": true, "fields": ["..."], "evidence": ["..."]},
 "P1": {"answer": "by configuration", "field": "...", "resolution": "ms", "which": "store time",
        "setting": "...", "default_on": false, "evidence": ["..."], "note": "..."},
 "P2": {"answer": "no", "evidence": ["..."]},
 "P3": {"answer": "no", "evidence": ["..."]},
 "not_determined": [],
 "read_back": []}
```

Each `"..."` in an `evidence` list stands for an item of the form `{"url": "...", "quote": "..."}`.
Every answer except `not applicable` carries at least one. P0 carries evidence even when there is
no acknowledgment.

- **The search's record** goes to `data/broker_audit/search_log.json`, one entry per search.
- **The population** goes to `data/broker_audit/candidates.json`, one entry per product found, with
  the decision and its reason.
- **The precedents** go to `data/broker_audit/precedents.json`, each with the fields it sends and
  its evidence.
- **Evidence from a PDF** is allowed when the PDF is the primary source. The fetch-back reads the
  PDF's text.

## What we expected

Written with this amendment, in [`AMENDMENT_01_EXPECTED.md`](AMENDMENT_01_EXPECTED.md), and
registered with it. The auditors do not read it until the records are coded. Where the audit finds
otherwise, the expectation is reported as wrong, beside what was found.
