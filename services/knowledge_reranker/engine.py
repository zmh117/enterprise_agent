"""固定 CPU Cross-Encoder；query 不截断，候选块按 token 窗口有界评分。"""

from collections.abc import Iterator
from dataclasses import dataclass
import os
from typing import Any

from app.modules.knowledge.domain.rerank_contract import (
    INFERENCE_THREADS,
    MAX_BATCH_PAIRS,
    MAX_BATCH_TOKENS,
    MAX_DOCUMENT_TOKENS,
    MAX_PAIR_TOKENS,
)
from app.modules.knowledge.domain.vector_contract import VectorError
from services.knowledge_embedding.online_queue import InferenceDeadline
from services.knowledge_reranker.model_files import MODEL_DIR, verify


@dataclass(repr=False)
class PreparedPairs:
    inputs: list[list[int]]
    truncated: list[bool]


def pair_ids(tokenizer: Any, query: list[int], document: list[int]) -> list[int]:
    # The pinned XLM-R tokenizer uses <s> A </s></s> B </s>.
    # Its current Transformers runtime no longer exposes the legacy build_inputs helper.
    return [
        tokenizer.cls_token_id,
        *query,
        tokenizer.sep_token_id,
        tokenizer.sep_token_id,
        *document,
        tokenizer.sep_token_id,
    ]


def window(blocks: list[list[int]], budget: int, separator: int) -> tuple[list[int], bool]:
    available = budget - (len(blocks) - 1)
    if available < len(blocks) or any(not block for block in blocks):
        raise VectorError("knowledge_rerank_input_limit")
    counts = [
        min(len(block), available // len(blocks) + int(i < available % len(blocks)))
        for i, block in enumerate(blocks)
    ]
    remaining = available - sum(counts)
    for i, block in enumerate(blocks):
        extra = min(remaining, len(block) - counts[i])
        counts[i] += extra
        remaining -= extra
    ids: list[int] = []
    for i, (block, count) in enumerate(zip(blocks, counts, strict=True)):
        if i:
            ids.append(separator)
        ids.extend(block[:count])
    return ids, any(count < len(block) for block, count in zip(blocks, counts, strict=True))


def prepare_pairs(
    tokenizer: Any, query: str, documents: list[list[str]], deadline: InferenceDeadline
) -> PreparedPairs:
    deadline.check()
    query_ids = tokenizer.encode(query, add_special_tokens=False, truncation=False, verbose=False)
    remaining = MAX_PAIR_TOKENS - len(query_ids) - tokenizer.num_special_tokens_to_add(pair=True)
    if not query_ids or remaining < 1:
        raise VectorError("knowledge_rerank_input_limit")
    inputs, truncated = [], []
    for blocks in documents:
        deadline.check()
        tokens = [
            tokenizer.encode(block, add_special_tokens=False, truncation=False, verbose=False)
            for block in blocks
        ]
        document, cropped = window(
            tokens, min(MAX_DOCUMENT_TOKENS, remaining), tokenizer.sep_token_id
        )
        pair = pair_ids(tokenizer, query_ids, document)
        if not 1 <= len(pair) <= MAX_PAIR_TOKENS:
            raise VectorError("knowledge_rerank_input_limit")
        inputs.append(pair)
        truncated.append(cropped)
    deadline.check()
    return PreparedPairs(inputs, truncated)


def microbatches(inputs: list[list[int]]) -> Iterator[list[list[int]]]:
    batch: list[list[int]] = []
    for pair in inputs:
        # Padding 也占用真实计算/内存预算。
        padded = max([len(pair), *(len(item) for item in batch)]) * (len(batch) + 1)
        if batch and (len(batch) >= MAX_BATCH_PAIRS or padded > MAX_BATCH_TOKENS):
            yield batch
            batch = []
        batch.append(pair)
    if batch:
        yield batch


class RerankerEngine:
    def __init__(self) -> None:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        verify()
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        torch.set_num_threads(INFERENCE_THREADS)
        torch.set_num_interop_threads(1)
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(MODEL_DIR), local_files_only=True, trust_remote_code=False
        )
        expected = self.tokenizer("query", "document", truncation=False)["input_ids"]
        actual = pair_ids(
            self.tokenizer,
            self.tokenizer.encode("query", add_special_tokens=False),
            self.tokenizer.encode("document", add_special_tokens=False),
        )
        if self.tokenizer.num_special_tokens_to_add(pair=True) != 4 or actual != expected:
            raise VectorError("knowledge_rerank_profile_mismatch")
        self.model = AutoModelForSequenceClassification.from_pretrained(
            str(MODEL_DIR),
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            weights_only=True,
            dtype=torch.float32,
        ).to("cpu")
        self.model.eval()
        if self.model.config.num_labels != 1:
            raise VectorError("knowledge_rerank_profile_mismatch")

    def rank(
        self, query: str, documents: list[list[str]], deadline: InferenceDeadline
    ) -> dict[str, Any]:
        import torch

        prepared = prepare_pairs(self.tokenizer, query, documents, deadline)
        ordered = sorted(enumerate(prepared.inputs), key=lambda item: (-len(item[1]), item[0]))
        scores: list[float] = [0.0] * len(ordered)
        offset = 0
        for batch in microbatches([ids for _, ids in ordered]):
            deadline.check()
            encoded = self.tokenizer.pad(
                [{"input_ids": ids, "attention_mask": [1] * len(ids)} for ids in batch],
                padding=True,
                return_tensors="pt",
            )
            with torch.inference_mode():
                logits = self.model(**encoded).logits.reshape(-1).float().tolist()
            deadline.check()
            for (position, _), score in zip(
                ordered[offset : offset + len(batch)], logits, strict=True
            ):
                scores[position] = score
            offset += len(batch)
        return {
            "scores": scores,
            "token_counts": [len(ids) for ids in prepared.inputs],
            "truncated": prepared.truncated,
        }
