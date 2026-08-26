from __future__ import annotations

from typing import Any, Final

from app.shared.ones_tool_contracts import ONES_STATUS_CATEGORIES
from services.ones_mcp_server.errors import invalid_provider_response
from services.ones_mcp_server.provider.graphql.documents import load_graphql_document
from services.ones_mcp_server.provider.graphql.operations.fixed import FixedGraphqlOperation
from services.ones_mcp_server.provider.graphql.operations.normalization import (
    bounded_int,
    bounded_string,
    normalized_list,
    optional_person,
    page_items,
    require_list,
    require_mapping,
    timestamp_text,
)


TESTCASE_LIBRARY_LIST = "testcase_library_list"
TESTCASE_MODULE_LIST = "testcase_module_list"
TEST_PLAN_LIST = "test_plan_list"
TESTCASE_MODULE_CASES = "testcase_module_cases"
TESTCASE_PLAN_CASES = "testcase_plan_cases"
TESTCASE_DETAIL = "testcase_detail"


def _library_variables(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    return {"pagination": {"limit": arguments["limit"]}, "_limit": arguments["limit"]}


def _library_response(payload: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    limit = bounded_int(variables.get("_limit"), minimum=1)
    raw, total, truncated, cursor = page_items(
        payload, collection="testcaseLibraries", limit=limit
    )
    libraries: list[dict[str, Any]] = []
    for raw_item in raw:
        item = require_mapping(raw_item)
        count = bounded_int(item.get("testcaseCaseCount", 0))
        sample = item.get("isSample", False)
        if type(sample) is not bool:
            raise invalid_provider_response("ones_provider_schema_invalid")
        libraries.append(
            {
                "uuid": bounded_string(item.get("uuid"), maximum=128),
                "name": bounded_string(item.get("name"), maximum=300),
                "case_count": count,
                "sample": sample,
            }
        )
    return normalized_list(
        "libraries", libraries, total=total, truncated=truncated, next_cursor=cursor
    )


def _module_variables(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    return {
        "moduleFilter": {"testcaseLibrary_in": [arguments["library_uuid"]]},
        "_limit": arguments["limit"],
    }


def _module_response(payload: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    data = require_mapping(payload.get("data"))
    raw = require_list(data.get("testcaseModules"))
    limit = bounded_int(variables.get("_limit"), minimum=1)
    modules: list[dict[str, Any]] = []
    for raw_item in raw[:limit]:
        item = require_mapping(raw_item)
        module: dict[str, Any] = {
            "uuid": bounded_string(item.get("uuid"), maximum=128),
            "name": bounded_string(item.get("name"), maximum=300),
            "path": bounded_string(item.get("path"), maximum=1000),
            "case_count": bounded_int(item.get("testcaseCaseCount", 0)),
        }
        parent = item.get("parent")
        if isinstance(parent, dict) and parent.get("uuid"):
            module["parent_uuid"] = bounded_string(parent.get("uuid"), maximum=128)
        modules.append(module)
    return normalized_list(
        "modules", modules, total=len(raw), truncated=len(raw) > limit
    )


def _plan_variables(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    return {"planFilter": {}, "_limit": arguments["limit"]}


def _plan_response(payload: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    limit = bounded_int(variables.get("_limit"), minimum=1)
    raw, total, truncated, cursor = page_items(
        payload, collection="testcasePlans", limit=limit
    )
    plans: list[dict[str, Any]] = []
    for raw_item in raw:
        item = require_mapping(raw_item)
        sample = item.get("isSample", False)
        if type(sample) is not bool:
            raise invalid_provider_response("ones_provider_schema_invalid")
        plan: dict[str, Any] = {
            "uuid": bounded_string(item.get("uuid"), maximum=128),
            "name": bounded_string(item.get("name"), maximum=300),
            "sample": sample,
        }
        owner = optional_person(item.get("owner"))
        if owner is not None:
            plan["owner"] = owner
        status = item.get("status")
        if isinstance(status, dict):
            category = bounded_string(status.get("category"), maximum=40)
            if category not in ONES_STATUS_CATEGORIES:
                raise invalid_provider_response("ones_provider_schema_invalid")
            plan["status"] = {
                "name": bounded_string(status.get("name"), maximum=200),
                "category": category,
            }
        plans.append(plan)
    return normalized_list("plans", plans, total=total, truncated=truncated, next_cursor=cursor)


def _module_case_variables(
    arguments: dict[str, Any], _context: dict[str, Any]
) -> dict[str, Any]:
    return {
        "testCaseFilter": [
            {
                "testcaseLibrary_in": [arguments["library_uuid"]],
                "path_match": arguments["source_uuid"],
            }
        ],
        "orderByFilter": {"priority": {"position": "ASC"}},
        "_limit": arguments["limit"],
    }


def _plan_case_variables(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    return {
        "testCaseFilter": [
            {"testcasePlan_in": [arguments["source_uuid"]], "testcaseCase": {}}
        ],
        "planFilter": {"uuid_in": [arguments["source_uuid"]]},
        "moduleFilter": {},
        "orderByFilter": {"testcaseCase": {"priority": {"position": "ASC"}}},
        "_limit": arguments["limit"],
    }


def _case_list_response(
    payload: dict[str, Any], variables: dict[str, Any]
) -> dict[str, Any]:
    limit = bounded_int(variables.get("_limit"), minimum=1)
    data = require_mapping(payload.get("data"))
    buckets = require_list(data.get("buckets"))
    items: list[dict[str, Any]] = []
    total = 0
    truncated = False
    cursor = ""
    for raw_bucket in buckets:
        bucket = require_mapping(raw_bucket)
        raw_cases = bucket.get("testcaseCases")
        plan_cases = bucket.get("testcasePlanCases")
        selected = require_list(raw_cases if raw_cases is not None else plan_cases)
        for raw_item in selected:
            item = require_mapping(raw_item)
            if plan_cases is not None:
                item = require_mapping(item.get("testcaseCase"))
            items.append({"uuid": bounded_string(item.get("uuid"), maximum=128)})
        page = require_mapping(bucket.get("pageInfo"))
        count = bounded_int(page.get("count", len(selected)))
        bucket_total = bounded_int(page.get("totalCount", count))
        total += bucket_total
        has_next = page.get("hasNextPage", False)
        if type(has_next) is not bool:
            raise invalid_provider_response("ones_provider_schema_invalid")
        truncated = truncated or has_next or bucket_total > count
        if isinstance(page.get("endCursor"), str):
            cursor = str(page["endCursor"])[:512]
    if len(items) > limit:
        items = items[:limit]
        truncated = True
    return normalized_list(
        "test_cases", items, total=total, truncated=truncated, next_cursor=cursor
    )


def _detail_variables(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    uuid = arguments["test_case_uuid"]
    return {
        "testCaseFilter": {"uuid_in": [uuid]},
        "stepFilter": {"testcaseCase_in": [uuid]},
    }


def _detail_response(payload: dict[str, Any], _variables: dict[str, Any]) -> dict[str, Any]:
    data = require_mapping(payload.get("data"))
    cases = require_list(data.get("testcaseCases"))
    if len(cases) != 1:
        raise invalid_provider_response("ones_provider_schema_invalid")
    item = require_mapping(cases[0])
    test_case: dict[str, Any] = {
        "uuid": bounded_string(item.get("uuid"), maximum=128),
        "name": bounded_string(item.get("name"), maximum=500),
    }
    for source, target in (
        ("testcaseLibrary", "library_uuid"),
        ("testcaseModule", "module_uuid"),
    ):
        value = item.get(source)
        if isinstance(value, dict) and value.get("uuid"):
            test_case[target] = bounded_string(value.get("uuid"), maximum=128)
    if item.get("path") is not None:
        test_case["path"] = bounded_string(item.get("path"), maximum=1000)
    assignee = optional_person(item.get("assign"))
    if assignee is not None:
        test_case["assignee"] = assignee
    if item.get("createTime") is not None:
        test_case["created_at"] = timestamp_text(item.get("createTime"))
    steps: list[dict[str, Any]] = []
    for raw_step in require_list(data.get("testcaseCaseSteps"))[:100]:
        step = require_mapping(raw_step)
        steps.append(
            {
                "index": bounded_int(step.get("index")),
                "description": bounded_string(
                    step.get("desc", ""), maximum=2000, allow_empty=True
                ),
                "expected_result": bounded_string(
                    step.get("result", ""), maximum=2000, allow_empty=True
                ),
            }
        )
    output: dict[str, Any] = {
        "test_case": test_case,
        "steps": steps,
        "untrusted_data": True,
    }
    if isinstance(item.get("desc"), str):
        output["description"] = str(item["desc"])[:4000]
    if isinstance(item.get("condition"), str):
        output["condition"] = str(item["condition"])[:2000]
    return output


TESTCASE_LIBRARY_LIST_OPERATION: Final = FixedGraphqlOperation(
    TESTCASE_LIBRARY_LIST,
    "QUERY_LIBRARY_LIST",
    load_graphql_document("testcase_library_list.graphql"),
    _library_variables,
    _library_response,
)
TESTCASE_MODULE_LIST_OPERATION: Final = FixedGraphqlOperation(
    TESTCASE_MODULE_LIST,
    "library-module-list-tree-NCdREx5Y",
    load_graphql_document("testcase_module_list.graphql"),
    _module_variables,
    _module_response,
)
TEST_PLAN_LIST_OPERATION: Final = FixedGraphqlOperation(
    TEST_PLAN_LIST,
    "plan-list",
    load_graphql_document("test_plan_list.graphql"),
    _plan_variables,
    _plan_response,
)
TESTCASE_MODULE_CASES_OPERATION: Final = FixedGraphqlOperation(
    TESTCASE_MODULE_CASES,
    "library-testcase-list-uuids",
    load_graphql_document("testcase_module_cases.graphql"),
    _module_case_variables,
    _case_list_response,
)
TESTCASE_PLAN_CASES_OPERATION: Final = FixedGraphqlOperation(
    TESTCASE_PLAN_CASES,
    "plan-testcase-list-uuids",
    load_graphql_document("testcase_plan_cases.graphql"),
    _plan_case_variables,
    _case_list_response,
)
TESTCASE_DETAIL_OPERATION: Final = FixedGraphqlOperation(
    TESTCASE_DETAIL,
    "library-testcase-detail",
    load_graphql_document("testcase_detail.graphql"),
    _detail_variables,
    _detail_response,
)

TEST_GRAPHQL_OPERATIONS: Final = (
    TESTCASE_LIBRARY_LIST_OPERATION,
    TESTCASE_MODULE_LIST_OPERATION,
    TEST_PLAN_LIST_OPERATION,
    TESTCASE_MODULE_CASES_OPERATION,
    TESTCASE_PLAN_CASES_OPERATION,
    TESTCASE_DETAIL_OPERATION,
)
