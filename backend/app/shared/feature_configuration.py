from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Mapping


FEATURE_COMPATIBILITY_REMOVAL_VERSION = "0.3.0"


class FeatureClassification(StrEnum):
    BOOTSTRAP_ONLY = "bootstrap-only"
    DEPLOYMENT_SAFETY_GATE = "deployment-safety-gate"
    GOVERNED_RUNTIME_POLICY = "governed-runtime-policy"
    TEST_ONLY = "test-only"
    DERIVED = "derived"


@dataclass(frozen=True)
class FeatureDiagnostic:
    code: str
    message: str
    keys: tuple[str, ...] = ()
    severity: str = "warning"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "keys": list(self.keys),
            "severity": self.severity,
        }


@dataclass(frozen=True)
class EffectiveFeatureValue:
    key: str
    effective_value: bool
    source: str
    classification: str
    deprecated_inputs: tuple[str, ...] = ()
    restart_required: bool = False
    requested_value: bool | None = None
    blocked_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "effective_value": self.effective_value,
            "source": self.source,
            "classification": self.classification,
            "deprecated_inputs": list(self.deprecated_inputs),
            "restart_required": self.restart_required,
            "requested_value": self.requested_value,
            "blocked_by": self.blocked_by,
        }


@dataclass(frozen=True)
class EffectiveFeatureConfiguration:
    values: tuple[EffectiveFeatureValue, ...]
    diagnostics: tuple[FeatureDiagnostic, ...] = ()

    def value(self, key: str) -> bool:
        item = self.item(key)
        return item.effective_value if item is not None else False

    def item(self, key: str) -> EffectiveFeatureValue | None:
        return next((item for item in self.values if item.key == key), None)

    @property
    def web_admin_enabled(self) -> bool:
        return self.value("FEATURE_WEB_ADMIN")

    @property
    def published_agent_runtime_enabled(self) -> bool:
        return self.value("FEATURE_PUBLISHED_AGENT_RUNTIME")

    @property
    def real_claude_enabled(self) -> bool:
        return self.value("FEATURE_REAL_CLAUDE")

    @property
    def real_internal_tools_enabled(self) -> bool:
        return self.value("FEATURE_REAL_INTERNAL_TOOLS")

    @property
    def unified_identity_enabled(self) -> bool:
        return self.value("UNIFIED_IDENTITY")

    @property
    def business_application_control_plane_enabled(self) -> bool:
        return self.value("BUSINESS_APPLICATION_CONTROL_PLANE")

    @property
    def test_identity_headers_enabled(self) -> bool:
        return self.value("TEST_IDENTITY_HEADERS")

    @property
    def permission_shadow_mode(self) -> bool:
        return self.value("PERMISSION_SHADOW_MODE")

    @property
    def webhook_ingress_compatibility_enabled(self) -> bool:
        return self.value("WEBHOOK_INGRESS_COMPATIBILITY")

    @property
    def continuous_conversation_compatibility_enabled(self) -> bool:
        return self.value("CONTINUOUS_CONVERSATION_COMPATIBILITY")

    @property
    def message_attachments_compatibility_enabled(self) -> bool:
        return self.value("MESSAGE_ATTACHMENTS_COMPATIBILITY")

    def to_snapshot(
        self,
        *,
        revision: int = 0,
        config_hash: str = "",
        source: str = "environment",
    ) -> dict[str, Any]:
        return {
            "source": source,
            "revision": revision,
            "config_hash": config_hash,
            "compatibility_removal_version": FEATURE_COMPATIBILITY_REMOVAL_VERSION,
            "values": [item.to_dict() for item in self.values],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


class FeatureConfigurationError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


TOP_LEVEL_FEATURE_KEYS = (
    "FEATURE_WEB_ADMIN",
    "FEATURE_PUBLISHED_AGENT_RUNTIME",
    "FEATURE_REAL_CLAUDE",
    "FEATURE_REAL_INTERNAL_TOOLS",
)

LEGACY_FEATURE_TARGETS: dict[str, str] = {
    "FEATURE_UNIFIED_IDENTITY": "FEATURE_WEB_ADMIN",
    "FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE": "FEATURE_WEB_ADMIN",
    "FEATURE_WEBHOOK_TRIGGERS": "published Connector/Trigger configuration",
    "FEATURE_CONTINUOUS_CONVERSATION": "Business Application session_policy",
    "FEATURE_MESSAGE_ATTACHMENTS": "Business Application session_policy",
    "FEATURE_TEST_IDENTITY_HEADERS": "test-only application configuration",
    "FEATURE_PERMISSION_SHADOW_MODE": "PERMISSION_SHADOW_MODE runtime policy",
}


def default_feature_configuration() -> EffectiveFeatureConfiguration:
    return feature_configuration_from_values()


def feature_configuration_from_values(
    *,
    web_admin: bool = False,
    published_agent_runtime: bool = False,
    real_claude: bool = False,
    real_internal_tools: bool = False,
    unified_identity: bool | None = None,
    business_application_control_plane: bool | None = None,
    test_identity_headers: bool = False,
    permission_shadow_mode: bool = True,
    webhook_ingress: bool = True,
    continuous_conversation: bool = False,
    message_attachments: bool = False,
    source: str = "safe-default",
    diagnostics: tuple[FeatureDiagnostic, ...] = (),
) -> EffectiveFeatureConfiguration:
    unified = web_admin if unified_identity is None else unified_identity
    control_plane = (
        web_admin
        if business_application_control_plane is None
        else business_application_control_plane
    )
    return EffectiveFeatureConfiguration(
        values=(
            _value(
                "FEATURE_WEB_ADMIN",
                web_admin,
                source,
                FeatureClassification.DEPLOYMENT_SAFETY_GATE,
                restart=True,
            ),
            _value(
                "FEATURE_PUBLISHED_AGENT_RUNTIME",
                published_agent_runtime,
                source,
                FeatureClassification.DEPLOYMENT_SAFETY_GATE,
                restart=True,
            ),
            _value(
                "FEATURE_REAL_CLAUDE",
                real_claude,
                source,
                FeatureClassification.DEPLOYMENT_SAFETY_GATE,
                restart=True,
            ),
            _value(
                "FEATURE_REAL_INTERNAL_TOOLS",
                real_internal_tools,
                source,
                FeatureClassification.DEPLOYMENT_SAFETY_GATE,
                restart=True,
            ),
            _value(
                "UNIFIED_IDENTITY",
                unified,
                "derived:FEATURE_WEB_ADMIN" if unified_identity is None else source,
                FeatureClassification.DERIVED,
            ),
            _value(
                "BUSINESS_APPLICATION_CONTROL_PLANE",
                control_plane,
                "derived:FEATURE_WEB_ADMIN"
                if business_application_control_plane is None
                else source,
                FeatureClassification.DERIVED,
            ),
            _value(
                "TEST_IDENTITY_HEADERS",
                test_identity_headers,
                source,
                FeatureClassification.TEST_ONLY,
                deprecated=("FEATURE_TEST_IDENTITY_HEADERS",)
                if source.startswith("legacy:")
                else (),
                restart=True,
            ),
            _value(
                "PERMISSION_SHADOW_MODE",
                permission_shadow_mode,
                source,
                FeatureClassification.GOVERNED_RUNTIME_POLICY,
                deprecated=("FEATURE_PERMISSION_SHADOW_MODE",)
                if source.startswith("legacy:")
                else (),
            ),
            _value(
                "WEBHOOK_INGRESS_COMPATIBILITY",
                webhook_ingress,
                source,
                FeatureClassification.GOVERNED_RUNTIME_POLICY,
                deprecated=("FEATURE_WEBHOOK_TRIGGERS",)
                if source.startswith("legacy:")
                else (),
            ),
            _value(
                "CONTINUOUS_CONVERSATION_COMPATIBILITY",
                continuous_conversation,
                source,
                FeatureClassification.GOVERNED_RUNTIME_POLICY,
                deprecated=("FEATURE_CONTINUOUS_CONVERSATION",)
                if source.startswith("legacy:")
                else (),
            ),
            _value(
                "MESSAGE_ATTACHMENTS_COMPATIBILITY",
                message_attachments,
                source,
                FeatureClassification.GOVERNED_RUNTIME_POLICY,
                deprecated=("FEATURE_MESSAGE_ATTACHMENTS",)
                if source.startswith("legacy:")
                else (),
            ),
        ),
        diagnostics=diagnostics,
    )


def resolve_feature_configuration(
    environment: str,
    environ: Mapping[str, str],
) -> EffectiveFeatureConfiguration:
    diagnostics: list[FeatureDiagnostic] = []
    canonical = {
        key: _optional_bool(environ, key)
        for key in TOP_LEVEL_FEATURE_KEYS
    }
    web_admin = canonical["FEATURE_WEB_ADMIN"]
    legacy_identity = _optional_bool(environ, "FEATURE_UNIFIED_IDENTITY")
    legacy_control_plane = _optional_bool(
        environ, "FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE"
    )
    if web_admin is not None:
        conflicts = tuple(
            key
            for key, value in (
                ("FEATURE_UNIFIED_IDENTITY", legacy_identity),
                (
                    "FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE",
                    legacy_control_plane,
                ),
            )
            if value is not None and value != web_admin
        )
        if conflicts:
            raise FeatureConfigurationError(
                "feature_configuration_conflict: FEATURE_WEB_ADMIN conflicts with "
                + ", ".join(conflicts)
            )
        unified_identity = web_admin
        business_control_plane = web_admin
    else:
        web_admin = False
        unified_identity = legacy_identity if legacy_identity is not None else False
        business_control_plane = (
            legacy_control_plane if legacy_control_plane is not None else False
        )

    for legacy_key, target in LEGACY_FEATURE_TARGETS.items():
        if legacy_key in environ:
            diagnostics.append(
                FeatureDiagnostic(
                    code="deprecated_feature_configuration",
                    message=(
                        f"{legacy_key} is deprecated; migrate to {target} before "
                        f"{FEATURE_COMPATIBILITY_REMOVAL_VERSION}"
                    ),
                    keys=(legacy_key,),
                )
            )

    test_headers = _optional_bool(environ, "FEATURE_TEST_IDENTITY_HEADERS") or False
    normalized_environment = environment.strip().lower()
    if test_headers and normalized_environment not in {"local", "test", "testing"}:
        raise FeatureConfigurationError(
            "test_only_feature_in_production: FEATURE_TEST_IDENTITY_HEADERS "
            f"cannot be enabled in {normalized_environment or 'production'}"
        )

    permission_shadow = _optional_bool(environ, "FEATURE_PERMISSION_SHADOW_MODE")
    webhook_enabled = _optional_bool(environ, "FEATURE_WEBHOOK_TRIGGERS")
    conversation_enabled = _optional_bool(
        environ, "FEATURE_CONTINUOUS_CONVERSATION"
    )
    attachments_enabled = _optional_bool(environ, "FEATURE_MESSAGE_ATTACHMENTS")

    configuration = feature_configuration_from_values(
        web_admin=bool(web_admin),
        published_agent_runtime=bool(
            canonical["FEATURE_PUBLISHED_AGENT_RUNTIME"] or False
        ),
        real_claude=bool(canonical["FEATURE_REAL_CLAUDE"] or False),
        real_internal_tools=bool(
            canonical["FEATURE_REAL_INTERNAL_TOOLS"] or False
        ),
        unified_identity=unified_identity,
        business_application_control_plane=business_control_plane,
        test_identity_headers=test_headers,
        permission_shadow_mode=True
        if permission_shadow is None
        else permission_shadow,
        webhook_ingress=True if webhook_enabled is None else webhook_enabled,
        continuous_conversation=False
        if conversation_enabled is None
        else conversation_enabled,
        message_attachments=False
        if attachments_enabled is None
        else attachments_enabled,
        source="environment",
        diagnostics=tuple(diagnostics),
    )
    return _mark_configuration_sources(configuration, environ)


def apply_runtime_feature_policies(
    configuration: EffectiveFeatureConfiguration,
    runtime_values: Mapping[str, Any],
) -> EffectiveFeatureConfiguration:
    values = list(configuration.values)
    diagnostics = list(configuration.diagnostics)

    for gate in (
        "FEATURE_PUBLISHED_AGENT_RUNTIME",
        "FEATURE_REAL_CLAUDE",
        "FEATURE_REAL_INTERNAL_TOOLS",
    ):
        requested = _coerce_optional_bool(runtime_values.get(gate))
        if requested is None:
            continue
        item = configuration.item(gate)
        if item is None:
            continue
        blocked = bool(requested and not item.effective_value)
        values = [
            replace(
                current,
                requested_value=requested,
                blocked_by=gate if blocked else "",
            )
            if current.key == gate
            else current
            for current in values
        ]
        diagnostics.append(
            FeatureDiagnostic(
                code=(
                    "deployment_gate_blocked_runtime_value"
                    if blocked
                    else "deprecated_runtime_feature_gate"
                ),
                message=(
                    f"{gate} runtime value is ignored; deployment environment "
                    "is the only authority for this safety gate"
                ),
                keys=(gate,),
                severity="error" if blocked else "warning",
            )
        )

    shadow = _coerce_optional_bool(
        runtime_values.get("PERMISSION_SHADOW_MODE")
    )
    if shadow is None:
        shadow = _coerce_optional_bool(
            runtime_values.get("FEATURE_PERMISSION_SHADOW_MODE")
        )
    if shadow is not None:
        values = [
            replace(
                current,
                effective_value=shadow,
                source="db:runtime-policy",
                deprecated_inputs=(
                    ("FEATURE_PERMISSION_SHADOW_MODE",)
                    if "FEATURE_PERMISSION_SHADOW_MODE" in runtime_values
                    else ()
                ),
            )
            if current.key == "PERMISSION_SHADOW_MODE"
            else current
            for current in values
        ]

    return EffectiveFeatureConfiguration(
        values=tuple(values),
        diagnostics=tuple(diagnostics),
    )


def feature_migration_report(
    environment: str, environ: Mapping[str, str]
) -> dict[str, Any]:
    configuration = resolve_feature_configuration(environment, environ)
    legacy = []
    policy_draft: dict[str, Any] = {}
    for key, target in LEGACY_FEATURE_TARGETS.items():
        if key not in environ:
            continue
        value = _optional_bool(environ, key)
        legacy.append(
            {
                "key": key,
                "configured": True,
                "value": value,
                "target": target,
                "removal_version": FEATURE_COMPATIBILITY_REMOVAL_VERSION,
            }
        )
        if key == "FEATURE_CONTINUOUS_CONVERSATION":
            policy_draft["continuous_conversation_enabled"] = bool(value)
        elif key == "FEATURE_MESSAGE_ATTACHMENTS":
            policy_draft["attachments_enabled"] = bool(value)
        elif key == "FEATURE_PERMISSION_SHADOW_MODE":
            policy_draft["permission_shadow_mode"] = bool(value)
        elif key == "FEATURE_WEBHOOK_TRIGGERS":
            policy_draft["webhook_ingress_enabled"] = bool(value)
    return {
        "write_performed": False,
        "publication_performed": False,
        "legacy": legacy,
        "policy_draft": policy_draft,
        "effective": configuration.to_snapshot(),
    }


def _mark_configuration_sources(
    configuration: EffectiveFeatureConfiguration,
    environ: Mapping[str, str],
) -> EffectiveFeatureConfiguration:
    targets = {
        "UNIFIED_IDENTITY": "FEATURE_UNIFIED_IDENTITY",
        "BUSINESS_APPLICATION_CONTROL_PLANE": (
            "FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE"
        ),
        "TEST_IDENTITY_HEADERS": "FEATURE_TEST_IDENTITY_HEADERS",
        "PERMISSION_SHADOW_MODE": "FEATURE_PERMISSION_SHADOW_MODE",
        "WEBHOOK_INGRESS_COMPATIBILITY": "FEATURE_WEBHOOK_TRIGGERS",
        "CONTINUOUS_CONVERSATION_COMPATIBILITY": (
            "FEATURE_CONTINUOUS_CONVERSATION"
        ),
        "MESSAGE_ATTACHMENTS_COMPATIBILITY": "FEATURE_MESSAGE_ATTACHMENTS",
    }
    values: list[EffectiveFeatureValue] = []
    for item in configuration.values:
        legacy_key = targets.get(item.key)
        if legacy_key and legacy_key in environ:
            values.append(
                replace(
                    item,
                    source=f"legacy:{legacy_key}",
                    deprecated_inputs=(legacy_key,),
                )
            )
        elif item.key in TOP_LEVEL_FEATURE_KEYS:
            values.append(
                replace(
                    item,
                    source=(
                        "environment"
                        if item.key in environ
                        else "safe-default"
                    ),
                )
            )
        elif item.key in {
            "UNIFIED_IDENTITY",
            "BUSINESS_APPLICATION_CONTROL_PLANE",
        }:
            values.append(
                replace(
                    item,
                    source=(
                        "derived:FEATURE_WEB_ADMIN"
                        if "FEATURE_WEB_ADMIN" in environ
                        else "safe-default"
                    ),
                )
            )
        else:
            values.append(replace(item, source="safe-default"))
    return replace(configuration, values=tuple(values))


def _optional_bool(environ: Mapping[str, str], key: str) -> bool | None:
    if key not in environ:
        return None
    return _parse_bool(environ[key], key)


def _parse_bool(value: Any, key: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise FeatureConfigurationError(
        f"invalid_feature_boolean: {key} must be true or false"
    )


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _value(
    key: str,
    value: bool,
    source: str,
    classification: FeatureClassification,
    *,
    deprecated: tuple[str, ...] = (),
    restart: bool = False,
) -> EffectiveFeatureValue:
    return EffectiveFeatureValue(
        key=key,
        effective_value=value,
        source=source,
        classification=classification.value,
        deprecated_inputs=deprecated,
        restart_required=restart,
    )
