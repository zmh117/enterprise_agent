from __future__ import annotations

import os
import unittest
from dataclasses import replace
from unittest.mock import patch

from app.modules.mcp_tool_runtime.infrastructure.secrets import DbBackedSecretResolver
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.runtime_config_loader import apply_runtime_config_overlay
from backend.tests.helpers import container, test_settings as make_settings


def _container(*, configure_seed_secrets: bool = True):
    runtime = container(configure_seed_secrets=configure_seed_secrets)
    runtime.permission_service.unified_enabled = True
    return runtime


class PlatformSecretAndRuntimeConfigTests(unittest.TestCase):
    def test_encrypted_db_secret_provider_does_not_persist_plaintext(self) -> None:
        c = _container(configure_seed_secrets=False)
        repository = PlatformConfigRepository(c.database)

        with patch.dict(
            os.environ,
            {"APP_CONFIG_MASTER_KEY": "test-master-key"},
            clear=False,
        ):
            secret = c.platform_config_service.create_platform_secret(
                {
                    "code": "deepseek_api_key",
                    "value": "sk-sensitive-value",
                    "purpose": "claude-runtime",
                },
                actor_id="user_local_admin",
            )
            self.assertEqual(
                "secret://platform/deepseek_api_key",
                secret["secret_ref"],
            )
            stored_versions = c.database.execute("select * from platform_secret_version")
            self.assertEqual(1, len(stored_versions))
            encoded = str(stored_versions)
            self.assertNotIn("sk-sensitive-value", encoded)

            resolver = DbBackedSecretResolver(
                repository,
                master_key=c.settings.app_config_master_key,
            )
            self.assertEqual(
                "sk-sensitive-value",
                resolver.resolve("secret://platform/deepseek_api_key"),
            )

            rotated = c.platform_config_service.rotate_platform_secret(
                "deepseek_api_key",
                {"value": "sk-rotated-value"},
                actor_id="user_local_admin",
            )
            self.assertEqual(2, rotated["active_version"])
            self.assertEqual(
                "sk-rotated-value",
                resolver.resolve("secret://platform/deepseek_api_key"),
            )

            c.platform_config_service.disable_platform_secret(
                "deepseek_api_key",
                actor_id="user_local_admin",
            )
            with self.assertRaises(Exception):
                resolver.resolve("secret://platform/deepseek_api_key")

        audit_text = str(repository.list_config_audit(limit=20))
        self.assertNotIn("sk-sensitive-value", audit_text)
        self.assertNotIn("sk-rotated-value", audit_text)

    def test_runtime_config_overlay_resolves_secret_backed_claude_settings(
        self,
    ) -> None:
        c = _container()
        base = replace(make_settings(), feature_real_claude=True)

        with patch.dict(
            os.environ,
            {"APP_CONFIG_MASTER_KEY": "test-master-key"},
            clear=False,
        ):
            c.platform_config_service.create_platform_secret(
                {"code": "deepseek_api_key", "value": "sk-db-configured"},
                actor_id="user_local_admin",
            )
            c.platform_config_service.upsert_runtime_config_value(
                {
                    "key": "ANTHROPIC_BASE_URL",
                    "value": "https://api.deepseek.com/anthropic",
                    "service_name": "agent-worker",
                },
                actor_id="user_local_admin",
            )
            c.platform_config_service.upsert_runtime_config_value(
                {
                    "key": "ANTHROPIC_MODEL",
                    "value": "deepseek-v4-pro[1m]",
                    "service_name": "agent-worker",
                },
                actor_id="user_local_admin",
            )
            c.platform_config_service.upsert_runtime_config_value(
                {
                    "key": "ANTHROPIC_API_KEY",
                    "secret_ref": "secret://platform/deepseek_api_key",
                    "service_name": "agent-worker",
                },
                actor_id="user_local_admin",
            )
            with self.assertRaisesRegex(ValueError, "deployment env"):
                c.platform_config_service.upsert_runtime_config_value(
                    {
                        "key": "FEATURE_REAL_CLAUDE",
                        "value": True,
                        "service_name": "agent-worker",
                    },
                    actor_id="user_local_admin",
                )

            overlaid = apply_runtime_config_overlay(
                base,
                c.database,
                service_name="agent-worker",
            )

        self.assertEqual(
            "https://api.deepseek.com/anthropic",
            overlaid.anthropic_base_url,
        )
        self.assertEqual("deepseek-v4-pro[1m]", overlaid.claude_model)
        self.assertEqual("sk-db-configured", overlaid.anthropic_api_key)
        self.assertTrue(overlaid.feature_real_claude)
        self.assertEqual("database", overlaid.runtime_config_source)
        self.assertFalse(overlaid.runtime_config_degraded)

    def test_runtime_config_overlay_covers_dingtalk(self) -> None:
        c = _container(configure_seed_secrets=False)
        base = make_settings()

        with patch.dict(
            os.environ,
            {"APP_CONFIG_MASTER_KEY": "test-master-key"},
            clear=False,
        ):
            c.platform_config_service.create_platform_secret(
                {
                    "code": "dingtalk_client_secret",
                    "value": "dingtalk-secret",
                },
                actor_id="user_local_admin",
            )
            c.platform_config_service.upsert_runtime_config_value(
                {
                    "key": "DINGTALK_CLIENT_SECRET",
                    "secret_ref": "secret://platform/dingtalk_client_secret",
                    "service_name": "dingtalk-stream-ingress",
                },
                actor_id="user_local_admin",
            )
            c.platform_config_service.upsert_runtime_config_value(
                {
                    "key": "DINGTALK_DEFAULT_ENVIRONMENT",
                    "value": "sanjiu",
                    "service_name": "dingtalk-stream-ingress",
                },
                actor_id="user_local_admin",
            )

            dingtalk_settings = apply_runtime_config_overlay(
                base,
                c.database,
                service_name="dingtalk-stream-ingress",
            )

        self.assertEqual(
            "dingtalk-secret",
            dingtalk_settings.dingtalk.stream_client_secret,
        )
        self.assertEqual(
            "sanjiu",
            dingtalk_settings.dingtalk.default_environment,
        )
        self.assertFalse(dingtalk_settings.runtime_config_degraded)

        with patch.dict(
            os.environ,
            {"APP_CONFIG_MASTER_KEY": "test-master-key"},
            clear=False,
        ):
            c.platform_config_service.repository.upsert_runtime_config_value(
                key="DINGTALK_CLIENT_SECRET",
                scope_type="global",
                scope_code="*",
                service_name="dingtalk-stream-ingress",
                secret_ref="secret://platform/missing_secret",
            )
            degraded = apply_runtime_config_overlay(
                base,
                c.database,
                service_name="dingtalk-stream-ingress",
            )
        self.assertTrue(degraded.runtime_config_degraded)
        self.assertIn(
            "平台凭据缺失或已停用",
            str(degraded.runtime_config_errors),
        )


if __name__ == "__main__":
    unittest.main()
