"""Deterministic test transport; never evidence of model relevance."""

from app.modules.knowledge.domain.rerank_contract import input_hashes
from app.modules.knowledge.domain.vector_contract import fingerprint
from app.modules.knowledge.infrastructure.reranker_profile import profile


class SyntheticReranker:
    profile_hash = fingerprint(profile())

    def __init__(self):
        self.calls = 0
        self.scores = None

    def rank(self, query, documents):
        self.calls += 1
        return {
            "profile_hash": self.profile_hash,
            "input_hashes": input_hashes(query, documents),
            "scores": self.scores if self.scores is not None else [0.0] * len(documents),
            "token_counts": [10] * len(documents),
            "truncated": [False] * len(documents),
        }
