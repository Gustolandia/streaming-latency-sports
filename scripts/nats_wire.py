#!/usr/bin/env python3
"""
nats_wire.py -- the NATS client protocol, and the few JetStream requests block N's clients make, as
functions over bytes: the frames each side writes, a splitter that says where the next frame ends,
the replies read back, and the stream sequence read out of a delivered message's reply subject.

Block N runs a JetStream pull consumer (scripts/nats_consumer.py) against a producer that publishes
through JetStream (scripts/nats_producer.py). No NATS library is used, as in
scripts/nats_reference.py: nothing stands between the socket and the clients' own stamps but what is
here. A reader of a packet capture taken on the client host reads the same bytes with the same
functions, so that a message is found there as the clients find it: by the broker's own number for
it, the stream sequence, and never by anything in its payload.

The protocol is lines ending CRLF. The client says CONNECT, PUB, HPUB (a publish with headers), SUB,
UNSUB, PING and PONG; the server says INFO on connect, MSG, HMSG (a delivery with headers), PING,
PONG, +OK and -ERR. A publish and a delivery carry a payload after their line, and the line's last
number is its size, headers included.

JetStream is reached by ordinary publishes to subjects under $JS.API, each with a reply subject the
answer comes back to:

  $JS.API.STREAM.CREATE.<stream>                 the stream; asked again with the same
                                                 configuration, the answer is the stream as it is
  $JS.API.CONSUMER.CREATE.<stream>.<consumer>    a durable pull consumer, made or left as it is
  $JS.API.CONSUMER.MSG.NEXT.<stream>.<consumer>  a pull request, {"batch":1,"expires":<ns>}

A publish to the stream's subject with a reply subject is answered there with its acknowledgment,
{"stream":...,"seq":N}. A message delivered for a pull request comes on the subscription that takes
the request's reply subject, but under the subject the message was published to: nats-server finds
the subscription by one subject and writes the delivery with another. So a delivery names no
request. Each request asks for one message, and with the server's default priority policy a
consumer's requests are served oldest first, its deliveries and statuses going out in the order the
server dispatches them: each delivery answers the oldest request still waiting. The delivery's own
reply subject, under $JS.ACK, names its stream sequence, and the consumer publishes +ACK to it. A
request that ends without a message is answered at its reply subject by a status message, headers
alone whose first line carries a code, with no reply subject: 408 when it expired.

Link, at the end, is one connection to the server: frames read whole, the server's PINGs answered,
and, when asked, each read taking exactly one frame, so that the kernel's receive timestamp of a
read (scripts/so_timestamps.py) is one message's own.
"""
import collections
import json
import os
import re
import socket
import struct
import threading

CRLF = b"\r\n"
PORT = 4222
PING = b"PING\r\n"
PONG = b"PONG\r\n"
#: This client's version, as its CONNECT reports it.
VERSION = "1"

#: The operations whose line is followed by a payload, the line's last argument being its size.
PAYLOAD_OPS = (b"MSG", b"HMSG", b"PUB", b"HPUB")
#: More bytes than any line the server sends; this many with no end of line is not the protocol.
MAX_CONTROL_LINE = 1 << 16
HEADER_VERSION = b"NATS/1.0"

#: The status codes a pull request is answered with, as nats-server writes them: an idle heartbeat,
#: no messages (for a request that asked not to wait), the request expired, the request refused or
#: ended (409, its description saying which), and no one listening on the subject.
HEARTBEAT, NO_MESSAGES, REQUEST_TIMEOUT, CONFLICT, NO_RESPONDERS = 100, 404, 408, 409, 503
#: JetStream's error code for a stream asked for again with another configuration.
STREAM_IN_USE = 10058

#: The durable consumer's limits. The pull consumer keeps --depth requests waiting, and the server
#: refuses a request beyond max_waiting (409 Exceeded MaxWaiting), so max_waiting is four times the
#: depth and never below 512, the server's own default (max_waiting_for, below): at least twice the
#: depth, as the design asks, so that depth 256 has 1,024. max_ack_pending is above any run's
#: message count, so that delivery never waits on an acknowledgment still on its way.
MAX_WAITING = 512
WAITING_PER_DEPTH = 4
MAX_ACK_PENDING = 1000000
STORAGE = ("file", "memory")

