"""Opt-in, disposable Redis conformance tests; never connects to configured business Redis.

RUN_REDIS_PAGINATION_INTEGRATION=1 .venv/bin/pytest -q \
    backend/tests/test_redis_scan_pagination_integration.py

Requires Docker and a local redis:7.4 image. Creates only synthetic keys in containers
owned by this fixture, with no mounted volumes; removes those exact containers on exit.
"""

from __future__ import annotations

import os
import random
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator

import pytest

from app.modules.mcp_tool_runtime.domain.addressing import ResourceBinding
from app.modules.mcp_tool_runtime.domain.topology import (
    Base,
    DatabaseEngine,
    Environment,
    RedisConnection,
    RedisMode,
    ResourceKind,
)
from app.modules.mcp_tool_runtime.infrastructure.redis_gateway import RealRedisGateway


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_REDIS_PAGINATION_INTEGRATION") != "1",
    reason="set RUN_REDIS_PAGINATION_INTEGRATION=1 to provision disposable Redis containers",
)


def _docker(*args: str) -> str:
    return subprocess.check_output(
        ["docker", *args], text=True, stderr=subprocess.STDOUT, timeout=30
    )


def _free_ports(count: int) -> list[int]:
    # Reserve a range below 55535 so each node's internal cluster bus port is valid too.
    for _ in range(100):
        start = random.randrange(20000, 30000)
        sockets: list[socket.socket] = []
        try:
            for port in range(start, start + count):
                listener = socket.socket()
                sockets.append(listener)
                listener.bind(("127.0.0.1", port))
            return list(range(start, start + count))
        except OSError:
            pass
        finally:
            for listener in sockets:
                listener.close()
    raise AssertionError("No local port range available for isolated Redis tests")


@pytest.fixture(scope="module", params=[RedisMode.STANDALONE, RedisMode.CLUSTER])
def redis_binding(request: pytest.FixtureRequest) -> Iterator[ResourceBinding]:
    redis = pytest.importorskip("redis")
    mode = request.param
    ports = _free_ports(3 if mode is RedisMode.CLUSTER else 1)
    name = "ea-pagination-test-" + uuid.uuid4().hex[:12]
    publish = [arg for port in ports for arg in ("-p", f"127.0.0.1:{port}:{port}")]
    commands = []
    for port in ports:
        cluster = (
            f" --cluster-enabled yes --cluster-config-file /tmp/nodes-{port}.conf"
            " --cluster-announce-ip 127.0.0.1"
            if mode is RedisMode.CLUSTER
            else ""
        )
        commands.append(
            f"redis-server --port {port} --bind 0.0.0.0 --protected-mode no"
            f" --save '' --appendonly no{cluster} &"
        )
    try:
        _docker(
            "run",
            "-d",
            "--name",
            name,
            "--tmpfs",
            "/data",
            *publish,
            "redis:7.4",
            "sh",
            "-c",
            "\n".join(commands) + "\nwait",
        )
        for port in ports:
            probe = redis.Redis(host="127.0.0.1", port=port, socket_timeout=1)
            try:
                for attempt in range(100):
                    try:
                        assert probe.ping()
                        break
                    except redis.ConnectionError:
                        if attempt == 99:
                            raise
                        time.sleep(0.1)
            finally:
                probe.close()
        if mode is RedisMode.CLUSTER:
            _docker(
                "exec",
                name,
                "redis-cli",
                "--cluster",
                "create",
                *(f"127.0.0.1:{port}" for port in ports),
                "--cluster-replicas",
                "0",
                "--cluster-yes",
            )
            for attempt in range(100):
                states = [
                    _docker("exec", name, "redis-cli", "-p", str(port), "cluster", "info")
                    for port in ports
                ]
                if all("cluster_state:ok" in state for state in states):
                    break
                if attempt == 99:
                    raise AssertionError("Disposable Redis cluster did not converge")
                time.sleep(0.1)
        connection = RedisConnection(host="127.0.0.1", port=ports[0], mode=mode)
        base = Base(code="fixture", engine=DatabaseEngine.MYSQL, redis=connection)
        yield ResourceBinding(
            environment=Environment(code="fixture", bases={"fixture": base}),
            base=base,
            kind=ResourceKind.REDIS,
            workshop=None,
            engine=DatabaseEngine.MYSQL,
            redis=connection,
        )
    finally:
        # Only this UUID-named disposable fixture; never delete user containers or volumes.
        _docker("rm", "-f", "-v", name)


@pytest.mark.parametrize("key_count,limit", [(0, 50), (50, 50), (51, 50), (501, 7)])
def test_live_scan_pages_recover_every_synthetic_key(
    redis_binding: ResourceBinding,
    key_count: int,
    limit: int,
) -> None:
    gateway = RealRedisGateway()
    prefix = "pagination-acceptance:" + uuid.uuid4().hex + ":"
    expected = {f"{prefix}{index:04d}" for index in range(key_count)}
    # This connection is exclusively to our disposable fixture, not a business resource.
    client = gateway._connect(redis_binding)
    try:
        for key in expected:
            client.set(key, "synthetic")
        # Populate a separate namespace so empty intermediate MATCH batches are exercised.
        for index in range(100):
            client.set(f"other-namespace:{index}", "synthetic")
    finally:
        client.close()
    collected: list[str] = []
    cursor: object = 0
    for _ in range(5000):
        response = gateway.scan(redis_binding, prefix + "*", limit, cursor)
        assert len(response.summary["keys"]) <= limit
        collected.extend(response.summary["keys"])
        cursor = response.metadata["next_provider_cursor"]
        assert response.truncated is (cursor != 0)
        if cursor == 0:
            break
    else:
        raise AssertionError("Redis pagination did not terminate")
    assert set(collected) == expected
    assert len(collected) == len(expected)  # Stable synthetic dataset: no duplicate/omitted pages.
