"""The franz-go and Java consumers, held to the clients' interface by reading their sources.

The block after U runs Kafka's own consumers beside the project's, and reads the latency from the
captures on the client's host. Each consumer must leave the files scripts/kafka_consumer.py
leaves, identify each message by the partition and offset its library hands back, end with the
line every consumer ends with, and, asked for --threads-out, list its threads in the one form the
kit reads.

These are source checks, as tests/unit/test_two_clients_write_the_same_files.py makes for the Java
client: CI has neither a JVM that may run it nor a Go toolchain, and no test here may skip. The
compilers' own checks run where the clients are built, in harness/java/build.sh and
harness/go/build.sh.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
SCRIPTS = ROOT / "scripts"
JAVA = ROOT / "harness" / "java" / "src" / "LawConsumer.java"
GO = ROOT / "harness" / "go"

sys.path.insert(0, str(SCRIPTS))

import kafka_consumer_confluent  # noqa: E402
import law_clock  # noqa: E402


def read(path):
    """A source as its compiler reads it. Git checks these files out with CRLF line endings on
    Windows (core.autocrlf), and the checks below match line ends."""
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def python_fieldnames(which):
    """The `which`-th csv fieldnames list in scripts/kafka_consumer.py."""
    source = read(SCRIPTS / "kafka_consumer.py")
    start = [m.start() for m in re.finditer(r"fieldnames=\[", source)][which]
    return re.findall(r'"([^"]+)"', source[start:source.index("]", start)])


def go_source():
    return read(GO / "main.go")


def go_strings(name):
    """The string slice `var <name> = []string{...}` in main.go."""
    source = go_source()
    start = source.index("var %s = []string{" % name)
    return re.findall(r'"([^"]*)"', source[start:source.index("}", start)])


def go_function(name):
    """The body of `func <name>(` in main.go, to the closing brace at the start of a line."""
    source = go_source()
    start = source.index("\nfunc %s(" % name)
    return source[start:source.index("\n}\n", start)]


def go_elements(body, opening):
    """The elements of the composite literal that `opening` begins in `body`, split at the commas
    outside any parentheses, with runs of white space made one space."""
    start = body.index(opening) + len(opening)
    elements, depth, current = [], 0, ""
    for char in body[start:body.index("}", start)]:
        depth += {"(": 1, ")": -1}.get(char, 0)
        if char == "," and depth == 0:
            elements.append(current)
            current = ""
        else:
            current += char
    return [re.sub(r"\s+", " ", e).strip() for e in elements + [current]]


def go_imports():
    """The import paths of main.go's import block."""
    source = go_source()
    start = source.index("import (")
    return re.findall(r'"([^"]+)"', source[start:source.index(")", start)])


def go_mod():
    return read(GO / "go.mod")


def go_requirements():
    """{module path: version} for every require line of go.mod."""
    return dict(re.findall(r"^\s*(?:require\s+)?([\w./-]+\.[\w./-]+)\s+(v[\w.+-]+)",
                           go_mod(), re.MULTILINE))


def java_source():
    return read(JAVA)


class TestTheGoConsumerTakesTheFlagsTheInterfaceNames:

    def test_its_flags_are_the_interfaces_and_no_more(self):
        flags = re.findall(r'flags\.(?:String|Float64)\("([a-z-]+)"', go_source())
        assert sorted(flags) == sorted(["bootstrap", "topic", "group", "run-id", "out",
                                        "idle-seconds", "threads-out"])

    def test_the_defaults_are_kafka_consumers(self):
        source = go_source()
        assert 'flags.String("bootstrap", "localhost:9092",' in source
        assert 'flags.String("topic", "sb-events",' in source
        assert 'flags.Float64("idle-seconds", 15,' in source
        assert 'groupID = "sb-consumer-" + *runID' in source

    def test_a_run_without_its_run_id_or_its_output_is_refused(self):
        assert 'if *runID == "" || *out == "" {' in go_function("run")


