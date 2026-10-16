"""Section VI gives the fix that keeps every client thread's wait out of a latency, for any tool.

15 Oct 2026, the author: "the general solution must be clearly explained for the industry wide
audience in the paper". Until then the fix was two paragraphs, third in Section VI, and said of
tools only that one "can read the kernel's timestamps on its own sockets". Section VI now opens
with the fix, says in four steps how a tool reads those timestamps, and says what a tool must
handle. These tests hold the steps to the module that took them in freeze 40
(scripts/so_timestamps.py), so the text cannot describe a fix the module does not implement, and
hold the paper's other mentions of the fix to Section VI.
"""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import so_timestamps as so  # noqa: E402


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


def flat(text):
    return " ".join(text.split())


def section(paper, label):
    """The \\section holding `label`, to the next \\section."""
    start = paper.index("\\label{%s}" % label)
    head = paper.rfind("\\section{", 0, start)
    end = paper.find("\\section{", start)
    return paper[head:end if end != -1 else len(paper)]


def paragraph(paper, opening):
    """The bold-led paragraph of Section VI that begins with `opening`, to the next one."""
    text = section(paper, "sec:practice")
    i = text.index("\\textbf{%s}" % opening)
    end = text.find("\n\n\\textbf{", i + 1)
    return text[i:end if end != -1 else len(text)]


def steps(paper):
    text = paragraph(paper, "Read those timestamps on the tool's own sockets.")
    body = text[text.index("\\begin{enumerate}"):text.index("\\end{enumerate}")]
    return [flat(item) for item in body.split("\\item")[1:]]


class TestSectionSixOpensWithTheFix:

    def test_the_first_rule_is_the_fix(self, paper):
        text = section(paper, "sec:practice")
        # A rule opens its paragraph; the table caption's bold title does not.
        heads = re.findall(r"\n\n\\textbf\{([^}]*)\}", text)
        assert heads[0] == "Let the kernel timestamp each message.", heads[:3]

    def test_the_lead_paragraph_says_the_fix_comes_first_and_why(self, paper):
        text = section(paper, "sec:practice")
        # 15 Oct 2026: Table IV spans both columns now, a table* float.
        lead = flat(text[text.index("\\label{sec:checks}"):text.index("\\begin{table")])
        # 15 Oct 2026, both referees of version 9 (A M2, B M3): the fix is scoped to a Linux
        # tool that can read its sockets' timestamps; the other steps find or shrink the wait.
        assert ("One fix ends the late reading in a Linux tool that can read its sockets' "
                "timestamps") in lead
        assert "take both of a message's timestamps from the kernel, not from the tool's threads" \
            in lead
        assert "The other steps find or shrink it" in lead

    def test_the_checks_table_leads_with_the_fix(self, paper):
        i = paper.index("\\label{tab:checks}")
        body = paper[paper.index("\\midrule", i):paper.index("\\bottomrule", i)]
        first = flat(body[len("\\midrule"):].split("\\\\")[0])
        # 15 Oct 2026: the row goes on, after a semicolon, to the clocks of two machines.
        assert first.startswith("Time each message between the kernel's timestamps as it leaves "
                                "and as it arrives, read on the tool's own sockets;"), first
        # The row names the socket form, so it quotes the socket runs (S3.10), not the captures'.
        assert "\\soFixMedianMovePct" in first and "\\soFixTailRatioLo" in first, first
        assert "(Supplement~S3.10)" in first and "\\fullFix" not in first, first

    def test_the_fix_says_where_the_waits_go(self, paper):
        """The waits are not dropped from the report, they are moved beside the latency: D is the
        sum of the three parts for every message, so a tool loses nothing by reporting W."""
        text = flat(paragraph(paper, "Let the kernel timestamp each message."))
        assert "\\emph{kernel-timed latency} $W$" in text
        # The two timestamps carry the names the steps use, where W is defined.
        assert "the transmit and receive timestamps" in text
        assert "from a message's transmit timestamp to its receive timestamp" in text
        assert "$D = H_{\\mathrm{out}} + W + H_{\\mathrm{in}}$ for every message" in text
        assert "beside what the application saw, $D$" in text


