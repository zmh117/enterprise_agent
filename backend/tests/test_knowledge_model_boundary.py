"""知识使用既有聊天模型；权限、工具依赖和镜像隔离保持有效。"""

from pathlib import Path
import json
import shlex
import shutil
import subprocess
import sys
import pytest
from app.shared.exceptions import AppError, NonRetryableExecutionError
from backend.tests.test_agent_profile_model_connections import (
    container,
    agent_config,
    ready_connection,
    ADMIN_ID,
    AGENT_CODE,
)
from backend.tests.test_knowledge_job_access import (
    knowledge_contract as knowledge_contract_fixture,
    job_fixture as job_fixture_impl,
)
from backend.tests.test_knowledge_authorization import add_base
from backend.tests.test_ones_mcp_runtime import _fixture
from app.modules.agent_config.application.service import agent_config_hash

knowledge_contract = knowledge_contract_fixture
job_fixture = job_fixture_impl


def publish(c, config):
    service = c.agent_config_service
    current = service.get(AGENT_CODE)["draft"]
    draft = service.save_draft(
        actor_id=ADMIN_ID,
        agent_code=AGENT_CODE,
        expected_revision=current["revision"],
        config=config,
    )
    return service.publish(actor_id=ADMIN_ID, agent_code=AGENT_CODE, revision_id=draft["id"])


@pytest.mark.parametrize("missing_detail", [False, True])
def test_external_chat_publication_needs_no_internal_approval(knowledge_contract, missing_detail):
    c = container()
    try:
        connection = ready_connection(c)
        config = agent_config(connection["id"])
        config["mcp_tool_ids"] = [
            "knowledge_list_bases",
            "knowledge_search",
            "ones_get_work_item_detail",
        ]
        if missing_detail:
            config["mcp_tool_ids"].remove("ones_get_work_item_detail")
            with pytest.raises(NonRetryableExecutionError):
                publish(c, config)
        else:
            published = publish(c, config)
            assert "model_data_boundary" not in published["snapshot"]
            assert published["snapshot"]["model_connection"]["revision_id"] == connection["id"]
            assert c.agent_config_service.publication(published["id"])["id"] == published["id"]
    finally:
        c.database.close()


def test_worker_accepts_authorized_knowledge_with_existing_external_model(knowledge_contract):
    capabilities = (
        "ones_work_item_search",
        "ones_get_work_item_detail",
        "knowledge_list_bases",
        "knowledge_search",
    )

    def configure_model(c):
        c.model_connection_service.dns_resolver = lambda *args, **kwargs: [
            (2, 1, 6, "", ("1.1.1.1", 443))
        ]
        connection = ready_connection(c)
        # The shared synthetic Job builder uses this seed publication; pin an actual
        # saved model revision before it builds the application and signed Job facts.
        snapshot = json.loads(
            c.database.execute_one(
                "select snapshot_json from agent_publication where id='agent_publication_default_v1'"
            )["snapshot_json"]
        )
        snapshot["model_connection"] = {
            "id": connection["connection_id"],
            "code": connection["connection_code"],
            "revision_id": connection["id"],
            "revision": connection["revision"],
            "config_hash": connection["config_hash"],
            "config": connection["config"],
        }
        c.database.execute(
            "update agent_publication set snapshot_json=?,config_hash=? where id='agent_publication_default_v1'",
            (json.dumps(snapshot), agent_config_hash(snapshot)),
        )

    def configure_access(c, selection):
        add_base(c, "kb-test")
        c.database.execute(
            "insert into rbac_role_application_knowledge_base(application_access_id,knowledge_base_id,created_at) "
            "select id,'kb-test',created_at from rbac_role_application_access where application_id=?",
            (selection["application_id"],),
        )

    fixture = _fixture(
        capabilities=capabilities,
        before_application=configure_model,
        before_job=configure_access,
        current_agent_envelope=True,
    )
    c = fixture["runtime"]
    try:
        context = c.agent_executor.context_builder.build(fixture["job"])
        assert context.model_runtime_binding is not None
        assert context.model_runtime_binding.provider_host == "api.deepseek.com"
        assert "knowledge_search" in context.allowed_tools
    finally:
        c.database.close()


def test_application_cannot_drop_detail_from_agent_envelope(job_fixture):
    c, job = job_fixture["runtime"], job_fixture["job"]
    with pytest.raises(NonRetryableExecutionError) as failure:
        c.business_application_service.mcp_tool_composition_service.prepare(
            agent_publication_id=job.agent_publication_id,
            raw_tools=["knowledge_search"],
        )
    assert failure.value.field_errors[0]["field"] == "mcp_tools"


@pytest.mark.parametrize("tool", ["knowledge_search", "ones_get_work_item_detail"])
def test_worker_rechecks_current_grants_before_model_or_summary(job_fixture, monkeypatch, tool):
    c, job = job_fixture["runtime"], job_fixture["job"]
    c.database.execute(
        "delete from rbac_role_application_mcp_tool where tool_identifier=?", (tool,)
    )
    monkeypatch.setattr(
        c.model_connection_service,
        "runtime_binding",
        lambda *args: pytest.fail("must not resolve model"),
    )
    builder = c.agent_executor.context_builder
    monkeypatch.setattr(
        builder.conversation_service, "build", lambda *args: pytest.fail("must not summarize")
    )
    with pytest.raises(AppError):
        builder.build(job)


@pytest.mark.parametrize("component", ["runtime", "worker"])
def test_image_copy_whitelist_can_import_boundary_without_expanding_runtime_business_modules(
    tmp_path, component
):
    root = Path(__file__).resolve().parents[2]
    begin, end = {
        "runtime": ("FROM claude-runtime AS python-agent-runtime", "FROM api-server AS tool-mcp"),
        "worker": (
            "FROM python-deps AS agent-worker",
            "FROM agent-worker AS file-processing-worker",
        ),
    }[component]
    section = (root / "backend/Dockerfile").read_text().split(begin, 1)[1].split(end, 1)[0]
    for line in section.splitlines():
        if not line.startswith("COPY "):
            continue
        _, *sources, target = shlex.split(line)
        destination = tmp_path / target.removeprefix("/app/")
        destination.mkdir(parents=True, exist_ok=True)
        for pattern in sources:
            matches = list(root.glob(pattern))
            assert matches, pattern
            for source in matches:
                if source.is_dir():
                    shutil.copytree(
                        source,
                        destination,
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"),
                    )
                else:
                    shutil.copy2(source, destination / source.name)
    command = (
        "import app.python_runtime.service; "
        "import sys; assert not any(name.startswith(('app.modules.knowledge', 'app.modules.authorization_center', "
        "'app.modules.identity', 'app.modules.job')) for name in sys.modules)"
    )
    if component == "worker":
        command = "import app.bootstrap; import app.workers.agent_job_worker"
    completed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=tmp_path,
        env={"PYTHONPATH": str(tmp_path / "backend")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
