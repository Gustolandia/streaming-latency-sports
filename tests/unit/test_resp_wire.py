"""Tests for scripts/resp_wire.py: RESP2 as the waiting consumer speaks it.

A command is held to the bytes Redis's protocol gives for it. A reply is framed whole, framed a
byte at a time as it might arrive, and framed again from its first unread byte after a part of it
has been read, as a reader that peeks and then reads sees it; each time its end must be found
exactly, and never past it. What is not RESP2 is refused rather than read on."""
import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import resp_wire as rw  # noqa: E402

#: An XREADGROUP reply as Redis 7 writes it in RESP2: one stream, two entries, the second with two
#: fields, and a nil array and an error after it, as the next replies on the same connection.
ENTRY_ONE = b"*2\r\n$15\r\n1790000000000-0\r\n*2\r\n$5\r\nvalue\r\n$7\r\n{\"a\":1}\r\n"
ENTRY_TWO = (b"*2\r\n$15\r\n1790000000001-0\r\n*4\r\n$5\r\nvalue\r\n$2\r\n{}\r\n"
             b"$3\r\npad\r\n$0\r\n\r\n")
REPLY = b"*1\r\n*2\r\n$3\r\ns47\r\n*2\r\n" + ENTRY_ONE + ENTRY_TWO
AFTER = b"*-1\r\n-ERR next\r\n"


class TestCommands:
    def test_a_command_is_an_array_of_bulk_strings(self):
        assert rw.command("XACK", "s47", "g47", "1-0", 200, b">") == (
            b"*6\r\n$4\r\nXACK\r\n$3\r\ns47\r\n$3\r\ng47\r\n$3\r\n1-0\r\n$3\r\n200\r\n$1\r\n>\r\n")

    def test_a_length_counts_the_bytes_of_the_utf8_text(self):
        assert rw.command("café") == b"*1\r\n$5\r\ncaf\xc3\xa9\r\n"

    def test_a_command_frames_and_decodes_as_what_it_says(self):
        data = rw.command("XREADGROUP", "GROUP", "g", "c", "COUNT", 7)
        assert rw.Framer().end(data, len(data)) == len(data)
        assert rw.decode(data) == [b"XREADGROUP", b"GROUP", b"g", b"c", b"COUNT", b"7"]


class TestFraming:
    @pytest.mark.parametrize("one", [b"+OK\r\n", b"-BUSYGROUP exists\r\n", b":12\r\n", b":-3\r\n",
                                     b"$3\r\nabc\r\n", b"$0\r\n\r\n", b"$-1\r\n", b"*-1\r\n",
                                     b"*0\r\n", b"*2\r\n:1\r\n*1\r\n$-1\r\n", REPLY])
    def test_each_kind_ends_where_it_ends_and_never_past(self, one):
        data = one + AFTER
        assert rw.Framer().end(data, len(data)) == len(one)
        assert rw.Framer().end(bytearray(data), len(data)) == len(one), "as a peek's buffer"

    def test_a_reply_given_a_byte_at_a_time_is_framed_once_and_ends_exactly(self):
        """One framer, given more each time, as the bytes arrive: until the last byte it says the
        reply is unfinished and how much the whole needs at least, and then its end."""
        framer = rw.Framer()
        for n in range(len(REPLY)):
            assert framer.end(REPLY + AFTER, n) is None
            assert n < framer.least <= len(REPLY), n
        assert framer.end(REPLY + AFTER, len(REPLY)) == len(REPLY)

    def test_a_fresh_framer_on_every_prefix_agrees(self):
        for n in range(len(REPLY)):
            framer = rw.Framer()
            assert framer.end(REPLY, n) is None and n < framer.least <= len(REPLY)

    def test_the_least_is_an_unfinished_bulk_strings_end(self):
        framer = rw.Framer()
        data = b"*1\r\n$10\r\nabc"
        assert framer.end(data, len(data)) is None and framer.least == 4 + 5 + 10 + 2

    def test_what_was_framed_is_kept_when_the_reply_is_given_again_with_more(self):
        """A reader that keeps what it has read of the reply gives it again with what has come
        since: the framer goes on from where it stopped, wherever that cut fell."""
        for cut in (1, 9, 30, len(REPLY) - 1):
            framer = rw.Framer()
            assert framer.end(REPLY[:cut], cut) is None
            stopped = framer.pos
            whole = bytearray(REPLY[:cut]) + REPLY[cut:] + AFTER
            assert framer.end(whole, len(whole)) == len(REPLY) and stopped <= cut, cut

    def test_a_long_number_line_still_unfinished_may_yet_be_right(self):
        """The longest number is twenty characters: its line can arrive up to its CR alone."""
        data = b"$" + b"9" * 20 + b"\r"
        assert rw.Framer().end(data, len(data)) is None

    @pytest.mark.parametrize("bad", [
        b"?what\r\n",                     # no such type byte
        b"$abc\r\n",                      # a length that is not a number
        b"$-2\r\n",                       # below the nil length
        b"$%d\r\n" % (rw.LONGEST_BULK + 1),
        b"*1x\r\n",
        b":12a\r\n",                      # an integer that is not one
        b"$3\r\nabcde\r\n",               # a bulk string longer than it said
        b"$" + b"1" * 22,                 # a number line too long to be one, unfinished
        b"*" + b"1" * 21 + b"\r\n",       # a number too long, finished
    ])
    def test_what_is_not_resp2_is_refused(self, bad):
        with pytest.raises(rw.ProtocolError):
            rw.Framer().end(bad, len(bad))


