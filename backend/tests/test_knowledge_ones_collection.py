"""受管 ONES 全量枚举：全部使用合成 Provider，不访问真实 ONES。"""

from datetime import date
import json
from types import SimpleNamespace

import pytest

from app.modules.knowledge.application.ones_collection import CollectionPage, collect_all
from app.modules.knowledge.application.ones_collection_normalizer import OnesCollectionNormalizer
from app.modules.knowledge.application.ones_collection_service import KnowledgeOnesCollectionService
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.sync import checked_configuration
from app.modules.knowledge.infrastructure.sync_repository import SyncRepository
from app.modules.knowledge.infrastructure.ones_collection_factory import (
    ManagedOnesCollectionProviderFactory,
)
from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient
from app.shared.exceptions import RetryableExecutionError
from backend.tests.test_knowledge_import import (
    database as database_fixture,
    export_row,
    prepare as prepare_legacy,
    run as import_legacy,
)
from backend.tests.test_knowledge_keep_ids import dataset
from app.modules.knowledge.infrastructure.keep_ids_export import prepare_keep_ids
from app.modules.knowledge.infrastructure.ones_collection_provider import (
    HttpOnesCollectionProvider,
)


FIRST = date(2024, 1, 1)
SECOND = date(2024, 1, 2)
TYPES = {"defect": ("defect-type",), "ticket": ("ticket-type",), "requirement": ("story-type",)}
database = database_fixture


def item(uuid: str, kind: str = "defect-type") -> dict:
    return {
        "uuid": uuid,
        "issueType": {"uuid": kind},
        "project": {"uuid": "project-1"},
        "createTime": 100,
    }


def detail(uuid: str, kind: str = "defect-type") -> dict:
    return {
        "uuid": uuid,
        "issue_type_uuid": kind,
        "project_uuid": "project-1",
        "create_time": 100,
    }


class Provider:
    def __init__(self) -> None:
        self.counts: dict[tuple, int] = {}
        self.pages: dict[tuple, CollectionPage] = {}
        self.details: dict[str, dict] = {}
        self.fetched: list[str] = []

    def catalog(self, issue_type_ids, *, check_active):
        check_active()
        return {}, {}

    def count(self, issue_type_id, first, last):
        return self.counts.get((issue_type_id, first, last), 0)

    def page(self, issue_type_id, first, last, *, after):
        return self.pages[(issue_type_id, first, last, after)]

    def detail(self, uuid):
        self.fetched.append(uuid)
        return self.details[uuid]


def scan(provider: Provider, *, first: date = FIRST, last: date = FIRST):
    committed = []
    counts = collect_all(
        provider,
        issue_types=TYPES,
        project_ids=frozenset({"project-1"}),
        first=first,
        last=last,
        child_type_ids=frozenset({"subtask-type"}),
        commit_page=lambda kind, rows, checkpoint: committed.append((kind, len(rows), checkpoint)),
    )
    return counts, committed


def test_rechecks_every_uuid_on_every_full_scan_and_commits_page_checkpoint():
    p = Provider()
    p.counts["defect-type", FIRST, FIRST] = 2
    p.pages["defect-type", FIRST, FIRST, None] = CollectionPage((item("a"),), 2, True, "c1")
    p.pages["defect-type", FIRST, FIRST, "c1"] = CollectionPage((item("b"),), 2, False, None)
    p.details = {"a": detail("a"), "b": detail("b")}
    first_counts, committed = scan(p)
    second_counts, _ = scan(p)
    assert first_counts == second_counts == {"defect": 2, "ticket": 0, "requirement": 0}
    assert p.fetched == ["a", "b", "a", "b"]
    assert [row[2]["next_cursor"] for row in committed] == ["c1", None]


def test_splits_capped_window_and_does_not_accept_partial_day():
    p = Provider()
    p.counts["defect-type", FIRST, SECOND] = 1000
    for day, uuid in ((FIRST, "a"), (SECOND, "b")):
        p.counts["defect-type", day, day] = 1
        p.pages["defect-type", day, day, None] = CollectionPage((item(uuid),), 1, False, None)
        p.details[uuid] = detail(uuid)
    assert scan(p, last=SECOND)[0]["defect"] == 2
    p.counts["defect-type", FIRST, FIRST] = 1000
    with pytest.raises(ExportValidationError, match="knowledge_collection_window_limit"):
        scan(p, last=SECOND)


