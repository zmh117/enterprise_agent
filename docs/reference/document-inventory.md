# 文档移动清单

此清单冻结 schema baseline 重组时的文档分类。`source` 是重组前路径；`target` 是当前路径。历史文件仍保留内容与 Git 追溯，但不再与当前架构并列。

| Source | Target | Classification |
|---|---|---|
| `docs/admin-web-mvp.md` | `docs/architecture/admin-web-mvp.md` | `architecture` |
| `docs/business-application-control-plane.md` | `docs/architecture/business-application-control-plane.md` | `architecture` |
| `docs/continuous-multimodal-conversations.md` | `docs/architecture/continuous-multimodal-conversations.md` | `architecture` |
| `docs/multi-application-agent-worker-and-dingtalk-bot-routing.md` | `docs/architecture/multi-application-agent-worker-and-dingtalk-bot-routing.md` | `architecture` |
| `docs/tool-mcp.md` | `docs/architecture/tool-mcp.md` | `architecture` |
| `docs/unified-identity-rbac-admin.md` | `docs/architecture/unified-identity-rbac-admin.md` | `architecture` |
| `docs/webhook-agent-triggers.md` | `docs/architecture/webhook-agent-triggers.md` | `architecture` |
| `new in baseline reorganization` | `docs/archive/implementation-baselines/README.md` | `new/archive-index` |
| `docs/admin-web-migration-baseline.md` | `docs/archive/implementation-baselines/admin-web-migration-baseline.md` | `archive/implementation-baseline` |
| `docs/admin-web-shadcn-scaffold.md` | `docs/archive/implementation-baselines/admin-web-shadcn-scaffold.md` | `archive/implementation-baseline` |
| `docs/business-application-control-plane-baseline.md` | `docs/archive/implementation-baselines/business-application-control-plane-baseline.md` | `archive/implementation-baseline` |
| `new in baseline reorganization` | `docs/archive/legacy-api-platform/README.md` | `new/archive-index` |
| `docs/adr/0001-persist-external-api-token-not-password.md` | `docs/archive/legacy-api-platform/decisions/0001-persist-external-api-token-not-password.md` | `archive/legacy-api-platform` |
| `docs/adr/0002-use-governed-declarative-capability-handlers.md` | `docs/archive/legacy-api-platform/decisions/0002-use-governed-declarative-capability-handlers.md` | `archive/legacy-api-platform` |
| `docs/adr/0003-bind-applications-to-capabilities-not-handlers.md` | `docs/archive/legacy-api-platform/decisions/0003-bind-applications-to-capabilities-not-handlers.md` | `archive/legacy-api-platform` |
| `docs/adr/0004-pin-capability-dependencies-in-application-publications.md` | `docs/archive/legacy-api-platform/decisions/0004-pin-capability-dependencies-in-application-publications.md` | `archive/legacy-api-platform` |
| `docs/adr/0005-resolve-external-api-credentials-from-current-actor.md` | `docs/archive/legacy-api-platform/decisions/0005-resolve-external-api-credentials-from-current-actor.md` | `archive/legacy-api-platform` |
| `docs/adr/0006-freeze-one-ones-team-per-application-capability-binding.md` | `docs/archive/legacy-api-platform/decisions/0006-freeze-one-ones-team-per-application-capability-binding.md` | `archive/legacy-api-platform` |
| `docs/adr/0007-classify-handler-side-effects-by-operation-semantics.md` | `docs/archive/legacy-api-platform/decisions/0007-classify-handler-side-effects-by-operation-semantics.md` | `archive/legacy-api-platform` |
| `docs/adr/0008-govern-capability-handlers-with-draft-verify-publish.md` | `docs/archive/legacy-api-platform/decisions/0008-govern-capability-handlers-with-draft-verify-publish.md` | `archive/legacy-api-platform` |
| `docs/adr/0009-separate-handler-verification-credentials-from-runtime-credentials.md` | `docs/archive/legacy-api-platform/decisions/0009-separate-handler-verification-credentials-from-runtime-credentials.md` | `archive/legacy-api-platform` |
| `docs/adr/0010-keep-authentication-profiles-outside-capability-catalog.md` | `docs/archive/legacy-api-platform/decisions/0010-keep-authentication-profiles-outside-capability-catalog.md` | `archive/legacy-api-platform` |
| `docs/adr/0011-freeze-auth-profile-not-user-token.md` | `docs/archive/legacy-api-platform/decisions/0011-freeze-auth-profile-not-user-token.md` | `archive/legacy-api-platform` |
| `docs/adr/0012-separate-application-readiness-from-user-capability-availability.md` | `docs/archive/legacy-api-platform/decisions/0012-separate-application-readiness-from-user-capability-availability.md` | `archive/legacy-api-platform` |
| `docs/adr/0013-filter-model-tools-by-user-capability-availability.md` | `docs/archive/legacy-api-platform/decisions/0013-filter-model-tools-by-user-capability-availability.md` | `archive/legacy-api-platform` |
| `docs/adr/0014-compile-restricted-field-mappings.md` | `docs/archive/legacy-api-platform/decisions/0014-compile-restricted-field-mappings.md` | `archive/legacy-api-platform` |
| `docs/adr/0015-capability-owns-public-schema-handler-implements-it.md` | `docs/archive/legacy-api-platform/decisions/0015-capability-owns-public-schema-handler-implements-it.md` | `archive/legacy-api-platform` |
| `docs/adr/0016-present-one-capability-configuration-keep-internal-separation.md` | `docs/archive/legacy-api-platform/decisions/0016-present-one-capability-configuration-keep-internal-separation.md` | `archive/legacy-api-platform` |
| `docs/adr/0017-govern-api-connections-as-shared-platform-resources.md` | `docs/archive/legacy-api-platform/decisions/0017-govern-api-connections-as-shared-platform-resources.md` | `archive/legacy-api-platform` |
| `docs/adr/0018-defer-network-zones-retain-connection-origin-boundary.md` | `docs/archive/legacy-api-platform/decisions/0018-defer-network-zones-retain-connection-origin-boundary.md` | `archive/legacy-api-platform` |
| `docs/adr/0019-version-api-connections-with-draft-verify-publish.md` | `docs/archive/legacy-api-platform/decisions/0019-version-api-connections-with-draft-verify-publish.md` | `archive/legacy-api-platform` |
| `docs/adr/0020-classify-external-api-failures-and-bound-query-retries.md` | `docs/archive/legacy-api-platform/decisions/0020-classify-external-api-failures-and-bound-query-retries.md` | `archive/legacy-api-platform` |
| `docs/adr/0021-persist-only-bounded-normalized-capability-output.md` | `docs/archive/legacy-api-platform/decisions/0021-persist-only-bounded-normalized-capability-output.md` | `archive/legacy-api-platform` |
| `docs/adr/0022-build-general-capability-framework-accept-with-one-ones-query.md` | `docs/archive/legacy-api-platform/decisions/0022-build-general-capability-framework-accept-with-one-ones-query.md` | `archive/legacy-api-platform` |
| `docs/adr/0023-users-self-manage-personal-external-api-credentials.md` | `docs/archive/legacy-api-platform/decisions/0023-users-self-manage-personal-external-api-credentials.md` | `archive/legacy-api-platform` |
| `docs/adr/0024-verify-capabilities-with-the-current-administrators-credential.md` | `docs/archive/legacy-api-platform/decisions/0024-verify-capabilities-with-the-current-administrators-credential.md` | `archive/legacy-api-platform` |
| `docs/adr/0028-separate-governed-api-administration-from-capability-execution.md` | `docs/archive/legacy-api-platform/decisions/0028-separate-governed-api-administration-from-capability-execution.md` | `archive/legacy-api-platform` |
| `docs/adr/0029-bootstrap-first-connection-with-transient-self-verification.md` | `docs/archive/legacy-api-platform/decisions/0029-bootstrap-first-connection-with-transient-self-verification.md` | `archive/legacy-api-platform` |
| `docs/adr/0030-classify-ones-output-as-internal-and-preserve-normalized-results.md` | `docs/archive/legacy-api-platform/decisions/0030-classify-ones-output-as-internal-and-preserve-normalized-results.md` | `archive/legacy-api-platform` |
| `docs/adr/0033-let-agents-compose-capabilities-through-public-schemas.md` | `docs/archive/legacy-api-platform/decisions/0033-let-agents-compose-capabilities-through-public-schemas.md` | `archive/legacy-api-platform` |
| `docs/adr/0034-show-full-business-fields-but-exclude-credentials-from-test-preview.md` | `docs/archive/legacy-api-platform/decisions/0034-show-full-business-fields-but-exclude-credentials-from-test-preview.md` | `archive/legacy-api-platform` |
| `docs/adr/0035-soft-deprecate-capability-releases-before-disable-or-archive.md` | `docs/archive/legacy-api-platform/decisions/0035-soft-deprecate-capability-releases-before-disable-or-archive.md` | `archive/legacy-api-platform` |
| `docs/adr/0036-use-stable-capability-codes-and-monotonic-release-revisions.md` | `docs/archive/legacy-api-platform/decisions/0036-use-stable-capability-codes-and-monotonic-release-revisions.md` | `archive/legacy-api-platform` |
| `docs/adr/0037-derive-capability-use-from-agent-and-application-configuration.md` | `docs/archive/legacy-api-platform/decisions/0037-derive-capability-use-from-agent-and-application-configuration.md` | `archive/legacy-api-platform` |
| `docs/adr/0038-pin-agent-publications-and-revalidate-application-capability-subsets.md` | `docs/archive/legacy-api-platform/decisions/0038-pin-agent-publications-and-revalidate-application-capability-subsets.md` | `archive/legacy-api-platform` |
| `docs/adr/0040-select-capability-releases-in-agents-and-display-business-descriptions.md` | `docs/archive/legacy-api-platform/decisions/0040-select-capability-releases-in-agents-and-display-business-descriptions.md` | `archive/legacy-api-platform` |
| `docs/adr/0041-separate-model-visible-capability-description-from-release-notes.md` | `docs/archive/legacy-api-platform/decisions/0041-separate-model-visible-capability-description-from-release-notes.md` | `archive/legacy-api-platform` |
| `docs/adr/0043-use-publication-chain-and-release-disable-instead-of-a-global-feature-flag.md` | `docs/archive/legacy-api-platform/decisions/0043-use-publication-chain-and-release-disable-instead-of-a-global-feature-flag.md` | `archive/legacy-api-platform` |
| `docs/adr/0044-use-one-capability-identifier-for-business-and-model-tool-names.md` | `docs/archive/legacy-api-platform/decisions/0044-use-one-capability-identifier-for-business-and-model-tool-names.md` | `archive/legacy-api-platform` |
| `docs/adr/0045-limit-mapping-plans-to-deterministic-projections-and-scalar-conversions.md` | `docs/archive/legacy-api-platform/decisions/0045-limit-mapping-plans-to-deterministic-projections-and-scalar-conversions.md` | `archive/legacy-api-platform` |
| `docs/adr/0046-use-optimistic-locking-content-hashes-and-idempotent-publication.md` | `docs/archive/legacy-api-platform/decisions/0046-use-optimistic-locking-content-hashes-and-idempotent-publication.md` | `archive/legacy-api-platform` |
| `docs/adr/0047-accept-v1-through-the-full-dingtalk-to-ones-publication-chain.md` | `docs/archive/legacy-api-platform/decisions/0047-accept-v1-through-the-full-dingtalk-to-ones-publication-chain.md` | `archive/legacy-api-platform` |
| `docs/adr/0048-allow-explicit-plain-http-api-connections.md` | `docs/archive/legacy-api-platform/decisions/0048-allow-explicit-plain-http-api-connections.md` | `archive/legacy-api-platform` |
| `docs/agent-profile-model-connections.md` | `docs/guides/agent-profile-model-connections.md` | `guides` |
| `docs/agent-test-data.md` | `docs/guides/agent-test-data.md` | `guides` |
| `docs/platform-config-api.md` | `docs/guides/platform-config-api.md` | `guides` |
| `docs/web-managed-multi-dingtalk-runtime.md` | `docs/guides/web-managed-multi-dingtalk-runtime.md` | `guides` |
| `docs/web-managed-secrets-and-env-config.md` | `docs/guides/web-managed-secrets-and-env-config.md` | `guides` |
| `docs/agent-retry-failure-delivery.md` | `docs/operations/agent-retry-failure-delivery.md` | `operations` |
| `docs/compose-postgres18-rabbitmq4-upgrade.md` | `docs/operations/compose-postgres18-rabbitmq4-upgrade.md` | `operations` |
| `docs/dingtalk-test-data-rebuild.md` | `docs/operations/dingtalk-test-data-rebuild.md` | `operations` |
| `docs/emergency-master-key-reencryption.md` | `docs/operations/emergency-master-key-reencryption.md` | `operations` |
| `docs/execution-policy-runtime-maintenance.md` | `docs/operations/execution-policy-runtime-maintenance.md` | `operations` |
| `docs/platform-master-key.md` | `docs/operations/platform-master-key.md` | `operations` |
| `new in baseline reorganization` | `docs/operations/schema-baseline-bootstrap.md` | `new/current` |
| `new in baseline reorganization` | `docs/operations/schema-baseline-upgrade.md` | `new/current` |
| `docs/chatgpt-context/01-project-overview.md` | `docs/reference/chatgpt-context/01-project-overview.md` | `reference/current-context` |
| `docs/chatgpt-context/02-system-architecture.md` | `docs/reference/chatgpt-context/02-system-architecture.md` | `reference/current-context` |
| `docs/chatgpt-context/03-domain-model.md` | `docs/reference/chatgpt-context/03-domain-model.md` | `reference/current-context` |
| `docs/chatgpt-context/04-runtime-flows.md` | `docs/reference/chatgpt-context/04-runtime-flows.md` | `reference/current-context` |
| `docs/chatgpt-context/05-security-and-governance.md` | `docs/reference/chatgpt-context/05-security-and-governance.md` | `reference/current-context` |
| `docs/chatgpt-context/06-deployment-and-operations.md` | `docs/reference/chatgpt-context/06-deployment-and-operations.md` | `reference/current-context` |
| `docs/chatgpt-context/07-implementation-status.md` | `docs/reference/chatgpt-context/07-implementation-status.md` | `reference/current-context` |
| `docs/chatgpt-context/08-design-decisions.md` | `docs/reference/chatgpt-context/08-design-decisions.md` | `reference/current-context` |
| `docs/chatgpt-context/09-chatgpt-collaboration-guide.md` | `docs/reference/chatgpt-context/09-chatgpt-collaboration-guide.md` | `reference/current-context` |
| `docs/chatgpt-context/README.md` | `docs/reference/chatgpt-context/README.md` | `reference/current-context` |
| `docs/adr/0025-resolve-ones-user-and-default-team-from-user-binding.md` | `docs/reference/decisions/0025-resolve-ones-user-and-default-team-from-user-binding.md` | `reference/current-decision` |
| `docs/adr/0026-bind-ones-with-a-two-stage-verification-challenge.md` | `docs/reference/decisions/0026-bind-ones-with-a-two-stage-verification-challenge.md` | `reference/current-decision` |
| `docs/adr/0027-reverify-and-snapshot-when-switching-default-team.md` | `docs/reference/decisions/0027-reverify-and-snapshot-when-switching-default-team.md` | `reference/current-decision` |
| `docs/adr/0031-reuse-external-identity-panel-with-self-and-admin-modes.md` | `docs/reference/decisions/0031-reuse-external-identity-panel-with-self-and-admin-modes.md` | `reference/current-decision` |
| `docs/adr/0032-support-one-ones-account-per-user-in-v1.md` | `docs/reference/decisions/0032-support-one-ones-account-per-user-in-v1.md` | `reference/current-decision` |
| `docs/adr/0039-derive-dingtalk-application-access-from-route-and-enabled-user.md` | `docs/reference/decisions/0039-derive-dingtalk-application-access-from-route-and-enabled-user.md` | `reference/current-decision` |
| `docs/adr/0042-freeze-job-subject-without-bypassing-live-revocation.md` | `docs/reference/decisions/0042-freeze-job-subject-without-bypassing-live-revocation.md` | `reference/current-decision` |
| `docs/adr/0049-model-dingtalk-identities-by-enterprise-and-observation.md` | `docs/reference/decisions/0049-model-dingtalk-identities-by-enterprise-and-observation.md` | `reference/current-decision` |
| `docs/adr/README.md` | `docs/reference/decisions/README.md` | `reference/current-decision` |
| `docs/compose-postgres18-rabbitmq4-verification.md` | `docs/verification/compose-postgres18-rabbitmq4-verification.md` | `verification` |

当前事实层级与入口见 [文档总索引](../README.md)。
