from __future__ import annotations

import re
from typing import Any

from services.mcp_common.platform_store import PlatformQuery


_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def collect_call_metrics(
    query: PlatformQuery,
    *,
    server_code: str,
    server_version: str,
) -> dict[str, Any]:
    totals = (
        query.execute_one(
            """
        select count(*) as call_count,
               coalesce(sum(duration_ms), 0) as duration_ms_total,
               coalesce(max(duration_ms), 0) as duration_ms_max,
               coalesce(sum(case when status = 'SUCCEEDED' then 1 else 0 end), 0)
                 as succeeded_count,
               coalesce(sum(case when status = 'FAILED' then 1 else 0 end), 0)
                 as failed_count,
               coalesce(sum(case when status = 'DENIED' then 1 else 0 end), 0)
                 as denied_count,
               coalesce(sum(case when correlation_id <> '' then 1 else 0 end), 0)
                 as correlation_count
          from mcp_tool_call_provenance
         where mcp_server_code = ?
        """,
            (server_code,),
        )
        or {}
    )
    call_count = max(0, int(totals.get("call_count") or 0))
    duration_total = max(0, int(totals.get("duration_ms_total") or 0))
    errors: dict[str, int] = {}
    for row in query.execute(
        """
        select a.error_code, count(*) as count
          from mcp_tool_call_attempt a
          join mcp_tool_call_provenance p on p.id = a.provenance_id
         where p.mcp_server_code = ? and a.error_code <> ''
         group by a.error_code
         order by a.error_code
        """,
        (server_code,),
    ):
        raw_code = str(row.get("error_code") or "")
        code = raw_code if _SAFE_ERROR_CODE.fullmatch(raw_code) else "other"
        errors[code] = errors.get(code, 0) + max(0, int(row.get("count") or 0))
    return {
        "status": "ok",
        "server_code": server_code,
        "server_version": server_version,
        "call_count": call_count,
        "succeeded_count": max(0, int(totals.get("succeeded_count") or 0)),
        "failed_count": max(0, int(totals.get("failed_count") or 0)),
        "denied_count": max(0, int(totals.get("denied_count") or 0)),
        "duration_ms_total": duration_total,
        "duration_ms_average": round(duration_total / call_count, 3) if call_count else 0,
        "duration_ms_max": max(0, int(totals.get("duration_ms_max") or 0)),
        "correlation_count": max(0, int(totals.get("correlation_count") or 0)),
        "errors": errors,
        "provider_query_executed": False,
    }


def safe_observability_failure(*, server_code: str, server_version: str) -> dict[str, Any]:
    return {
        "status": "degraded",
        "server_code": server_code,
        "server_version": server_version,
        "error_code": "platform_observability_unavailable",
        "provider_query_executed": False,
    }


def generation_health_status_code(snapshot: dict[str, Any]) -> int:
    generation_status = str(snapshot["generation_status"])
    exact_lkg_serving = (
        int(snapshot["active_deployment_count"]) > 0
        and int(snapshot["active_generation_count"]) == int(snapshot["active_deployment_count"])
        and int(snapshot["last_known_good_generation_count"])
        == int(snapshot["active_deployment_count"])
    )
    return 503 if generation_status == "degraded" and not exact_lkg_serving else 200


def collect_data_generation_health(
    query: PlatformQuery,
    generation_reconciler: Any | None,
) -> dict[str, int | str]:
    deployment = (
        query.execute_one(
            """
        select count(*) as deployment_count,
               coalesce(sum(case
                 when current.status = 'ACTIVE'
                  and current.resource_revision_id = d.resource_revision_id
                 then 1 else 0 end), 0) as active_count,
               coalesce(sum(case
                 when lkg.status = 'ACTIVE'
                  and lkg.resource_revision_id = d.resource_revision_id
                 then 1 else 0 end), 0) as lkg_count
          from mcp_resource_deployment d
          left join mcp_resource_generation current
            on current.id = d.current_generation_id
          left join mcp_resource_generation lkg
            on lkg.id = d.last_known_good_generation_id
         where d.status = 'ACTIVE'
        """
        )
        or {}
    )
    deployment_count = max(0, int(deployment.get("deployment_count") or 0))
    active_count = max(0, int(deployment.get("active_count") or 0))
    lkg_count = max(0, int(deployment.get("lkg_count") or 0))
    runtime = (
        generation_reconciler.status()
        if generation_reconciler is not None
        else {"status": "ready", "building": 0, "failed": 0}
    )
    building = max(0, int(runtime.get("building") or 0))
    failed = max(0, int(runtime.get("failed") or 0))
    if deployment_count == 0:
        status = "unconfigured"
    elif active_count != deployment_count or lkg_count != deployment_count or failed:
        status = "degraded"
    elif building:
        status = "building"
    else:
        status = "ready"
    return {
        "generation_status": status,
        "active_deployment_count": deployment_count,
        "active_generation_count": active_count,
        "last_known_good_generation_count": lkg_count,
        "building_generation_count": building,
        "failed_generation_count": failed,
    }
