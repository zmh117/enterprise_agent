"""显式准备固定重排模型；复用公开模型文件的摘要校验。"""

from pathlib import Path

from app.modules.knowledge.infrastructure.reranker_profile import MODEL
from services.knowledge_embedding.model_files import prepare_model, verify_model

MODEL_DIR = Path("/models") / MODEL["revision"]


def verify(root: Path = MODEL_DIR) -> None:
    verify_model(root, model=MODEL)


if __name__ == "__main__":
    try:
        prepare_model(MODEL_DIR, model=MODEL)
        print('{"event":"reranker_model_prepared"}', flush=True)
    except Exception:
        print('{"event":"reranker_model_prepare_failed"}', flush=True)
        raise SystemExit(1) from None
