import type { Status, User } from "../../identity/domain/models";

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

export type RoleDetail = { role: Role; permissions: Permission[]; members: User[] };

export type AuditEvent = {
  id: string;
  event_type: string;
  actor_id?: string;
  status: string;
  summary: string;
  created_at: string;
  payload_summary: { payload?: string; truncated?: boolean };
};

