from __future__ import annotations

import re
from typing import Any, Protocol


_OPERATION_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class GraphqlOperation(Protocol):
    """A code-owned ONES GraphQL query contract.

    Documents, paths, variable builders, and parsers are implementation facts.
    None of them are accepted from MCP Tool input.
    """

    code: str
    path: str
    document: str

    def build_variables(
        self,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]: ...

    def parse_response(
        self,
        payload: dict[str, Any],
        *,
        variables: dict[str, Any],
    ) -> dict[str, Any]: ...


class GraphqlOperationRegistry:
    def __init__(self, operations: tuple[GraphqlOperation, ...]) -> None:
        registered: dict[str, GraphqlOperation] = {}
        for operation in operations:
            if (
                not _OPERATION_CODE.fullmatch(operation.code)
                or not operation.path.startswith("/")
                or not operation.path.endswith("/graphql")
                or "://" in operation.path
                or "?" in operation.path
                or "#" in operation.path
                or not operation.document.lstrip().startswith("query ")
            ):
                raise ValueError("ONES GraphQL operation contract is invalid")
            if operation.code in registered:
                raise ValueError(f"Duplicate ONES GraphQL operation: {operation.code}")
            registered[operation.code] = operation
        if not registered:
            raise ValueError("At least one ONES GraphQL operation is required")
        self._operations = registered

    def require(self, code: str) -> GraphqlOperation:
        try:
            return self._operations[code]
        except KeyError as exc:
            raise KeyError(f"Unknown ONES GraphQL operation: {code}") from exc

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(sorted(self._operations))
