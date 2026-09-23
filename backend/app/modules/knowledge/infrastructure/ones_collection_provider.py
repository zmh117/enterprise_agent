"""固定 ONES 只读接口适配器；不执行本地导出脚本或抓取讨论/附件。"""

from __future__ import annotations

from datetime import date
from collections.abc import Callable
from typing import Any

from app.modules.knowledge.application.ones_collection import CollectionPage, PAGE_SIZE
from app.modules.knowledge.domain.normalization import ExportValidationError, identifier
from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient
from services.ones_mcp_server.provider.rest.operations.common import request_headers


_GRAPHQL_PATH = "/project/api/project/team/{team}/items/graphql"
_DETAIL_PATH = "/project/api/project/team/{team}/task/{uuid}/info"
_STAMPS_PATH = "/project/api/project/team/{team}/stamps/data"
_SCOPE_QUERY = """{
  issueTypeScopes(filter: $filter) {
    uuid name scope scopeName
    issueType { uuid name }
  }
}"""
_LIST_QUERY = """
{
  buckets(groupBy:$groupBy orderBy:$groupOrderBy pagination:$pagination filter:$groupFilter) {
    tasks(filterGroup:$filterGroup orderBy:$orderBy limit:1000) {
      uuid number name createTime
      project { uuid name }
      status { uuid name }
      sprint { uuid name }
      issueType { uuid name }
      subIssueType { uuid name }
      parent { uuid }
      subTaskCount
    }
    pageInfo { count totalCount hasNextPage endCursor }
  }
}
"""
_COUNT_QUERY = """
{
  buckets(groupBy:$groupBy orderBy:$groupOrderBy pagination:$pagination filter:$groupFilter) {
    tasks(filterGroup:$filterGroup orderBy:$orderBy limit:0) { uuid }
    pageInfo { totalCount hasNextPage }
  }
}
"""


