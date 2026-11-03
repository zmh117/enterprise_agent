export type WebhookRecipient = {
  connector_id: string
  kind: "group" | "user"
  target_id: string
  label: string
}
export type WebhookConfig = {
  schema_version: 1
  adapter: "generic_json_v1" | "grafana_alertmanager_v1"
  authentication: { type: "bearer_v1"; secret_ref: string }
  mapping: {
    variables: Record<string, string>
    filters: Array<{ pointer: string; operator: string; value?: unknown }>
    message_template: string
    event_id_pointer: string
    status_pointer: string
  }
  routing: Record<
    string,
    {
      mode: "fixed" | "extract"
      value: string
      pointer: string
      allowed_values: string[]
    }
  >
  agent: { code: string; publication_id: string }
  delivery: {
    type: string
    connector_id: string
    target: Record<string, unknown>
    options: Record<string, unknown>
  }
  idempotency: { cooldown_seconds: number }
  limits: {
    requests_per_minute: number
    max_in_flight: number
    max_alerts: number
  }
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
  agents: Array<{
    code: string
    name: string
    publication_id: string
    revision: number
  }>
  connectors: Array<{
    id: string
    name: string
    connector_type: string
    allow_delivery: number | boolean
    supports_robot_delivery?: number | boolean
  }>
}
export function initialWebhookConfig(
  type: "generic" | "grafana"
): WebhookConfig {
  return {
    schema_version: 1,
    adapter: type === "grafana" ? "grafana_alertmanager_v1" : "generic_json_v1",
    authentication: { type: "bearer_v1", secret_ref: "" },
    mapping: {
      variables: {
        message: type === "grafana" ? "/commonAnnotations/summary" : "/message",
      },
      filters: [],
      message_template: "{message}",
      event_id_pointer: type === "generic" ? "/id" : "",
      status_pointer: "",
    },
    routing: Object.fromEntries(
      ["project_code", "environment", "base", "workshop", "service"].map(
        (key) => [
          key,
          { mode: "fixed", value: "", pointer: "", allowed_values: [] },
        ]
      )
    ),
    agent: { code: "", publication_id: "" },
    delivery: { type: "none", connector_id: "", target: {}, options: {} },
    idempotency: { cooldown_seconds: 300 },
    limits: { requests_per_minute: 60, max_in_flight: 10, max_alerts: 20 },
  }
}
