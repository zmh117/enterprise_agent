"""Large output, parser bounds and cancellation without proprietary source or a server."""

import sys
import tracemalloc

import pytest

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_svn_stream import SvnXmlRecords
from backend.tests.test_code_svn_execution import source_for


def test_records_over_eight_mib_release_xml_nodes():
    count = 0

    def consume(node):
        nonlocal count
        assert node.findtext("name") == "a" * 1000
        count += 1

    row = b'<entry kind="file"><name>' + b"a" * 1000 + b"</name></entry>"
    tracemalloc.start()
    try:
        parser = SvnXmlRecords(("lists", "list", "entry"), consume)
        parser.feed(b"<lists><list>")
        for _ in range(12000):
            parser.feed(row)
        parser.feed(b"</list></lists>")
        parser.finish()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert count == 12000 and parser.bytes > 8 * 1024**2
    assert peak < 2 * 1024**2


@pytest.mark.parametrize(
    "data",
    [
        b'<!DOCTYPE info [<!ENTITY x "secret">]><info/>',
        b"<info><entry>",
        b"<wrong/>",
        b"<info>" + b"<a>" * 33,
        b"<info><entry>" + b"x" * (256 * 1024),
        b"\x00<info/>",
    ],
)
def test_unsafe_or_incomplete_xml_is_rejected(data):
    parser = SvnXmlRecords(("info", "entry"), lambda node: None)
    with pytest.raises(CodeKnowledgeError):
        for pos in range(0, len(data), 1024):
            parser.feed(data[pos : pos + 1024])
        parser.finish()


def test_dtd_split_across_chunks_is_rejected():
    parser = SvnXmlRecords(("info", "entry"), lambda node: None)
    parser.feed(b"<!DOC")
    with pytest.raises(CodeKnowledgeError, match="response_invalid"):
        parser.feed(b"TYPE info><info/>")


def test_entry_and_total_byte_limits_remain_effective(monkeypatch):
    from app.modules.knowledge.infrastructure import code_svn_stream

    monkeypatch.setattr(code_svn_stream, "MAX_METADATA_ENTRIES", 2)
    parser = SvnXmlRecords(("info", "entry"), lambda node: None)
    with pytest.raises(CodeKnowledgeError, match="INVENTORY_LIMIT"):
        parser.feed(b"<info><entry/><entry/><entry/></info>")
    monkeypatch.setattr(code_svn_stream, "MAX_METADATA_BYTES", 8)
    parser = SvnXmlRecords(("info", "entry"), lambda node: None)
    with pytest.raises(CodeKnowledgeError, match="METADATA_LIMIT"):
        parser.feed(b"<info></info>")


def test_download_drains_large_stdout_and_stderr_without_buffering(tmp_path):
    executable = tmp_path / "svn"
    executable.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "for i in range(160):\n"
        ' sys.stdout.buffer.write(b"progress" * 10000)\n'
        ' sys.stderr.buffer.write(b"warning" * 1000)\n'
    )
    executable.chmod(0o700)
    assert source_for(tmp_path, executable).execute("update", [], timeout=10, limit=None) == b""


def test_streaming_process_reads_large_xml_and_reports_only_safe_limit_metadata(tmp_path):
    executable = tmp_path / "svn"
    executable.write_text(
        f"#!{sys.executable}\nimport sys\n"
        'print("<info>")\n'
        'for i in range(12000): print("<entry><path>" + "private" * 150 + "</path></entry>")\n'
        'print("</info>")\n'
    )
    executable.chmod(0o700)
    source = source_for(tmp_path, executable)
    count = []
    source.records("info", [], ("info", "entry"), lambda node: count.append(1))
    assert len(count) == 12000
    with pytest.raises(CodeKnowledgeError) as caught:
        source.execute("info", [], timeout=10, limit=1024)
    assert caught.value.diagnostic["operation"] == "info"
    assert caught.value.diagnostic["output_stream"] == "stdout"
    assert caught.value.diagnostic["observed_bytes"] > 1024
    assert "private" not in str(vars(caught.value))
