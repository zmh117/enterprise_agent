import { jsonBody, request } from "@enterprise-agent/api-client";
import type { ChannelProvider, Connector, ConnectorDraft, ManagedSecret, ManagedSecretDraft, ProbeResult, Skill, ToolProvider, ToolResource, ToolResourceDraft } from "../domain/models";

export const catalogRepository = {
  skills: () => request<{ skills: Skill[] }>("/api/admin/skills"),
  toolProviders: () => request<{ providers: ToolProvider[] }>("/api/admin/tool-providers"),
  toolResources: () => request<{ items: ToolResource[] }>("/api/admin/tool-resources"),
  channelProviders: () => request<{ providers: ChannelProvider[] }>("/api/admin/channel-providers"),
  connectors: () => request<{ items: Connector[] }>("/api/admin/connectors"),
  secrets: () => request<{ secrets: ManagedSecret[] }>("/api/platform/secrets?include_disabled=false"),
  createSecret: (draft: ManagedSecretDraft) => request<{ secret: ManagedSecret }>("/api/platform/secrets", { method: "POST", ...jsonBody({ ...draft, metadata: { source: "admin-web" } }) }),
  saveToolResource: (draft: ToolResourceDraft) => request<{ resource: ToolResource }>(draft.expected_revision ? `/api/admin/tool-resources/${encodeURIComponent(draft.code)}` : "/api/admin/tool-resources", { method: draft.expected_revision ? "PUT" : "POST", ...jsonBody(draft) }),
  setToolResourceStatus: (resource: ToolResource) => request<{ resource: ToolResource }>(`/api/admin/tool-resources/${encodeURIComponent(resource.code)}/status`, { method: "PUT", ...jsonBody({ expected_revision: resource.revision, status: resource.status === "enabled" ? "disabled" : "enabled" }) }),
  testToolResource: (code: string) => request<{ result: ProbeResult }>(`/api/admin/tool-resources/${encodeURIComponent(code)}/test`, { method: "POST" }),
  saveConnector: (draft: ConnectorDraft) => request<{ connector: Connector }>(draft.expected_revision ? `/api/admin/connectors/${encodeURIComponent(draft.id)}` : "/api/admin/connectors", { method: draft.expected_revision ? "PUT" : "POST", ...jsonBody(draft) }),
  validateConnector: (draft: ConnectorDraft) => request<{ result: ProbeResult }>("/api/admin/connectors/validate", { method: "POST", ...jsonBody(draft) }),
  setConnectorStatus: (connector: Connector) => request<{ connector: Connector }>(`/api/admin/connectors/${encodeURIComponent(connector.id)}/status`, { method: "PUT", ...jsonBody({ expected_revision: connector.revision, status: connector.enabled ? "disabled" : "enabled" }) }),
};