class TestTheStepsAreTheModulesSteps:
    """Each step says what scripts/so_timestamps.py does, and the count the text gives is the count
    of the list."""

    def test_four_steps_wherever_the_paper_counts_them(self, paper):
        assert len(steps(paper)) == 4
        text = flat(paragraph(paper, "Read those timestamps on the tool's own sockets."))
        assert "in four steps" in text
        intro = flat(section(paper, "sec:intro"))
        # 15 Oct 2026: "a Linux tool can read on its own sockets in four steps".
        assert "can read on its own sockets in four steps" in intro

    def test_step_one_asks_for_what_the_module_asks_for(self, paper):
        first = steps(paper)[0]
        assert "software timestamps for transmit and receive" in first
        assert "an identifier for each write" in first
        # The identifier counts bytes from the moment the option is on, so it must be on first.
        assert "before its first write" in first
        assert "so that byte offsets count from the first byte sent" in flat(so.__doc__)
        for where in ("software", "sched"):
            flags = so.Ledger(where).flags
            assert flags & so.SOF_TIMESTAMPING_RX_SOFTWARE and flags & so.SOF_TIMESTAMPING_SOFTWARE
            assert flags & so.SOF_TIMESTAMPING_OPT_ID, "the identifier for each write"
            assert flags & so.TRANSMIT[where]

    def test_step_two_keys_each_write_as_the_module_does(self, paper):
        second = steps(paper)[1]
        assert "\\emph{error queue}" in second
        assert "the byte offset of the write's last byte" in second
        assert "with the byte offset of the call's last byte (OPT_ID)" in flat(so.__doc__)

    def test_step_two_says_why_the_queue_is_drained_at_every_write_and_read(self, paper):
        second = steps(paper)[1]
        # 15 Oct 2026: the step says which queue it reads and who spins.
        assert "Read the error queue at every write and read" in second
        assert "a client that polls the socket spins" in second
        doc = flat(so.__doc__)
        assert "The error queue is drained on every send and read" in doc
        assert "a client waiting on it would spin" in doc

    def test_step_three_names_the_packet_a_read_returns(self, paper):
        """Linux overwrites the read's timestamp with each packet the read consumes
        (tcp_update_recv_tstamps in net/ipv4/tcp.c, read 15 Oct 2026), so it is the last one's."""
        assert "that of the last packet the read consumed" in steps(paper)[2]
        assert "that of the last packet the read consumed" in flat(so.__doc__)

    def test_the_module_the_text_cites_is_the_one_tested(self, paper):
        text = flat(paragraph(paper, "Read those timestamps on the tool's own sockets."))
        cited = re.search(r"\\brk\{(scripts/[^}]+)\}", text).group(1)
        assert cited == "scripts/so_timestamps.py" and (REPO / cited).is_file()
        # How a module beneath unchanged libraries knows which messages a write or read carried.
        # 15 Oct 2026: the fourth step says it, "Find each message in the bytes".
        assert "Find each message in the bytes" in text
        assert "Each event id is found in the bytes" in flat(so.__doc__)
        assert "(Supplement~S3.10)" in text


