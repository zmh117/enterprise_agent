import type { ConnectorSummary } from "../../agent-management/domain/models";
import type { Status } from "../../identity/domain/models";

export type WebhookRoutingRule = {
  mode: "fixed" | "extract";
  value: string;
  pointer: string;
  allowed_values: string[];
};

export type WebhookTriggerConfig = {
  schema_version: 1;
  adapter: "grafana_alertmanager_v1" | "generic_json_v1";
  authentication: {
    type: "bearer_v1" | "hmac_sha256_v1";
    secret_ref: string;
    timestamp_header: string;
    nonce_header: string;
    signature_header: string;
    window_seconds: number;
  };
  mapping: {
    variables: Record<string, string>;
    filters: Array<{ pointer: string; operator: "exists" | "equals" | "in" | "not_equals"; value?: unknown }>;
    message_template: string;
    event_id_pointer: string;
    status_pointer: string;
  };
  routing: Record<"project_code" | "environment" | "base" | "workshop" | "service", WebhookRoutingRule>;
  agent: { code: string; publication_id: string };
  delivery: { type: string; connector_id: string; target: Record<string, string>; options: Record<string, unknown> };
  idempotency: { cooldown_seconds: number };
  limits: { requests_per_minute: number; max_in_flight: number; max_alerts: number };
};

export type WebhookTriggerDefinition = {
  id: string;
  code: string;
  name: string;
  trigger_type: "grafana" | "generic";
  public_id: string;
  connector_id: string;
  service_account_id: string;
  service_account_username: string;
  service_account_display_name: string;
  service_account_status: Status;
  status: Status;
  current_publication_id?: string;
  revision: number;
  publication_revision?: number;
  agent_publication_id?: string;
  recent_event_status?: string;
  recent_event_at?: string;
  event_count?: number;
  rejected_event_count?: number;
  failed_event_count?: number;
  created_at: string;
  updated_at: string;
};

export type WebhookRevision = {
  id: string;
  revision: number;
  status: string;
  config_hash: string;
  config: WebhookTriggerConfig;
  validation: { valid?: boolean; errors?: Array<{ field: string; message: string }>; effective_read_only_tools?: string[]; agent_publication_id?: string; agent_revision?: number };
};

export type WebhookPublication = {
  id: string;
  revision: number;
  config_hash: string;
  agent_publication_id: string;
  agent_revision: number;
  snapshot: WebhookTriggerConfig & { service_account_id: string; source_connector_id: string };
  published_by: string;
  published_at: string;
};

export type WebhookTriggerPayload = {
  definition: WebhookTriggerDefinition;
  draft: WebhookRevision | null;
  current_publication: WebhookPublication | null;
  publications: WebhookPublication[];
};

export type WebhookEvent = {
  id: string;
  trigger_code: string;
  trigger_name: string;
  trigger_revision: number;
  status: string;
  auth_result: string;
  filter_result: string;
  error_code: string;
  error_summary: string;
  external_event_id: string;
  correlation_id: string;
  job_id?: string;
  request_bytes: number;
  safe_summary: Record<string, unknown>;
  normalized_event: Record<string, unknown>;
  received_at: string;
};

export type WebhookCatalog = { agent: { code: string; name: string; publication_id: string; revision: number; config_hash: string; read_only_tools: string[] }; connectors: ConnectorSummary[] };

