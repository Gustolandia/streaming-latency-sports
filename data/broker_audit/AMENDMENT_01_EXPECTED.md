# What we expected from amendment 1, before any search

Written 27 October 2026 with [`AMENDMENT_01.md`](AMENDMENT_01.md), before any search under it was
run and before any record under it was coded. It is written from what the author knew. The auditors
do not read it until the records are coded. Where the audit finds otherwise, the expectation is
reported as wrong, beside what was found.

## Overall

- **No broker the search finds delivers the time the request or credit that took a message
  arrived.** So no broker delivers the wait itself.
- **A few more brokers deliver a stay.** All of them in milliseconds or coarser, except PGMQ, in
  microseconds.
- **Many brokers keep a request's arrival or a send time and do not send it.**
- **No broker puts both its receive time and its send time in a publish acknowledgment.** So no
  producer can take the broker's hold out of its round trip without a clock shared with the broker.
- **The size of the search.** Between 150 and 300 products found; between 100 and 200 coded after
  duplicates, copies and exclusions.

## Brokers we expect to deliver a stay, or the parts of one

- **Apache EventMesh.** Timestamps in each event's extensions (ms), set as the event passes through
  EventMesh. Among them is the time EventMesh sent the event to the consumer. So: a stay.
- **IBM MQ.** Two things, both delivered:
  - the put date and time, set by the queue manager, in hundredths of a second;
  - the expiry, which the queue manager reduces by the message's time on the queue, in tenths of a
    second.
  So a derivable stay, for messages put with an expiry.
- **Alibaba Cloud's Simple Message Queue (MNS) and Tencent's CMQ.** The enqueue time, the first
  dequeue time and the next visible time (ms), delivered. So a stay like SQS's, but for every
  receive: the next visible time, less the visibility timeout, is the receive's time.
- **Yandex Message Queue.** SQS's attributes (ms), for SQS's reason.
- **Oracle Cloud Infrastructure Queue.** The time a received message becomes visible again (ms). So
  a derivable stay, if the documentation states that the visibility timeout counts from the receive.
- **PGMQ.** The enqueue time, and the visibility time set at the read, in microseconds. So a
  derivable stay.
- **AMQP 1.0.** The standard asks (SHOULD) an intermediary to reduce a message's ttl by the
  message's time there, in ms. We expect few brokers to do it.
- **OPC UA subscriptions.** The server's timestamp of a value, and the notification's publish time,
  both on the server's clock, in units of 100 ns. So a stay. An OPC UA server is not a broker in the
  usual sense.
- **Webhook services that follow Standard Webhooks (Svix among them).** A timestamp of each delivery
  attempt, to the second, beside the event's creation time. So a stay, to the second.

## Brokers we expect to deliver only the arrival

- **60East AMPS:** the time AMPS processed the message, when the subscriber asks for it.
- **Apache Iggy:** a server timestamp, in microseconds.
- **Eclipse Zenoh:** a hybrid logical clock timestamp, set by the first router.
- **PubNub:** a timetoken, in units of 100 ns. **Ably:** a timestamp, in ms.
- **Nakadi:** the received time, in ms.
- **Azure IoT Hub:** the enqueued time, in ms.
- **Oracle Advanced Queuing and SQL Server Service Broker:** the enqueue time.
- **MSMQ:** the arrived time and the sent time, to the second.
- **Salesforce's Platform Events:** the created date.
- **Amazon SNS:** the notification's timestamp.
- **XMPP:** a delay stamp on a stored message.
- **Faktory:** the enqueued time.
- **The KX kdb+ tickerplant:** a time column added at receipt, in nanoseconds.
- **Bloomberg's BlazingMQ:** we are unsure. We expect an id that holds a timer tick, which is not a
  wall-clock time.

## Brokers we expect to deliver no broker time

- Mosquitto and the other MQTT 5.0 brokers, beyond the standard's expiry.
- Beanstalkd: a job's age only through a separate command, to the second.
- Gearman, Pusher, Mercure and Centrifugo.
- Redis's relatives, which follow Redis.

## Requests that wait

- IBM MQ's get with wait, AMPS's subscriptions, MQTT's subscriptions and most real-time services:
  standing, or credit.
- The cloud queues that long-poll: one request at a time per connection, or several.

## The producer's side

- **Kafka:** the produce response carries the log append time when the topic uses LogAppendTime
  (ms). So a receive time, by configuration.
- **Redis:** XADD returns the entry id, whose millisecond part is the server's time when the server
  makes the id.
- **PubNub:** the publish response carries the message's timetoken. So a receive time.
- **Azure Queue Storage:** the response to Put Message carries the insertion time, to the second.
- **No time in the acknowledgment:** NATS JetStream, RabbitMQ, Pulsar, SQS, Pub/Sub, Kinesis,
  Service Bus, Event Hubs, and MQTT.

## The precedents

- **NTP, ICMP Timestamp, TWAMP and STAMP:** the far end's receive and send times.
- **RTCP's receiver reports:** the delay since the last sender report.
- **SIP's Timestamp header:** the far end's delay, which it may add.
- **QUIC's ACK Delay:** how long the receiver held an acknowledgment.
- **HTTP's Server-Timing:** a server's durations.
- **Web routers' request-start header:** the router's receive time.
- **Eurex's T7 order-entry responses:** the gateway's receive and send times, in nanoseconds.
- **CME's market data:** the match time and the gateway's send time, in nanoseconds.
- **DDS and ROS 2:** a reader gets the source and the receive timestamps.