class TestWhatAToolMustHandle:

    def test_each_requirement_is_named(self, paper):
        text = flat(paragraph(paper, "What a tool must handle."))
        # 15 Oct 2026, both referees of version 9: the drained read and the pull consumer's
        # wait, the kernel thread's wait and the card's clock, the timestamp taken before the
        # packet scheduler (A m12: the kernel documentation's name for it), two machines' clocks,
        # Java and kernel bypass.
        for phrase in ("times the earlier ones late",
                       "which is the consumer's wait",
                       "A pull consumer",
                       "taken before the packet scheduler (\\texttt{TX\\_SCHED})",
                       "a card's hardware timestamp",
                       "on a clock of its own that the tool must tie to the system's",
                       "on two machines, $W$ spans two clocks",
                       "so a Java tool needs a native call",
                       "A kernel-bypass stack has no kernel timestamps at all",
                       "A tool that cannot yet take them needs what follows"):
            assert phrase in text, phrase

    def test_the_figures_it_quotes_are_the_ledgers(self, paper):
        text = flat(paragraph(paper, "What a tool must handle."))
        # 15 Oct 2026: the card's lead moved to the socket paragraph, and the share of reads
        # whose receive timestamps matched the captures' to Supplement S3.10.
        for macro in ("\\soFixQueueLeadLoUs", "\\soFixQueueLeadHiUs",
                      "\\osPullTopLoPct", "\\osPullTopHiPct"):
            assert macro in text, macro
        sockets = flat(paragraph(paper, "Read those timestamps on the tool's own sockets."))
        for macro in ("\\fullFixKernelDelayLoUs", "\\fullFixKernelDelayHiUs"):
            assert macro in sockets, macro
        assert "\\soFixSameReceivePct" in (REPO / "supplement.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def note():
    """Supplement S3.10's paragraph for a tool's author, its line breaks folded."""
    text = (REPO / "supplement.tex").read_text(encoding="utf-8")
    i = text.index("For a tool's author, the module's choices are these.")
    return flat(text[i:text.index("\n\n", i)])


class TestTheSupplementGivesTheModulesChoices:
    """Supplement S3.10's paragraph for a tool's author names the flags, the order of things and
    the two traps the pilot met. Each is held to the module or to F2's record."""

    def test_every_flag_it_names_is_one_the_module_asks_for(self, note):
        named = set(re.findall(r"\\texttt\{(?:SOF\\_TIMESTAMPING\\_)?([A-Z\\_]+)\}", note))
        named = {n.replace("\\_", "_") for n in named}
        assert named == {"TX_SCHED", "TX_SOFTWARE", "RX_SOFTWARE", "SOFTWARE", "OPT_ID",
                         "OPT_TSONLY"}, named
        for name in named:
            value = getattr(so, "SOF_TIMESTAMPING_" + name)
            assert any(so.Ledger(where).flags & value for where in so.TRANSMIT), name

    def test_the_repeated_timestamp_is_the_records_and_the_first_is_kept(self, note):
        assert "came back twice for every write, and the module keeps the first" in note
        record = flat((REPO / "docs" / "results" / "so_fix" / "README.md")
                      .read_text(encoding="utf-8"))
        assert "arrives for every send, twice; the first is kept" in record
        source = (REPO / "scripts" / "so_timestamps.py").read_text(encoding="utf-8")
        drain = source[source.index("def _drain("):source.index("class TimestampingSocket")]
        assert "stream.keys.setdefault(key, ns)" in drain, "a later repeat must not overwrite"

    def test_the_queue_is_read_only_when_poll_says_so(self, note):
        assert "only when \\texttt{poll()} reports something waiting there" in note
        assert "the pilot's first three \\kafka{} attempts failed" in note
        assert "POLLERR" in flat(so._queued.__doc__)
        record = flat((REPO / "docs" / "results" / "so_fix" / "README.md")
                      .read_text(encoding="utf-8"))
        assert "On Kafka all three attempts failed before a message was sent" in record

    def test_it_cites_the_kernels_own_account(self, note):
        assert "~\\cite{linux_timestamping}" in note
        bib = (REPO / "manuscript_references.bib").read_text(encoding="utf-8")
        assert "https://docs.kernel.org/networking/timestamping.html" in bib


class TestTheOtherMentionsAgree:

    def test_the_abstract_says_any_tool_can_read_them(self, paper):
        abstract = flat(paper[paper.index("\\begin{abstract}"):paper.index("\\end{abstract}")])
        # 15 Oct 2026, both referees of version 9 (A M2, B M3): the abstract names Linux and
        # the tool's own sockets, and no longer says "even under load" (block L, L-b).
        # 16 Oct 2026: and scopes the claim, since at 2,000 messages a second a pull consumer's
        # wait enters W (referee A, M2 fix 2: "any scope condition").
        assert ("Kernel timestamps, read on a tool's own Linux sockets, exclude the "
                "clock-reading threads' wait at modest rates.") in abstract
        assert "even under load" not in abstract

    def test_the_conclusion_says_what_to_report(self, paper):
        conclusion = flat(section(paper, "sec:conclusion"))
        # 15 Oct 2026: the conclusion scopes the stillness to fifty messages a second.
        # 16 Oct 2026: what to report comes first and the scope after it, so the clause no longer
        # splits "report that latency" from "beside the end-to-end latency"; the scope names the
        # kernel-timed latency, since an "it" after "the end-to-end latency" read as that one.
        assert ("On Linux a tool can time each message between the kernel's timestamps, read on "
                "its own sockets, and report that latency beside the end-to-end latency. At fifty "
                "messages a second the kernel-timed latency held no client thread's wait.") \
            in conclusion

    def test_the_limits_stay_in_section_viii(self, paper):
        """The author's rule (B26): each limit of the study is stated, whole, in Section VIII. The
        fix's are its rate, pair, kernel and single machine, where its timestamps were taken, and
        its unmeasured cost."""
        limits = flat(section(paper, "sec:limitations"))
        # 15 Oct 2026, both referees of version 9: the scope names partition, load and rate, and
        # the module's cost is measured now (A M2.4, B m35), in Section VI, so Section VIII no
        # longer calls it unmeasured.
        assert ("Those tests used one pair of machines and one kernel, with one partition, "
                "background load on the client machine alone, and the producer and the consumer "
                "on one machine") in limits
        assert "judged at fifty messages a second only" in limits
        assert "we did not measure what taking the timestamps costs a tool" not in limits
        sockets = flat(paragraph(paper, "Read those timestamps on the tool's own sockets."))
        assert "\\moduleCostKafkaLo" in sockets and "\\moduleTailHi" in sockets
        assert "the clients used neither encryption nor compression" in limits
        assert "though we did not test it" not in flat(paragraph(paper, "What a tool must handle.")), \
            "a limit of the study belongs in Section VIII, not with the requirements"
