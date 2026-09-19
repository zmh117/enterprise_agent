"""只读本地模型运行。此模块仅在独立模型镜像中导入。"""

import os

from app.modules.knowledge.domain.vector_contract import MAX_TOKENS, VectorError, validate_vector
from services.knowledge_embedding.model_files import MODEL_DIR, verify_model


class EmbeddingEngine:
    def __init__(self) -> None:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"] = "1"
        verify_model()
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(4)
        torch.set_num_interop_threads(1)
        self.model = SentenceTransformer(
            str(MODEL_DIR),
            device="cpu",
            local_files_only=True,
            trust_remote_code=False,
            model_kwargs={"weights_only": True, "use_safetensors": False, "dtype": torch.float32},
        )
        self.model.max_seq_length = MAX_TOKENS
        self.model.eval()
        if self.model.get_sentence_embedding_dimension() != 1024:
            raise VectorError("knowledge_embedding_profile_mismatch")

    def count(self, texts: list[str]) -> list[int]:
        encoded = self.model.tokenizer(texts, truncation=False, add_special_tokens=True)
        return [len(ids) for ids in encoded["input_ids"]]

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(
            texts,
            batch_size=len(texts),
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
            precision="float32",
        ).tolist()
        return [validate_vector(v) for v in vectors]
