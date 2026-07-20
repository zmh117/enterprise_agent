import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { App } from "./App";
import { AuthProvider } from "./auth";
import type { Principal } from "./lib/types";

const adminCapabilities: Principal["capabilities"] = { users_manage: true, roles_manage: true, identities_manage: true, agent_edit: true, agent_publish: true, audit_read: true, webhook_read: true, webhook_edit: true, webhook_publish: true, webhook_rotate: true, webhook_manage_service_account: true };
let currentUser: Principal;

const webhookConfig = {
  schema_version: 1 as const,
  adapter: "grafana_alertmanager_v1" as const,
  authentication: { type: "bearer_v1" as const, secret_ref: "env:GRAFANA_WEBHOOK_TOKEN", timestamp_header: "x-webhook-timestamp", nonce_header: "x-webhook-nonce", signature_header: "x-webhook-signature", window_seconds: 300 },
  mapping: { variables: { summary: "/commonAnnotations/summary" }, filters: [], message_template: "Diagnose {summary}", event_id_pointer: "", status_pointer: "" },
  routing: {
    project_code: { mode: "fixed" as const, value: "default", pointer: "", allowed_values: [] },
    environment: { mode: "fixed" as const, value: "prod", pointer: "", allowed_values: [] },
    base: { mode: "fixed" as const, value: "guanlan", pointer: "", allowed_values: [] },
    workshop: { mode: "fixed" as const, value: "GL001", pointer: "", allowed_values: [] },
    service: { mode: "fixed" as const, value: "order-service", pointer: "", allowed_values: [] },
  },
  agent: { code: "default-diagnostic-agent", publication_id: "agent-pub-1" },
  delivery: { type: "dingtalk_webhook_robot", connector_id: "connector-dingtalk", target: { webhook_id: "alert-group" }, options: {} },
  idempotency: { cooldown_seconds: 300 },
  limits: { requests_per_minute: 60, max_in_flight: 10, max_alerts: 20 },
};

function renderApp(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><AuthProvider><App /></AuthProvider></MemoryRouter></QueryClientProvider>);
}

