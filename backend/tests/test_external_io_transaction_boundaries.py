from __future__ import annotations

import pytest

from app.modules.admin.infrastructure.rabbitmq_status import (
    RabbitMQQueueStatusAdapter,
)
from app.modules.attachments.storage import S3ObjectStorage
from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.delivery.infrastructure.adapters import (
    DingTalkStreamSessionWebhookDeliveryAdapter,
)
from app.modules.internal_api_platform.infrastructure.db.drivers import (
    MysqlExecutor,
)
from app.modules.internal_tools.infrastructure.internal_api_client import (
    HttpInternalApiClient,
    ToolRequestContext,
)
from app.modules.message_bus.infrastructure.rabbitmq_publisher import (
    RabbitMQPublisher,
)
from app.shared.config import ObjectStorageSettings, QueueSettings
from app.shared.database import Database, ExternalIOInUnitOfWorkError


def test_rabbitmq_publish_is_rejected_before_network_inside_uow() -> None:
    database = Database("sqlite:///:memory:")
    publisher = RabbitMQPublisher("amqp://unused", QueueSettings())
    try:
        with database.unit_of_work():
            with pytest.raises(
                ExternalIOInUnitOfWorkError,
                match="rabbitmq.publish_agent_message",
            ):
                publisher.publish_agent_job(
                    "event-1",
                    "job-1",
                    "correlation-1",
                )
    finally:
        database.close()


def test_internal_tool_http_is_rejected_before_transport_inside_uow() -> None:
    database = Database("sqlite:///:memory:")
    transport_called = False

    def forbidden_transport(*args: object, **kwargs: object) -> object:
        del args, kwargs
        nonlocal transport_called
        transport_called = True
        raise AssertionError("transport must not run")

    client = HttpInternalApiClient(
        "http://internal-api.invalid",
        urlopen_func=forbidden_transport,
    )
    context = ToolRequestContext(
        job_id="job-1",
        user_id="user-1",
        project_code="default",
    )
    try:
        with database.unit_of_work():
            with pytest.raises(
                ExternalIOInUnitOfWorkError,
                match="internal_api.http",
            ):
                client.get_er_context("orders", context)
        assert transport_called is False
    finally:
        database.close()


def test_dingtalk_delivery_is_rejected_before_transport_inside_uow() -> None:
    database = Database("sqlite:///:memory:")
    adapter = DingTalkStreamSessionWebhookDeliveryAdapter()
    route = ReplyRoute(
        type="dingtalk_stream_session_webhook",
        connector_id="",
        target={"session_webhook": "http://unused.invalid/webhook"},
    )
    try:
        with database.unit_of_work():
            with pytest.raises(
                ExternalIOInUnitOfWorkError,
                match="dingtalk.session_webhook_delivery",
            ):
                adapter.send(
                    connector=None,
                    route=route,
                    title="title",
                    text="text",
                )
    finally:
        database.close()


def test_database_tool_connection_is_rejected_inside_platform_uow() -> None:
    database = Database("sqlite:///:memory:")
    try:
        with database.unit_of_work():
            with pytest.raises(
                ExternalIOInUnitOfWorkError,
                match="tool_database.mysql",
            ):
                MysqlExecutor().execute(
                    None,  # type: ignore[arg-type]
                    "select 1",
                    timeout_seconds=1,
                    max_rows=1,
                )
    finally:
        database.close()


def test_rabbitmq_status_boundary_violation_is_not_swallowed_as_unavailable() -> None:
    database = Database("sqlite:///:memory:")
    adapter = RabbitMQQueueStatusAdapter("amqp://unused", QueueSettings())
    try:
        with database.unit_of_work():
            with pytest.raises(
                ExternalIOInUnitOfWorkError,
                match="rabbitmq.management_status",
            ):
                adapter.collect()
    finally:
        database.close()


def test_object_storage_is_rejected_before_client_call_inside_uow() -> None:
    database = Database("sqlite:///:memory:")
    client_called = False

    class ForbiddenS3Client:
        def get_object(self, **kwargs: object) -> object:
            del kwargs
            nonlocal client_called
            client_called = True
            raise AssertionError("client must not run")

    storage = S3ObjectStorage(ObjectStorageSettings(), client=ForbiddenS3Client())
    try:
        with database.unit_of_work():
            with pytest.raises(
                ExternalIOInUnitOfWorkError,
                match="object_storage.get",
            ):
                storage.get(key="object-key")
        assert client_called is False
    finally:
        database.close()