@pytest.mark.parametrize(
    ("bad_page", "code"),
    [
        (CollectionPage((item("a"),), 2, False, None), "knowledge_collection_incomplete"),
        (CollectionPage((item("a"),), 2, True, None), "knowledge_collection_cursor_invalid"),
        (CollectionPage((item("a"),), 3, False, None), "knowledge_collection_page_invalid"),
    ],
)
def test_rejects_incomplete_pagination(bad_page: CollectionPage, code: str):
    p = Provider()
    p.counts["defect-type", FIRST, FIRST] = 2
    p.pages["defect-type", FIRST, FIRST, None] = bad_page
    p.details["a"] = detail("a")
    with pytest.raises(ExportValidationError, match=code):
        scan(p)


def test_rejects_duplicate_page_and_wrong_detail_without_success():
    p = Provider()
    p.counts["defect-type", FIRST, FIRST] = 2
    p.pages["defect-type", FIRST, FIRST, None] = CollectionPage((item("a"),), 2, True, "c1")
    p.pages["defect-type", FIRST, FIRST, "c1"] = CollectionPage((item("a"),), 2, False, None)
    p.details["a"] = detail("a")
    with pytest.raises(ExportValidationError, match="knowledge_collection_scope_changed"):
        scan(p)
    p.pages["defect-type", FIRST, FIRST, "c1"] = CollectionPage((item("b"),), 2, False, None)
    p.details["b"] = detail("wrong")
    with pytest.raises(ExportValidationError, match="knowledge_collection_detail_mismatch"):
        scan(p)


def test_rejects_repeated_cursor_and_missing_detail():
    p = Provider()
    p.counts["defect-type", FIRST, FIRST] = 2
    p.pages["defect-type", FIRST, FIRST, None] = CollectionPage((item("a"),), 2, True, "c1")
    p.pages["defect-type", FIRST, FIRST, "c1"] = CollectionPage((item("b"),), 2, True, "c1")
    p.details = {"a": detail("a"), "b": detail("b")}
    with pytest.raises(ExportValidationError, match="knowledge_collection_cursor_invalid"):
        scan(p)
    p.pages["defect-type", FIRST, FIRST, "c1"] = CollectionPage((item("b"),), 2, False, None)
    p.details["b"] = {**detail("b"), "project_uuid": "other-project"}
    with pytest.raises(ExportValidationError, match="knowledge_collection_detail_mismatch"):
        scan(p)


def test_rejects_out_of_scope_project_and_type():
    p = Provider()
    p.counts["defect-type", FIRST, FIRST] = 1
    wrong = item("a")
    wrong["project"] = {"uuid": "other-project"}
    p.pages["defect-type", FIRST, FIRST, None] = CollectionPage((wrong,), 1, False, None)
    with pytest.raises(ExportValidationError, match="knowledge_collection_scope_changed"):
        scan(p)
    wrong["project"] = {"uuid": "project-1"}
    wrong["issueType"] = {"uuid": "ticket-type"}
    with pytest.raises(ExportValidationError, match="knowledge_collection_scope_changed"):
        scan(p)