#: The longest a read waits in the kernel before it comes back empty-handed (SO_RCVTIMEO), so that
#: a loop can look at its clock; and how many such waits a request's answer is given.
WAIT_S = 0.25
REPLY_WAITS = 40
CONNECT_S = 5.0
#: A one-reply read first peeks this much: more than a control line and a typical message, and few
#: enough that a backlog is not copied whole for every frame taken from it.
PEEK_BYTES = 4096
READ_BYTES = 65536
#: Linux's; this module's clients run on Linux, and the tests stand in for the socket.
MSG_DONTWAIT = getattr(socket, "MSG_DONTWAIT", 0x40)
#: The subscription a Link's own requests are answered on; the clients number theirs from 2.
REQUEST_SID = 1


class ProtocolError(ValueError):
    """Bytes that are not the NATS protocol: the stream has lost its place, and nothing after
    them can be trusted to be read where it begins."""


class Closed(OSError):
    """The server closed the connection."""


class ServerError(OSError):
    """The server said -ERR."""


class NoReply(OSError):
    """A request the server did not answer within the waits it was given."""


class JetStreamError(RuntimeError):
    """JetStream's answer was an error, or a status message where an answer was due: its code
    (HTTP-like), its own error code where it gave one, and its description."""

    def __init__(self, code, err_code, description):
        RuntimeError.__init__(self, "%s (code %s, err_code %s)" % (description, code, err_code))
        self.code = code
        self.err_code = err_code
        self.description = description


# --- what the client writes ---------------------------------------------------------------------

def _json(value):
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _then(word):
    """`word` and a space, or nothing: an optional argument in a protocol line."""
    return "%s " % word if word else ""


def connect(name):
    """CONNECT, with headers on (JetStream's status messages are headers) and no_responders on, so
    that a request to a subject nobody listens on is answered at once by a 503 rather than never."""
    options = {"verbose": False, "pedantic": False, "tls_required": False, "name": name,
               "lang": "python", "version": VERSION, "protocol": 1, "echo": True,
               "headers": True, "no_responders": True}
    return b"CONNECT " + _json(options) + CRLF


def pub(subject, payload, reply=None):
    """PUB <subject> [reply] <size>, and the payload."""
    return (("PUB %s %s%d\r\n" % (subject, _then(reply), len(payload))).encode("utf-8")
            + payload + CRLF)


def hpub(subject, headers, payload, reply=None):
    """HPUB <subject> [reply] <header size> <total size>, the header block, and the payload."""
    return (("HPUB %s %s%d %d\r\n" % (subject, _then(reply), len(headers),
                                       len(headers) + len(payload))).encode("utf-8")
            + headers + payload + CRLF)


def header_block(fields=(), status=None):
    """A header block: NATS/1.0, a status code and its description when `status` is one, a line
    for each (name, value), and the empty line that ends it."""
    first = HEADER_VERSION
    if status is not None:
        first += (" %d %s" % status).rstrip().encode("utf-8")
    lines = [first] + [("%s: %s" % field).encode("utf-8") for field in fields]
    return CRLF.join(lines) + CRLF + CRLF


def sub(subject, sid, queue=None):
    """SUB <subject> [queue group] <sid>."""
    return ("SUB %s %s%s\r\n" % (subject, _then(queue), sid)).encode("utf-8")


def unsub(sid, max_msgs=None):
    """UNSUB <sid> [max messages]."""
    return ("UNSUB %s%s\r\n" % (sid, "" if max_msgs is None else " %d" % max_msgs)).encode("utf-8")


# --- where a frame ends -------------------------------------------------------------------------

def _size(word, line):
    if not word.isdigit():
        raise ProtocolError("a payload size that is not a number: %r" % line[:120])
    return int(word)