class TestTheGoConsumerWritesKafkaConsumersFiles:

    def test_consumer_csv_has_kafka_consumers_columns(self):
        assert go_strings("consumerColumns") == python_fieldnames(0)

    def test_the_event_log_has_kafka_consumers_columns(self):
        assert go_strings("eventColumns") == python_fieldnames(1)

    def test_the_fields_it_copies_are_the_event_logs_after_its_event_id(self):
        columns = go_strings("eventColumns")
        assert go_strings("copied") == columns[columns.index("event_id") + 1:]

    def test_the_rows_are_built_in_the_columns_order(self):
        """The two literals that make the rows, read in order: the stamps and the broker's ids
        sit where the headers put them."""
        body = go_function("run")
        assert go_elements(body, "row := []string{") == [
            "*runID", '"kafka"', "*topic", "eventID", 'pythonCell(fields["match_id"])',
            'pythonCell(fields["t_sim_seconds"])', "tConsume", "tOutput"]
        assert go_elements(body, "event := []string{") == [
            "*runID", '"kafka"', "record.Topic", "strconv.FormatInt(int64(record.Partition), 10)",
            "strconv.FormatInt(record.Offset, 10)", "tConsume", "eventID"]

    def test_the_event_log_is_named_beside_the_output_as_python_names_it(self):
        assert 'strings.TrimSuffix(name, filepath.Ext(name))+"_events.csv"' in go_function(
            "beside")

    def test_rows_end_as_pythons_csv_module_ends_them(self):
        assert "writer.UseCRLF = true" in go_function("create")

    def test_values_are_written_as_pythons_csv_writer_writes_what_json_loads_made(self):
        body = go_function("pythonCell")
        for spelled in ('case "", "null":\n\t\treturn ""', 'case "true":\n\t\treturn "True"',
                        'case "false":\n\t\treturn "False"'):
            assert spelled in body

    def test_it_ends_with_the_line_every_consumer_ends_with_once_for_each_file(self):
        body = go_function("run")
        assert body.count('fmt.Printf("OK franz-go consumer: wrote %d rows -> %s\\n", written,') \
            == 2


class TestTheGoConsumersStampsAndIds:

    def test_the_receive_stamp_is_one_wall_clock_reading_under_two_names(self):
        """Go's time.Now() reads CLOCK_REALTIME for the wall clock; UnixNano is that reading."""
        body = go_function("run")
        assert body.count("received := time.Now()") == 1
        assert "tConsume := strconv.FormatInt(received.UnixNano(), 10)" in body
        assert "tOutput := strconv.FormatInt(time.Now().UnixNano(), 10)" in body
        assert body.index("received := time.Now()") < body.index("tOutput :=")

    def test_the_payload_decides_only_whether_a_message_is_this_runs(self):
        body = go_function("run")
        assert 'if id, ok := text(fields["run_id"]); !ok || id != *runID {' in body
        assert body.count('fields["event_id"]') == 1, "event_id is read once, for its column"

    def test_the_clock_is_held_to_the_bar_every_client_is(self):
        source = go_source()
        assert re.search(r"\bfinestUsableNs\s*=\s*%d\b" % law_clock.FINEST_USABLE_NS, source)
        assert re.search(r"\bclockSamples\s*=\s*%d\b" % law_clock.SAMPLES, source)
        assert "resolution <= 0 || resolution > finestUsableNs" in go_function("run")
        assert "clock_resolution_ns=%d" in go_function("run")


class TestTheGoConsumersLibrary:

    def test_it_consumes_one_topic_in_a_group_from_the_earliest_offset(self):
        body = go_function("run")
        for option in ("kgo.ConsumerGroup(groupID)", "kgo.ConsumeTopics(*topic)",
                       "kgo.ConsumeResetOffset(kgo.NewOffset().AtStart())",
                       "kgo.AllowAutoTopicCreation()", "kgo.OnPartitionsAssigned("):
            assert option in body

    def test_the_only_library_it_imports_is_franz_gos_client(self):
        """go.mod's requirements then cover every package it builds."""
        outside = [path for path in go_imports() if "." in path.split("/")[0]]
        assert outside == ["github.com/twmb/franz-go/pkg/kgo"]

    @pytest.mark.parametrize("path", go_imports())
    def test_every_import_is_used(self, path):
        """Go refuses to compile a file with an unused import, and nothing compiles it in CI."""
        name = path.rsplit("/", 1)[-1]
        source = go_source()
        assert re.search(r"\b%s\." % re.escape(name), source[source.index("\n)\n"):]), (
            "%s is imported and not used" % path)

    def test_go_mod_pins_kgo_verifiers_franz_go_and_toolchain(self):
        mod = go_mod()
        assert re.search(r"^module franz-consumer$", mod, re.MULTILINE)
        assert re.search(r"^go 1\.23\.8$", mod, re.MULTILINE)
        assert re.search(r"^toolchain go1\.23\.11$", mod, re.MULTILINE)
        assert go_requirements() == {
            "github.com/twmb/franz-go": "v1.19.5",
            "github.com/klauspost/compress": "v1.18.0",
            "github.com/pierrec/lz4/v4": "v4.1.22",
            "github.com/twmb/franz-go/pkg/kmsg": "v1.11.2",
        }

    def test_go_sum_vouches_for_every_module_go_mod_names(self):
        lines = read(GO / "go.sum").splitlines()
        for line in lines:
            assert re.match(r"^[\w./-]+ v[\w.+-]+(/go\.mod)? h1:[A-Za-z0-9+/]{43}=$", line), line
        for path, version in go_requirements().items():
            assert sum(1 for line in lines if line.startswith("%s %s h1:" % (path, version))) == 1
            assert sum(1 for line in lines
                       if line.startswith("%s %s/go.mod h1:" % (path, version))) == 1

    def test_build_sh_holds_the_build_to_go_mods_pins(self):
        build = (GO / "build.sh").read_bytes().decode("utf-8")
        assert "\r" not in build, "the driver's bash reads a CRLF script as broken"
        assert "FRANZ_GO_VERSION=%s\n" % go_requirements()["github.com/twmb/franz-go"] in build
        assert "GO_TOOLCHAIN=%s\n" % re.search(r"^toolchain (\S+)$", go_mod(),
                                               re.MULTILINE).group(1) in build
        assert 'export GOTOOLCHAIN="$GO_TOOLCHAIN" GOFLAGS=-mod=readonly CGO_ENABLED=0' in build
        assert "go vet ." in build and "go build -o out/franz-consumer ." in build
        assert "go version -m out/franz-consumer > out/BUILD_INFO.txt" in build

    def test_what_is_built_is_not_committed(self):
        assert "out/" in read(GO / ".gitignore").splitlines()

    def test_the_readme_names_the_pins_go_mod_holds(self):
        readme = read(GO / "README.md")
        for path, version in go_requirements().items():
            assert "| %s | %s |" % (path, version) in readme
        assert "bash harness/go/build.sh" in readme and "GOTOOLCHAIN=go1.23.11" in readme


