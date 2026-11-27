from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.modules.channel.browser.http import deny
from app.modules.channel.browser.scope import (
    ScopeKey,
    active_app,
    authorized_scopes,
    fingerprint,
    scope_key,
)
from app.shared.secret_redaction import is_sensitive_key


class PageRule(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    origin: str = Field(max_length=300)
    path: str = Field(min_length=1, max_length=768)
    hash_path: str = Field(default="", max_length=768)
    query: dict[str, str] = Field(default_factory=dict, max_length=8)

    def canonical(self) -> dict[str, Any]:
        try:
            addr = urlsplit(self.origin)
            host = addr.hostname or ""
            hostname = f"[{host}]" if ":" in host else host
            default = 443 if addr.scheme == "https" else 80
            port = "" if addr.port in (None, default) else f":{addr.port}"
        except ValueError as exc:
            raise deny("invalid_request", 422) from exc
        if (
            addr.scheme not in ("http", "https")
            or not host
            or not re.fullmatch(r"[a-z0-9.:-]+", host)
            or self.origin != f"{addr.scheme}://{hostname}{port}"
        ):
            raise deny("invalid_request", 422)
        for path in [self.path, self.hash_path or "/"]:
            if (
                not path.startswith("/")
                or any(char in path for char in ("?", "#", "\\"))
                or any(ord(char) < 33 or ord(char) > 126 for char in path)
                or any(part in (".", "..") for part in path.split("/"))
            ):
                raise deny("invalid_request", 422)
        for key, value in self.query.items():
            if (
                not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{0,63}", key)
                or is_sensitive_key(key)
                or re.search(r"cookie|session|ticket|signature|csrf|jwt|^sid$|^pwd$", key, re.I)
                or not re.fullmatch(r"[\w.-]{1,128}", value)
            ):
                raise deny("invalid_request", 422)
        return self.model_dump()


class SaveBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    rule: PageRule
    environment_id: str = Field(min_length=1, max_length=128)
    base_id: str | None = Field(default=None, min_length=1, max_length=128)
    workshop_id: str | None = Field(default=None, min_length=1, max_length=128)
    floating: bool = True
    previous_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)


def workshop_choices(c: Any, user: str, app: str) -> list[dict[str, Any]]:
    accesses = c.authorization_center_repository.business_access_for_user(
        user_id=user, application_id=app
    )
    return authorized_scopes(c, app, accesses)


def current_bindings(c: Any, origin: str, user: str) -> list[dict[str, Any]]:
    return c.database.execute(
        """select * from browser_workshop_binding where origin=? and user_id=?
           and is_head=1 order by id""",
        (origin, user),
    )


def public_binding(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: row[key] for key in ("id", "revision", "environment_id", "base_id", "workshop_id")},
        "rule": json.loads(row["rule_json"]),
        "enabled": bool(row["enabled"]),
        "floating": bool(row.get("floating", 1)),
    }


def routing_bindings(
    rows: list[dict[str, Any]], choices: set[ScopeKey], app: str
) -> list[dict[str, Any]]:
    visible = [
        public_binding(row)
        for row in rows
        if row["application_id"] == app and scope_key(row) in choices
    ]
    # Keep a more specific, inaccessible route from falling through to an authorized parent.
    # Only report path boundaries on origins this account can already bind, once per origin.
    first_by_origin = {}
    for binding in visible:
        first_by_origin.setdefault(binding["rule"]["origin"], binding)
    reserved: dict[str, set[tuple[str, str]]] = {origin: set() for origin in first_by_origin}
    for row in rows:
        if row["application_id"] != app or scope_key(row) not in choices:
            rule = json.loads(row["rule_json"])
            if rule["origin"] in reserved:
                reserved[rule["origin"]].add((rule["path"], rule["hash_path"]))
    for origin, binding in first_by_origin.items():
        binding["reserved_paths"] = [
            {"path": path, "hash_path": fragment} for path, fragment in sorted(reserved[origin])
        ]
    return visible