def _measure(buf, start):
    """(the frame's whole length, whether a payload follows its line) for the frame that begins at
    `start`, once its control line has arrived; None until then."""
    end = buf.find(CRLF, start)
    if end < 0:
        if len(buf) - start > MAX_CONTROL_LINE:
            raise ProtocolError("%d bytes with no end of line: not the NATS protocol"
                                % (len(buf) - start))
        return None
    line = bytes(buf[start:end])
    words = line.split()
    if not words or words[0].upper() not in PAYLOAD_OPS:
        return end + 2 - start, False
    return end + 2 - start + _size(words[-1], line) + 2, True


def frame_size(buf, start=0):
    """The length of the frame that begins at `start` once its control line has arrived, whether or
    not the rest has; None while the line is incomplete. A one-reply read asks the kernel to wait
    for exactly this many bytes."""
    measured = _measure(buf, start)
    return None if measured is None else measured[0]


def frame_length(buf, start=0):
    """The byte length of the next complete frame in `buf` from `start`, or None while it is
    incomplete: the splitter the clients' reads and a capture reader share. Either side's frames
    are measured, and a payload must be followed by CRLF where its size says it ends."""
    measured = _measure(buf, start)
    if measured is None or len(buf) - start < measured[0]:
        return None
    size, payload = measured
    if payload and buf[start + size - 2:start + size] != CRLF:
        raise ProtocolError("a payload not followed by CRLF where its size said it ends")
    return size


# --- what a frame says --------------------------------------------------------------------------

#: One frame read into its parts. For MSG and HMSG (deliveries) and PUB and HPUB (publishes): the
#: subject, the subscription id (deliveries only), the reply subject or None, the header block
#: (empty without one) and the payload. For every other frame: the operation, and in `payload`
#: whatever follows it on its line, such as INFO's JSON or -ERR's text.
Frame = collections.namedtuple("Frame", "op subject sid reply headers payload")


def parse_frame(frame):
    """One whole frame, as frame_length measures it, read into a Frame."""
    end = frame.index(CRLF)
    words = frame[:end].split()
    op = words[0].upper().decode("ascii", "replace") if words else ""
    if op not in ("MSG", "HMSG", "PUB", "HPUB"):
        return Frame(op, None, None, None, b"", frame[len(op):end].strip())
    delivery = op in ("MSG", "HMSG")
    headed = op in ("HMSG", "HPUB")
    # The subject and the size, the subscription id on a delivery, the header size where headers
    # come; and a reply subject or not.
    base = 2 + delivery + headed
    args = words[1:]
    if len(args) not in (base, base + 1):
        raise ProtocolError("%s with %d arguments: %r" % (op, len(args), frame[:end][:120]))
    text = [word.decode("utf-8", "replace") for word in args]
    header_size = _size(args[-2], frame[:end]) if headed else 0
    body = frame[end + 2:len(frame) - 2]
    if header_size > len(body):
        raise ProtocolError("headers longer than the frame: %r" % frame[:end][:120])
    return Frame(op, text[0], text[1] if delivery else None,
                 text[1 + delivery] if len(args) == base + 1 else None,
                 body[:header_size], body[header_size:])


def parse_headers(block):
    """(status code or None, description, {name: value}) of a header block. A name given twice
    keeps its last value."""
    lines = block.split(CRLF)
    if not lines[0].startswith(HEADER_VERSION):
        raise ProtocolError("a header block that does not begin NATS/1.0: %r" % block[:60])
    code, _, description = lines[0][len(HEADER_VERSION):].strip().partition(b" ")
    fields = {}
    for line in lines[1:]:
        name, colon, value = line.partition(b":")
        if colon:
            fields[name.strip().decode("utf-8", "replace")] = value.strip().decode("utf-8",
                                                                                   "replace")
    return (int(code) if code.isdigit() else None,
            description.strip().decode("utf-8", "replace"), fields)


def status(frame):
    """(code, description) of a status message, a delivery whose headers' first line carries a
    code; None for any other frame, a delivered message among them."""
    if not frame.headers:
        return None
    code, description, _fields = parse_headers(frame.headers)
    return None if code is None else (code, description)


# --- JetStream ----------------------------------------------------------------------------------

