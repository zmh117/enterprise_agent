"""SVN XML records only: bounded parser state, no whole-output buffer or disk spool."""

from collections.abc import Callable, Iterator
from typing import cast
import xml.etree.ElementTree as ET

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError

MAX_METADATA_BYTES = 256 * 1024 * 1024
MAX_RECORD_BYTES = 256 * 1024
MAX_METADATA_ENTRIES = 100_000
MAX_XML_DEPTH = 32


class SvnXmlRecords:
    def __init__(self, path: tuple[str, ...], consume: Callable[[ET.Element], None]) -> None:
        self.path, self.consume = path, consume
        self.parser = ET.XMLPullParser(events=("start", "end"))
        self.stack: list[ET.Element] = []
        self.tail = b""
        self.pending = self.count = self.bytes = 0
        self.complete = False

    def feed(self, block: bytes) -> None:
        self.bytes += len(block)
        self.pending += len(block)
        guard = (self.tail + block).upper()
        self.tail = guard[-16:]
        if b"<!DOCTYPE" in guard or b"<!ENTITY" in guard or b"\x00" in block:
            raise CodeKnowledgeError("code_svn_response_invalid")
        if self.bytes > MAX_METADATA_BYTES or self.pending > MAX_RECORD_BYTES:
            raise CodeKnowledgeError("CODE_SVN_METADATA_LIMIT")
        try:
            self.parser.feed(block)
            self._events()
        except ET.ParseError:
            raise CodeKnowledgeError("code_svn_response_invalid") from None

    def _events(self) -> None:
        for event, node in cast(Iterator[tuple[str, ET.Element]], self.parser.read_events()):
            if event == "start":
                self.stack.append(node)
                if len(self.stack) > MAX_XML_DEPTH:
                    raise CodeKnowledgeError("CODE_SVN_METADATA_LIMIT")
                if len(self.stack) == 1 and node.tag != self.path[0]:
                    raise CodeKnowledgeError("code_svn_response_invalid")
            else:
                if tuple(n.tag for n in self.stack) == self.path:
                    self.count += 1
                    if self.count > MAX_METADATA_ENTRIES:
                        raise CodeKnowledgeError("CODE_CHECKOUT_INVENTORY_LIMIT")
                    self.consume(node)
                    self.pending = 0
                    self.stack[-2].remove(node)
                    node.clear()
                elif len(self.stack) <= len(self.path):
                    # No unbounded accumulation of unknown records or wrappers.
                    if node.tag not in self.path:
                        raise CodeKnowledgeError("code_svn_response_invalid")
                    if len(self.stack) > 1:
                        self.stack[-2].remove(node)
                    else:
                        self.complete = True
                    node.clear()
                self.stack.pop()

    def finish(self) -> None:
        try:
            self.parser.close()
            self._events()
        except ET.ParseError:
            raise CodeKnowledgeError("code_svn_response_invalid") from None
        if not self.complete or self.stack:
            raise CodeKnowledgeError("code_svn_response_invalid")