def overlaps(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a["origin"] != b["origin"] or any(
        a[key].rstrip("/") != b[key].rstrip("/") for key in ("path", "hash_path")
    ):
        return False
    return all(a["query"][key] == b["query"][key] for key in a["query"].keys() & b["query"].keys())


def save_binding(c: Any, origin: str, user: str, app: str, body: SaveBinding) -> dict[str, Any]:
    rule = body.rule.canonical()
    if not any(
        all(row[k] == getattr(body, k) for k in ("environment_id", "base_id", "workshop_id"))
        for row in workshop_choices(c, user, app)
    ):
        raise deny("access_denied", 403)
    heads = current_bindings(c, origin, user)
    key = fingerprint(rule)
    target = next((r for r in heads if r["application_id"] == app and r["route_key"] == key), None)
    old = (
        next((r for r in heads if r["id"] == body.previous_id), None)
        if body.previous_id
        else target
    )
    if body.previous_id and (not old or not old["enabled"]):
        raise deny("binding_conflict", 409)
    if old:
        active_app(c, origin, user, old["application_id"])
        if scope_key(old) not in {
            scope_key(s) for s in workshop_choices(c, user, old["application_id"])
        }:
            raise deny("access_denied", 403)
    if (old["revision"] if old else 0) != body.expected_revision or (target and target != old):
        raise deny("binding_conflict", 409)
    if any(r != old and r["enabled"] and overlaps(rule, json.loads(r["rule_json"])) for r in heads):
        raise deny("binding_conflict", 409)
    if (
        old
        and old["enabled"]
        and old["application_id"] == app
        and old["route_key"] == key
        and scope_key(old) == (body.environment_id, body.base_id, body.workshop_id)
    ):
        # Display preferences do not invalidate the immutable capture scope of an open document.
        if bool(old["floating"]) != body.floating:
            c.database.execute(
                "update browser_workshop_binding set floating=? where id=? and revision=?",
                (int(body.floating), old["id"], old["revision"]),
            )
        return public_binding({**old, "floating": body.floating})
    binding_id, revision = (old["id"], old["revision"] + 1) if old else (uuid4().hex, 1)
    if old:
        c.database.execute(
            "update browser_workshop_binding set is_head=0 where id=? and revision=?",
            (old["id"], old["revision"]),
        )
    row = c.database.execute_one(
        """insert into browser_workshop_binding(id,revision,origin,user_id,application_id,route_key,rule_json,
           environment_id,base_id,workshop_id,floating,is_head,enabled) values(?,?,?,?,?,?,?,?,?,?,?,1,1) returning *""",
        (
            binding_id,
            revision,
            origin,
            user,
            app,
            key,
            json.dumps(rule, sort_keys=True),
            body.environment_id,
            body.base_id,
            body.workshop_id,
            int(body.floating),
        ),
    )
    assert row is not None
    return public_binding(row)


def revoke_binding(
    c: Any, origin: str, user: str, app: str, binding_id: str, revision: int
) -> None:
    row = c.database.execute_one(
        """select * from browser_workshop_binding where id=? and origin=? and user_id=?
           and application_id=? and is_head=1""",
        (binding_id, origin, user, app),
    )
    if not row:
        raise deny("not_found", 404)
    if scope_key(row) not in {scope_key(s) for s in workshop_choices(c, user, app)}:
        raise deny("access_denied", 403)
    if row["revision"] != revision:
        raise deny("binding_conflict", 409)
    if row["enabled"]:
        c.database.execute(
            "update browser_workshop_binding set is_head=0 where id=? and revision=?",
            (binding_id, revision),
        )
        c.database.execute(
            """insert into browser_workshop_binding(id,revision,origin,user_id,application_id,route_key,rule_json,
               environment_id,base_id,workshop_id,floating,is_head,enabled)
               select id,revision+1,origin,user_id,application_id,route_key,rule_json,
               environment_id,base_id,workshop_id,floating,1,0 from browser_workshop_binding where id=? and revision=?""",
            (binding_id, revision),
        )