def test_fixed_http_adapter_uses_scoped_list_and_detail_without_discussions():
    class Http:
        target = SimpleNamespace(base_url="https://ones.example.test")

        def __init__(self):
            self.calls = []

        def post_json(self, path, payload, *, headers, query=None):
            self.calls.append(("POST", path, payload, query))
            if query == {"t": "total-task-count"}:
                return {"data": {"buckets": [{"pageInfo": {"totalCount": 1}}]}}
            return {
                "data": {
                    "buckets": [
                        {
                            "tasks": [item("a")],
                            "pageInfo": {
                                "totalCount": 1,
                                "count": 1,
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                        }
                    ]
                }
            }

        def get_json(self, path, payload, *, headers):
            self.calls.append(("GET", path, payload, None))
            return {"task": detail("a")}

    http = Http()
    provider = HttpOnesCollectionProvider(
        http,
        team_id="team-1",
        project_ids=frozenset({"project-1"}),
        token="synthetic",
        user_id="collector",
    )
    assert provider.count("defect-type", FIRST, FIRST) == 1
    assert provider.page("defect-type", FIRST, FIRST, after=None).items[0]["uuid"] == "a"
    assert provider.detail("a")["uuid"] == "a"
    assert len(http.calls) == 3
    assert all("messages" not in str(call) and "attachment" not in str(call) for call in http.calls)
    assert http.calls[0][2]["variables"]["filterGroup"][0] == {
        "issueType_in": ["defect-type"],
        "project_in": ["project-1"],
        "parent_in": [""],
        "createTime_range": {"gte": "2024-01-01", "lte": "2024-01-01"},
    }


def test_http_adapter_rejects_graphql_error_without_echoing_provider_body():
    class Http:
        target = SimpleNamespace(base_url="https://ones.example.test")

        def post_json(self, *args, **kwargs):
            return {"errors": [{"message": "provider private response"}]}

    provider = HttpOnesCollectionProvider(
        Http(),
        team_id="team-1",
        project_ids=frozenset({"project-1"}),
        token="synthetic",
        user_id="collector",
    )
    with pytest.raises(ExportValidationError, match="knowledge_collection_provider_error"):
        provider.count("defect-type", FIRST, FIRST)


def test_http_catalog_uses_only_fields_members_and_scopes():
    class Http:
        target = SimpleNamespace(base_url="https://ones.example.test")

        def __init__(self):
            self.tags = []

        def post_json(self, path, payload, *, headers, query):
            self.tags.append(query["t"])
            if query["t"] == "field":
                return {
                    "field": {
                        "fields": [
                            {
                                "uuid": "field-1",
                                "name": "模块",
                                "type": 1,
                                "options": [{"uuid": "choice-1", "value": "模块甲"}],
                            }
                        ]
                    }
                }
            if query["t"] == "team_member":
                return {"team_member": {"members": [{"uuid": "user-1", "name": "合成人员"}]}}
            return {
                "data": {
                    "issueTypeScopes": [
                        {
                            "uuid": "scope-1",
                            "scopeName": "范围",
                            "name": "缺陷",
                            "issueType": {"uuid": "defect-type", "name": "缺陷"},
                        }
                    ]
                }
            }

    http = Http()
    provider = HttpOnesCollectionProvider(
        http,
        team_id="team-1",
        project_ids=frozenset({"project-1"}),
        token="synthetic",
        user_id="collector",
    )
    fields, names = provider.catalog(("defect-type",), check_active=lambda: None)
    assert fields["field-1"]["options"][0]["value"] == "模块甲"
    assert names["user-1"] == "合成人员"
    assert names["defect-type"] == "缺陷"
    assert http.tags == ["field", "team_member", "issueTypeScopes"]


def test_story_children_are_fetched_and_counted_without_a_comment_request():
    p = Provider()
    p.counts["story-type", FIRST, FIRST] = 1
    p.pages["story-type", FIRST, FIRST, None] = CollectionPage(
        (item("story", "story-type"),), 1, False, None
    )
    p.details["story"] = {**detail("story", "story-type"), "subtasks": [{"uuid": "child"}]}
    p.details["child"] = {
        **detail("child", "subtask-type"),
        "sub_issue_type_uuid": "subtask-type",
        "parent_uuid": "story",
    }
    counts, pages = scan(p)
    assert counts["requirement"] == 2
    assert p.fetched == ["story", "child"]
    assert pages[-1][2]["children_processed"] == 1


def test_story_child_with_missing_parent_fails_closed():
    p = Provider()
    p.counts["story-type", FIRST, FIRST] = 1
    p.pages["story-type", FIRST, FIRST, None] = CollectionPage(
        (item("story", "story-type"),), 1, False, None
    )
    p.details["story"] = {**detail("story", "story-type"), "subtasks": ["child"]}
    p.details["child"] = {
        **detail("child", "subtask-type"),
        "sub_issue_type_uuid": "subtask-type",
        "parent_uuid": "unknown",
    }
    with pytest.raises(ExportValidationError, match="knowledge_collection_child_invalid"):
        scan(p)


def test_collector_configuration_keeps_only_fixed_scope_and_credential_reference():
    collector = {
        "provider_origin": "https://ones.example.test",
        "team_id": "team-1",
        "project_ids": ["project-1"],
        "issue_types": {
            "defect": ["defect-type"],
            "ticket": ["ticket-type"],
            "requirement": ["story-type"],
        },
        "child_type_ids": ["subtask-type"],
        "first_date": "2024-01-01",
        "credential_ref": "secret://platform/knowledge-collector",
    }
    config = checked_configuration(
        {
            "base_codes": {
                "defect": "ones-defects-offline",
                "ticket": "ones-tickets-offline",
                "requirement": "ones-stories-offline",
            },
            "resource_ids": [],
            "collector": collector,
        }
    )
    assert config["collector"]["credential_ref"] == "secret://platform/knowledge-collector"
    with pytest.raises(ExportValidationError, match="knowledge_collection_configuration_invalid"):
        checked_configuration({**config, "collector": {**collector, "token": "synthetic"}})
    with pytest.raises(ExportValidationError, match="knowledge_collection_configuration_invalid"):
        checked_configuration(
            {
                **config,
                "collector": {
                    **collector,
                    "provider_origin": "https://user:pass@ones.example.test",
                },
            }
        )


def test_online_normalization_projects_only_needed_text_and_ids(tmp_path):
    rows = dataset(tmp_path)
    listing = json.loads((tmp_path / "缺陷_list.jsonl").read_text())
    fields = {
        "field_module": {
            "uuid": "field_module",
            "name": "所属功能模块",
            "type": 1,
            "options": [{"uuid": "module_report", "value": "报工管理"}],
        }
    }
    normalizer = OnesCollectionNormalizer(fields=fields, names={})
    source = {**rows["缺陷"], "resources": [{"private": "discard"}], "comments": ["discard"]}
    record = normalizer.normalize(listing, source, kind="defect")
    assert record.values["title"] == "合成报工重复提交"
    assert record.values["attributes"]["source_fields"]["field_module"]["display"] == "报工管理"
    assert record.values["completeness"]["discussion"] == "not_indexed"
    assert "discard" not in json.dumps(record.values)


def test_managed_collection_default_off_then_stages_full_three_type_scan(database, tmp_path):
    rows = dataset(tmp_path)
    collector = {
        "provider_origin": "https://ones.example.test",
        "team_id": "team-1",
        "project_ids": ["project_id"],
        "issue_types": {
            "defect": ["type_1"],
            "ticket": ["type_2"],
            "requirement": ["type_3"],
        },
        "child_type_ids": ["type_4"],
        "first_date": FIRST.isoformat(),
        "credential_ref": "secret://platform/synthetic-collector",
    }
    repo = SyncRepository(database)
    binding = repo.configure(
        code="synthetic_online",
        source_code="synthetic_online_source",
        configuration={
            "base_codes": {
                "defect": "synthetic_online_defects",
                "ticket": "synthetic_online_tickets",
                "requirement": "synthetic_online_stories",
            },
            "resource_ids": [],
            "collector": collector,
        },
        expected_revision=0,
    )
    p = Provider()
    for kind, label, issue_type in (
        ("defect", "缺陷", "type_1"),
        ("ticket", "工单", "type_2"),
        ("requirement", "Story", "type_3"),
    ):
        listing = json.loads((tmp_path / (label + "_list.jsonl")).read_text())
        p.counts[issue_type, FIRST, FIRST] = 1
        p.pages[issue_type, FIRST, FIRST, None] = CollectionPage((listing,), 1, False, None)
        p.details[rows[label]["uuid"]] = rows[label]
    p.details[rows["子任务"]["uuid"]] = {
        **rows["子任务"],
        "sub_issue_type_uuid": "type_4",
    }
    fields = {
        "field_module": {
            "uuid": "field_module",
            "name": "所属功能模块",
            "type": 1,
            "options": [{"uuid": "module_report", "value": "报工管理"}],
        }
    }
    p.catalog = lambda _ids, check_active: (fields, {"type_4": "Sub-task"})
    service = KnowledgeOnesCollectionService(repo, lambda _collector: p)
    with pytest.raises(ExportValidationError, match="knowledge_collection_disabled"):
        service.collect_once(binding["id"], through=FIRST)
    assert database.execute('select id from "knowledge.sync_run"') == []
    repo.set_collection_enabled(binding["id"], enabled=True, expected_revision=1)
    result = service.collect_once(binding["id"], scan_at="2026-09-23T00:00:00+00:00", through=FIRST)
    assert result["phase"] == "STAGED"
    assert result["counts"] == {"created": 4}
    assert len(p.fetched) == 4
    assert database.execute_one('select count(*) as n from "knowledge.document_revision"')["n"] == 4
    assert database.execute('select * from "knowledge.knowledge_base_document"') == []


def test_online_page_replay_keeps_one_candidate_and_count(database, tmp_path):
    dataset(tmp_path)
    prepared = prepare_keep_ids(tmp_path, expected={"缺陷": 1, "工单": 1, "Story": 1, "子任务": 1})
    repo = SyncRepository(database)
    binding = repo.configure(
        code="synthetic_replay",
        source_code="synthetic_replay_source",
        configuration={
            "base_codes": {
                "defect": "synthetic_replay_defects",
                "ticket": "synthetic_replay_tickets",
                "requirement": "synthetic_replay_stories",
            },
            "resource_ids": [],
            "collector": {
                "provider_origin": "https://ones.example.test",
                "team_id": "team-1",
                "project_ids": ["project_id"],
                "issue_types": {
                    "defect": ["type_1"],
                    "ticket": ["type_2"],
                    "requirement": ["type_3"],
                },
                "child_type_ids": ["type_4"],
                "first_date": FIRST.isoformat(),
                "credential_ref": "secret://platform/synthetic-collector",
            },
        },
        expected_revision=0,
    )
    repo.set_collection_enabled(binding["id"], enabled=True, expected_revision=1)
    run = repo.begin_collection(binding["id"], "2026-09-23T01:00:00+00:00")
    record = prepared[0].records[0]
    checkpoint = {
        "kind": "defect",
        "issue_type_id": "type_1",
        "first": FIRST.isoformat(),
        "last": FIRST.isoformat(),
        "next_cursor": None,
        "enumerated": 1,
        "expected": 1,
    }
    repo.commit_collection_page(run["id"], (record,), checkpoint)
    repo.fail(run["id"], "knowledge_collection_provider_unavailable")
    assert repo.active_collection(binding["id"])["id"] == run["id"]
    repo.commit_collection_page(run["id"], (record,), checkpoint)
    assert repo.summary(run["id"])["checkpoint"] == {"processed": 1, "total": 1}
    assert database.execute_one('select count(*) as n from "knowledge.document_revision"')["n"] == 1


def test_online_scan_rejects_disappearing_existing_uuid(database, tmp_path):
    import_legacy(database, prepare_legacy(tmp_path, [export_row()]))
    repo = SyncRepository(database)
    binding = repo.configure(
        code="synthetic_visibility",
        source_code="synthetic_source",
        configuration={
            "base_codes": {
                "defect": "synthetic_base",
                "ticket": "synthetic_visibility_tickets",
                "requirement": "synthetic_visibility_stories",
            },
            "resource_ids": [],
            "collector": {
                "provider_origin": "https://ones.example.test",
                "team_id": "team-1",
                "project_ids": ["project_id"],
                "issue_types": {
                    "defect": ["type_1"],
                    "ticket": ["type_2"],
                    "requirement": ["type_3"],
                },
                "child_type_ids": ["type_4"],
                "first_date": FIRST.isoformat(),
                "credential_ref": "secret://platform/synthetic-collector",
            },
        },
        expected_revision=0,
    )
    repo.set_collection_enabled(binding["id"], enabled=True, expected_revision=1)
    active = repo.begin_collection(binding["id"], "2026-09-23T02:00:00+00:00")
    with pytest.raises(ExportValidationError, match="knowledge_collection_visibility_shrank"):
        repo.complete_collection(active["id"], {"defect": 0, "ticket": 0, "requirement": 0})
    assert repo.run(active["id"])["phase"] == "COLLECTING"


def _enabled_binding(database):
    repo = SyncRepository(database)
    binding = repo.configure(
        code="synthetic_errors",
        source_code="synthetic_errors_source",
        configuration={
            "base_codes": {
                "defect": "synthetic_errors_defects",
                "ticket": "synthetic_errors_tickets",
                "requirement": "synthetic_errors_stories",
            },
            "resource_ids": [],
            "collector": {
                "provider_origin": "https://ones.example.test",
                "team_id": "team-1",
                "project_ids": ["project-1"],
                "issue_types": {kind: list(values) for kind, values in TYPES.items()},
                "child_type_ids": ["subtask-type"],
                "first_date": FIRST.isoformat(),
                "credential_ref": "secret://platform/synthetic-collector",
            },
        },
        expected_revision=0,
    )
    repo.set_collection_enabled(binding["id"], enabled=True, expected_revision=1)
    return repo, binding


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "knowledge_collection_unauthorized"),
        (403, "knowledge_collection_forbidden"),
        (404, "knowledge_collection_not_found"),
        (429, "knowledge_collection_rate_limited"),
        (503, "knowledge_collection_provider_unavailable"),
    ],
)
def test_provider_failure_is_fixed_code_and_staged_data_remains_unpublished(database, status, code):
    repo, binding = _enabled_binding(database)

    class FailingProvider(Provider):
        def catalog(self, issue_type_ids, *, check_active):
            raise OnesProviderHttpClient.status_error(status)

    service = KnowledgeOnesCollectionService(repo, lambda _config: FailingProvider())
    with pytest.raises(ExportValidationError, match=code):
        service.collect_once(binding["id"], through=FIRST)
    active = repo.active_collection(binding["id"])
    assert active["error_code"] == code and active["phase"] == "COLLECTING"
    assert database.execute('select * from "knowledge.knowledge_base_document"') == []


