#!/usr/bin/env python3
"""
resp_wire.py -- Redis's wire format, RESP2, as the waiting consumer
(scripts/redis_consumer_waiting.py) speaks it on its own sockets.

A command is an array of bulk strings. A reply is one value, each kind a type byte and a line ended
by CRLF, with what the line announces after it for a bulk string and an array:

  +OK            a simple string        :12              an integer
  -ERR message   an error               $5 CRLF hello    a bulk string; $-1, the nil one
  *2 ...         an array of two values; *-1, the nil array, which a BLOCK that timed out gives

Framer finds where one reply ends in bytes that arrive a part at a time, each look at them made
again from the reply's first byte, as a read with MSG_PEEK makes it. It keeps what it has framed,
so each byte is framed once however many times the reply is looked at, and while the reply is
unfinished it says how many bytes the whole of it needs at least, for a reader that waits for them
in the kernel. decode() turns a whole reply into Python values, and entries() reads the
entries of an XREADGROUP reply, each by the broker's own id.

Bytes that are not RESP2 raise ProtocolError: a connection whose framing is lost cannot be read on,
and the run stops and says why.
"""
import re

CRLF = b"\r\n"
#: A length or an integer: an optional minus sign and digits, nothing else.
NUMBER = re.compile(rb"-?[0-9]+")
#: The longest line a length or an integer needs: a sign and the 19 digits of a 64-bit integer.
LONGEST_NUMBER = 20
#: Redis's own ceiling on one bulk string (proto-max-bulk-len, 512 MiB): a longer one is not
#: Redis's.
LONGEST_BULK = 512 * 1024 * 1024
#: The type bytes whose line holds a number.
NUMBERED = (b"$", b"*", b":")


class ProtocolError(ValueError):
    """Bytes that are not a RESP2 reply."""


class ReplyError(Exception):
    """An error reply, the broker's own message: decode() returns it as a value, and a caller that
    meant it as a failure raises it."""


def command(*args):
    """The bytes of one command: an array of bulk strings, each argument as UTF-8."""
    parts = [b"*%d\r\n" % len(args)]
    for arg in args:
        data = arg if isinstance(arg, bytes) else str(arg).encode("utf-8")
        parts.append(b"$%d\r\n%s\r\n" % (len(data), data))
    return b"".join(parts)


def _number(head, at):
    """The value of a length or an integer line."""
    if len(head) > LONGEST_NUMBER or not NUMBER.fullmatch(head):
        raise ProtocolError("not a number at offset %d: %r" % (at, bytes(head[:LONGEST_NUMBER])))
    return int(head)


def _length(head, at):
    """A bulk string's or an array's length: -1 for the nil one."""
    size = _number(head, at)
    if size < -1 or size > LONGEST_BULK:
        raise ProtocolError("not a length at offset %d: %d" % (at, size))
    return size


class Framer(object):
    """Where one reply ends.

    end() is given the reply's bytes from its first byte, and may be given them again, with more,
    as more arrive. What it has framed is not framed again: `pos` is where framing stopped, and
    `left` the values still owed at each depth of nesting. A reply is never framed past its end,
    so bytes of the next reply are never taken for this one's."""

    def __init__(self):
        self.pos = 0
        self.left = [1]
        #: Once end() finds the reply unfinished: the fewest bytes the whole of it can take.
        self.least = 1

    def end(self, data, n):
        """The reply's length once data[:n] holds its last byte; else None, with `least` set.
        While it is unfinished, every one of those n bytes is this reply's: framing stopped inside
        a line or inside a bulk string."""
        pos, left = self.pos, self.left
        while True:
            while left and not left[-1]:
                left.pop()
            if not left:
                self.pos = pos
                return pos
            line = data.find(CRLF, pos, n)
            if line < 0:
                # A number's whole line is its type byte, the number and CRLF: unfinished, it
                # holds at most the type byte, the number and the CR.
                if data[pos:pos + 1] in NUMBERED and n - pos > LONGEST_NUMBER + 2:
                    raise ProtocolError("a number line longer than %d bytes at offset %d"
                                        % (LONGEST_NUMBER, pos))
                self.pos, self.least = pos, n + 1
                return None
            kind, head, after = data[pos:pos + 1], data[pos + 1:line], line + 2
            if kind == b"$":
                size = _length(head, pos)
                if size >= 0:
                    after += size + 2
                    if after > n:
                        self.pos, self.least = pos, after
                        return None
                    if data[after - 2:after] != CRLF:
                        raise ProtocolError("a bulk string not ended by CRLF at offset %d"
                                            % (after - 2))
            elif kind == b"*":
                size = _length(head, pos)
                if size > 0:
                    left[-1] -= 1
                    left.append(size)
                    pos = after
                    continue
            elif kind == b":":
                _number(head, pos)
            elif kind not in (b"+", b"-"):
                raise ProtocolError("not a RESP2 value at offset %d: %r"
                                    % (pos, bytes(data[pos:pos + 16])))
            left[-1] -= 1
            pos = after


