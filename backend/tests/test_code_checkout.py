"""持久 SVN 检出边界；合成数据，不读取实际凭据或工程正文。"""

import json
from threading import Event
from types import SimpleNamespace

import pytest

from app.cli.code_checkout_worker import tick
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_checkout_client import registered_url, selection
from app.modules.knowledge.infrastructure.code_checkout_jobs import CodeCheckoutJobs
from backend.tests.test_knowledge_api import managed as managed_fixture
from backend.tests.test_unified_identity_rbac import login, csrf_headers

managed = managed_fixture
URL = "https://localhost:18443/repos/mes/trunk"


@pytest.fixture
def checkout(managed, tmp_path, monkeypatch):
    runtime, client, _, admin, _ = managed
    config = tmp_path / "checkout.json"
    config.write_text(
        json.dumps(
            {
                "mes-local": {
                    "branch_url": "https://code-svn:8443/repos/mes/trunk",
                    "public_url": URL,
                    "repository_uuid": "synthetic-uuid",
                    "branch_path": "/trunk",
                    "auth_ref": "mes-local",
                }
            }
        )
    )
    monkeypatch.setenv("CODE_CHECKOUT_REGISTRY_FILE", str(config))
    monkeypatch.setenv("CODE_CHECKOUT_ENABLED", "true")
    return CodeCheckoutJobs(runtime.database, admin, config), client, tmp_path


def browse(jobs, key="browse-one"):
    return jobs.submit_browse(actor_id="user_local_admin", url=URL, revision=None, request_key=key)


def ready(jobs):
    job = browse(jobs)
    jobs.update(
        job["id"],
        "SUCCEEDED",
        {
            "revision": 2,
            "directories": [
                "set_server",
                "set_server/config",
                "set_web",
                "set_web/EBR",
                "set_web/JTH",
            ],
        },
    )
    return job["id"]


def test_registered_targets_and_selection_are_closed(checkout):
    jobs, _, _ = checkout
    for url in [
        "http://localhost/repo",
        "https://user:synthetic@example.test/repo",
        URL + "/../../../private",
        "https://example.test/",
    ]:
        with pytest.raises(CodeKnowledgeError, match="unregistered"):
            registered_url(jobs.registry_file, url)
    for paths in [[], [".."], ["a", "a/b"], ["a", "a"], ["", "a"]]:
        with pytest.raises(CodeKnowledgeError):
            selection(paths, ["a", "a/b"])
    assert selection(["a/b"], ["a", "a/b"]) == ["a/b"]
    assert selection([""], ["a"]) == [""]


def test_persistence_idempotency_and_version_pinning(checkout):
    jobs, _, _ = checkout
    first = browse(jobs)
    assert browse(jobs) == first
    with pytest.raises(CodeKnowledgeError, match="idempotency_conflict"):
        jobs.submit_browse(
            actor_id="user_local_admin", url=URL, revision=3, request_key="browse-one"
        )
    jobs.update(
        first["id"],
        "SUCCEEDED",
        {
            "revision": 2,
            "directories": ["set_server", "set_web", "set_web/EBR"],
            "files": ["README.md"],
        },
    )
    args = dict(
        actor_id="user_local_admin",
        browse_job_id=first["id"],
        paths=["README.md", "set_server", "set_web/EBR"],
        folder="mes-r2",
        request_key="checkout-one",
    )
    result = jobs.submit_checkout(**args)
    assert jobs.submit_checkout(**args) == result
    reopened = CodeCheckoutJobs(jobs.db, jobs.admin, jobs.registry_file)
    assert reopened.get(result["id"])["request"]["revision"] == 2
    assert "README.md" in reopened.get(result["id"])["request"]["paths"]
    assert reopened.snapshot()["jobs"][0]["id"] == result["id"]
    with pytest.raises(CodeKnowledgeError):
        jobs.submit_checkout(**(args | {"folder": "../elsewhere", "request_key": "bad-target"}))


def test_http_admin_csrf_and_extra_parameters(checkout):
    jobs, client, _ = checkout
    base = "/api/platform/knowledge/code/checkouts"
    assert client.get(base).status_code in (401, 403)
    csrf = login(client, "admin")
    body = {"url": URL, "revision": None, "request_key": "http-one"}
    assert client.post(base + "/browse", json=body).status_code == 403
    assert (
        client.post(
            base + "/browse", headers=csrf_headers(csrf), json=body | {"command": "ignored"}
        ).status_code
        == 400
    )
    response = client.post(base + "/browse", headers=csrf_headers(csrf), json=body)
    assert response.status_code == 202
    assert client.get(base + "/" + response.json()["id"]).json()["state"] == "QUEUED"
    assert jobs.db.execute_one("select count(*) as n from agent_job")["n"] == 0


def test_worker_revalidates_registration_and_recovers_interruption(checkout):
    jobs, _, root = checkout
    prior = browse(jobs)
    jobs.update(prior["id"], "RUNNING")
    queued = browse(jobs, "second-browse")
    data = json.loads(jobs.registry_file.read_text())
    data["mes-local"]["repository_uuid"] = "changed-uuid"
    jobs.registry_file.write_text(json.dumps(data))
    assert tick(jobs, root, root, Event())
    assert jobs.get(prior["id"])["state"] == "INTERRUPTED"
    assert jobs.get(queued["id"])["error_code"] == "code_checkout_registration_changed"


def test_worker_uses_pinned_version_and_safe_failure(checkout, monkeypatch):
    jobs, _, root = checkout
    prior = ready(jobs)
    queued = jobs.submit_checkout(
        actor_id="user_local_admin",
        browse_job_id=prior,
        paths=["set_web/JTH"],
        folder="selected",
        request_key="worker-one",
    )
    observed = []

    def run(**kwargs):
        observed.append(kwargs)
        raise OSError("synthetic-private-exception-body")

    monkeypatch.setattr(
        "app.cli.code_checkout_worker.WorkingCopyClient",
        lambda *args: SimpleNamespace(checkout=run),
    )
    assert tick(jobs, root, root, Event())
    assert observed[0]["revision"] == 2 and observed[0]["paths"] == ["set_web/JTH"]
    result = jobs.get(queued["id"])
    assert result["state"] == "FAILED" and result["error_code"] == "code_checkout_failed"
    assert "synthetic-private" not in json.dumps(result)


def test_worker_checks_current_user_authority(checkout, monkeypatch):
    jobs, _, root = checkout
    queued = browse(jobs)
    jobs.db.execute("update app_user set status='disabled' where id='user_local_admin'")
    monkeypatch.setattr(
        "app.cli.code_checkout_worker.WorkingCopyClient",
        lambda *args: pytest.fail("must not connect"),
    )
    assert tick(jobs, root, root, Event())
    assert jobs.get(queued["id"])["error_code"] == "code_checkout_access_denied"


def test_checkout_does_not_overwrite_existing_target(tmp_path):
    from app.modules.knowledge.infrastructure.code_checkout_client import WorkingCopyClient

    client = object.__new__(WorkingCopyClient)
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "manual.txt").write_text("manual change")
    with pytest.raises(CodeKnowledgeError, match="destination_exists"):
        client.checkout(
            root=tmp_path, folder="existing", job_id="synthetic", revision=2, paths=[""]
        )
    assert (destination / "manual.txt").read_text() == "manual change"
    (tmp_path / "link").symlink_to(destination, target_is_directory=True)
    with pytest.raises(CodeKnowledgeError, match="destination_exists"):
        client.checkout(root=tmp_path, folder="link", job_id="synthetic", revision=2, paths=[""])
