from __future__ import annotations

import json
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.shared.exceptions import NonRetryableExecutionError


class DingTalkCallbackClient:
    def __init__(self, *, callback_url: str, host_allowlist: tuple[str, ...] = ()) -> None:
        self.callback_url = callback_url
        self.host_allowlist = host_allowlist
        self.sent_messages: list[dict[str, str]] = []

    def send_markdown(self, *, conversation_id: str, title: str, text: str) -> None:
        payload = {"conversation_id": conversation_id, "title": title, "text": text}
        self.sent_messages.append(payload)
        if not self.callback_url:
            return
        parsed = urlparse(self.callback_url)
        if self.host_allowlist and parsed.hostname not in self.host_allowlist:
            raise NonRetryableExecutionError(
                f"Callback host {parsed.hostname} is not allowed",
                safe_message="Callback host is not allowed",
            )
        request = Request(
            self.callback_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            response.read()