def decode(data):
    """The value of the one whole reply `data` holds: bytes for a simple or a bulk string, an int,
    a list for an array, None for the nil bulk string or array, and a ReplyError for an error."""
    value, end = _value(data, 0)
    if end != len(data):
        raise ProtocolError("%d bytes after the reply" % (len(data) - end))
    return value


def _value(data, pos):
    """(the value that starts at `pos`, where it ends)."""
    line = data.find(CRLF, pos)
    if line < 0:
        raise ProtocolError("an unfinished reply at offset %d" % pos)
    kind, head, after = data[pos:pos + 1], data[pos + 1:line], line + 2
    if kind == b"+":
        return bytes(head), after
    if kind == b"-":
        return ReplyError(bytes(head).decode("utf-8", "replace")), after
    if kind == b":":
        return _number(head, pos), after
    if kind == b"$":
        size = _length(head, pos)
        if size < 0:
            return None, after
        end = after + size
        if data[end:end + 2] != CRLF:
            raise ProtocolError("a bulk string not ended by CRLF at offset %d" % end)
        return bytes(data[after:end]), end + 2
    if kind == b"*":
        size = _length(head, pos)
        if size < 0:
            return None, after
        items = []
        for _ in range(size):
            item, after = _value(data, after)
            items.append(item)
        return items, after
    raise ProtocolError("not a RESP2 value at offset %d: %r" % (pos, bytes(data[pos:pos + 16])))


def entries(reply):
    """[(stream, entry id, {field: value} or None)] for each entry of a decoded XREADGROUP or XREAD
    reply, in the broker's order, every name and value as UTF-8 text, and None for an entry the
    stream no longer holds; [] for the nil array a BLOCK that timed out gives. An error reply is
    raised; a reply of any other shape is a ProtocolError."""
    if isinstance(reply, ReplyError):
        raise reply
    if reply is None:
        return []
    if not isinstance(reply, list):
        raise ProtocolError("not a reply to XREADGROUP: %r" % (reply,))
    found = []
    for item in reply:
        if not (isinstance(item, list) and len(item) == 2 and isinstance(item[0], bytes)
                and isinstance(item[1], list)):
            raise ProtocolError("not a stream and its entries: %r" % (item,))
        stream = item[0].decode("utf-8")
        for entry in item[1]:
            if not (isinstance(entry, list) and len(entry) == 2 and isinstance(entry[0], bytes)):
                raise ProtocolError("not an entry: %r" % (entry,))
            fields = entry[1]
            if fields is not None:
                if not (isinstance(fields, list) and len(fields) % 2 == 0
                        and all(isinstance(f, bytes) for f in fields)):
                    raise ProtocolError("not an entry's fields: %r" % (fields,))
                text = [f.decode("utf-8") for f in fields]
                fields = dict(zip(text[0::2], text[1::2]))
            found.append((stream, entry[0].decode("utf-8"), fields))
    return found
