"""Loopback fixture controlled over stdin by the extension's browser test."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time

from contextlib import ExitStack

import uvicorn

from backend.tests.helpers import grant_test_application_access
from backend.tests.test_browser_extension_stream import (
    emit_delta,
    make_member,
    prepare,
    start_events,
)


def start_server(resources: ExitStack, recording_mode: bool):
    os.environ.update(
        BUILD_SOURCE_REVISION="test-revision", BUILD_ID="test-build", BUILD_PLATFORM="linux/amd64"
    )
    tools = ("search_recording", "get_recording_evidence") if recording_mode else ()
    api, app_id, password = prepare(tools=tools, secure_cookies=True)
    c = api.state.container
    member = make_member(c, password)
    grant_test_application_access(
        c, application_id=app_id, role_code="operators", user_id=member["id"], capabilities=tools
    )
    if os.environ.get("EA_TEST_SIGNIN_RECOVERY") == "1":
        second = c.identity_repository.create_user(
            username="demo-second", display_name="第二位合成操作员"
        )
        c.identity_repository.set_password_hash(
            second["id"], c.auth_service.passwords.hash(password)
        )
        grant_test_application_access(
            c,
            application_id=app_id,
            role_code="second-operators",
            user_id=second["id"],
            capabilities=tools,
        )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    files = None
    if recording_mode:
        from backend.tests.support.browser_recording_fixture import enable_recordings

        files = enable_recordings(resources, api, sock.getsockname()[1])
    srv = uvicorn.Server(uvicorn.Config(api, log_level="error", access_log=False))
    thread = threading.Thread(target=srv.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    while not srv.started and thread.is_alive():
        time.sleep(0.03)
    if not srv.started:
        raise RuntimeError("Fixture failed to start")
    # A fresh synthetic account in a temporary database. The driver consumes this pipe in memory.
    print(
        json.dumps(
            {
                "port": sock.getsockname()[1],
                "username": member["username"],
                "password": password,
            }
        ),
        flush=True,
    )
    return c, sock, srv, thread, files


def run_fixture(resources: ExitStack) -> None:
    recording_mode = os.environ.get("EA_TEST_RECORDING") == "1"
    c, sock, srv, thread, files = start_server(resources, recording_mode)
    evidence = None
    fragments = [
        "我查一下。\n\n**缺",
        "少批号**。\n\n|项目|结果|\n|---|---|\n",
        '|校验|退回|\n\n```json\n{"ok":false}\n```',
    ]
    step = 0
    retry = 0
    try:
        for command in sys.stdin:
            if command.strip() == "stop":
                break
            if command.strip() == "expire-recording" and files is not None:
                keys, _ = files.store.recording_keys("", 100)
                assert len(keys) == 2
                c.database.execute("update browser_recording set expires_at=0")
                files.cleanup()
                keys, _ = files.store.recording_keys("", 100)
                indexed = c.database.execute_one(
                    "select count(*) as n from browser_recording_evidence"
                )["n"]
                print(json.dumps({"indexed": indexed, "stored_parts": len(keys)}), flush=True)
                continue
            if command.strip() == "captured-save" and files is not None:
                from backend.tests.support.browser_recording_fixture import controlled_capture

                print(json.dumps(controlled_capture(c)), flush=True)
                continue
            if command.strip() == "end-session":
                c.database.execute(
                    "update user_session set idle_expires_at='2000-01-01T00:00:00+00:00'"
                )
                print(json.dumps({"ended": True}), flush=True)
                continue
            if command.strip() == "expire":
                c.database.execute(
                    "update browser_extension_credential set expires_at=0 where kind='access'"
                )
                print(json.dumps({"expired": True}), flush=True)
                continue
            if recording_mode and command.strip() in {"follow-2", "follow-3"}:
                from backend.tests.support.browser_recording_fixture import controlled_followup

                print(
                    json.dumps(controlled_followup(c, int(command.strip()[-1]), evidence)),
                    flush=True,
                )
                continue
            assert command.strip() in {"advance", "attempt-fails"}
            jobs = c.database.execute(
                "select j.id,j.session_id from agent_job j join browser_message_receipt r on r.job_id=j.id"
            )
            assert len(jobs) == 1
            job = jobs[0]["id"]
            if command.strip() == "attempt-fails":
                assert step == 0 and retry == 0
                c.database.execute(
                    """update agent_job set status='RUNNING',locked_by='synthetic-worker',
                    worker_claim_version=1,worker_lease_until='2099-01-01T00:00:00+00:00' where id=?""",
                    (job,),
                )
                start_events(c, job)
                emit_delta(c, job, 3, "上一轮的合成草稿")
                retry = 1
                print(json.dumps({"failed_attempt": 0}), flush=True)
                continue
            if step == 0:
                c.database.execute(
                    """update agent_job set status='RUNNING',locked_by='synthetic-worker',worker_claim_version=1,
                    worker_lease_until='2099-01-01T00:00:00+00:00',retry_count=? where id=?""",
                    (retry, job),
                )
                start_events(c, job, retry)
                if recording_mode:
                    initial = c.agent_repository.get_job(job)

                    def search(filters):
                        return c.tool_service.call_tool(
                            job_id=job,
                            user_id=initial.internal_user_id,
                            project_code=initial.project_code,
                            tool_name="search_recording",
                            arguments=filters,
                        ).summary

                    save = search({"action": "submit"})["hits"][0]["evidence_id"]
                    evidence = search({"related_to": save, "business_outcome": "failure"})["hits"][
                        0
                    ]["evidence_id"]
            if step < len(fragments):
                emit_delta(c, job, 3 + step, fragments[step])
            else:
                with c.database.unit_of_work():
                    final = "".join(fragments)
                    c.session_repository.add_message(
                        session_id=jobs[0]["session_id"],
                        job_id=job,
                        role="assistant",
                        content=final,
                    )
                    c.database.execute(
                        "update agent_job set status='SUCCEEDED',result=? where id=?", (final, job)
                    )
            step += 1
            print(json.dumps({"step": step, "jobs": len(jobs)}), flush=True)
    finally:
        srv.should_exit = True
        thread.join(timeout=5)
        sock.close()
        c.database.close()


def main() -> None:
    with ExitStack() as resources:
        run_fixture(resources)


if __name__ == "__main__":
    main()
