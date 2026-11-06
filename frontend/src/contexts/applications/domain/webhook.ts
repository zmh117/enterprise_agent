export type WebhookConfig = {
  schema_version: 2
  adapter: "generic_json_v1" | "grafana_alertmanager_v1"
  authentication: { type: "bearer_v1"; secret_ref: string }
  role_ids: string[]
}
export type WebhookDefinition = {
  id: string
  code: string
  name: string
  trigger_type: "generic" | "grafana"
  connector_id: string
  public_id: string
  revision: number
  status: "enabled" | "disabled"
  service_account_id: string
  service_account_username: string
  service_account_status: string
}
export type WebhookRevision = {
  id: string
  revision: number
  config: WebhookConfig
  validation: {
    valid?: boolean
    errors?: Array<{ field: string; message: string }>
  }
}
export type WebhookDetail = {
  definition: WebhookDefinition
  draft: WebhookRevision | null
  current_publication: { id: string; revision: number } | null
}
export type WebhookCatalog = {
  roles: Array<{ id: string; name: string; code: string }>
}
export function initialWebhookConfig(
  type: "generic" | "grafana"
): WebhookConfig {
  return {
    schema_version: 2,
    adapter: type === "grafana" ? "grafana_alertmanager_v1" : "generic_json_v1",
    authentication: { type: "bearer_v1", secret_ref: "" },
    role_ids: [],
  }
}
