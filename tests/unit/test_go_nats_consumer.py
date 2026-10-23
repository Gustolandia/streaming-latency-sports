"""The nats.go consumer, held to the clients' interface by reading its sources.

Block N's NATS JetStream consumer keeps its pull requests waiting at the server, so that the
client's own thread stays out of what reaches its kernel. scripts/nats_consumer.py keeps them
waiting by hand; harness/go-nats runs nats.go's Consume, which keeps them waiting by itself. That
consumer must take nats_consumer.py's flags, leave the files it leaves, identify each message by
the stream sequence its metadata gives, make the stream and the durable consumer nats_wire.py
makes, leave nats.go's pull options at their defaults, end with the line every consumer ends with,
and, asked for --threads-out, list its threads in the one form the kit reads.

These are source checks, as tests/unit/test_go_and_java_consumers.py makes for the franz-go
consumer: CI has no Go toolchain, and no test here may skip. The compiler's own check runs where
the consumer is built, in harness/go-nats/build.sh.
"""
import ast
import json
import math
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
SCRIPTS = ROOT / "scripts"
GO = ROOT / "harness" / "go-nats"
FRANZ = ROOT / "harness" / "go"

sys.path.insert(0, str(SCRIPTS))

import kafka_consumer_confluent  # noqa: E402
import law_clock  # noqa: E402
import nats_consumer  # noqa: E402
import nats_wire  # noqa: E402

#: nats_consumer.py's flags this consumer takes; those it leaves, because the requests, the reads
#: and the threads are nats.go's here; and its own.
SHARED = ["probe-ms", "run-id", "out", "stream", "subject", "durable", "host", "port", "storage",
          "idle-seconds"]
LEFT = ["depth", "expires-s", "one-reply-reads", "delete-stream", "thread-record"]
OWN = ["max-messages", "threshold", "threads-out"]

#: The pins: nats.go v1.54.0, the latest release on 23 Oct 2026 (the module proxy's @latest and
#: GitHub's latest release), and the modules its go.mod requires, at the versions it names.
PINS = {
    "github.com/nats-io/nats.go": "v1.54.0",
    "github.com/klauspost/compress": "v1.20.0",
    "github.com/nats-io/nkeys": "v0.4.16",
    "github.com/nats-io/nuid": "v1.0.1",
    "golang.org/x/crypto": "v0.57.0",
    "golang.org/x/sys": "v0.48.0",
}

#: The JSON nats.go v1.54.0 makes of the fields and values this consumer sets: the struct tags of
#: StreamConfig and ConsumerConfig, and the MarshalJSON of each policy (jetstream/stream_config.go
#: and jetstream/consumer_config.go).
STREAM_KEYS = {"Name": "name", "Subjects": "subjects", "Retention": "retention",
               "Storage": "storage", "Replicas": "num_replicas", "Discard": "discard"}
CONSUMER_KEYS = {"Durable": "durable_name", "DeliverPolicy": "deliver_policy",
                 "AckPolicy": "ack_policy", "ReplayPolicy": "replay_policy",
                 "MaxAckPending": "max_ack_pending", "MaxWaiting": "max_waiting"}
POLICY_JSON = {"jetstream.LimitsPolicy": "limits", "jetstream.DiscardOld": "old",
               "jetstream.DeliverAllPolicy": "all", "jetstream.AckExplicitPolicy": "explicit",
               "jetstream.ReplayInstantPolicy": "instant"}

#: The helpers this consumer takes from harness/go's unchanged, but for the program's name.
FRANZ_HELPERS = ["create", "close", "beside", "text", "pythonCell", "clockResolutionNs",
                 "moduleVersion", "writeThreads", "taskIDs"]


def read(path):
    """A source as its compiler reads it. Git checks these files out with CRLF line endings on
    Windows (core.autocrlf), and the checks below match line ends."""
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def go_source():
    return read(GO / "main.go")


