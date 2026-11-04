"""部署级模式边界：默认在线核验，显式离线，错误不降级。"""

import pytest

from app.modules.knowledge.application.search import KnowledgeSearch
from app.modules.knowledge.domain.models import KnowledgeAccessMode
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.shared.exceptions import AppError
from services.knowledge_mcp_server.bootstrap import configured_access_mode
from backend.tests.test_knowledge_search import (
    knowledge_contract as knowledge_contract,
    readable_fixture as readable_fixture,
    bridge_fixture as bridge_fixture,
    search_fixture as search_fixture,
    search,
)


def use_online(f):
    offline = f["search"]
    # Omitted mode must select online, never infer offline from a missing dependency.
    f["search"] = KnowledgeSearch(
        offline.access,
        offline.resources,
        offline.embedding,
        offline.qdrant,
        offline.audit,
        reranker=offline.reranker,
        readability=f["readability_client"],
    )
    return f


def test_unset_deployment_mode_is_online(monkeypatch):
    monkeypatch.delenv("KNOWLEDGE_ACCESS_MODE", raising=False)
    assert configured_access_mode() is KnowledgeAccessMode.ONLINE


@pytest.mark.parametrize("value", ["online", "offline"])
def test_explicit_deployment_mode(monkeypatch, value):
    monkeypatch.setenv("KNOWLEDGE_ACCESS_MODE", value)
    assert configured_access_mode().value == value


@pytest.mark.parametrize("value", ["", "OFFLINE", "off", "false", "offline ", "typo"])
def test_invalid_deployment_mode_never_falls_back(monkeypatch, value):
    monkeypatch.setenv("KNOWLEDGE_ACCESS_MODE", value)
    with pytest.raises(ValueError):
        configured_access_mode()


def test_missing_online_dependency_refuses_construction(search_fixture):
    s = search_fixture["search"]
    with pytest.raises(ValueError, match="ONES"):
        KnowledgeSearch(s.access, s.resources, s.embedding, s.qdrant, s.audit, reranker=s.reranker)


def test_default_online_returns_snapshot_only_after_current_ones_check(search_fixture):
    f = use_online(search_fixture)
    result = search(f)
    assert result["access_mode"] == "online"
    assert result["content_mode"] == "ingested_snapshot"
    assert result["content_scope"] == "matched_chunks"
    hit = result["documents"][0]
    assert hit["title"] and hit["ingested_at"] and hit["source_name"]
    assert any(e["text"] for e in hit["evidence"])
    assert len(f["hops"]) == 1 and f["calls"] == ["POST"]


@pytest.mark.parametrize("status", [403, 404])
def test_online_denied_items_never_expose_snapshot_content(search_fixture, status):
    f = use_online(search_fixture)

    def denied(*args):
        raise f["provider_http"].status_error(status)

    f["provider_http"]._open_response = denied
    result = search(f)
    assert result["access_mode"] == "online" and not result["documents"]
    assert len(f["hops"]) == 1


@pytest.mark.parametrize("failure", ["provider", "identity", "grant", "malformed_bridge"])
def test_online_failures_do_not_return_offline_content(search_fixture, monkeypatch, failure):
    f = use_online(search_fixture)
    if failure == "identity":
        f["runtime"].database.execute(
            "update user_external_identity set status='disabled' where provider='ones'"
        )
    elif failure == "grant":
        f["runtime"].database.execute(
            "delete from rbac_role_application_mcp_tool where tool_identifier='ones_get_work_item_detail'"
        )
    elif failure == "malformed_bridge":
        monkeypatch.setattr(f["readability_client"], "check", lambda **kwargs: {})
    else:

        def unavailable(*args):
            raise f["provider_http"].status_error(500)

        f["provider_http"]._open_response = unavailable
    with pytest.raises(AppError):
        search(f)
    assert f["search"].access_mode is KnowledgeAccessMode.ONLINE
    assert not f["runtime"].database.execute(
        "select id from audit_event where event_type='knowledge.search.completed' and job_id=?",
        (f["job"].id,),
    )


def test_online_rechecks_identity_after_provider_result(search_fixture):
    f = use_online(search_fixture)
    original = f["provider_http"]._open_response

    def changed(*args):
        response = original(*args)
        f["runtime"].database.execute(
            "update user_external_identity set status='disabled' where provider='ones'"
        )
        return response

    f["provider_http"]._open_response = changed
    with pytest.raises(AppError):
        search(f)


@pytest.mark.parametrize("mode", [KnowledgeAccessMode.ONLINE, KnowledgeAccessMode.OFFLINE])
def test_model_cannot_override_deployment_mode(search_fixture, mode):
    f = use_online(search_fixture) if mode is KnowledgeAccessMode.ONLINE else search_fixture
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_input_invalid"):
        search(f, access_mode="offline")
    assert not f["hops"]


def test_explicit_offline_never_consults_identity_or_provider(search_fixture, monkeypatch):
    f = search_fixture
    monkeypatch.setattr(
        f["search"].access, "identity", lambda *args: pytest.fail("offline identity access")
    )
    monkeypatch.setattr(
        f["readability_client"], "check", lambda **kwargs: pytest.fail("offline provider access")
    )
    assert search(f)["access_mode"] == "offline"
    assert not f["hops"] and not f["calls"]


def test_main_compose_defaults_only_unset_mode_and_example_stays_online():
    from pathlib import Path
    import yaml

    root = Path(__file__).resolve().parents[2]
    services = yaml.safe_load((root / "docker-compose.yml").read_text())["services"]
    assert (
        services["knowledge-mcp"]["environment"]["KNOWLEDGE_ACCESS_MODE"]
        == "${KNOWLEDGE_ACCESS_MODE-online}"
    )
    assert "KNOWLEDGE_ACCESS_MODE=online" in (root / ".env.example").read_text().splitlines()
