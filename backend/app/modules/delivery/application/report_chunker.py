from __future__ import annotations


class ReportChunker:
    def __init__(self, max_chars: int = 3500) -> None:
        self.max_chars = max(200, max_chars)

    def chunks(self, text: str) -> list[str]:
        if len(text) <= self.max_chars:
            return [text]
        return [
            text[index : index + self.max_chars] for index in range(0, len(text), self.max_chars)
        ]

    def titled_chunks(self, *, title: str, text: str) -> list[tuple[str, str]]:
        chunks = self.chunks(text)
        if len(chunks) == 1:
            return [(title, text)]
        total = len(chunks)
        return [
            (f"{title} part {index + 1}/{total}", f"part {index + 1}/{total}\n\n{chunk}")
            for index, chunk in enumerate(chunks)
        ]