class TestDecoding:
    def test_each_kind_has_its_value(self):
        assert rw.decode(b"+OK\r\n") == b"OK"
        assert rw.decode(b":-12\r\n") == -12
        assert rw.decode(b"$3\r\nabc\r\n") == b"abc"
        assert rw.decode(b"$-1\r\n") is None and rw.decode(b"*-1\r\n") is None
        assert rw.decode(b"*0\r\n") == []
        assert rw.decode(bytearray(b"*2\r\n:1\r\n*1\r\n$0\r\n\r\n")) == [1, [b""]]
        error = rw.decode(b"-NOGROUP No such key\r\n")
        assert isinstance(error, rw.ReplyError) and str(error) == "NOGROUP No such key"

    def test_an_xreadgroup_reply(self):
        assert rw.decode(REPLY) == [[b"s47", [
            [b"1790000000000-0", [b"value", b'{"a":1}']],
            [b"1790000000001-0", [b"value", b"{}", b"pad", b""]]]]]

    @pytest.mark.parametrize("bad", [b"+OK", b"$3\r\nabcd\r\n", b"*2\r\n:1\r\n", b"!x\r\n",
                                     b":1\r\n:2\r\n"])
    def test_an_unfinished_malformed_or_overlong_reply_is_refused(self, bad):
        with pytest.raises(rw.ProtocolError):
            rw.decode(bad)


def test_it_parses_as_python_39():
    with open(rw.__file__, encoding="utf-8") as fh:
        ast.parse(fh.read(), feature_version=(3, 9))


class TestEntries:
    def test_entries_by_the_brokers_own_ids_in_order(self):
        assert rw.entries(rw.decode(REPLY)) == [
            ("s47", "1790000000000-0", {"value": '{"a":1}'}),
            ("s47", "1790000000001-0", {"value": "{}", "pad": ""})]

    def test_a_block_that_timed_out_has_none_and_an_entry_gone_has_no_fields(self):
        assert rw.entries(None) == [] and rw.entries([]) == []
        assert rw.entries([[b"s", []]]) == []
        assert rw.entries([[b"s", [[b"1-0", None]]]]) == [("s", "1-0", None)]

    def test_text_is_utf8(self):
        assert rw.entries([[b"s", [[b"1-0", [b"v", b"caf\xc3\xa9"]]]]]) == [
            ("s", "1-0", {"v": "café"})]

    def test_an_error_reply_is_raised(self):
        with pytest.raises(rw.ReplyError, match="NOGROUP"):
            rw.entries(rw.ReplyError("NOGROUP No such key"))

    @pytest.mark.parametrize("bad", [
        5, b"OK",                                         # not an array
        [[b"s"]], [5], [[b"s", None]], [["s", []]],       # not a stream and its entries
        [[b"s", [[b"1-0"]]]], [[b"s", [5]]], [[b"s", [[None, []]]]],   # not an entry
        [[b"s", [[b"1-0", [b"v"]]]]], [[b"s", [[b"1-0", [b"v", 5]]]]],  # not its fields
        [[b"s", [[b"1-0", b"v"]]]],
    ])
    def test_any_other_shape_is_refused(self, bad):
        with pytest.raises(rw.ProtocolError):
            rw.entries(bad)