class TestTheGoConsumersThreadList:

    def test_its_columns_are_the_other_consumers(self):
        assert go_strings("threadColumns") == kafka_consumer_confluent.THREAD_COLUMNS

    def test_it_reads_the_kernels_list_and_writes_it_whole(self):
        source = go_source()
        assert re.search(r'\btasks\s*=\s*"/proc/self/task"', source)
        body = go_function("writeThreads")
        assert 'partial := path + ".tmp"' in body and "os.Rename(partial, path)" in body

    def test_it_is_written_once_assigned_and_at_the_end_if_never(self):
        body = go_function("run")
        assert "if !listed && assigned.Load() {" in body
        assert "if status == 0 && !listed {" in body
        assert body.count("writeThreads(*threadsOut)") == 2


class TestTheJavaConsumer:

    def test_it_takes_threads_out(self):
        assert 'String threadsOut = opt.get("threads-out");' in java_source()

    def test_the_poll_thread_is_named_before_the_client_is_made(self):
        source = java_source()
        name = re.search(r'static final String POLL_THREAD = "([^"]+)";', source).group(1)
        assert len(name.encode("utf-8")) <= 15, "the kernel keeps 15 bytes of a thread's name"
        assert source.index("Thread.currentThread().setName(POLL_THREAD);") \
            < source.index("new KafkaConsumer<>(props)")

    def test_its_thread_list_has_the_other_consumers_columns(self):
        header = re.search(r'static final String THREAD_HEADER = "([^"]+)";', java_source())
        assert header.group(1).split(",") == kafka_consumer_confluent.THREAD_COLUMNS

    def test_the_poll_thread_is_found_by_its_own_kernel_id_and_marked_as_fetching(self):
        source = java_source()
        assert 'Files.readSymbolicLink(Paths.get("/proc/thread-self"))' in source
        assert '(poll ? "poll+fetch" : "")' in source

    def test_the_list_is_written_once_assigned_and_at_the_end_if_never(self):
        source = java_source()
        assert "if (!listed && !consumer.assignment().isEmpty()) {" in source
        assert source.count("writeThreads(Paths.get(threadsOut));") == 2
        assert "StandardCopyOption.ATOMIC_MOVE" in source

    def test_it_uses_the_classic_group_protocol_by_name(self):
        assert 'props.put(ConsumerConfig.GROUP_PROTOCOL_CONFIG, "classic");' in java_source()

    def test_partition_and_offset_come_from_the_clients_record(self):
        source = java_source()
        start = source.index("eventWriter.write(runId);")
        logged = source[start:source.index("eventWriter.newLine();", start)]
        assert "Integer.toString(record.partition())" in logged
        assert "Long.toString(record.offset())" in logged

    def test_it_ends_with_the_line_every_consumer_ends_with_once_for_each_file(self):
        source = java_source()
        assert source.count('System.out.println("OK java consumer: wrote " + written') == 2
        assert "WROTE " not in source


class TestEveryConsumerEndsTheSameWay:
    """The interface: `OK <client> consumer: wrote N rows -> PATH` at the end, for each file."""

    @pytest.mark.parametrize("path,pattern", [
        (SCRIPTS / "kafka_consumer.py", r'print\(f"OK kafka consumer: wrote \{\w+\} rows -> \{'),
        (SCRIPTS / "kafka_consumer_confluent.py",
         r'print\("OK confluent consumer: wrote %d rows -> %s"'),
        (JAVA, r'System\.out\.println\("OK java consumer: wrote " \+ written \+ " rows -> "'),
        (GO / "main.go", r'fmt\.Printf\("OK franz-go consumer: wrote %d rows -> %s\\n"'),
    ], ids=["kafka-python", "confluent", "java", "franz-go"])
    def test_twice(self, path, pattern):
        assert len(re.findall(pattern, read(path))) == 2