describe("admin routing", () => {
  beforeEach(() => {
    currentUser = { id: "user-1", username: "admin", display_name: "管理员", roles: ["platform-admin"], auth_source: "local", capabilities: adminCapabilities };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/auth/me") return new Response(JSON.stringify({ user: currentUser }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (path.includes("/api/admin/agents/default-diagnostic-agent")) return new Response(JSON.stringify({ agent: { definition: { code: "default-diagnostic-agent", name: "默认诊断 Agent", description: "", status: "enabled" }, draft: null, current_publication: null, catalog: { models: [], tools: [], skills: [], connectors: [] } }, publications: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (path === "/api/admin/webhook-triggers/catalog") return new Response(JSON.stringify({ agent: { code: "default-diagnostic-agent", name: "默认诊断 Agent", publication_id: "agent-pub-1", revision: 1, config_hash: "agent-hash", read_only_tools: ["query_database", "query_loki"] }, connectors: [{ id: "connector-grafana-default", name: "Grafana", allow_ingress: true, allow_delivery: false }, { id: "connector-dingtalk", name: "钉钉", allow_ingress: false, allow_delivery: true }] }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (path === "/api/admin/webhook-triggers") return new Response(JSON.stringify({ triggers: [{ id: "trigger-1", code: "grafana-default", name: "默认 Grafana 告警", trigger_type: "grafana", public_id: "wh_example", connector_id: "connector-grafana-default", service_account_id: "svc-1", service_account_username: "svc-webhook-grafana", service_account_display_name: "Grafana", service_account_status: "enabled", status: "enabled", current_publication_id: "pub-1", revision: 1, publication_revision: 1, agent_publication_id: "agent-pub-1", created_at: "2026-07-19", updated_at: "2026-07-19" }] }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (path === "/api/admin/webhook-triggers/grafana-default") return new Response(JSON.stringify({ trigger: { definition: { id: "trigger-1", code: "grafana-default", name: "默认 Grafana 告警", trigger_type: "grafana", public_id: "wh_example", connector_id: "connector-grafana-default", service_account_id: "svc-1", service_account_username: "svc-webhook-grafana", service_account_display_name: "Grafana", service_account_status: "enabled", status: "enabled", current_publication_id: "pub-1", revision: 1, created_at: "2026-07-19", updated_at: "2026-07-19" }, draft: { id: "revision-1", revision: 1, status: "validated", config_hash: "trigger-hash", config: webhookConfig, validation: { valid: true, errors: [], effective_read_only_tools: ["query_database"] } }, current_publication: { id: "pub-1", revision: 1, config_hash: "trigger-hash", agent_publication_id: "agent-pub-1", agent_revision: 1, agent_config_hash: "agent-hash", snapshot: webhookConfig, published_at: "2026-07-19" }, publications: [{ id: "pub-1", revision: 1, config_hash: "trigger-hash", agent_publication_id: "agent-pub-1", agent_revision: 1, agent_config_hash: "agent-hash", snapshot: webhookConfig, published_at: "2026-07-19" }, { id: "pub-0", revision: 0, config_hash: "old-hash", agent_publication_id: "agent-pub-1", agent_revision: 1, agent_config_hash: "agent-hash", snapshot: webhookConfig, published_at: "2026-07-18" }] } }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (path.endsWith("/preview")) return new Response(JSON.stringify({ preview: { ignored: false, dedup_key: "grafana:test:firing", routing: { project_code: "default" }, side_effects: false } }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (path === "/api/admin/webhook-triggers/grafana-default/events") return new Response(JSON.stringify({ events: [{ id: "event-1", trigger_code: "grafana-default", external_event_id: "group-1", correlation_id: "correlation-1", status: "JOB_CREATED", auth_result: "bearer_v1", filter_result: "matched", error_code: "", received_at: "2026-07-19T01:00:00Z" }] }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (path === "/api/admin/webhook-events/event-1") return new Response(JSON.stringify({ event: { id: "event-1", correlation_id: "correlation-1", status: "JOB_CREATED" }, evidence: { job: { id: "job-1", status: "SUCCEEDED" }, tool_calls: [{ tool_name: "query_database", status: "SUCCEEDED" }], delivery_attempts: [{ status: "SUCCEEDED" }], delivery_chunks: [{ chunk_index: 1, status: "SUCCEEDED" }] } }), { status: 200, headers: { "Content-Type": "application/json" } });
      return new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
  });

  afterEach(() => vi.unstubAllGlobals());

  it("redirects every non-default Agent route to the only exposed default Agent", async () => {
    renderApp("/admin/agents/secondary-agent");
    await waitFor(() => expect(screen.getByText("默认诊断 Agent")).toBeInTheDocument());
    expect(screen.queryByText("新建 Agent")).not.toBeInTheDocument();
    expect(screen.queryByText("secondary-agent")).not.toBeInTheDocument();
  });

  it("hides management navigation and denies direct routes without capabilities", async () => {
    currentUser = { id: "user-2", username: "viewer", display_name: "只读用户", roles: ["viewer"], auth_source: "local", capabilities: { users_manage: false, roles_manage: false, identities_manage: false, agent_edit: false, agent_publish: false, audit_read: false, webhook_read: false, webhook_edit: false, webhook_publish: false, webhook_rotate: false, webhook_manage_service_account: false } };
    renderApp("/admin/users");
    await waitFor(() => expect(screen.getByText("无管理权限")).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: "用户与身份" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "默认诊断 Agent" })).not.toBeInTheDocument();
  });

  it("shows managed Webhook list but hides create action for read-only operators", async () => {
    currentUser = { ...currentUser, capabilities: { ...adminCapabilities, webhook_edit: false, webhook_publish: false, webhook_rotate: false, webhook_manage_service_account: false } };
    renderApp("/admin/webhooks");
    await waitFor(() => expect(screen.getByText("默认 Grafana 告警")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Webhook 触发器" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "新建 Trigger" })).not.toBeInTheDocument();
  });

  it("renders fixed Agent controls, safe preview and guarded release actions", async () => {
    renderApp("/admin/webhooks/grafana-default");
    await waitFor(() => expect(screen.getByText("固定 Agent 与 Delivery")).toBeInTheDocument());
    expect(screen.getByText("query_database")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /发布不可变快照/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /轮换 public ID/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /回滚/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /运行无副作用预览/ }));
    await waitFor(() => expect(screen.getByText(/grafana:test:firing/)).toBeInTheDocument());
    expect(screen.getByText(/"side_effects": false/)).toBeInTheDocument();
  });

  it("shows event to job, tool and delivery evidence without raw payload", async () => {
    renderApp("/admin/webhooks/grafana-default/events");
    await waitFor(() => expect(screen.getByText("group-1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /group-1/ }));
    await waitFor(() => expect(screen.getByText(/query_database/)).toBeInTheDocument());
    expect(screen.getByText(/delivery_chunks/)).toBeInTheDocument();
    expect(screen.queryByText(/raw_payload/)).not.toBeInTheDocument();
  });
});
