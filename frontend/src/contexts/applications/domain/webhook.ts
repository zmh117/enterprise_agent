export type WebhookConfig = {
  schema_version: 3
  adapter: "generic_json_v1" | "grafana_alertmanager_v1"
  authentication: { type: "none" | "bearer_v1"; secret_ref: string }
  execution_user_id: string
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
}
export type WebhookRevision = {
  id: string
  revision: number
  status?: "draft" | "validated" | "published"
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
  users: Array<{ id: string; display_name: string; username: string }>
}
export function initialWebhookConfig(
  type: "generic" | "grafana"
): WebhookConfig {
  return {
    schema_version: 3,
    adapter: type === "grafana" ? "grafana_alertmanager_v1" : "generic_json_v1",
    authentication: { type: "none", secret_ref: "" },
    execution_user_id: "",
  }
}