def test_provider_timeout_is_fixed_code_and_can_be_replayed(database):
    repo, binding = _enabled_binding(database)

    class FailingProvider(Provider):
        def catalog(self, issue_type_ids, *, check_active):
            raise RetryableExecutionError(
                "synthetic timeout",
                safe_message="synthetic",
                error_code="ones_provider_unavailable",
            )

    service = KnowledgeOnesCollectionService(repo, lambda _config: FailingProvider())
    with pytest.raises(ExportValidationError, match="knowledge_collection_provider_unavailable"):
        service.collect_once(binding["id"], through=FIRST)
    run = repo.active_collection(binding["id"])
    assert run["phase"] == "COLLECTING"


def test_disable_cancels_scan_before_next_request(database):
    repo, binding = _enabled_binding(database)

    class DisableProvider(Provider):
        def count(self, issue_type_id, first, last):
            repo.set_collection_enabled(binding["id"], enabled=False, expected_revision=1)
            return 1

    p = DisableProvider()
    service = KnowledgeOnesCollectionService(repo, lambda _config: p)
    with pytest.raises(ExportValidationError, match="knowledge_collection_disabled"):
        service.collect_once(binding["id"], through=FIRST)
    assert repo.active_collection(binding["id"]) is None
    assert p.fetched == []


