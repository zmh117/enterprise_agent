from __future__ import annotations

from typing import Any

from app.modules.mcp_audit import McpAuditHandle
from services.ones_mcp_server.auth.principal import ResolvedOnesPrincipal
from services.ones_mcp_server.condition_dictionary import QueryConditionDictionary
from services.ones_mcp_server.contracts import PROVIDER_HEADERS
from services.ones_mcp_server.errors import invalid_provider_response
from services.ones_mcp_server.pagination import (
    MAX_GRAPHQL_LIST_RESULTS,
    OnesGraphqlListCursorCodec,
    OnesGraphqlListPage,
)
from services.ones_mcp_server.provider.graphql.client import OnesGraphqlClient
from services.ones_mcp_server.provider.graphql.operations.business_queries import (
    ISSUE_TYPE_LIST,
    PROJECT_SEARCH,
    SPRINT_WORK_ITEM_QUERY,
    WORK_ITEM_DETAIL,
    WORK_ITEM_QUERY,
)
from services.ones_mcp_server.provider.graphql.operations.test_queries import (
    TEST_PLAN_LIST,
    TESTCASE_DETAIL,
    TESTCASE_LIBRARY_LIST,
    TESTCASE_MODULE_CASES,
    TESTCASE_MODULE_LIST,
    TESTCASE_PLAN_CASES,
)
from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient
from services.ones_mcp_server.provider.rest.operations.basic_queries import (
    PROJECT_SPRINTS_OPERATION,
    TEAM_USER_SEARCH_OPERATION,
    WORK_ITEM_MESSAGES_OPERATION,
)
from services.ones_mcp_server.provider.rest.operations.project_role_members import (
    TEAM_USERS_OPERATION,
)
from services.ones_mcp_server.tools.base import (
    BaseOnesQueryService,
    BaseOnesResourceQueryService,
    ProviderCall,
)
from services.ones_mcp_server.tools.validation import (
    custom_option_filters,
    identifier,
    identifier_list,
    integer,
    invalid_input,
    require_fields,
    status_categories,
    text,
    timestamp,
)


