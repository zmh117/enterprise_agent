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
    ordered_uuid_fingerprint,
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
    limit = int(arguments["limit"])
    return {
        "pagination": {
            "limit": limit,
            "after": str(arguments.get("provider_cursor") or ""),
            "preciseCount": True,
        },
        "_limit": limit,
        "_cumulative_returned": int(arguments.get("cumulative_returned") or 0),
    }


def _library_response(payload: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    limit = bounded_int(variables.get("_limit"), minimum=1)
    cumulative_returned = bounded_int(variables.get("_cumulative_returned", 0), minimum=0)
    raw, total, truncated, cursor = page_items(
        payload,
        collection="testcaseLibraries",
        limit=limit,
        prior_count=cumulative_returned,
    )
    libraries: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw):
        path = f"data.buckets[0].testcaseLibraries[{index}]"
        item = require_mapping(raw_item, path=path)
        count = bounded_int(item.get("testcaseCaseCount", 0), path=f"{path}.testcaseCaseCount")
        sample = item.get("isSample", False)
        if type(sample) is not bool:
            raise invalid_provider_response("ones_provider_schema_invalid")
        libraries.append(
            {
                "uuid": bounded_string(item.get("uuid"), maximum=128, path=f"{path}.uuid"),
                "name": bounded_string(item.get("name"), maximum=300, path=f"{path}.name"),
                "case_count": count,
                "sample": sample,
            }
        )
    output = normalized_list("libraries", libraries, total=total, truncated=truncated)
    output["_provider_cursor"] = cursor
    return output


