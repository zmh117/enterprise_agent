export type Status = "enabled" | "disabled";

export type Principal = {
  id: string;
  username: string;
  display_name: string;
  roles: string[];
  auth_source: string;
  capabilities: {
    users_manage: boolean;
    roles_manage: boolean;
    identities_manage: boolean;
    agent_edit: boolean;
    agent_publish: boolean;
    audit_read: boolean;
  };
};

export type User = {
  id: string;
  username: string;
  display_name: string;
  email: string;
  status: Status;
  revision: number;
};

export type Role = {
  id: string;
  code: string;
  name: string;
  description: string;
  status: Status;
  revision: number;
  membership_id?: string;
  membership_revision?: number;
};

export type Identity = {
  id: string;
  user_id: string;
  provider: string;
  tenant_code: string;
  external_subject_id: string;
  connector_id: string;
  display_name: string;
  status: Status;
  revision: number;
  last_seen_at?: string;
};

export type Session = {
  id: string;
  status: string;
  created_at: string;
  last_seen_at: string;
  idle_expires_at: string;
  absolute_expires_at: string;
  user_agent_summary: string;
  remote_address_summary: string;
};

export type Permission = {
  id: string;
  subject_type: "user" | "role";
  subject_code: string;
  resource_type: string;
  resource_code: string;
  action: string;
  effect: "allow" | "deny";
  priority: number;
  status: Status;
  revision: number;
};

export type Connector = {
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

export type Publication = {
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
  current_publication: Publication | null;
  catalog: { models: string[]; tools: string[]; skills: string[]; connectors: Connector[] };
};

export type AuditEvent = {
  id: string;
  event_type: string;
  actor_id?: string;
  status: string;
  summary: string;
  created_at: string;
  payload_summary: { payload?: string; truncated?: boolean };
};
