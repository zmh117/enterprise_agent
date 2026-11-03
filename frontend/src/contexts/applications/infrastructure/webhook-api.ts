import { apiRequest } from "@/shared/api/api-client"
import type {
  WebhookConfig,
  WebhookDetail,
  WebhookCatalog,
  WebhookRevision,
  WebhookDefinition,
} from "@/contexts/applications/domain/webhook"
const path = (code: string) =>
  `/api/admin/webhook-triggers/${encodeURIComponent(code)}`
export const getWebhook = async (code: string) =>
  (await apiRequest<{ trigger: WebhookDetail }>(path(code))).trigger
export const getWebhookCatalog = () =>
  apiRequest<WebhookCatalog>("/api/admin/webhook-triggers/catalog")
export const saveWebhookDraft = (
  code: string,
  expectedRevision: number,
  config: WebhookConfig
) =>
  apiRequest<{ revision: WebhookRevision }>(`${path(code)}/revisions`, {
    method: "POST",
    body: { expected_revision: expectedRevision, config },
  })
export const webhookRevisionAction = (
  code: string,
  revisionId: string,
  action: "validate" | "preview" | "publish",
  sample?: Record<string, unknown>
) =>
  apiRequest<{ preview?: unknown }>(
    `${path(code)}/revisions/${encodeURIComponent(revisionId)}/${action}`,
    {
      method: "POST",
      body: action === "preview" ? { sample_payload: sample } : {},
    }
  )
export const setWebhookEnabled = (
  definition: Pick<WebhookDefinition, "code" | "name" | "connector_id" | "revision">,
  enabled: boolean
) =>
  apiRequest(`${path(definition.code)}`, {
    method: "PATCH",
    body: {
      expected_revision: definition.revision,
      name: definition.name,
      connector_id: definition.connector_id,
      status: enabled ? "enabled" : "disabled",
    },
  })