def _module_variables(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    return {
        "moduleFilter": {"testcaseLibrary_in": [arguments["library_uuid"]]},
        "_limit": arguments["limit"],
        "_offset": int(arguments.get("page_offset") or 0),
    }


def _module_response(payload: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    data = require_mapping(payload.get("data"), path="data")
    raw = require_list(data.get("testcaseModules"), path="data.testcaseModules")
    limit = bounded_int(variables.get("_limit"), minimum=1)
    offset = bounded_int(variables.get("_offset", 0), minimum=0)
    modules: list[dict[str, Any]] = []
    uuids: list[str] = []
    for index, raw_item in enumerate(raw):
        path = f"data.testcaseModules[{index}]"
        item = require_mapping(raw_item, path=path)
        uuid = bounded_string(item.get("uuid"), maximum=128, path=f"{path}.uuid")
        uuids.append(uuid)
        module: dict[str, Any] = {
            "uuid": uuid,
            "name": bounded_string(item.get("name"), maximum=300, path=f"{path}.name"),
            "path": bounded_string(item.get("path"), maximum=1000, path=f"{path}.path"),
            "case_count": bounded_int(
                item.get("testcaseCaseCount", 0), path=f"{path}.testcaseCaseCount"
            ),
        }
        parent = item.get("parent")
        if isinstance(parent, dict) and parent.get("uuid"):
            module["parent_uuid"] = bounded_string(
                parent.get("uuid"), maximum=128, path=f"{path}.parent.uuid"
            )
        modules.append(module)
    page = modules[offset : offset + limit]
    next_offset = offset + len(page)
    output = normalized_list("modules", page, total=len(raw), truncated=next_offset < len(raw))
    output["_next_offset"] = next_offset
    output["_collection_fingerprint"] = ordered_uuid_fingerprint(uuids)
    return output


def _plan_variables(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    limit = int(arguments["limit"])
    return {
        "planFilter": {},
        "pagination": {
            "limit": limit,
            "after": str(arguments.get("provider_cursor") or ""),
            "preciseCount": True,
        },
        "_limit": limit,
        "_cumulative_returned": int(arguments.get("cumulative_returned") or 0),
    }


def _plan_response(payload: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    limit = bounded_int(variables.get("_limit"), minimum=1)
    cumulative_returned = bounded_int(variables.get("_cumulative_returned", 0), minimum=0)
    raw, total, truncated, cursor = page_items(
        payload,
        collection="testcasePlans",
        limit=limit,
        prior_count=cumulative_returned,
    )
    plans: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw):
        path = f"data.buckets[0].testcasePlans[{index}]"
        item = require_mapping(raw_item, path=path)
        sample = item.get("isSample", False)
        if type(sample) is not bool:
            raise invalid_provider_response("ones_provider_schema_invalid")
        plan: dict[str, Any] = {
            "uuid": bounded_string(item.get("uuid"), maximum=128, path=f"{path}.uuid"),
            "name": bounded_string(item.get("name"), maximum=300, path=f"{path}.name"),
            "sample": sample,
        }
        owner = optional_person(item.get("owner"), path=f"{path}.owner")
        if owner is not None:
            plan["owner"] = owner
        status = item.get("status")
        if isinstance(status, dict):
            category = bounded_string(
                status.get("category"), maximum=40, path=f"{path}.status.category"
            )
            if category not in ONES_STATUS_CATEGORIES:
                raise invalid_provider_response("ones_provider_schema_invalid")
            plan["status"] = {
                "name": bounded_string(status.get("name"), maximum=200, path=f"{path}.status.name"),
                "category": category,
            }
        plans.append(plan)
    output = normalized_list("plans", plans, total=total, truncated=truncated)
    output["_provider_cursor"] = cursor
    return output


def _module_case_variables(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    return {
        "testCaseFilter": [
            {
                "testcaseLibrary_in": [arguments["library_uuid"]],
                "path_match": arguments["source_uuid"],
            }
        ],
        "orderByFilter": {"priority": {"position": "ASC"}},
        "pagination": {
            "limit": int(arguments["limit"]),
            "after": str(arguments.get("provider_cursor") or ""),
            "preciseCount": True,
        },
        "_limit": arguments["limit"],
        "_cumulative_returned": int(arguments.get("cumulative_returned") or 0),
        "_case_collection": "testcaseCases",
    }


def _plan_case_variables(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    return {
        "testCaseFilter": [{"testcasePlan_in": [arguments["source_uuid"]], "testcaseCase": {}}],
        "planFilter": {"uuid_in": [arguments["source_uuid"]]},
        "moduleFilter": {},
        "orderByFilter": {"testcaseCase": {"priority": {"position": "ASC"}}},
        "pagination": {
            "limit": int(arguments["limit"]),
            "after": str(arguments.get("provider_cursor") or ""),
            "preciseCount": True,
        },
        "_limit": arguments["limit"],
        "_cumulative_returned": int(arguments.get("cumulative_returned") or 0),
        "_case_collection": "testcasePlanCases",
    }


def _case_list_response(payload: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    limit = bounded_int(variables.get("_limit"), minimum=1)
    collection = variables["_case_collection"]
    if collection not in {"testcaseCases", "testcasePlanCases"}:
        raise ValueError("Invalid fixed testcase collection")
    raw, total, truncated, cursor = page_items(
        payload,
        collection=collection,
        limit=limit,
        prior_count=bounded_int(variables.get("_cumulative_returned", 0)),
    )
    items: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        path = f"data.buckets[0].{collection}[{index}]"
        if collection == "testcasePlanCases":
            path += ".testcaseCase"
            item = require_mapping(item.get("testcaseCase"), path=path)
        items.append({"uuid": bounded_string(item.get("uuid"), maximum=128, path=f"{path}.uuid")})
    output = normalized_list("test_cases", items, total=total, truncated=truncated)
    output["_provider_cursor"] = cursor
    return output


def _detail_variables(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    uuid = arguments["test_case_uuid"]
    return {
        "testCaseFilter": {"uuid_in": [uuid]},
        "stepFilter": {"testcaseCase_in": [uuid]},
    }


def _detail_response(payload: dict[str, Any], _variables: dict[str, Any]) -> dict[str, Any]:
    data = require_mapping(payload.get("data"), path="data")
    cases = require_list(data.get("testcaseCases"), path="data.testcaseCases")
    if len(cases) != 1:
        raise invalid_provider_response("ones_provider_schema_invalid")
    path = "data.testcaseCases[0]"
    item = require_mapping(cases[0], path=path)
    test_case: dict[str, Any] = {
        "uuid": bounded_string(item.get("uuid"), maximum=128, path=f"{path}.uuid"),
        "name": bounded_string(item.get("name"), maximum=500, path=f"{path}.name"),
    }
    for source, target in (
        ("testcaseLibrary", "library_uuid"),
        ("testcaseModule", "module_uuid"),
    ):
        value = item.get(source)
        if isinstance(value, dict) and value.get("uuid"):
            test_case[target] = bounded_string(
                value.get("uuid"), maximum=128, path=f"{path}.{source}.uuid"
            )
    if item.get("path") is not None:
        test_case["path"] = bounded_string(item.get("path"), maximum=1000, path=f"{path}.path")
    assignee = optional_person(item.get("assign"), path=f"{path}.assign")
    if assignee is not None:
        test_case["assignee"] = assignee
    if item.get("createTime") is not None:
        test_case["created_at"] = timestamp_text(
            item.get("createTime"), unit="seconds", path="data.testcaseCases[0].createTime"
        )
    steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(
        require_list(data.get("testcaseCaseSteps"), path="data.testcaseCaseSteps")[:100]
    ):
        step_path = f"data.testcaseCaseSteps[{index}]"
        step = require_mapping(raw_step, path=step_path)
        steps.append(
            {
                "index": bounded_int(step.get("index"), path=f"{step_path}.index"),
                "description": bounded_string(
                    step.get("desc", ""), maximum=2000, allow_empty=True, path=f"{step_path}.desc"
                ),
                "expected_result": bounded_string(
                    step.get("result", ""),
                    maximum=2000,
                    allow_empty=True,
                    path=f"{step_path}.result",
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
