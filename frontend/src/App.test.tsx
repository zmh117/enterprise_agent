import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { App } from "./App";
import { AuthProvider } from "./auth";
import type { Principal } from "./lib/types";

const adminCapabilities: Principal["capabilities"] = { users_manage: true, roles_manage: true, identities_manage: true, agent_edit: true, agent_publish: true, audit_read: true };
let currentUser: Principal;

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
    currentUser = { id: "user-2", username: "viewer", display_name: "只读用户", roles: ["viewer"], auth_source: "local", capabilities: { users_manage: false, roles_manage: false, identities_manage: false, agent_edit: false, agent_publish: false, audit_read: false } };
    renderApp("/admin/users");
    await waitFor(() => expect(screen.getByText("无管理权限")).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: "用户与身份" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "默认诊断 Agent" })).not.toBeInTheDocument();
  });
});