def test_managed_factory_enforces_allowlist_and_credential_reference_only():
    config = {
        "provider_origin": "https://ones.example.test",
        "team_id": "team-1",
        "project_ids": ["project-1"],
        "credential_ref": "secret://platform/synthetic-collector",
    }
    factory = ManagedOnesCollectionProviderFactory(
        lambda ref: json.dumps({"token": "synthetic", "user_id": "collector"}),
        allowed_hosts=("ones.example.test",),
        app_env="production",
    )
    provider = factory(config)
    assert provider.http.target.host == "ones.example.test"
    production_http = ManagedOnesCollectionProviderFactory(
        lambda ref: json.dumps({"token": "synthetic", "user_id": "collector"}),
        allowed_hosts=("ones.example.test",),
        app_env="production",
        allow_insecure_local=True,
    )
    assert production_http(
        {**config, "provider_origin": "http://ones.example.test"}
    ).http.target.base_url == ("http://ones.example.test")
    with pytest.raises(ExportValidationError, match="knowledge_collection_target_invalid"):
        factory({**config, "provider_origin": "http://ones.example.test"})
    with pytest.raises(ExportValidationError, match="knowledge_collection_target_invalid"):
        factory({**config, "provider_origin": "https://not-allowed.example.test"})
    bad_secret = ManagedOnesCollectionProviderFactory(
        lambda ref: json.dumps({"token": "synthetic", "user_id": "collector", "password": "x"}),
        allowed_hosts=("ones.example.test",),
        app_env="production",
    )
    with pytest.raises(ExportValidationError, match="knowledge_collection_identity_missing"):
        bad_secret(config)


def test_collection_scope_cannot_change_after_first_run(database):
    repo, binding = _enabled_binding(database)
    repo.begin_collection(binding["id"], "2026-09-23T03:00:00+00:00")
    changed = {
        **binding["configuration_json"],
        "collector": {
            **binding["configuration_json"]["collector"],
            "project_ids": ["different-project"],
        },
    }
    with pytest.raises(ExportValidationError, match="knowledge_collection_scope_changed"):
        repo.configure(
            code="synthetic_errors",
            source_code="synthetic_errors_source",
            configuration=changed,
            expected_revision=1,
        )