class HttpOnesCollectionProvider:
    """实例、Team、项目及采集身份在构造时固定，查询参数不能改目标。"""

    def __init__(
        self,
        http: OnesProviderHttpClient,
        *,
        team_id: str,
        project_ids: frozenset[str],
        token: str,
        user_id: str,
    ) -> None:
        self.http = http
        self.team_id = identifier(team_id)
        if not project_ids or any(identifier(value) != value for value in project_ids):
            raise ExportValidationError("knowledge_collection_scope_invalid")
        self.project_ids = tuple(sorted(project_ids))
        if not token or not user_id:
            raise ExportValidationError("knowledge_collection_identity_missing")
        self._headers = request_headers(http, token=token, user_id=identifier(user_id))

    def _bucket(
        self,
        query: str,
        issue_type_id: str,
        first: date,
        last: date,
        *,
        after: str | None,
        count_only: bool,
    ) -> dict[str, Any]:
        pagination: dict[str, Any] = {
            "limit": 0 if count_only else PAGE_SIZE,
            "preciseCount": count_only,
        }
        if after is not None:
            pagination["after"] = after
        variables: dict[str, Any] = {
            "groupBy": {"tasks": {}},
            "groupOrderBy": None,
            "orderBy": {"position": "ASC", "createTime": "DESC"},
            "filterGroup": [
                {
                    "issueType_in": [identifier(issue_type_id)],
                    "project_in": list(self.project_ids),
                    "parent_in": [""],
                    "createTime_range": {"gte": first.isoformat(), "lte": last.isoformat()},
                }
            ],
            "search": None,
            "pagination": pagination,
        }
        response = self.http.post_json(
            _GRAPHQL_PATH.format(team=self.team_id),
            {"query": query, "variables": variables},
            headers=self._headers,
            query={"t": "total-task-count" if count_only else "group-task-data"},
        )
        if response.get("errors"):
            raise ExportValidationError("knowledge_collection_provider_error")
        data = response.get("data")
        buckets = data.get("buckets") if isinstance(data, dict) else None
        if not isinstance(buckets, list) or len(buckets) != 1 or not isinstance(buckets[0], dict):
            raise ExportValidationError("knowledge_collection_page_invalid")
        return buckets[0]

    def count(self, issue_type_id: str, first: date, last: date) -> int:
        bucket = self._bucket(_COUNT_QUERY, issue_type_id, first, last, after=None, count_only=True)
        info = bucket.get("pageInfo")
        value = info.get("totalCount") if isinstance(info, dict) else None
        if type(value) is not int or value < 0:
            raise ExportValidationError("knowledge_collection_count_invalid")
        return value

    def page(
        self, issue_type_id: str, first: date, last: date, *, after: str | None
    ) -> CollectionPage:
        bucket = self._bucket(
            _LIST_QUERY, issue_type_id, first, last, after=after, count_only=False
        )
        tasks, info = bucket.get("tasks"), bucket.get("pageInfo")
        if not isinstance(tasks, list) or not isinstance(info, dict):
            raise ExportValidationError("knowledge_collection_page_invalid")
        total, has_next, cursor = (
            info.get("totalCount"),
            info.get("hasNextPage"),
            info.get("endCursor"),
        )
        count = info.get("count")
        if (
            type(total) is not int
            or type(has_next) is not bool
            or type(count) is not int
            or cursor is not None
            and not isinstance(cursor, str)
            or any(not isinstance(item, dict) for item in tasks)
        ):
            raise ExportValidationError("knowledge_collection_page_invalid")
        return CollectionPage(tuple(tasks), total, has_next, cursor, count)

    def detail(self, work_item_id: str) -> dict[str, Any]:
        response = self.http.get_json(
            _DETAIL_PATH.format(team=self.team_id, uuid=identifier(work_item_id)),
            None,
            headers=self._headers,
        )
        result = response.get("task") if isinstance(response.get("task"), dict) else response
        if not isinstance(result, dict) or result.get("uuid") != work_item_id:
            raise ExportValidationError("knowledge_collection_detail_mismatch")
        return result

    def catalog(  # noqa: C901, PLR0915
        self, issue_type_ids: tuple[str, ...], *, check_active: Callable[[], None]
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        """只获取规范化必需的字段、成员和类型范围名称。"""
        path = _STAMPS_PATH.format(team=self.team_id)
        check_active()
        fields_body = self.http.post_json(
            path, {"field": 0}, headers=self._headers, query={"t": "field"}
        )
        check_active()
        members_body = self.http.post_json(
            path, {"team_member": 0}, headers=self._headers, query={"t": "team_member"}
        )
        field_node, member_node = fields_body.get("field"), members_body.get("team_member")
        if not isinstance(field_node, dict) or not isinstance(member_node, dict):
            raise ExportValidationError("knowledge_collection_catalog_invalid")
        fields, members = field_node.get("fields"), member_node.get("members")
        if not isinstance(fields, list) or not isinstance(members, list):
            raise ExportValidationError("knowledge_collection_catalog_invalid")
        field_map: dict[str, dict[str, Any]] = {}
        names: dict[str, str] = {}
        for field in fields:
            if not isinstance(field, dict) or not isinstance(field.get("name"), str):
                raise ExportValidationError("knowledge_collection_catalog_invalid")
            fid = identifier(field.get("uuid"))
            options = field.get("options") or []
            if fid in field_map or not isinstance(options, list):
                raise ExportValidationError("knowledge_collection_catalog_invalid")
            option_ids: set[str] = set()
            for option in options:
                if not isinstance(option, dict) or "value" not in option:
                    raise ExportValidationError("knowledge_collection_catalog_invalid")
                option_id = identifier(option.get("uuid"))
                if option_id in option_ids:
                    raise ExportValidationError("knowledge_collection_catalog_invalid")
                option_ids.add(option_id)
            field_map[fid] = {
                "uuid": fid,
                "name": field["name"],
                "type": field.get("type"),
                "options": options,
            }
        for member in members:
            if not isinstance(member, dict):
                raise ExportValidationError("knowledge_collection_catalog_invalid")
            uid, name = member.get("uuid"), member.get("name")
            if uid and isinstance(name, str) and name:
                names[identifier(uid)] = name
        for issue_type_id in issue_type_ids:
            check_active()
            response = self.http.post_json(
                _GRAPHQL_PATH.format(team=self.team_id),
                {
                    "query": _SCOPE_QUERY,
                    "variables": {"filter": {"issueType_in": [identifier(issue_type_id)]}},
                },
                headers=self._headers,
                query={"t": "issueTypeScopes"},
            )
            if response.get("errors"):
                raise ExportValidationError("knowledge_collection_provider_error")
            data = response.get("data")
            scopes = data.get("issueTypeScopes") if isinstance(data, dict) else None
            if not isinstance(scopes, list):
                raise ExportValidationError("knowledge_collection_catalog_invalid")
            for scope in scopes:
                if not isinstance(scope, dict):
                    raise ExportValidationError("knowledge_collection_catalog_invalid")
                uid = scope.get("uuid")
                type_node = scope.get("issueType") or {}
                scope_name, type_name = scope.get("scopeName"), scope.get("name")
                if not type_name and isinstance(type_node, dict):
                    type_name = type_node.get("name")
                if scope_name is not None and not isinstance(scope_name, str):
                    raise ExportValidationError("knowledge_collection_catalog_invalid")
                if type_name is not None and not isinstance(type_name, str):
                    raise ExportValidationError("knowledge_collection_catalog_invalid")
                if uid and (scope_name or type_name):
                    label = (
                        f"{scope_name}·{type_name}"
                        if scope_name and type_name
                        else scope_name or type_name
                    )
                    names[identifier(uid)] = str(label)
                if isinstance(type_node, dict) and type_node.get("uuid") and type_node.get("name"):
                    names[identifier(type_node["uuid"])] = type_node["name"]
        return field_map, names
