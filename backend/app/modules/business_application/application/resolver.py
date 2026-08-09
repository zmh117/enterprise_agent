from __future__ import annotations

from typing import Any

from app.modules.business_application.domain.policies import (
    normalize_routing_key,
    validate_code,
    validate_environment,
    verify_snapshot,
)
from app.modules.business_application.domain.runtime import (
    RouteResolutionOutcome,
    RuntimeReadinessEvaluator,
    RuntimeReason,
    RuntimeRouteResolution,
)
from app.modules.business_application.infrastructure import BusinessApplicationRepository
from app.shared.exceptions import NonRetryableExecutionError

SCHEMA_VERSION = 1


class BusinessApplicationResolver:
    """Read immutable routing publications; it has no management write surface."""

    def __init__(
        self,
        repository: BusinessApplicationRepository,
        runtime_evaluator: RuntimeReadinessEvaluator | None = None,
    ) -> None:
        self.repository = repository
        self.runtime_evaluator = runtime_evaluator or RuntimeReadinessEvaluator(
            data_plane_enabled=False,
            runtime_environment="local",
        )

    def resolve_active(self, application_code: str, environment: str) -> dict[str, Any]:
        application = self.repository.get_by_code(validate_code(application_code))
        if str(application["status"]) != "enabled":
            raise self.configuration_error("Business Application is not enabled")
        deployment = self.repository.get_deployment(
            str(application["id"]), validate_environment(environment)
        )
        if deployment is None or not deployment["active"] or not deployment["publication_id"]:
            raise self.configuration_error("Business Application is not active")
        publication = self._verified(str(deployment["publication_id"]))
        readiness = self.runtime_evaluator.evaluate(
            snapshot=dict(publication["snapshot"]), deployment=deployment
        )
        return {
            "application": self._application_summary(application),
            "deployment": {**deployment, **readiness.to_dict()},
            "publication": {**publication, **readiness.to_dict()},
            **readiness.to_dict(),
        }

    def resolve_trigger(
        self,
        environment: str,
        trigger_type: str,
        connector_id: str,
        routing_key: str,
    ) -> dict[str, Any]:
        resolution = self.resolve_route(environment, trigger_type, connector_id, routing_key)
        if resolution.outcome == RouteResolutionOutcome.NOT_MATCHED:
            raise self.configuration_error(
                "No active Business Application route",
                error_code=RuntimeReason.ROUTE_NOT_MATCHED.value,
            )
        if resolution.outcome == RouteResolutionOutcome.BLOCKED:
            raise self.configuration_error(resolution.message, error_code=resolution.reason_code)
        return resolution.to_dict()

    def resolve_trigger_optional(
        self,
        environment: str,
        trigger_type: str,
        connector_id: str,
        routing_key: str,
    ) -> dict[str, Any] | None:
        resolution = self.resolve_route(environment, trigger_type, connector_id, routing_key)
        if resolution.outcome == RouteResolutionOutcome.NOT_MATCHED:
            return None
        if resolution.outcome == RouteResolutionOutcome.BLOCKED:
            raise self.configuration_error(resolution.message, error_code=resolution.reason_code)
        return resolution.to_dict()

    def resolve_route(
        self,
        environment: str,
        trigger_type: str,
        connector_id: str,
        routing_key: str,
    ) -> RuntimeRouteResolution:
        normalized_environment = validate_environment(environment)
        route = self.repository.find_route(
            environment=normalized_environment,
            trigger_type=trigger_type,
            connector_id=connector_id,
            normalized_routing_key=normalize_routing_key(routing_key),
        )
        if route is None:
            readiness = self.runtime_evaluator.empty(reason=RuntimeReason.ROUTE_NOT_MATCHED)
            return RuntimeRouteResolution(
                outcome=RouteResolutionOutcome.NOT_MATCHED,
                reason_code=RuntimeReason.ROUTE_NOT_MATCHED.value,
                message="No active Business Application route matched",
                readiness=readiness,
            )
        application = self.repository.get_by_id(str(route["application_id"]))
        deployment = self.repository.get_deployment(str(application["id"]), normalized_environment)
        if (
            str(application.get("status") or "") != "enabled"
            or deployment is None
            or not bool(deployment.get("active"))
        ):
            readiness = self.runtime_evaluator.blocked_integrity(
                deployment_environment=normalized_environment
            )
            return RuntimeRouteResolution(
                outcome=RouteResolutionOutcome.BLOCKED,
                reason_code=RuntimeReason.PUBLICATION_INTEGRITY_ERROR.value,
                message="Business Application is not active",
                readiness=readiness,
                application=self._application_summary(application),
                deployment=deployment,
                route=self._safe_route(route),
            )
        try:
            publication = self._verified(str(deployment["publication_id"]))
        except Exception:
            readiness = self.runtime_evaluator.blocked_integrity(
                deployment_environment=normalized_environment
            )
            return RuntimeRouteResolution(
                outcome=RouteResolutionOutcome.BLOCKED,
                reason_code=RuntimeReason.PUBLICATION_INTEGRITY_ERROR.value,
                message="Business Application publication integrity check failed",
                readiness=readiness,
                application=self._application_summary(application),
                deployment=deployment,
                route=self._safe_route(route),
            )
        readiness = self.runtime_evaluator.evaluate(
            snapshot=dict(publication["snapshot"]), deployment=deployment
        )
        return RuntimeRouteResolution(
            outcome=(
                RouteResolutionOutcome.BLOCKED
                if readiness.runtime_status.value == "blocked"
                else RouteResolutionOutcome.MATCHED
            ),
            reason_code=readiness.reason_code,
            message=readiness.message,
            readiness=readiness,
            application=self._application_summary(application),
            deployment=deployment,
            publication=publication,
            route=self._safe_route(route),
        )

    def _verified(self, publication_id: str) -> dict[str, Any]:
        publication = self.repository.get_publication(publication_id)
        if int(publication["schema_version"]) != SCHEMA_VERSION or not verify_snapshot(
            publication["snapshot"], str(publication["config_hash"])
        ):
            raise self.configuration_error(
                "Business Application publication integrity check failed"
            )
        return publication

    @staticmethod
    def configuration_error(
        message: str,
        *,
        error_code: str = "business_application_configuration_error",
    ) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            message,
            safe_message="业务应用运行配置不可用",
            error_code=error_code,
        )

    @staticmethod
    def _application_summary(application: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": application["id"],
            "code": application["code"],
            "project_code": application["project_code"],
        }

    @staticmethod
    def _safe_route(route: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": route["id"],
            "deployment_id": route["deployment_id"],
            "application_id": route["application_id"],
            "publication_id": route["publication_id"],
            "environment": route["environment"],
            "trigger_type": route["trigger_type"],
            "connector_id": route["connector_id"],
        }