class GraphqlQueryService(BaseOnesQueryService):
    operation_code: str

    def __init__(self, *args: Any, graphql: OnesGraphqlClient, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.graphql = graphql

    def selected_operation(self, arguments: dict[str, Any]) -> str:
        del arguments
        return self.operation_code

    def call_provider(
        self,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
    ) -> ProviderCall:
        execution = self.graphql.execute(
            self.selected_operation(arguments),
            arguments=arguments,
            context={"team_id": principal.team_id},
            headers={
                PROVIDER_HEADERS["token"]: principal.credential.secrets.token,
                PROVIDER_HEADERS["user"]: principal.provider_user_id,
            },
        )
        return ProviderCall(
            execution.output,
            execution.request,
            self.response_summary(execution.output),
        )


class PaginatedGraphqlQueryService(GraphqlQueryService):
    pagination_mode = OnesGraphqlListCursorCodec.PROVIDER_MODE
    output_field: str

    @staticmethod
    def response_summary(output: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "result_keys": sorted(key for key in output if not key.startswith("_"))
        }
        for key in ("total", "returned", "truncated"):
            if key in output:
                summary[key] = output[key]
        return summary

    def prepare_provider_arguments(
        self,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        del principal
        return dict(arguments)

    def _execute_with_refresh(
        self,
        *,
        claims: dict[str, Any],
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        page = OnesGraphqlListCursorCodec.decode(
            str(arguments.get("cursor") or ""),
            tool_identifier=self.tool_identifier,
            input_schema=self.input_schema,
            mode=self.pagination_mode,
            claims=claims,
            principal=principal,
            request=arguments,
        )
        provider_arguments = self.prepare_provider_arguments(
            principal,
            {key: value for key, value in arguments.items() if key != "cursor"},
        )
        provider_arguments.update(
            {
                "limit": min(int(arguments["limit"]), page.remaining),
                "provider_cursor": page.provider_cursor,
                "page_offset": page.offset,
                "cumulative_returned": page.cumulative_returned,
            }
        )
        provider_output = super()._execute_with_refresh(
            claims=claims,
            handle=handle,
            principal=principal,
            arguments=provider_arguments,
        )
        return self._public_page_output(
            provider_output,
            claims=claims,
            principal=principal,
            request=arguments,
            page=page,
        )

    def _public_page_output(
        self,
        provider_output: dict[str, Any],
        *,
        claims: dict[str, Any],
        principal: ResolvedOnesPrincipal,
        request: dict[str, Any],
        page: OnesGraphqlListPage,
    ) -> dict[str, Any]:
        items = provider_output.get(self.output_field)
        total = provider_output.get("total")
        returned_value = provider_output.get("returned")
        truncated = provider_output.get("truncated")
        if (
            not isinstance(items, list)
            or type(total) is not int
            or total < 0
            or type(returned_value) is not int
            or returned_value != len(items)
            or type(truncated) is not bool
        ):
            raise invalid_provider_response("ones_provider_schema_invalid")
        returned = len(items)
        cumulative_returned = page.cumulative_returned + returned
        if (
            returned > min(int(request["limit"]), page.remaining)
            or cumulative_returned > MAX_GRAPHQL_LIST_RESULTS
        ):
            raise invalid_provider_response("ones_provider_schema_invalid")

        continuation = self._continuation_page(
            provider_output,
            page=page,
            returned=returned,
            cumulative_returned=cumulative_returned,
            truncated=truncated,
        )
        pagination_limit_reached = (
            truncated and cumulative_returned >= MAX_GRAPHQL_LIST_RESULTS
        )
        output: dict[str, Any] = {
            self.output_field: items,
            "total": total,
            "returned": returned,
            "cumulative_returned": cumulative_returned,
            "truncated": truncated,
            "pagination_limit_reached": pagination_limit_reached,
            "untrusted_data": True,
        }
        if truncated and not pagination_limit_reached:
            if continuation is None:
                raise invalid_provider_response("ones_provider_schema_invalid")
            output["next_cursor"] = OnesGraphqlListCursorCodec.encode(
                page=continuation,
                tool_identifier=self.tool_identifier,
                input_schema=self.input_schema,
                claims=claims,
                principal=principal,
                request=request,
            )
        return output

    def _continuation_page(
        self,
        provider_output: dict[str, Any],
        *,
        page: OnesGraphqlListPage,
        returned: int,
        cumulative_returned: int,
        truncated: bool,
    ) -> OnesGraphqlListPage | None:
        if self.pagination_mode == OnesGraphqlListCursorCodec.PROVIDER_MODE:
            provider_cursor = provider_output.get("_provider_cursor")
            if not isinstance(provider_cursor, str):
                raise invalid_provider_response("ones_provider_schema_invalid")
            if truncated:
                if (
                    not returned
                    or not provider_cursor
                    or provider_cursor == page.provider_cursor
                ):
                    raise invalid_provider_response("ones_provider_schema_invalid")
                return OnesGraphqlListPage(
                    mode=self.pagination_mode,
                    provider_cursor=provider_cursor,
                    cumulative_returned=cumulative_returned,
                )
            return None

        next_offset = provider_output.get("_next_offset")
        collection_fingerprint = provider_output.get("_collection_fingerprint")
        if (
            type(next_offset) is not int
            or not isinstance(collection_fingerprint, str)
            or len(collection_fingerprint) != 64
        ):
            raise invalid_provider_response("ones_provider_schema_invalid")
        if page.collection_fingerprint and (
            collection_fingerprint != page.collection_fingerprint
        ):
            raise OnesGraphqlListCursorCodec.stale()
        if truncated:
            if not returned or next_offset <= page.offset or next_offset != cumulative_returned:
                raise invalid_provider_response("ones_provider_schema_invalid")
            return OnesGraphqlListPage(
                mode=self.pagination_mode,
                offset=next_offset,
                collection_fingerprint=collection_fingerprint,
                cumulative_returned=cumulative_returned,
            )
        return None


def _cursor(arguments: dict[str, Any], result: dict[str, Any]) -> None:
    if "cursor" in arguments:
        value = text(arguments["cursor"], maximum=4096, allow_empty=True)
        if value:
            result["cursor"] = value


class OnesProjectSearchService(PaginatedGraphqlQueryService):
    tool_identifier = "ones_search_projects"
    operation_code = PROJECT_SEARCH
    output_field = "projects"

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = require_fields(
            arguments,
            allowed={"keyword", "limit", "cursor"},
            required={"keyword", "limit"},
        )
        result = {
            "keyword": text(value["keyword"], maximum=200, allow_empty=True).strip(),
            "limit": integer(value["limit"], minimum=1, maximum=100),
        }
        _cursor(value, result)
        return result


class OnesIssueTypeListService(PaginatedGraphqlQueryService):
    tool_identifier = "ones_list_issue_types"
    operation_code = ISSUE_TYPE_LIST
    output_field = "issue_types"
    pagination_mode = OnesGraphqlListCursorCodec.SNAPSHOT_OFFSET_MODE

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = require_fields(
            arguments,
            allowed={"project_uuid", "limit", "cursor"},
            required={"project_uuid", "limit"},
        )
        result = {
            "project_uuid": identifier(value["project_uuid"]),
            "limit": integer(value["limit"], minimum=1, maximum=100),
        }
        _cursor(value, result)
        return result


class OnesWorkItemQueryService(PaginatedGraphqlQueryService):
    tool_identifier = "ones_query_work_items"
    operation_code = WORK_ITEM_QUERY
    output_field = "items"
    _allowed = {
        "keyword",
        "project_uuid",
        "sprint_uuid",
        "issue_type_uuids",
        "status_uuids",
        "status_categories",
        "assignee_uuids",
        "created_from",
        "created_to",
        "limit",
        "cursor",
    }

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = require_fields(arguments, allowed=self._allowed, required={"limit"})
        result: dict[str, Any] = {"limit": integer(value["limit"], minimum=1, maximum=100)}
        if "keyword" in value:
            result["keyword"] = text(value["keyword"], maximum=200, allow_empty=True).strip()
        for key in ("project_uuid", "sprint_uuid"):
            if key in value:
                result[key] = identifier(value[key])
        if "sprint_uuid" in result and "project_uuid" not in result:
            raise invalid_input("ONES sprint query requires a project")
        for key in ("issue_type_uuids", "status_uuids", "assignee_uuids"):
            if key in value:
                result[key] = identifier_list(value[key], maximum_items=20)
        if "status_categories" in value:
            result["status_categories"] = status_categories(value["status_categories"])
        for key in ("created_from", "created_to"):
            if key in value:
                result[key] = timestamp(value[key])
        if "created_from" in result and "created_to" in result:
            from datetime import datetime

            start = datetime.fromisoformat(result["created_from"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(result["created_to"].replace("Z", "+00:00"))
            if end <= start:
                raise invalid_input("ONES work item time range is invalid")
        _cursor(value, result)
        return result

    def selected_operation(self, arguments: dict[str, Any]) -> str:
        return SPRINT_WORK_ITEM_QUERY if arguments.get("sprint_uuid") else WORK_ITEM_QUERY


class OnesCustomOptionWorkItemQueryService(OnesWorkItemQueryService):
    tool_identifier = "ones_query_work_items_with_custom_options"
    _allowed = OnesWorkItemQueryService._allowed | {"custom_option_filters"}

    def __init__(
        self,
        *args: Any,
        graphql: OnesGraphqlClient,
        dictionary: QueryConditionDictionary,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, graphql=graphql, **kwargs)
        self.dictionary = dictionary

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if "custom_option_filters" not in arguments:
            raise invalid_input()
        result = super().validate_arguments(arguments)
        result["custom_option_filters"] = custom_option_filters(arguments["custom_option_filters"])
        return result

    def prepare_provider_arguments(
        self,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        provider_arguments = dict(arguments)
        filters = list(arguments.get("custom_option_filters") or [])
        if filters:
            provider_arguments["custom_option_filters"] = self.dictionary.validated_custom_filters(
                team_uuid=principal.team_id,
                filters=filters,
            )
        return provider_arguments


class OnesWorkItemDetailService(GraphqlQueryService):
    tool_identifier = "ones_get_work_item_detail"
    operation_code = WORK_ITEM_DETAIL

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = require_fields(
            arguments,
            allowed={"work_item_uuid"},
            required={"work_item_uuid"},
        )
        return {"work_item_uuid": identifier(value["work_item_uuid"])}


class OnesTestcaseLibraryListService(PaginatedGraphqlQueryService):
    tool_identifier = "ones_list_testcase_libraries"
    operation_code = TESTCASE_LIBRARY_LIST
    output_field = "libraries"

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = require_fields(arguments, allowed={"limit", "cursor"}, required={"limit"})
        result = {"limit": integer(value["limit"], minimum=1, maximum=100)}
        _cursor(value, result)
        return result


class OnesTestcaseModuleListService(PaginatedGraphqlQueryService):
    tool_identifier = "ones_list_testcase_modules"
    operation_code = TESTCASE_MODULE_LIST
    output_field = "modules"
    pagination_mode = OnesGraphqlListCursorCodec.SNAPSHOT_OFFSET_MODE

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = require_fields(
            arguments,
            allowed={"library_uuid", "limit", "cursor"},
            required={"library_uuid", "limit"},
        )
        result = {
            "library_uuid": identifier(value["library_uuid"]),
            "limit": integer(value["limit"], minimum=1, maximum=200),
        }
        _cursor(value, result)
        return result


class OnesTestPlanListService(PaginatedGraphqlQueryService):
    tool_identifier = "ones_list_test_plans"
    operation_code = TEST_PLAN_LIST
    output_field = "plans"

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = require_fields(arguments, allowed={"limit", "cursor"}, required={"limit"})
        result = {"limit": integer(value["limit"], minimum=1, maximum=100)}
        _cursor(value, result)
        return result


class OnesTestCaseQueryService(PaginatedGraphqlQueryService):
    tool_identifier = "ones_query_test_cases"
    operation_code = TESTCASE_MODULE_CASES
    output_field = "test_cases"

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = require_fields(
            arguments,
            allowed={"source", "source_uuid", "library_uuid", "limit", "cursor"},
            required={"source", "source_uuid", "limit"},
        )
        source = value["source"]
        if source not in {"module", "plan"}:
            raise invalid_input()
        result: dict[str, Any] = {
            "source": source,
            "source_uuid": identifier(value["source_uuid"]),
            "limit": integer(value["limit"], minimum=1, maximum=200),
        }
        if "library_uuid" in value:
            result["library_uuid"] = identifier(value["library_uuid"])
        if source == "module" and "library_uuid" not in result:
            raise invalid_input("ONES module query requires a testcase library")
        if source == "plan" and "library_uuid" in result:
            raise invalid_input("ONES plan query does not accept a testcase library")
        _cursor(value, result)
        return result

    def selected_operation(self, arguments: dict[str, Any]) -> str:
        return TESTCASE_MODULE_CASES if arguments["source"] == "module" else TESTCASE_PLAN_CASES


class OnesTestCaseDetailService(GraphqlQueryService):
    tool_identifier = "ones_get_test_case_detail"
    operation_code = TESTCASE_DETAIL

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = require_fields(
            arguments,
            allowed={"test_case_uuid"},
            required={"test_case_uuid"},
        )
        return {"test_case_uuid": identifier(value["test_case_uuid"])}


class RestQueryService(BaseOnesQueryService):
    def __init__(self, *args: Any, http: OnesProviderHttpClient, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.http = http


class OnesProjectSprintListService(RestQueryService):
    tool_identifier = "ones_list_project_sprints"

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = require_fields(
            arguments,
            allowed={"project_uuid", "limit"},
            required={"project_uuid", "limit"},
        )
        return {
            "project_uuid": identifier(value["project_uuid"]),
            "limit": integer(value["limit"], minimum=1, maximum=100),
        }

    def call_provider(
        self,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
    ) -> ProviderCall:
        execution = PROJECT_SPRINTS_OPERATION.execute(
            self.http,
            team_uuid=principal.team_id,
            project_uuid=arguments["project_uuid"],
            limit=arguments["limit"],
            token=principal.credential.secrets.token,
            user_id=principal.provider_user_id,
        )
        return ProviderCall(
            execution.output,
            execution.request,
            self.response_summary(execution.output),
        )


class OnesWorkItemMessageListService(RestQueryService):
    tool_identifier = "ones_list_work_item_messages"

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = require_fields(
            arguments,
            allowed={"work_item_uuid", "limit"},
            required={"work_item_uuid", "limit"},
        )
        return {
            "work_item_uuid": identifier(value["work_item_uuid"]),
            "limit": integer(value["limit"], minimum=1, maximum=100),
        }

    def call_provider(
        self,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
    ) -> ProviderCall:
        execution = WORK_ITEM_MESSAGES_OPERATION.execute(
            self.http,
            team_uuid=principal.team_id,
            work_item_uuid=arguments["work_item_uuid"],
            limit=arguments["limit"],
            token=principal.credential.secrets.token,
            user_id=principal.provider_user_id,
        )
        return ProviderCall(
            execution.output,
            execution.request,
            self.response_summary(execution.output),
        )


class OnesTeamUserSearchService(RestQueryService):
    tool_identifier = "ones_search_team_users"

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = require_fields(
            arguments,
            allowed={"keyword", "project_uuid", "limit"},
            required={"keyword", "limit"},
        )
        result: dict[str, Any] = {
            "keyword": text(value["keyword"], maximum=200, allow_empty=True).strip(),
            "limit": integer(value["limit"], minimum=1, maximum=100),
        }
        if "project_uuid" in value:
            result["project_uuid"] = identifier(value["project_uuid"])
        return result

    def call_provider(
        self,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
    ) -> ProviderCall:
        execution = TEAM_USER_SEARCH_OPERATION.execute(
            self.http,
            team_uuid=principal.team_id,
            keyword=arguments["keyword"],
            project_uuid=str(arguments.get("project_uuid") or ""),
            limit=arguments["limit"],
            token=principal.credential.secrets.token,
            user_id=principal.provider_user_id,
        )
        return ProviderCall(
            execution.output,
            execution.request,
            self.response_summary(execution.output),
        )


class OnesUsersByUuidService(RestQueryService):
    tool_identifier = "ones_get_users_by_uuids"

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = require_fields(
            arguments,
            allowed={"user_uuids"},
            required={"user_uuids"},
        )
        return {"user_uuids": identifier_list(value["user_uuids"], maximum_items=100)}

    def call_provider(
        self,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
    ) -> ProviderCall:
        execution = TEAM_USERS_OPERATION.execute(
            self.http,
            team_uuid=principal.team_id,
            member_uuids=arguments["user_uuids"],
            token=principal.credential.secrets.token,
            user_id=principal.provider_user_id,
        )
        users_by_uuid = execution.output
        users = [
            {"uuid": uuid, "name": users_by_uuid[uuid]}
            for uuid in arguments["user_uuids"]
            if uuid in users_by_uuid
        ]
        output = {
            "users": users,
            "total": len(users),
            "returned": len(users),
            "truncated": False,
            "untrusted_data": True,
        }
        return ProviderCall(
            output,
            {
                "operation": execution.request["operation"],
                "method": execution.request["method"],
                "requested": len(arguments["user_uuids"]),
            },
            self.response_summary(output),
        )


class OnesQueryConditionResolverService(BaseOnesResourceQueryService):
    tool_identifier = "ones_resolve_query_conditions"

    def __init__(
        self,
        *args: Any,
        dictionary: QueryConditionDictionary,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.dictionary = dictionary

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = require_fields(
            arguments,
            allowed={"condition_type", "keyword", "field_keyword", "limit"},
            required={"condition_type", "keyword", "limit"},
        )
        condition_type = text(value["condition_type"], maximum=30)
        if condition_type not in {"status", "custom_option"}:
            raise invalid_input()
        keyword = text(value["keyword"], maximum=200).strip()
        if not keyword:
            raise invalid_input()
        field_keyword = ""
        if "field_keyword" in value:
            field_keyword = text(value["field_keyword"], maximum=200).strip()
        if condition_type == "custom_option" and not field_keyword:
            raise invalid_input()
        if condition_type == "status" and field_keyword:
            raise invalid_input()
        return {
            "condition_type": condition_type,
            "keyword": keyword,
            "field_keyword": field_keyword,
            "limit": integer(value["limit"], minimum=1, maximum=20),
        }

    def call_provider(
        self,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
    ) -> ProviderCall:
        output = self.dictionary.resolve(team_uuid=principal.team_id, **arguments)
        return ProviderCall(
            output,
            {
                "operation": "resolve_query_conditions",
                "condition_type": arguments["condition_type"],
                "keyword_length": len(arguments["keyword"]),
                "field_keyword_length": len(arguments["field_keyword"]),
                "limit": arguments["limit"],
                "dictionary_version": self.dictionary.dictionary_version,
            },
            self.response_summary(output),
        )
