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
    webhook_read: boolean;
    webhook_edit: boolean;
    webhook_publish: boolean;
    webhook_rotate: boolean;
    webhook_manage_service_account: boolean;
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

export type ExternalIdentity = {
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

export type LoginSession = {
  id: string;
  status: string;
  created_at: string;
  last_seen_at: string;
  idle_expires_at: string;
  absolute_expires_at: string;
  user_agent_summary: string;
  remote_address_summary: string;
};

export type DingTalkTenant = { connector_id: string; name: string; tenant_code: string };

export type RoleAssignment = { id: string; code: string; name: string; status: string; membership_revision?: number };
export type UserDetail = { user: User; roles: RoleAssignment[]; identities: ExternalIdentity[]; sessions: LoginSession[] };