API = "$JS.API"
ACK = b"+ACK"
#: Where a delivered message's reply subject begins: its acknowledgment is published to it.
ACK_PREFIX = "$JS.ACK."


def stream_create(stream, subjects, storage="file", replicas=1):
    """(subject, payload) of the request that creates a stream on `subjects`, kept on file or in
    memory, with one replica. Asked again with the same configuration, the server answers with the
    stream as it is; with another, with error 10058."""
    if storage not in STORAGE:
        raise ValueError("a stream is kept on file or in memory, not %r" % (storage,))
    config = {"name": stream, "subjects": list(subjects), "retention": "limits",
              "storage": storage, "num_replicas": replicas, "discard": "old"}
    return "%s.STREAM.CREATE.%s" % (API, stream), _json(config)


def stream_info(stream):
    return "%s.STREAM.INFO.%s" % (API, stream), b""


def stream_delete(stream):
    return "%s.STREAM.DELETE.%s" % (API, stream), b""


def consumer_create(stream, durable, max_ack_pending=MAX_ACK_PENDING, max_waiting=MAX_WAITING):
    """(subject, payload) of the request that makes a durable pull consumer of the whole stream,
    each message acknowledged by itself. With no action named, the server makes the consumer, or
    leaves one that exists with this configuration as it is."""
    config = {"durable_name": durable, "deliver_policy": "all", "ack_policy": "explicit",
              "replay_policy": "instant", "max_ack_pending": max_ack_pending,
              "max_waiting": max_waiting}
    return ("%s.CONSUMER.CREATE.%s.%s" % (API, stream, durable),
            _json({"stream_name": stream, "config": config}))


def max_waiting_for(depth):
    """The durable consumer's max_waiting for a client that keeps `depth` requests waiting: four
    times the depth, and never below the server's own default, 512."""
    return max(MAX_WAITING, WAITING_PER_DEPTH * depth)


def pull_request(stream, consumer, expires_ns, batch=1):
    """(subject, payload) of a pull request for `batch` messages, which waits at the server for
    `expires_ns` nanoseconds and is then answered by 408 Request Timeout."""
    return ("%s.CONSUMER.MSG.NEXT.%s.%s" % (API, stream, consumer),
            _json({"batch": batch, "expires": int(expires_ns)}))


def ack(reply):
    """The acknowledgment of a delivered message: +ACK, published to its reply subject."""
    return pub(reply, ACK)


def is_delivery(frame, sid):
    """Whether `frame` is a message delivered for a pull request on the subscription `sid`, the one
    that takes the requests' reply subjects: a MSG or HMSG on it with a reply subject under $JS.ACK,
    whatever its subject. nats-server writes a delivery under the subject the message was published
    to, so the delivery names no request; with one message to each request, it answers the oldest
    request still waiting. A status message comes under the reply subject of the request it
    answers, with no reply subject of its own, and a PONG has neither."""
    return frame.sid == str(sid) and (frame.reply or "").startswith(ACK_PREFIX)


def request_status(frame, prefix):
    """(code, description) of a status message that answers one of the requests whose reply
    subjects begin `prefix`: a frame under such a reply subject whose headers' first line carries a
    code. It names the request it answers, and ends it unless it is a heartbeat. None for any other
    frame, a delivery and a PONG among them."""
    if not (frame.subject or "").startswith(prefix):
        return None
    return status(frame)


def api_reply(payload):
    """A JetStream answer read as JSON; JetStreamError where it is an error."""
    try:
        reply = json.loads(payload)
    except ValueError:
        raise ProtocolError("a JetStream answer that is not JSON: %r" % payload[:120])
    if not isinstance(reply, dict):
        raise ProtocolError("a JetStream answer that is not an object: %r" % payload[:120])
    error = reply.get("error")
    if error:
        raise JetStreamError(error.get("code"), error.get("err_code"),
                             error.get("description", ""))
    return reply


