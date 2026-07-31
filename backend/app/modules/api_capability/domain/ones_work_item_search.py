from __future__ import annotations

from typing import Any


ONES_WORK_ITEM_SEARCH_IDENTIFIER = "cap__ones__work_item__search"

ONES_WORK_ITEM_SEARCH_GRAPHQL = """
query SearchWorkItems(
  $keyword: String!
  $issue_type: String!
  $limit: Int!
  $user_id: ID!
  $team_id: ID!
) {
  workItems(
    keyword: $keyword
    issueType: $issue_type
    limit: $limit
    userId: $user_id
    teamId: $team_id
  ) {
    items { number name type }
    total
    truncated
  }
}
""".strip()


def ones_work_item_search_template() -> dict[str, Any]:
    return {
        "identifier": ONES_WORK_ITEM_SEARCH_IDENTIFIER,
        "capability": {
            "name": "搜索 ONES 工作项",
            "description": (
                "按关键词和工作项类型搜索当前用户默认 Team 中的 ONES "
                "需求、任务或缺陷，返回有界的编号、名称和类型列表。"
            ),
            "operation_semantics": "QUERY",
            "data_classification": "INTERNAL",
            "input_schema": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                    },
                    "issue_type": {
                        "type": "string",
                        "enum": ["demand", "task", "defect"],
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": ["keyword", "issue_type", "limit"],
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "minItems": 0,
                        "maxItems": 50,
                        "items": {
                            "type": "object",
                            "properties": {
                                "number": {
                                    "type": "integer",
                                    "minimum": 1,
                                },
                                "name": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 500,
                                },
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "demand",
                                        "task",
                                        "defect",
                                    ],
                                },
                            },
                            "required": ["number", "name", "type"],
                            "additionalProperties": False,
                        },
                    },
                    "total": {
                        "type": "integer",
                        "minimum": 0,
                    },
                    "truncated": {"type": "boolean"},
                },
                "required": ["items", "total", "truncated"],
                "additionalProperties": False,
            },
        },
        "handler": {
            "method": "POST",
            "relative_path": "/project/api/project/items/graphql",
            "graphql_document": ONES_WORK_ITEM_SEARCH_GRAPHQL,
        },
        "mapping_ast": {
            "schema_version": 1,
            "request": {
                "op": "object",
                "fields": {
                    "body": {
                        "op": "object",
                        "fields": {
                            "keyword": {
                                "op": "source",
                                "source": "AGENT_INPUT",
                                "path": "$.keyword",
                            },
                            "issue_type": {
                                "op": "source",
                                "source": "AGENT_INPUT",
                                "path": "$.issue_type",
                            },
                            "limit": {
                                "op": "source",
                                "source": "AGENT_INPUT",
                                "path": "$.limit",
                            },
                            "user_id": {
                                "op": "source",
                                "source": "SYSTEM_CONTEXT",
                                "path": "$.external_user_id",
                            },
                            "team_id": {
                                "op": "source",
                                "source": "SYSTEM_CONTEXT",
                                "path": "$.default_team_id",
                            },
                        },
                    },
                    "query": {"op": "object", "fields": {}},
                },
            },
            "response": {
                "op": "object",
                "fields": {
                    "items": {
                        "op": "array_map",
                        "source": {
                            "op": "source",
                            "source": "RESPONSE",
                            "path": "$.data.workItems.items",
                        },
                        "item": {
                            "op": "object",
                            "fields": {
                                "number": {
                                    "op": "source",
                                    "source": "RESPONSE",
                                    "path": "$.number",
                                },
                                "name": {
                                    "op": "source",
                                    "source": "RESPONSE",
                                    "path": "$.name",
                                },
                                "type": {
                                    "op": "source",
                                    "source": "RESPONSE",
                                    "path": "$.type",
                                },
                            },
                        },
                    },
                    "total": {
                        "op": "source",
                        "source": "RESPONSE",
                        "path": "$.data.workItems.total",
                    },
                    "truncated": {
                        "op": "source",
                        "source": "RESPONSE",
                        "path": "$.data.workItems.truncated",
                    },
                },
            },
        },
    }
