import type { Status } from "../../identity/domain/models";

export type ConnectorSummary = {
  id: string;
  connector_id?: string;
  name: string;
  connector_type?: string;
  tenant_code?: string;
  allow_ingress?: number;
  allow_delivery?: number;
};

export type AgentConfig = {
  business_role: string;
  business_instructions: string;
  model_policy: { model: string };
  execution: { max_turns: number; timeout_seconds: number };
  tools: string[];
  skills: string[];
  routing: { project_code: string };
  channels: { ingress: string[]; delivery: string[] };
};

export type AgentRevision = {
  id: string;
  revision: number;
  status: string;
  config_hash: string;
  config: AgentConfig;
  validation: { valid?: boolean; errors?: Array<{ field: string; message: string }> };
};

export type AgentPublication = {
  id: string;
  revision: number;
  schema_version: number;
  config_hash: string;
  snapshot: AgentConfig;
  published_by: string;
  published_at: string;
};

export type AgentPayload = {
  definition: { code: string; name: string; description: string; status: Status };
  draft: AgentRevision | null;
  current_publication: AgentPublication | null;
  catalog: { models: string[]; tools: string[]; skills: string[]; connectors: ConnectorSummary[] };
};