def pub_ack(payload):
    """(stream, stream sequence, whether JetStream had the message already) of a publish's
    acknowledgment; JetStreamError where it is an error."""
    reply = api_reply(payload)
    try:
        return reply["stream"], int(reply["seq"]), bool(reply.get("duplicate", False))
    except (KeyError, TypeError, ValueError):
        raise ProtocolError("not a publish acknowledgment: %r" % payload[:120])


#: What a delivered message's reply subject says: the domain and the account's hash (empty in the
#: older form), the stream and the consumer, how many times this message has been delivered, its
#: stream sequence and consumer sequence, the time the stream stored it (ns since the epoch, on the
#: broker's clock), and how many messages were left for the consumer after it.
AckMeta = collections.namedtuple("AckMeta", "domain account_hash stream consumer delivered "
                                            "stream_seq consumer_seq timestamp_ns pending")


def _number(token, subject):
    if not (token.isascii() and token.isdigit()):
        raise ProtocolError("not a number in an acknowledgment subject: %r" % (subject,))
    return int(token)


def ack_metadata(subject):
    """A delivered message's reply subject read as the official clients read it (nats.go's
    internal/parser and nats.py's Msg.Metadata). The older form has nine tokens:

        $JS.ACK.<stream>.<consumer>.<delivered>.<stream seq>.<consumer seq>.<time>.<pending>

    and the newer puts the domain ("_" for none) and the account's hash after ACK: eleven tokens,
    and any after them, which are not read. Ten tokens, or fewer than nine, are not an
    acknowledgment subject."""
    tokens = (subject or "").split(".")
    n = len(tokens)
    if n < 9 or 9 < n < 11 or tokens[:2] != ["$JS", "ACK"]:
        raise ProtocolError("not a JetStream acknowledgment subject: %r" % (subject,))
    if n == 9:
        tokens = tokens[:2] + ["", ""] + tokens[2:]
    elif tokens[2] == "_":
        tokens[2] = ""
    numbers = [_number(token, subject) for token in tokens[6:11]]
    return AckMeta(tokens[2], tokens[3], tokens[4], tokens[5], *numbers)


# --- names --------------------------------------------------------------------------------------

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
#: What JetStream refuses in a stream's or a consumer's name: whitespace, '.', '*', '>' and path
#: separators; and characters that do not print, checked apart.
_NAME = re.compile(r"[^\s.*>/\\]+\Z")
#: A subject to publish to: tokens of no whitespace and no wildcard, divided by single dots.
_SUBJECT = re.compile(r"[^\s.*>]+(?:\.[^\s.*>]+)*\Z")


def safe_name(text):
    """`text` with every character but letters, digits, '_' and '-' made '_': a name made from a
    run id that JetStream takes whatever the run id holds."""
    return _UNSAFE.sub("_", text)


def checked_name(text):
    """A stream's or consumer's name as given, or ValueError where JetStream would refuse it."""
    if not (_NAME.match(text) and text.isprintable()):
        raise ValueError("%r cannot name a stream or a consumer" % (text,))
    return text


def checked_subject(text):
    """A subject to publish to as given, or ValueError where it is not one."""
    if not _SUBJECT.match(text):
        raise ValueError("%r is not a subject to publish to" % (text,))
    return text


def default_subject(stream):
    """The subject a stream is created on when none is named: one of its own, so that two streams
    never claim one subject."""
    return "sbl.%s" % stream


def new_inbox(rand=os.urandom):
    """A prefix for reply subjects that no other connection uses: _INBOX and 22 hex digits."""
    return "_INBOX." + rand(11).hex()


def timeval(seconds):
    """`seconds` as Linux's struct timeval, for SO_RCVTIMEO."""
    whole = int(seconds)
    return struct.pack("ll", whole, int(round((seconds - whole) * 1e6)))


# --- one connection -----------------------------------------------------------------------------

