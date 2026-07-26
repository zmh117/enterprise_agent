from __future__ import annotations

import json
from typing import Any

from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound


_BUSINESS_CAPABILITY_NAMES_ZH = {
    "get_er_context": "查看 ER 模型上下文",
    "get_business_flow_context": "查看业务流程上下文",
    "get_schema_directory": "查看数据库结构目录",
    "diagnose_loki_labels": "诊断日志标签",
    "diagnose_loki_label_values": "诊断日志标签值",
    "diagnose_loki_probe": "探测日志数据",
    "query_loki": "只读查询日志",
    "query_database": "只读查询数据库",
    "query_redis_get": "只读获取 Redis 键值",
    "query_redis_scan": "只读扫描 Redis 键",
}


class AuthorizationCenterRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_roles(
        self,
        *,
        search: str = "",
        status: str = "",
        origin: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if search.strip():
            pattern = f"%{search.strip().lower()}%"
            clauses.append(
                "(lower(r.code) like ? or lower(r.name) like ? or lower(r.description) like ?)"
            )
            params.extend((pattern, pattern, pattern))
        if status:
            clauses.append("r.status = ?")
            params.append(status)
        if origin:
            clauses.append("r.origin = ?")
            params.append(origin)
        where = f"where {' and '.join(clauses)}" if clauses else ""
        count = self.database.execute_one(
            f"select count(*) as count from rbac_role r {where}",
            tuple(params),
        )
        rows = self.database.execute(
            f"""
            select r.*,
                   (select count(*) from rbac_user_role ur
                     where ur.role_id = r.id and ur.status = 'enabled'
                       and (ur.expires_at is null or ur.expires_at > ?)) as member_count,
                   (select count(*) from rbac_role_admin_capability ac
                     where ac.role_id = r.id and ac.status = 'enabled') as admin_capability_count,
                   (select count(*) from rbac_role_application_access aa
                     where aa.role_id = r.id and aa.status = 'enabled') as application_count
            from rbac_role r
            {where}
            order by r.protected desc, lower(r.name), r.code
            limit ? offset ?
            """,
            (now_iso(), *params, limit, offset),
        )
        return ([self._role(row) for row in rows], int((count or {}).get("count") or 0))

    def get_role(self, role_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select r.*,
                   (select count(*) from rbac_user_role ur
                     where ur.role_id = r.id and ur.status = 'enabled'
                       and (ur.expires_at is null or ur.expires_at > ?)) as member_count
            from rbac_role r where r.id = ?
            """,
            (now_iso(), role_id),
        )
        if row is None:
            raise NotFound("Role not found", safe_message="未找到角色")
        return self._role(row)

    def get_role_by_code(self, code: str) -> dict[str, Any] | None:
        row = self.database.execute_one("select * from rbac_role where code = ?", (code,))
        return self._role(row) if row else None

    def create_role(
        self,
        *,
        code: str,
        name: str,
        description: str,
        purpose_tags: list[str],
    ) -> dict[str, Any]:
        role_id = new_id("role")
        timestamp = now_iso()
        try:
            self.database.execute(
                """
                insert into rbac_role
                  (id, code, name, description, status, revision, origin, protected,
                   purpose_tags_json, metadata_revision, admin_revision,
                   business_revision, membership_revision, created_at, updated_at)
                values (?, ?, ?, ?, 'enabled', 1, 'custom', 0, ?, 1, 1, 1, 1, ?, ?)
                """,
                (
                    role_id,
                    code,
                    name,
                    description,
                    _json_text(purpose_tags),
                    timestamp,
                    timestamp,
                ),
            )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise NonRetryableExecutionError(
                    "Role code already exists",
                    safe_message="角色编码已存在",
                    error_code="role_code_conflict",
                    field_errors=[{"field": "code", "message": "角色编码已存在"}],
                ) from exc
            raise
        return self.get_role(role_id)

    def update_metadata(
        self,
        role_id: str,
        *,
        expected_revision: int,
        name: str,
        description: str,
        purpose_tags: list[str],
        status: str,
    ) -> dict[str, Any]:
        current = self.get_role(role_id)
        if current["protected"] and status != current["status"]:
            raise NonRetryableExecutionError(
                "Protected role cannot be disabled",
                safe_message="受保护系统角色不能停用",
                error_code="protected_role",
            )
        rows = self.database.execute(
            """
            update rbac_role
               set name = ?, description = ?, purpose_tags_json = ?, status = ?,
                   metadata_revision = metadata_revision + 1,
                   revision = revision + 1, updated_at = ?
             where id = ? and metadata_revision = ?
            returning id
            """,
            (
                name,
                description,
                _json_text(purpose_tags),
                status,
                now_iso(),
                role_id,
                expected_revision,
            ),
        )
        self._require_revision(rows, "角色基本信息")
        return self.get_role(role_id)

    def list_admin_bindings(self, role_id: str) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select id, capability_code, resource_type, resource_code, status,
                   created_at, updated_at
              from rbac_role_admin_capability
             where role_id = ? and status = 'enabled'
             order by capability_code, resource_type, resource_code
            """,
            (role_id,),
        )

    def replace_admin_bindings(
        self,
        role_id: str,
        *,
        expected_revision: int,
        bindings: list[dict[str, str]],
    ) -> dict[str, Any]:
        timestamp = now_iso()
        with self.database.transaction():
            rows = self.database.execute(
                """
                update rbac_role
                   set admin_revision = admin_revision + 1, updated_at = ?
                 where id = ? and admin_revision = ? and protected = 0
                returning id
                """,
                (timestamp, role_id, expected_revision),
            )
            if not rows:
                role = self.get_role(role_id)
                if role["protected"]:
                    raise NonRetryableExecutionError(
                        "Protected role capabilities are implicit",
                        safe_message="受保护系统角色的管理能力由系统自动维护",
                        error_code="protected_role",
                    )
                self._require_revision(rows, "管理能力授权区")
            self.database.execute(
                "delete from rbac_role_admin_capability where role_id = ?",
                (role_id,),
            )
            for binding in bindings:
                self.database.execute(
                    """
                    insert into rbac_role_admin_capability
                      (id, role_id, capability_code, resource_type, resource_code,
                       status, created_at, updated_at)
                    values (?, ?, ?, ?, ?, 'enabled', ?, ?)
                    """,
                    (
                        new_id("role_admin_capability"),
                        role_id,
                        binding["capability_code"],
                        binding["resource_type"],
                        binding["resource_code"],
                        timestamp,
                        timestamp,
                    ),
                )
        return {
            "revision": self.get_role(role_id)["admin_revision"],
            "bindings": self.list_admin_bindings(role_id),
        }

    def list_business_access(self, role_id: str) -> list[dict[str, Any]]:
        accesses = self.database.execute(
            """
            select aa.*, a.code as application_code, a.name as application_name,
                   a.status as application_status
              from rbac_role_application_access aa
              join business_application a on a.id = aa.application_id
             where aa.role_id = ?
             order by a.code
            """,
            (role_id,),
        )
        for access in accesses:
            access["capability_codes"] = [
                str(row["capability_code"])
                for row in self.database.execute(
                    """
                    select capability_code
                      from rbac_role_application_capability
                     where application_access_id = ?
                     order by capability_code
                    """,
                    (access["id"],),
                )
            ]
            access["scopes"] = self.database.execute(
                """
                select s.id, s.scope_key, s.environment_id, e.code as environment_code,
                       s.base_id, b.code as base_code, s.workshop_id,
                       w.code as workshop_code
                  from rbac_role_application_scope s
                  join platform_environment e on e.id = s.environment_id
                  left join platform_base b on b.id = s.base_id
                  left join platform_workshop w on w.id = s.workshop_id
                 where s.application_access_id = ?
                 order by s.scope_key
                """,
                (access["id"],),
            )
        return accesses

    def replace_business_access(
        self,
        role_id: str,
        *,
        expected_revision: int,
        applications: list[dict[str, Any]],
    ) -> dict[str, Any]:
        timestamp = now_iso()
        with self.database.transaction():
            rows = self.database.execute(
                """
                update rbac_role
                   set business_revision = business_revision + 1, updated_at = ?
                 where id = ? and business_revision = ? and protected = 0
                returning id
                """,
                (timestamp, role_id, expected_revision),
            )
            if not rows:
                role = self.get_role(role_id)
                if role["protected"]:
                    raise NonRetryableExecutionError(
                        "Protected role business access cannot be edited",
                        safe_message="受保护系统角色不能配置业务应用权限",
                        error_code="protected_role",
                    )
                self._require_revision(rows, "业务应用授权区")
            current_ids = [
                str(row["id"])
                for row in self.database.execute(
                    "select id from rbac_role_application_access where role_id = ?",
                    (role_id,),
                )
            ]
            for access_id in current_ids:
                self.database.execute(
                    "delete from rbac_role_application_scope where application_access_id = ?",
                    (access_id,),
                )
                self.database.execute(
                    "delete from rbac_role_application_capability where application_access_id = ?",
                    (access_id,),
                )
            self.database.execute(
                "delete from rbac_role_application_access where role_id = ?",
                (role_id,),
            )
            for application in applications:
                access_id = new_id("role_application_access")
                self.database.execute(
                    """
                    insert into rbac_role_application_access
                      (id, role_id, application_id, status, revision, created_at, updated_at)
                    values (?, ?, ?, 'enabled', 1, ?, ?)
                    """,
                    (access_id, role_id, application["application_id"], timestamp, timestamp),
                )
                for code in application["capability_codes"]:
                    self.database.execute(
                        """
                        insert into rbac_role_application_capability
                          (id, application_access_id, capability_code, created_at)
                        values (?, ?, ?, ?)
                        """,
                        (new_id("role_app_capability"), access_id, code, timestamp),
                    )
                for scope in application["scopes"]:
                    self.database.execute(
                        """
                        insert into rbac_role_application_scope
                          (id, application_access_id, environment_id, base_id,
                           workshop_id, scope_key, created_at)
                        values (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_id("role_app_scope"),
                            access_id,
                            scope["environment_id"],
                            scope.get("base_id"),
                            scope.get("workshop_id"),
                            scope["scope_key"],
                            timestamp,
                        ),
                    )
        return {
            "revision": self.get_role(role_id)["business_revision"],
            "applications": self.list_business_access(role_id),
        }

    def active_role_rows_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select r.*, ur.id as membership_id, ur.expires_at,
                   ur.revision as membership_row_revision
              from rbac_user_role ur
              join rbac_role r on r.id = ur.role_id
              join app_user u on u.id = ur.user_id
             where ur.user_id = ? and ur.status = 'enabled'
               and r.status = 'enabled' and u.status = 'enabled'
               and (ur.expires_at is null or ur.expires_at > ?)
             order by r.code
            """,
            (user_id, now_iso()),
        )

    def admin_bindings_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select ac.*, r.code as role_code, r.id as role_id
              from rbac_role_admin_capability ac
              join rbac_role r on r.id = ac.role_id
              join rbac_user_role ur on ur.role_id = r.id
              join app_user u on u.id = ur.user_id
             where ur.user_id = ? and ac.status = 'enabled'
               and ur.status = 'enabled' and r.status = 'enabled'
               and u.status = 'enabled'
               and (ur.expires_at is null or ur.expires_at > ?)
             order by r.code, ac.capability_code
            """,
            (user_id, now_iso()),
        )

    def business_access_for_user(
        self,
        *,
        user_id: str,
        application_id: str,
    ) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select aa.*, r.code as role_code, r.id as role_id
              from rbac_role_application_access aa
              join rbac_role r on r.id = aa.role_id
              join rbac_user_role ur on ur.role_id = r.id
              join app_user u on u.id = ur.user_id
             where ur.user_id = ? and aa.application_id = ?
               and aa.status = 'enabled' and ur.status = 'enabled'
               and r.status = 'enabled' and u.status = 'enabled'
               and (ur.expires_at is null or ur.expires_at > ?)
             order by r.code
            """,
            (user_id, application_id, now_iso()),
        )
        for row in rows:
            row["capability_codes"] = [
                str(item["capability_code"])
                for item in self.database.execute(
                    """
                    select capability_code from rbac_role_application_capability
                     where application_access_id = ? order by capability_code
                    """,
                    (row["id"],),
                )
            ]
            row["scopes"] = self.database.execute(
                """
                select s.scope_key, e.code as environment_code,
                       b.code as base_code, w.code as workshop_code
                  from rbac_role_application_scope s
                  join platform_environment e on e.id = s.environment_id
                  left join platform_base b on b.id = s.base_id
                  left join platform_workshop w on w.id = s.workshop_id
                 where s.application_access_id = ?
                 order by s.scope_key
                """,
                (row["id"],),
            )
        return rows

    def application_catalog(self) -> list[dict[str, Any]]:
        applications = self.database.execute(
            """
            select id, code, name, description, project_code, status
              from business_application
             where status != 'archived'
             order by name, code
            """
        )
        for application in applications:
            revision = self.database.execute_one(
                """
                select id, agent_publication_id from business_application_revision
                 where application_id = ?
                 order by revision desc limit 1
                """,
                (application["id"],),
            )
            application["capabilities"] = (
                self.database.execute(
                    """
                    select c.capability_code, c.version_constraint
                      from business_application_revision_capability c
                      join tool_definition t
                        on t.name = c.capability_code
                       and t.enabled = 1 and t.read_only = 1
                      join agent_tool_binding atb
                        on atb.publication_id = ?
                       and atb.tool_name = c.capability_code
                     where c.revision_id = ? and c.enabled = 1
                     order by c.capability_code
                    """,
                    (revision["agent_publication_id"], revision["id"]),
                )
                if revision
                else []
            )
            for capability in application["capabilities"]:
                capability["display_name_zh"] = _BUSINESS_CAPABILITY_NAMES_ZH.get(
                    str(capability["capability_code"]),
                    "只读业务能力",
                )
        return applications

    def application_capability_is_effective(
        self, application_id: str, capability_code: str
    ) -> bool:
        deployment = self.database.execute_one(
            """
            select p.snapshot_json
              from business_application_deployment d
              join business_application_publication p on p.id = d.publication_id
             where d.application_id = ? and d.environment = 'local'
               and d.active = 1
             order by d.updated_at desc limit 1
            """,
            (application_id,),
        )
        if deployment is None:
            return False
        try:
            snapshot = json.loads(str(deployment.get("snapshot_json") or "{}"))
        except json.JSONDecodeError:
            return False
        capabilities = {
            str(item.get("capability_code") or "")
            for item in snapshot.get("capabilities") or []
            if isinstance(item, dict) and bool(item.get("enabled", True))
        }
        agent = snapshot.get("agent") if isinstance(snapshot, dict) else None
        publication_id = str(agent.get("id") or "") if isinstance(agent, dict) else ""
        if capability_code not in capabilities or not publication_id:
            return False
        row = self.database.execute_one(
            """
            select t.id
              from tool_definition t
              join agent_tool_binding atb
                on atb.tool_name = t.name and atb.publication_id = ?
             where t.name = ? and t.enabled = 1 and t.read_only = 1
            """,
            (publication_id, capability_code),
        )
        return row is not None

    def active_application_agent_code(self, application_id: str) -> str:
        row = self.database.execute_one(
            """
            select p.snapshot_json
              from business_application_deployment d
              join business_application_publication p on p.id = d.publication_id
             where d.application_id = ? and d.environment = 'local' and d.active = 1
             order by d.updated_at desc limit 1
            """,
            (application_id,),
        )
        if row is None:
            return ""
        try:
            snapshot = json.loads(str(row.get("snapshot_json") or "{}"))
        except json.JSONDecodeError:
            return ""
        agent = snapshot.get("agent") if isinstance(snapshot, dict) else None
        return str(agent.get("code") or "") if isinstance(agent, dict) else ""

    def topology_catalog(self) -> list[dict[str, Any]]:
        environments = self.database.execute(
            """
            select id, code, display_name, status
              from platform_environment where status = 'enabled'
             order by display_name, code
            """
        )
        for environment in environments:
            bases = self.database.execute(
                """
                select id, code, display_name, engine, status
                  from platform_base
                 where environment_id = ? and status = 'enabled'
                 order by display_name, code
                """,
                (environment["id"],),
            )
            for base in bases:
                base["workshops"] = self.database.execute(
                    """
                    select id, code, display_name, status
                      from platform_workshop
                     where base_id = ? and status = 'enabled'
                     order by display_name, code
                    """,
                    (base["id"],),
                )
            environment["bases"] = bases
        return environments

    def scope_node(
        self,
        *,
        environment_id: str,
        base_id: str | None,
        workshop_id: str | None,
    ) -> dict[str, Any]:
        environment = self.database.execute_one(
            "select id, code, status from platform_environment where id = ?",
            (environment_id,),
        )
        if environment is None or environment["status"] != "enabled":
            raise NonRetryableExecutionError(
                "Environment is not assignable",
                safe_message="所选环境不可授权",
                error_code="scope_invalid",
            )
        base = None
        if base_id:
            base = self.database.execute_one(
                """
                select id, code, environment_id, status
                  from platform_base where id = ?
                """,
                (base_id,),
            )
            if (
                base is None
                or base["status"] != "enabled"
                or str(base["environment_id"]) != environment_id
            ):
                raise NonRetryableExecutionError(
                    "Base does not belong to environment",
                    safe_message="所选基地不属于该环境",
                    error_code="scope_invalid",
                )
        workshop = None
        if workshop_id:
            workshop = self.database.execute_one(
                """
                select id, code, base_id, status
                  from platform_workshop where id = ?
                """,
                (workshop_id,),
            )
            if (
                workshop is None
                or workshop["status"] != "enabled"
                or base is None
                or str(workshop["base_id"]) != str(base["id"])
            ):
                raise NonRetryableExecutionError(
                    "Workshop does not belong to base",
                    safe_message="所选车间不属于该基地",
                    error_code="scope_invalid",
                )
        return {
            "environment_id": environment_id,
            "base_id": base_id,
            "workshop_id": workshop_id,
            "scope_key": "/".join(
                value
                for value in (
                    str(environment["code"]),
                    str((base or {}).get("code") or ""),
                    str((workshop or {}).get("code") or ""),
                )
                if value
            ),
        }

    def expand_current_scopes(
        self,
        *,
        level: str,
        environment_id: str = "",
        base_id: str = "",
    ) -> list[dict[str, Any]]:
        if level == "environments":
            rows = self.database.execute(
                "select id from platform_environment where status = 'enabled' order by id"
            )
            return [
                self.scope_node(
                    environment_id=str(row["id"]),
                    base_id=None,
                    workshop_id=None,
                )
                for row in rows
            ]
        if level == "bases":
            if not environment_id:
                raise NonRetryableExecutionError(
                    "Environment is required for current bases",
                    safe_message="选择当前全部基地时必须指定环境",
                    error_code="scope_invalid",
                )
            rows = self.database.execute(
                """
                select id from platform_base
                 where environment_id = ? and status = 'enabled'
                 order by id
                """,
                (environment_id,),
            )
            return [
                self.scope_node(
                    environment_id=environment_id,
                    base_id=str(row["id"]),
                    workshop_id=None,
                )
                for row in rows
            ]
        if level == "workshops":
            if not environment_id or not base_id:
                raise NonRetryableExecutionError(
                    "Environment and base are required for current workshops",
                    safe_message="选择当前全部车间时必须指定环境和基地",
                    error_code="scope_invalid",
                )
            rows = self.database.execute(
                """
                select id from platform_workshop
                 where base_id = ? and status = 'enabled'
                 order by id
                """,
                (base_id,),
            )
            return [
                self.scope_node(
                    environment_id=environment_id,
                    base_id=base_id,
                    workshop_id=str(row["id"]),
                )
                for row in rows
            ]
        raise NonRetryableExecutionError(
            "Unsupported current scope level",
            safe_message="“当前全部”的范围层级无效",
            error_code="scope_invalid",
        )

    def bump_membership_revision(self, role_id: str, expected_revision: int) -> int:
        rows = self.database.execute(
            """
            update rbac_role
               set membership_revision = membership_revision + 1, updated_at = ?
             where id = ? and membership_revision = ?
            returning membership_revision
            """,
            (now_iso(), role_id, expected_revision),
        )
        self._require_revision(rows, "角色成员")
        return int(rows[0]["membership_revision"])

    def lock_platform_admin_memberships(self) -> None:
        suffix = " for update" if self.database.engine == "postgres" else ""
        self.database.execute(
            f"""
            select ur.id
              from rbac_user_role ur
              join rbac_role r on r.id = ur.role_id
             where r.code = 'platform-admin'
            {suffix}
            """
        )

    @staticmethod
    def _require_revision(rows: list[dict[str, Any]], section_name: str) -> None:
        if not rows:
            raise NonRetryableExecutionError(
                f"{section_name} revision conflict",
                safe_message=f"{section_name}已被其他管理员修改，请刷新后重试",
                error_code="revision_conflict",
            )

    @staticmethod
    def _role(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["protected"] = bool(result.get("protected"))
        result["purpose_tags"] = _json_list(result.pop("purpose_tags_json", "[]"))
        for field in (
            "revision",
            "metadata_revision",
            "admin_revision",
            "business_revision",
            "membership_revision",
            "member_count",
            "admin_capability_count",
            "application_count",
        ):
            if field in result:
                result[field] = int(result.get(field) or 0)
        return result


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