def go_code(source, keep_strings=True):
    """`source` with its comments taken out and, unless `keep_strings`, its string and rune
    literals emptied, so that a name is found only where the code uses it."""
    def replace(match):
        token = match.group(0)
        if token.startswith("/"):
            return ""
        return token if keep_strings else token[0] * 2
    return re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|`[^`]*`|\'(?:\\.|[^\'\\\n])+\'',
                  replace, source, flags=re.DOTALL)


def function_in(source, name):
    """The function or method `name` in a Go source, from `func` to the closing brace at the start
    of a line."""
    start = re.search(r"\nfunc (?:\([^)]*\) )?%s\(" % re.escape(name), source).start()
    return source[start:source.index("\n}\n", start)]


def go_function(name):
    return function_in(go_source(), name)


def go_strings(name):
    """The string slice `var <name> = []string{...}` in main.go."""
    source = go_source()
    start = source.index("var %s = []string{" % name)
    return re.findall(r'"([^"]*)"', source[start:source.index("}", start)])


def go_constant(name):
    """The integer constant `<name> = <digits>` in main.go."""
    return int(re.search(r"^\t%s\s*=\s*(\d+)$" % re.escape(name), go_source(),
                         re.MULTILINE).group(1))


def split_outside(body, opening, pairs="()"):
    """The items between `opening` and the bracket that closes it, split at the commas outside
    any bracket of `pairs`, with runs of white space made one space; an empty last item, after a
    trailing comma, is dropped."""
    start = body.index(opening) + len(opening)
    items, depth, current = [], 0, ""
    for char in body[start:]:
        if char in pairs[0::2]:
            depth += 1
        elif char in pairs[1::2]:
            if depth == 0:
                break
            depth -= 1
        if char == "," and depth == 0:
            items.append(current)
            current = ""
        else:
            current += char
    items = [re.sub(r"\s+", " ", item).strip() for item in items + [current]]
    return items if items[-1] else items[:-1]


def go_fields(body, opening):
    """{field: value} of the keyed composite literal `opening` begins in `body`."""
    return dict((key.strip(), value.strip()) for key, value in
                (item.split(":", 1) for item in split_outside(body, opening, "(){}")))


def as_json(fields, keys, names):
    """The JSON nats.go makes of a Go literal's fields: each key by its struct tag, each value a
    policy's JSON name, a number, one of `names`, or a constant of main.go."""
    made = {}
    for field, value in fields.items():
        if value in POLICY_JSON:
            made[keys[field]] = POLICY_JSON[value]
        elif value in names:
            made[keys[field]] = names[value]
        elif value.isdigit():
            made[keys[field]] = int(value)
        else:
            made[keys[field]] = go_constant(value)
    return made


def go_imports():
    """The import paths of main.go's import block."""
    source = go_source()
    start = source.index("import (")
    return re.findall(r'"([^"]+)"', source[start:source.index(")", start)])


def package_name(path):
    """The name main.go calls the package at `path` by: its last element, but for nats.go, whose
    package is nats."""
    return {"github.com/nats-io/nats.go": "nats"}.get(path, path.rsplit("/", 1)[-1])


def go_flags():
    """{flag: (kind, default as the source spells it)} for every flag main.go declares."""
    return {name: (kind, default.strip()) for kind, name, default in re.findall(
        r'flags\.(String|Int|Float64|Bool)\("([a-z-]+)",\s*([^,]+),', go_source())}


def go_mod():
    return read(GO / "go.mod")


def go_requirements():
    """{module path: version} for every require line of go.mod."""
    return dict(re.findall(r"^\s*(?:require\s+)?([\w./-]+\.[\w./-]+)\s+(v[\w.+-]+)",
                           go_mod(), re.MULTILINE))


def python_value(node):
    """What an add_argument keyword names: a literal, a built-in type, or a name in nats_wire or
    in nats_consumer itself."""
    if isinstance(node, ast.Name):
        return {"int": int, "float": float}.get(node.id) or getattr(nats_consumer, node.id)
    if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "nats_wire"):
        return getattr(nats_wire, node.attr)
    return ast.literal_eval(node)


def nats_consumer_flags():
    """{flag: {keyword: value}} for every ap.add_argument call in scripts/nats_consumer.py."""
    flags = {}
    for node in ast.walk(ast.parse(read(SCRIPTS / "nats_consumer.py"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            flags[ast.literal_eval(node.args[0])[2:]] = {
                keyword.arg: python_value(keyword.value) for keyword in node.keywords}
    return flags


def nats_fieldnames(which):
    """The `which`-th csv fieldnames list in scripts/nats_consumer.py."""
    source = read(SCRIPTS / "nats_consumer.py")
    start = [m.start() for m in re.finditer(r"fieldnames=\[", source)][which]
    return re.findall(r'"([^"]+)"', source[start:source.index("]", start)])


class TestItTakesTheNatsConsumersFlags:

    def test_its_flags_are_those_it_shares_with_the_nats_consumer_and_its_own(self):
        assert sorted(go_flags()) == sorted(SHARED + OWN)

    def test_every_other_flag_of_the_nats_consumer_is_one_it_leaves_to_nats_go(self):
        """A flag added to nats_consumer.py is one this consumer takes, or says it leaves."""
        assert sorted(nats_consumer_flags()) == sorted(SHARED + LEFT)

    @pytest.mark.parametrize("flag", ["stream", "host", "port", "storage", "idle-seconds",
                                      "probe-ms"])
    def test_each_default_is_the_nats_consumers(self, flag):
        kind, default = go_flags()[flag]
        python = nats_consumer_flags()[flag]
        if python.get("type") is int:
            assert (kind, int(default)) == ("Int", python["default"])
        else:
            assert (kind, default) == ("String", '"%s"' % python["default"])

    def test_a_run_without_its_run_id_or_its_output_is_refused(self):
        python = nats_consumer_flags()
        assert python["run-id"]["required"] and python["out"]["required"]
        assert 'if *runID == "" || *out == "" {' in go_function("run")

    def test_the_subject_and_the_durable_default_as_the_nats_consumers_do(self):
        body = go_function("run")
        assert nats_wire.default_subject("S") == "sbl.S"
        assert 'subject = "sbl." + *streamName' in body
        assert 'nats_wire.safe_name("sbl-" + args.run_id)' in read(SCRIPTS / "nats_consumer.py")
        assert 'durable = safeName("sbl-" + *runID)' in body

    def test_the_default_durable_keeps_what_nats_wire_keeps(self):
        assert nats_wire._UNSAFE.pattern == "[^A-Za-z0-9_-]"
        body = go_function("safeName")
        for kept in ("c == '_'", "c == '-'", "('0' <= c && c <= '9')", "('a' <= c && c <= 'z')",
                     "('A' <= c && c <= 'Z')"):
            assert kept in body
        assert "return '_'" in body

    def test_the_storage_is_one_of_nats_wires_two(self):
        body = go_function("run")
        switch = body[body.index("switch *storage {"):]
        switch = switch[:switch.index("\n\t}\n")]
        assert re.findall(r'case "(\w+)":', switch) == list(nats_wire.STORAGE)
        assert "kept := jetstream.FileStorage" in body
        assert 'case "memory":\n\t\tkept = jetstream.MemoryStorage' in switch

    def test_names_and_subjects_are_checked_as_nats_wire_checks_them(self):
        assert nats_wire._NAME.pattern == r"[^\s.*>/\\]+\Z"
        assert nats_wire._SUBJECT.pattern == r"[^\s.*>]+(?:\.[^\s.*>]+)*\Z"
        name = go_function("checkedName")
        assert 'name == ""' in name and 'strings.ContainsAny(name, ".*>/\\\\")' in name
        assert "strings.IndexFunc(name, pythonSpace) >= 0" in name
        assert "!unicode.IsPrint(c)" in name
        subject = go_function("checkedSubject")
        assert 'strings.Split(subject, ".")' in subject and 'token == ""' in subject
        assert 'strings.ContainsAny(token, "*>")' in subject
        assert "strings.IndexFunc(token, pythonSpace) >= 0" in subject
        assert ("[]error{checkedName(*streamName), checkedSubject(subject),\n\t\t"
                "checkedName(durable)}") in go_function("run")

    def test_white_space_is_pythons(self):
        """Python's \\s, which nats_wire.py's checks use, is Go's unicode.IsSpace and U+001C to
        U+001F. In Latin-1, where Go's rule is a list (\\t \\n \\v \\f \\r, space, U+0085 and
        U+00A0), the two are read here side by side; beyond it both follow Unicode's White_Space."""
        go_latin1 = {0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x20, 0x85, 0xa0}
        python = {c for c in range(0x100) if re.match(r"\s", chr(c))}
        assert python == go_latin1 | {0x1c, 0x1d, 0x1e, 0x1f}
        assert "unicode.IsSpace(c) || (c >= 0x1c && c <= 0x1f)" in go_function("pythonSpace")


class TestItWritesTheNatsConsumersFiles:

    def test_consumer_csv_has_the_nats_consumers_columns(self):
        assert go_strings("consumerColumns") == nats_fieldnames(0)

    def test_the_event_log_has_the_nats_consumers_columns(self):
        assert go_strings("eventColumns") == nats_fieldnames(1)

    def test_the_fields_it_copies_are_the_event_logs_after_its_event_id(self):
        columns = go_strings("eventColumns")
        assert go_strings("copied") == columns[columns.index("event_id") + 1:]

    def test_the_rows_are_built_in_the_columns_order(self):
        """The two literals that make the rows, read in order: the stamps and the server's ids
        sit where the headers put them."""
        body = go_function("take")
        assert split_outside(body, "row := []string{", "(){}") == [
            "r.runID", '"nats"', "meta.Stream", "eventID", 'pythonCell(fields["match_id"])',
            'pythonCell(fields["t_sim_seconds"])', "tConsume", "tOutput", "seq"]
        assert split_outside(body, "event := []string{", "(){}") == [
            "r.runID", '"nats"', "meta.Stream", "seq", "tConsume", "eventID"]

    def test_backend_and_stream_are_written_as_the_nats_consumer_writes_them(self):
        source = read(SCRIPTS / "nats_consumer.py")
        assert source.count('"backend": "nats"') == 2
        assert source.count('"stream": meta.stream') == 2

    def test_the_event_log_is_named_beside_the_output_as_python_names_it(self):
        assert 'strings.TrimSuffix(name, filepath.Ext(name))+"_events.csv"' in go_function(
            "beside")
        assert 'Path(args.out).stem + "_events.csv"' in read(SCRIPTS / "nats_consumer.py")

    def test_rows_end_as_pythons_csv_module_ends_them(self):
        assert "writer.UseCRLF = true" in go_function("create")

    def test_values_are_written_as_pythons_csv_writer_writes_what_json_loads_made(self):
        body = go_function("pythonCell")
        for spelled in ('case "", "null":\n\t\treturn ""', 'case "true":\n\t\treturn "True"',
                        'case "false":\n\t\treturn "False"'):
            assert spelled in body

    def test_it_ends_with_the_line_every_consumer_ends_with_once_for_each_file(self):
        """The interface: `OK <client> consumer: wrote N rows -> PATH` at the end, for each
        file, as nats_consumer.py ends."""
        source = go_source()
        assert len(re.findall(r'fmt\.Printf\("OK nats\.go consumer: wrote %d rows -> %s\\n", '
                              r'r\.written, ', source)) == 2
        assert len(re.findall(r'print\(f"OK nats consumer: wrote \{\w+\} rows -> \{',
                              read(SCRIPTS / "nats_consumer.py"))) == 2
        body = go_function("run")
        assert body.index("redeliveries not written") < body.index("wrote %d rows")


class TestTheStampsAndTheStreamSequence:

    def test_the_receive_stamp_is_the_handlers_first_reading(self):
        body = go_function("handle")
        first = body[body.index("{") + 1:].strip().splitlines()[0]
        assert first == "received := time.Now()"
        assert go_source().count("received := time.Now()") == 1

    def test_t_consume_and_t_cons_recv_are_that_reading_and_t_output_the_next(self):
        """Go's time.Now() reads CLOCK_REALTIME for the wall clock; UnixNano is that reading.
        t_output_ns is taken only for a message found to be this run's, as in nats_consumer.py."""
        body = go_function("take")
        assert "tConsume := strconv.FormatInt(received.UnixNano(), 10)" in body
        assert "tOutput := strconv.FormatInt(time.Now().UnixNano(), 10)" in body
        assert body.index("} else if thisRun {") < body.index("tConsume :=") \
            < body.index("tOutput :=")

    def test_the_stream_sequence_comes_from_the_messages_metadata(self):
        body = go_function("take")
        assert body.index("meta, err := msg.Metadata()") < body.index("json.Unmarshal(")
        assert "seq := strconv.FormatUint(meta.Sequence.Stream, 10)" in body
        assert body.index("if meta.Sequence.Stream == 0 {") < body.index("seq :=")

    def test_the_payload_gives_no_id(self):
        """The payload is read for run_id, event_id and the fields copied after it, and for
        nothing else: the stream sequence, the stream and the delivery count come from the
        metadata alone."""
        code = go_code(go_source())
        assert set(re.findall(r'fields\["(\w+)"\]', code)) == {
            "run_id", "event_id", "match_id", "t_sim_seconds"}
        assert len(re.findall(r"fields\[name\]", code)) == 1
        assert ("for _, name := range copied {\n\t\t\tevent = append(event, "
                "pythonCell(fields[name]))") in go_function("take")
        assert not {"stream", "stream_seq"} & set(go_strings("copied"))
        assert code.count('fields["event_id"]') == 1, "event_id is read once, for its column"

    def test_the_payload_decides_only_whether_a_message_is_this_runs(self):
        body = go_function("take")
        assert 'id, ok := text(fields["run_id"])' in body
        assert "thisRun := ok && id == r.runID" in body

    def test_a_message_delivered_again_is_acknowledged_and_not_written(self):
        body = go_function("take")
        assert "if thisRun && meta.NumDelivered > 1 {\n\t\tr.redelivered++" in body
        python = read(SCRIPTS / "nats_consumer.py")
        assert "if this_run and meta.delivered > 1:\n                    redelivered += 1" \
            in python

    def test_every_message_is_acknowledged_after_its_rows(self):
        """At the function's own level, so that another run's message and a redelivery are
        acknowledged too, as nats_consumer.py acknowledges every delivered message."""
        body = go_function("take")
        assert body.count("msg.Ack()") == 1
        assert "\n\tif err := msg.Ack(); err != nil {" in body
        assert body.index("r.events.writer.Write(event)") < body.index("msg.Ack()")

    def test_the_idle_stop_is_the_nats_consumers(self):
        """Every delivered message, of any run, starts the idle time again, and the time first
        counts from the first request; the run stops once --idle-seconds pass with none."""
        python = read(SCRIPTS / "nats_consumer.py")
        assert "acks.write(nats_wire.ack(frame.reply))\n                last_msg = clock()" in python
        assert "if not delivered and now - last_msg >= args.idle_seconds:" in python
        take = go_function("take")
        assert take.index("msg.Ack()") < take.index("r.lastMessage = time.Now()")
        run = go_function("run")
        assert run.index("r.lastMessage = time.Now()") < run.index("cons.Consume(")
        assert "idle := time.Duration(*idleSeconds) * time.Second" in run
        assert "for status == 0 && !r.over(idle) {\n\t\ttime.Sleep(idleCheck)" in run
        assert "time.Since(r.lastMessage) >= idle" in go_function("over")
        assert re.search(r"\bidleCheck\s*=\s*%d \* time\.Millisecond" % int(nats_wire.WAIT_S * 1000),
                         go_source())

    def test_the_clock_is_held_to_the_bar_every_client_is(self):
        assert go_constant("finestUsableNs") == law_clock.FINEST_USABLE_NS
        assert go_constant("clockSamples") == law_clock.SAMPLES
        assert "resolution <= 0 || resolution > finestUsableNs" in go_function("run")
        assert "clock_resolution_ns=%d" in go_function("run")


class TestTheStreamAndTheDurableConsumer:

    def test_the_stream_is_the_one_nats_wire_makes(self):
        made = as_json(go_fields(go_function("run"), "jetstream.StreamConfig{"), STREAM_KEYS,
                       {"*streamName": "S", "[]string{subject}": ["sbl.S"], "kept": "memory"})
        assert made == json.loads(nats_wire.stream_create("S", ["sbl.S"], "memory")[1])

    def test_a_stream_made_otherwise_is_taken_as_nats_wire_takes_it(self):
        """Asked again with another configuration, the server answers 10058, which nats.go
        gives as ErrStreamNameAlreadyInUse (JSErrCodeStreamNameInUse, jetstream/errors.go)."""
        assert nats_wire.STREAM_IN_USE == 10058
        body = go_function("ensureStream")
        assert "if !errors.Is(err, jetstream.ErrStreamNameAlreadyInUse) {" in body
        assert ("!slices.Contains(have.Subjects, want.Subjects[0]) || "
                "have.Storage != want.Storage") in body

    def test_the_durable_consumer_is_the_one_nats_consumer_makes(self):
        """Made or left as it is (CreateOrUpdateConsumer sends no action, as nats_wire.py's
        request names none), with nats_wire.py's limits."""
        body = go_function("run")
        assert "js.CreateOrUpdateConsumer(ctx, *streamName, jetstream.ConsumerConfig{" in body
        made = as_json(go_fields(body, "jetstream.ConsumerConfig{"), CONSUMER_KEYS,
                       {"durable": "D"})
        request = json.loads(nats_wire.consumer_create("S", "D")[1])
        assert made == request["config"] and "action" not in request
        assert go_constant("maxWaiting") == nats_wire.MAX_WAITING
        assert go_constant("maxAckPending") == nats_wire.MAX_ACK_PENDING


class TestConsumeRunsWithNatsGosPullOptions:

    def test_consume_is_given_the_two_counts_on_record_and_an_error_handler(self):
        assert split_outside(go_function("run"), "cons.Consume(") == [
            "r.handle", "jetstream.PullMaxMessages(*maxMessages)",
            "jetstream.PullThresholdMessages(*threshold)",
            "jetstream.ConsumeErrHandler(r.reported)"]

    def test_no_other_option_of_consume_is_named(self):
        """nats.go v1.54.0's options for Consume are its Pull... types, StopAfter and
        ConsumeErrHandler (jetstream/jetstream_options.go)."""
        named = set(re.findall(r"\bjetstream\.(Pull\w+|StopAfter|ConsumeErrHandler)\b",
                               go_code(go_source(), keep_strings=False)))
        assert named == {"PullMaxMessages", "PullThresholdMessages", "ConsumeErrHandler"}

    def test_the_counts_default_to_nats_gos_own(self):
        """500 (DefaultMaxMessages), and half of it rounded up, which is what nats.go makes of a
        threshold of 0 (setDefaults, jetstream/pull.go)."""
        flags = go_flags()
        assert flags["max-messages"] == ("Int", "jetstream.DefaultMaxMessages")
        assert flags["threshold"] == ("Int", "0")
        body = go_function("run")
        assert "if *threshold == 0 {" in body
        assert body.index("*threshold = (*maxMessages + 1) / 2") < body.index("cons.Consume(")

    def test_half_rounded_up_is_what_the_threshold_rule_gives(self):
        """nats.go: int(math.Ceil(float64(MaxMessages) / 2)); this consumer: (max + 1) / 2, the
        same for every count it takes, which is at least 1."""
        assert "*maxMessages < 1 || *threshold < 0" in go_function("run")
        assert all((n + 1) // 2 == math.ceil(n / 2.0) for n in range(1, 100001))

    def test_the_expiry_on_record_is_nats_gos(self):
        assert "jetstream.DefaultExpires.Milliseconds()" in go_function("run")

    def test_only_a_leadership_change_is_survived(self):
        body = go_function("reported")
        assert re.findall(r"jetstream\.(Err\w+)", body) == ["ErrConsumerLeadershipChanged"]
        assert 'r.fail(fmt.Errorf("nats.go\'s Consume reported: %w", err))' in body

    def test_a_lost_connection_or_an_error_nats_go_reports_ends_the_run(self):
        body = go_function("run")
        assert "nats.DisconnectErrHandler(func(_ *nats.Conn, err error) {\n\t\t\tr.fail(" in body
        assert ("nats.ErrorHandler(func(_ *nats.Conn, _ *nats.Subscription, err error) {"
                "\n\t\t\tr.fail(") in body
        assert "if !r.stopping && r.err == nil {" in go_function("fail")


class TestTheModuleAndItsBuild:

    def test_the_only_libraries_it_imports_are_nats_gos(self):
        """go.mod's requirements then cover every package it builds."""
        outside = [path for path in go_imports() if "." in path.split("/")[0]]
        assert outside == ["github.com/nats-io/nats.go", "github.com/nats-io/nats.go/jetstream"]

    @pytest.mark.parametrize("path", go_imports())
    def test_every_import_is_used(self, path):
        """Go refuses to compile a file with an unused import, and nothing compiles it in CI."""
        source = go_source()
        code = go_code(source[source.index("\n)\n"):], keep_strings=False)
        assert re.search(r"\b%s\.[A-Z]" % re.escape(package_name(path)), code), (
            "%s is imported and not used" % path)

    def test_go_mod_pins_nats_go_and_the_go_line_its_requirements_need(self):
        mod = go_mod()
        assert re.search(r"^module natsgo-consumer$", mod, re.MULTILINE)
        assert re.search(r"^go 1\.26\.0$", mod, re.MULTILINE)
        assert not re.search(r"^toolchain\b", mod, re.MULTILINE), (
            "go1.26.0 is what the go line implies; a toolchain line saying so is dropped by the "
            "go command, which -mod=readonly turns into a stopped build")
        assert go_requirements() == PINS

    def test_nats_go_is_the_one_direct_requirement(self):
        mod = go_mod()
        assert re.findall(r"^require (\S+) (\S+)$", mod, re.MULTILINE) == [
            ("github.com/nats-io/nats.go", PINS["github.com/nats-io/nats.go"])]
        indirect = re.findall(r"^\t(\S+) (\S+) // indirect$", mod, re.MULTILINE)
        assert dict(indirect) == dict((path, version) for path, version in PINS.items()
                                      if path != "github.com/nats-io/nats.go")

    def test_go_sum_vouches_for_every_module_go_mod_names_and_no_other(self):
        lines = read(GO / "go.sum").splitlines()
        for line in lines:
            assert re.match(r"^[\w./-]+ v[\w.+-]+(/go\.mod)? h1:[A-Za-z0-9+/]{43}=$", line), line
        for path, version in go_requirements().items():
            assert sum(1 for line in lines if line.startswith("%s %s h1:" % (path, version))) == 1
            assert sum(1 for line in lines
                       if line.startswith("%s %s/go.mod h1:" % (path, version))) == 1
        assert len(lines) == 2 * len(go_requirements())

    def test_build_sh_pins_go_mods_nats_go_and_the_toolchain_its_go_line_implies(self):
        build = (GO / "build.sh").read_bytes().decode("utf-8")
        assert "\r" not in build, "the driver's bash reads a CRLF script as broken"
        assert "NATS_GO_VERSION=%s\n" % go_requirements()["github.com/nats-io/nats.go"] in build
        assert "GO_TOOLCHAIN=go%s\n" % re.search(r"^go (\S+)$", go_mod(),
                                                 re.MULTILINE).group(1) in build

    def test_build_sh_runs_harness_gos_build_with_this_consumers_pins(self):
        """Every command of harness/go/build.sh, with franz-go's names and pins made this
        consumer's, is a line of this one: the toolchain named exactly and fetched by the go
        command, a module go.sum does not vouch for refused, go vet before go build, and the
        binary's build record checked against the pins."""
        mapping = [("github.com/twmb/franz-go", "github.com/nats-io/nats.go"),
                   ("FRANZ_GO_VERSION", "NATS_GO_VERSION"), ("franz-consumer", "natsgo-consumer"),
                   ("franz-go", "nats.go"), ("harness/go/", "harness/go-nats/"),
                   ("v1.19.5", PINS["github.com/nats-io/nats.go"]), ("go1.23.11", "go1.26.0")]
        ours = set((GO / "build.sh").read_bytes().decode("utf-8").splitlines())
        theirs = (FRANZ / "build.sh").read_bytes().decode("utf-8").splitlines()
        commands = [line for line in theirs if line.strip() and not line.lstrip().startswith("#")]
        assert len(commands) > 20
        for line in commands:
            for old, new in mapping:
                line = line.replace(old, new)
            assert line in ours, line

    def test_what_is_built_is_not_committed(self):
        assert "out/" in read(GO / ".gitignore").splitlines()

    def test_the_readme_names_the_pins_go_mod_holds(self):
        readme = read(GO / "README.md")
        for path, version in go_requirements().items():
            assert "| %s | %s |" % (path, version) in readme
        assert "| toolchain | go1.26.0 |" in readme
        assert "bash harness/go-nats/build.sh" in readme and "GOTOOLCHAIN=go1.26.0" in readme

    @pytest.mark.parametrize("name", FRANZ_HELPERS)
    def test_each_helper_is_harness_gos(self, name):
        """The tables, the event log's name, the cells, the clock, the build record and the thread
        list are harness/go's code, so that the two Go consumers write alike."""
        def squeezed(source):
            return re.sub(r"\s+", " ", go_code(function_in(source, name))).strip()
        franz = squeezed(read(FRANZ / "main.go")).replace("franz-consumer", "natsgo-consumer")
        assert squeezed(go_source()) == franz


class TestTheThreadList:

    def test_its_columns_are_the_other_consumers(self):
        assert go_strings("threadColumns") == kafka_consumer_confluent.THREAD_COLUMNS

    def test_it_reads_the_kernels_list_and_writes_it_whole(self):
        assert re.search(r'\btasks\s*=\s*"/proc/self/task"', go_source())
        body = go_function("writeThreads")
        assert 'partial := path + ".tmp"' in body and "os.Rename(partial, path)" in body

    def test_it_is_written_once_consume_has_asked_for_messages(self):
        body = go_function("run")
        assert body.count("writeThreads(*threadsOut)") == 1
        assert body.index("cons.Consume(") < body.index("writeThreads(*threadsOut)") \
            < body.index("r.over(idle)")


class TestItProbesItsConnection:

    def test_a_ping_every_probe_ms_with_no_limit_a_stall_could_reach(self):
        body = go_function("probing")
        assert "o.PingInterval = time.Duration(probeMs) * time.Millisecond" in body
        assert "o.MaxPingsOut = 1 << 20" in body
        assert "if probeMs == 0 {\n\t\treturn func(*nats.Options) error { return nil }" in body

    def test_the_connection_is_made_with_it_and_its_value_is_on_record(self):
        body = go_function("run")
        assert "probing(*probeMs))" in body and "probe_ms=%d" in body
        assert 'fmt.Fprintln(os.Stderr, "natsgo-consumer: --probe-ms is at least 0")' in body