class Link(object):
    """One connection to the server: frames read whole, the server's PINGs answered, an -ERR raised,
    and writes made under one lock where two threads write.

    The socket is blocking, with SO_RCVTIMEO bounding each read, so that a read waits in the
    kernel. A socket with Python's own timeout waits in poll() instead, and poll() reports a socket
    readable whenever its error queue holds an entry, as it does after every send once the kernel's
    transmit timestamps are asked for (scripts/so_timestamps.py): such a wait spins until data
    comes. A blocking read sleeps until data arrives or the timeout passes, whatever the error
    queue holds.

    With `one_reply`, every read takes exactly one frame: the bytes waiting are first looked at
    without being taken (MSG_PEEK), the splitter says where the first frame ends, and a read of
    exactly that many bytes takes it. A frame whose rest has not arrived is waited for by a peek
    the kernel holds until that many bytes are there (MSG_PEEK | MSG_WAITALL, which Linux honours
    on a TCP socket). If such a wait passes, or the server goes, with the frame still incomplete,
    what has come is taken, and the frame is finished by reads that stop at its end. Without
    `one_reply`, a read takes whatever has come, and the frames are cut from what is held."""

    def __init__(self, sock, one_reply=False, wait_s=WAIT_S):
        self.sock = sock
        self.one_reply = one_reply
        self.wait_s = wait_s
        self.lock = threading.Lock()
        self.held = b""
        self.at = 0
        self.info = {}
        self.inbox = None
        self.asked = 0
        sock.settimeout(None)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO, timeval(wait_s))
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    @classmethod
    def open(cls, dial, host, port, name, one_reply=False, waits=REPLY_WAITS, wait_s=WAIT_S):
        """A connection that has read the server's INFO, said CONNECT and had its PONG back, by
        which the server has taken the CONNECT. `dial` is socket.create_connection, or a
        stand-in for it; each read waits at most `wait_s` in the kernel."""
        link = cls(dial((host, port), CONNECT_S), one_reply, wait_s)
        greeting = link.wait_for(lambda frame: True, waits, "greeting from %s:%d" % (host, port))
        if greeting.op != "INFO":
            raise ProtocolError("%s:%d is not a NATS server: it began with %r"
                                % (host, port, greeting.op))
        link.info = json.loads(greeting.payload)
        if not link.info.get("headers"):
            raise ProtocolError("the server at %s:%d takes no headers, and JetStream's status "
                                "messages are headers" % (host, port))
        link.send(connect(name) + PING)
        link.wait_for(lambda frame: frame.op == "PONG", waits, "PONG from %s:%d" % (host, port))
        return link

    def write(self, data):
        """Write a frame, for a caller that holds the lock or is the only thread that writes."""
        self.sock.sendall(data)

    def send(self, data):
        with self.lock:
            self.sock.sendall(data)

    def close(self):
        self.sock.close()

    def next_frame(self):
        """The next frame the caller is to see, or None when a read's wait passed with none. A PING
        is answered and an +OK passed over on the way; an -ERR is raised."""
        while True:
            try:
                raw = self._one() if self.one_reply else self._plain()
            except (BlockingIOError, socket.timeout):
                return None
            frame = parse_frame(raw)
            if self._heard(frame):
                return frame

    def wait_for(self, match, waits, what):
        """The first frame `match` accepts, through at most `waits` reads that come back empty."""
        empty = 0
        while empty < waits:
            frame = self.next_frame()
            if frame is None:
                empty += 1
            elif match(frame):
                return frame
        raise NoReply("no %s in %d waits of %.2f s" % (what, waits, self.wait_s))

    def request(self, subject, payload, waits=REPLY_WAITS):
        """Publish `payload` to `subject` with a reply subject of this connection's own, and return
        the frame that comes back to it. Frames for anything else are passed over."""
        if self.inbox is None:
            self.inbox = new_inbox()
            self.send(sub(self.inbox + ".*", REQUEST_SID))
        self.asked += 1
        reply = "%s.%d" % (self.inbox, self.asked)
        self.send(pub(subject, payload, reply))
        return self.wait_for(lambda frame: frame.subject == reply, waits, "reply to " + subject)

    def service(self):
        """Read whatever has come without waiting for more, answering the server's PINGs, and pass
        everything else over: for a connection the client writes on and has nothing to read from,
        such as the consumer's acknowledgments', which the server still PINGs."""
        try:
            self._more(self.sock.recv(READ_BYTES, MSG_DONTWAIT))
        except (BlockingIOError, socket.timeout):
            return
        frame = self._held_frame()
        while frame is not None:
            self._heard(parse_frame(frame))
            frame = self._held_frame()

    def _heard(self, frame):
        """Whether the caller is to see `frame`."""
        if frame.op == "PING":
            self.send(PONG)
            return False
        if frame.op == "-ERR":
            raise ServerError("the server said -ERR %s" % frame.payload.decode("utf-8", "replace"))
        return frame.op != "+OK"

    def _more(self, chunk):
        if not chunk:
            raise Closed("the server closed the connection")
        self.held = self.held[self.at:] + chunk
        self.at = 0

    def _held_frame(self):
        n = frame_length(self.held, self.at)
        if n is None:
            return None
        self.at += n
        return self.held[self.at - n:self.at]

    def _plain(self):
        frame = self._held_frame()
        while frame is None:
            self._more(self.sock.recv(READ_BYTES))
            frame = self._held_frame()
        return frame

    def _one(self):
        if self.held:
            return self._finish()
        seen = 0
        peek = self.sock.recv(PEEK_BYTES, socket.MSG_PEEK)
        while True:
            if not peek:
                raise Closed("the server closed the connection")
            n = frame_length(peek)
            if n is not None:
                return self._take(n)
            if len(peek) <= seen:
                # The wait passed, or the server went, with nothing more of the frame come.
                self._more(self.sock.recv(len(peek)))
                return self._finish()
            seen = len(peek)
            size = frame_size(peek)
            peek = self.sock.recv(size or seen + 1, socket.MSG_PEEK | socket.MSG_WAITALL)
            if size is None:
                # Its line was cut short, and a byte more has come, or the wait passed: whatever
                # has come is looked at, the rest of the line with it if it is there.
                peek = self.sock.recv(seen + PEEK_BYTES, socket.MSG_PEEK)

    def _take(self, n):
        """Exactly the `n` bytes of a frame a peek has seen whole."""
        data = self.sock.recv(n)
        if len(data) == n:
            return data
        self._more(data)
        return self._finish()

    def _finish(self):
        """The frame begun in what is held, read on to its end and never past it: the rest of its
        line a byte at a time while the line is incomplete, then all the rest in one read."""
        while True:
            n = frame_length(self.held)
            if n is not None:
                frame, self.held = self.held, b""
                return frame
            size = frame_size(self.held)
            self._more(self.sock.recv(size - len(self.held) if size else 1))


