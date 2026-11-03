"""单次工具调用拥有的短期 Principal 续期；不改变原调用的截止或重试语义。"""

from contextvars import copy_context
import threading
import time
from typing import Any

from app.modules.knowledge.application.principal import stable_claims
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.infrastructure.readability_client import KnowledgeReadabilityClient
from app.modules.knowledge.infrastructure.reader_access import KnowledgePrincipalAccess
from app.shared.io_deadline import current_io_deadline, io_deadline
from app.shared.principal_token_contract import MAX_PRINCIPAL_TOKEN_BYTES
from services.knowledge_mcp_server.execution import CallControl

REFRESH_MARGIN_SECONDS = 60
REFRESH_TIMEOUT_SECONDS = 5


class InflightPrincipal:
    def __init__(
        self,
        token: str,
        tool: str,
        access: KnowledgePrincipalAccess,
        client: KnowledgeReadabilityClient,
        control: CallControl,
    ) -> None:
        self._token = token
        self._tool, self._access, self._client, self._control = tool, access, client, control
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._failed = False
        self._expires = 0
        self._binding: dict[str, Any] = {}

    @property
    def failed(self) -> bool:
        with self._lock:
            return self._failed

    def current(self) -> str:
        with self._lock:
            if self._failed or not self._token or self._expires <= time.time():
                raise KnowledgeGovernanceError("knowledge_principal_refresh_failed")
            return self._token

    def _validate(self, token: str) -> dict[str, Any]:
        self._access.authenticate(token, self._tool)
        return self._access.verifier.verify(
            token, required_scope=f"mcp:knowledge-mcp:{self._tool}:invoke"
        )

    def __enter__(self) -> "InflightPrincipal":
        try:
            claims = self._validate(self._token)
            self._binding = stable_claims(claims)
            self._expires = claims["exp"]
            self._authorization = self._access.authenticate(self._token, self._tool)
            self.current()
            if self._expires - time.time() <= REFRESH_MARGIN_SECONDS:
                self._renew()
            context = copy_context()
            self._worker = threading.Thread(
                target=lambda: context.run(self._run),
                name="knowledge-principal-refresh",
                daemon=True,
            )
            self._worker.start()
            return self
        except Exception:
            self._token = ""
            if not self._active():
                raise
            self._fail()
            raise KnowledgeGovernanceError("knowledge_principal_refresh_failed") from None

    def _renew(self) -> None:
        self._control.check()
        with io_deadline(
            min(REFRESH_TIMEOUT_SECONDS, self._control.remaining()),
            cancelled=lambda: self._stop.is_set() or self._control.cancelled.is_set(),
        ):
            value = self._client.renew_principal(self.current())
            if (
                not isinstance(value, dict)
                or set(value) != {"access_token", "expires_at"}
                or not isinstance(value["access_token"], str)
                or not 0 < len(value["access_token"]) <= MAX_PRINCIPAL_TOKEN_BYTES
                or type(value["expires_at"]) is not int
            ):
                raise ValueError
            token = value["access_token"]
            claims = self._validate(token)
            if (
                stable_claims(claims) != self._binding
                or claims["exp"] != value["expires_at"]
                or claims["exp"] <= self._expires
                or claims["exp"] <= time.time() + REFRESH_MARGIN_SECONDS
                or self._access.authenticate(token, self._tool) != self._authorization
            ):
                raise ValueError
            self._control.check()
            with self._lock:
                if not self._stop.is_set():
                    self._token, self._expires = token, claims["exp"]

    def _fail(self) -> None:
        with self._lock:
            self._failed = True
        self._control.cancelled.set()

    def _active(self) -> bool:
        deadline = current_io_deadline()
        return (
            not self._stop.is_set()
            and not self._control.cancelled.is_set()
            and self._control.remaining() > 0
            and (deadline is None or not deadline.expired())
        )

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._control.check()
                delay = self._expires - time.time() - REFRESH_MARGIN_SECONDS
                if delay <= 0:
                    self._renew()
                else:
                    self._stop.wait(min(1, delay, max(0, self._control.remaining())))
        except Exception:
            if self._active():
                self._fail()

    def __exit__(self, *_: Any) -> None:
        self._stop.set()
        if self._worker is not None:
            # 续期 I/O 继承原取消并额外限制 5 秒；不遗留失去所属调用的续期线程。
            self._worker.join()
        with self._lock:
            self._token = ""
            self._binding.clear()
