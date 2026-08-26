from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FixedGraphqlOperation:
    code: str
    query_type: str
    document: str
    variable_builder: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    response_parser: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    path_template: str = "/project/api/project/team/{team_uuid}/items/graphql"

    def build_variables(
        self,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return self.variable_builder(arguments, context)

    def parse_response(
        self,
        payload: dict[str, Any],
        *,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        return self.response_parser(payload, variables)

