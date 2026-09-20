"""Synthetic dependencies on real HTTP; never mount business input or model files."""

from pathlib import Path

from fastapi.responses import JSONResponse

from backend.tests.support.ones_provider import create_app
from services.knowledge_embedding.api import create_app as embedding_app


class SyntheticEngine:
    def count(self, texts):
        return [min(len(text) + 2, 2000) for text in texts]

    def encode(self, texts):
        return [[1.0] + [0.0] * 1023 for _ in texts]


ones = create_app()


@ones.middleware("http")
async def controlled_provider(request, call_next):
    # Test-only failure injection, outside every production image and network.
    mode = Path("/fixture/provider-mode").read_text().strip()
    if request.url.path.endswith("/graphql") and mode != "allow":
        return JSONResponse({"error": "synthetic"}, status_code=int(mode))
    return await call_next(request)


embedding = embedding_app(SyntheticEngine())
