import { jsonBody, request } from "@enterprise-agent/api-client";

import type { WebhookCatalog, WebhookEvent, WebhookPublication, WebhookRevision, WebhookTriggerConfig, WebhookTriggerDefinition, WebhookTriggerPayload } from "../domain/models";

export const webhookRepository = {
  list: () => request<{ triggers: WebhookTriggerDefinition[] }>("/api/admin/webhook-triggers"),
  catalog: () => request<WebhookCatalog>("/api/admin/webhook-triggers/catalog"),
  get: (code: string) => request<{ trigger: WebhookTriggerPayload }>(`/api/admin/webhook-triggers/${code}`),
  create: (input: { code: string; name: string; trigger_type: string; connector_id: string; config: WebhookTriggerConfig }) => request<{ trigger: { definition: WebhookTriggerDefinition } }>("/api/admin/webhook-triggers", { method: "POST", ...jsonBody(input) }),
  saveRevision: (code: string, expectedRevision: number, config: WebhookTriggerConfig) => request<{ revision: WebhookRevision }>(`/api/admin/webhook-triggers/${code}/revisions`, { method: "POST", ...jsonBody({ expected_revision: expectedRevision, config }) }),
  validateRevision: (code: string, revisionId: string) => request<{ revision: WebhookRevision }>(`/api/admin/webhook-triggers/${code}/revisions/${revisionId}/validate`, { method: "POST" }),
  previewRevision: (code: string, revisionId: string, payload: Record<string, unknown>) => request<{ preview: Record<string, unknown> }>(`/api/admin/webhook-triggers/${code}/revisions/${revisionId}/preview`, { method: "POST", ...jsonBody({ sample_payload: payload }) }),
  publishRevision: (code: string, revisionId: string) => request<{ publication: WebhookPublication }>(`/api/admin/webhook-triggers/${code}/revisions/${revisionId}/publish`, { method: "POST" }),
  rotatePublicId: (code: string, expectedRevision?: number) => request(`/api/admin/webhook-triggers/${code}/rotate-public-id`, { method: "POST", ...jsonBody({ expected_revision: expectedRevision, confirm: true }) }),
  rollback: (code: string, publicationId: string, expectedRevision?: number) => request(`/api/admin/webhook-triggers/${code}/publications/${publicationId}/rollback`, { method: "POST", ...jsonBody({ publication_id: publicationId, expected_revision: expectedRevision }) }),
  setStatus: (code: string, trigger: WebhookTriggerDefinition, name: string, enabled: boolean) => request(`/api/admin/webhook-triggers/${code}`, { method: "PATCH", ...jsonBody({ expected_revision: trigger.revision, name, connector_id: trigger.connector_id, status: enabled ? "enabled" : "disabled" }) }),
  setServiceAccountStatus: (code: string, expectedRevision: number | undefined, enabled: boolean) => request(`/api/admin/webhook-triggers/${code}/service-account`, { method: "PUT", ...jsonBody({ expected_revision: expectedRevision, enabled }) }),
  listEvents: (code: string, status: string) => request<{ events: WebhookEvent[] }>(`/api/admin/webhook-triggers/${code}/events${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  getEvent: (eventId: string) => request<{ event: WebhookEvent; evidence: Record<string, unknown> }>(`/api/admin/webhook-events/${eventId}`),
};

