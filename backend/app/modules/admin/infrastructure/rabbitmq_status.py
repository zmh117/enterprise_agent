from __future__ import annotations

from datetime import datetime, timezone
import base64
import json
from typing import Any
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

from app.shared.config import QueueSettings


class RabbitMQQueueStatusAdapter:
    """Reads the RabbitMQ management API with an allowlist and a short timeout."""

    def __init__(self, rabbitmq_url: str, queue_settings: QueueSettings) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.queue_settings = queue_settings

    def collect(self) -> dict[str, Any]:
        collected_at = datetime.now(timezone.utc).isoformat()
        try:
            items = [self._status(item) for item in self._allowlist()]
        except Exception:
            return {
                "availability": "unavailable",
                "collected_at": collected_at,
                "error": {
                    "code": "queue_status_unavailable",
                    "message": "Queue status is temporarily unavailable",
                },
                "items": [],
            }
        return {
            "availability": "available",
            "collected_at": collected_at,
            "error": None,
            "items": items,
        }

    def _status(self, item: dict[str, Any]) -> dict[str, Any]:
        parsed = urlparse(self.rabbitmq_url)
        host = parsed.hostname or "localhost"
        management_port = 15672 if parsed.port in {None, 5672} else parsed.port + 10000
        vhost = unquote(parsed.path.removeprefix("/")) or "/"
        url = f"http://{host}:{management_port}/api/queues/{quote(vhost, safe='')}/{quote(item['name'], safe='')}"
        credentials = f"{unquote(parsed.username or 'guest')}:{unquote(parsed.password or 'guest')}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": "Basic " + base64.b64encode(credentials.encode()).decode(),
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=2) as response:
                payload = json.loads(response.read(128_000).decode("utf-8"))
            return {
                **item,
                "availability": "available",
                "ready": int(payload.get("messages_ready") or 0),
                "unacked": int(payload.get("messages_unacknowledged") or 0),
                "consumers": int(payload.get("consumers") or 0),
            }
        except Exception:
            return {
                **item,
                "availability": "unavailable",
                "ready": None,
                "unacked": None,
                "consumers": None,
            }

    def _allowlist(self) -> list[dict[str, Any]]:
        q = self.queue_settings
        return [
            {
                "name": q.job_queue,
                "purpose": "Agent jobs",
                "retry_of": None,
                "dead_letter_of": None,
            },
            {
                "name": q.retry_queue,
                "purpose": "Agent retry delay",
                "retry_of": q.job_queue,
                "dead_letter_of": None,
            },
            {
                "name": q.dead_queue,
                "purpose": "Agent dead letters",
                "retry_of": None,
                "dead_letter_of": q.job_queue,
            },
            {
                "name": q.legacy_retry_queue,
                "purpose": "Legacy retry compatibility",
                "retry_of": q.job_queue,
                "dead_letter_of": None,
            },
            {
                "name": q.attachment_queue,
                "purpose": "Attachment processing",
                "retry_of": None,
                "dead_letter_of": None,
            },
            {
                "name": q.attachment_retry_queue,
                "purpose": "Attachment retry",
                "retry_of": q.attachment_queue,
                "dead_letter_of": None,
            },
            {
                "name": q.attachment_dead_queue,
                "purpose": "Attachment dead letters",
                "retry_of": None,
                "dead_letter_of": q.attachment_queue,
            },
            {
                "name": q.webhook_queue,
                "purpose": "Webhook dispatch",
                "retry_of": None,
                "dead_letter_of": None,
            },
            {
                "name": q.webhook_dead_queue,
                "purpose": "Webhook dead letters",
                "retry_of": None,
                "dead_letter_of": q.webhook_queue,
            },
        ]