# --- the requests both clients make -------------------------------------------------------------

def api(link, subject, payload):
    """JetStream's answer to one request on `link`, read as JSON. A status message in its place,
    503 when JetStream is not there to answer, is a JetStreamError like an error."""
    frame = link.request(subject, payload)
    code = status(frame)
    if code is not None:
        raise JetStreamError(code[0], None, code[1] or "no one answered %s: is the server "
                             "started with JetStream on (nats-server -js)?" % subject)
    return api_reply(frame.payload)


def ensure_stream(link, stream, subject, storage="file"):
    """The stream, created if it is absent. One that exists with another configuration than this
    request's, as a server may hold for one made by an older client, is taken if it is kept the
    same way and on this subject; otherwise its error is raised."""
    try:
        return api(link, *stream_create(stream, [subject], storage))
    except JetStreamError as exc:
        if exc.err_code != STREAM_IN_USE:
            raise
    info = api(link, *stream_info(stream))
    config = info.get("config", {})
    if subject not in config.get("subjects", ()) or config.get("storage") != storage:
        raise JetStreamError(400, STREAM_IN_USE, "stream %s exists on %s with %s storage, not on "
                             "%s with %s" % (stream, config.get("subjects"), config.get("storage"),
                                             subject, storage))
    return info


def ensure_consumer(link, stream, durable, max_ack_pending=MAX_ACK_PENDING,
                    max_waiting=MAX_WAITING):
    """The durable pull consumer, made if it is absent."""
    return api(link, *consumer_create(stream, durable, max_ack_pending, max_waiting))
