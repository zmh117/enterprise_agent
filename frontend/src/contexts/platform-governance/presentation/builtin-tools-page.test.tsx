import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import { BuiltinToolsPage } from "@/contexts/platform-governance/presentation/builtin-tools-page"

function response(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })
  )
}

function renderPage() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <MemoryRouter>
        <BuiltinToolsPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

const digest = "a".repeat(64)
const schemaHash = "b".repeat(64)
const evidence = {
  id: "builtin_tool_verification_current",
  tool_identifier: "query_database",
  handler_version: "1.0.0",
  implementation_digest: digest,
  verifier_version: "1.0.0",
  normalized_input_hash: "c".repeat(64),
  status: "PASSED",
  result_summary: {
    check_count: 2,
    checks: [{ code: "readonly.boundary", status: "PASSED" }],
    truncated: false,
  },
  safe_error_summary: "",
  verified_by: "user_admin",
  verified_at: "2026-08-06T04:00:00Z",
}

function builtinTool(options?: {
  evidence?: boolean
  releaseStatus?: "ACTIVE" | "DEPRECATED" | "DISABLED" | "ARCHIVED"
  dependencies?: number
}) {
  const releases = options?.releaseStatus
    ? [
        {
          id: "builtin_tool_release_query_database_1",
          tool_identifier: "query_database",
          release_revision: 1,
          tool_semantic_version: "1.0.0",
          handler_version: "1.0.0",
          implementation_digest: digest,
          manifest_hash: "d".repeat(64),
          public_schema_hash: schemaHash,
          verification_id: evidence.id,
          status: options.releaseStatus,
          published_by: "user_admin",
          published_at: "2026-08-06T04:01:00Z",
          deprecated_by: "",
          deprecated_at: null,
          disabled_by: "",
          disabled_at: null,
          archived_by: "",
          archived_at: null,
          dependencies: {
            active_agent_publications: options.dependencies ?? 0,
            active_application_publications: 0,
            recoverable_jobs: 0,
          },
          lifecycle_audit: [
            {
              id: "builtin_tool_lifecycle_audit_1",
              tool_release_id: "builtin_tool_release_query_database_1",
              previous_status: null,
              new_status: "ACTIVE",
              reason_code: "PUBLISHED",
              safe_summary: "",
              actor_id: "user_admin",
              correlation_id: "builtin-tool-test",
              occurred_at: "2026-08-06T04:01:00Z",
            },
          ],
        },
      ]
    : []
  return {
    manifest: {
      tool_identifier: "query_database",
      tool_semantic_version: "1.0.0",
      handler_id: "query_database",
      handler_version: "1.0.0",
      display_name: "查询数据库",
      description: "只允许执行受治理范围内的只读数据库查询。",
      input_schema: { type: "object" },
      output_schema: { type: "object" },
      risk_level: "HIGH",
      required_permissions: ["tool:use"],
      resource_slots: [
        {
          code: "database",
          resource_kind: "database",
          required: true,
          allowed_scope_types: ["environment", "base", "workshop"],
        },
      ],
      visibility: "application",
      public_schema_hash: schemaHash,
      verifier_plan: {
        verifier_id: "builtin-readonly",
        verifier_version: "1.0.0",
        checks: ["readonly.boundary"],
        max_duration_ms: 1000,
        max_result_bytes: 4096,
      },
      safety_boundary: {
        read_only: true,
        allowed_effects: ["read"],
        required_guards: ["job_snapshot"],
      },
    },
    code_implementation_digest: digest,
    installation: {
      tool_identifier: "query_database",
      handler_version: "1.0.0",
      implementation_digest: digest,
      installation_status: "INSTALLED",
      safe_health_summary: "",
      first_seen_at: "2026-08-06T03:00:00Z",
      last_seen_at: "2026-08-06T04:00:00Z",
    },
    verifications: options?.evidence === false ? [] : [evidence],
    releases,
    effective_status: releases.length ? "CALLABLE" : "UNPUBLISHED",
  }
}

function mockCatalog(
  capabilities: string[],
  tool = builtinTool(),
  mutation?: (url: string, init?: RequestInit) => Promise<Response> | undefined
) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input)
    const overridden = mutation?.(url, init)
    if (overridden) return overridden
    if (url === "/api/admin/capabilities") {
      return response({ capabilities, modules: {} })
    }
    if (url === "/api/platform/builtin-tools") {
      return response({ tools: [tool] })
    }
    if (url.endsWith("/api/platform/builtin-tools/query_database")) {
      return response({ tool })
    }
    throw new Error(`Unexpected request: ${url}`)
  })
}

afterEach(() => vi.restoreAllMocks())

describe("Built-in readonly Tool governance page", () => {
  it("keeps every mutation disabled for a read-only administrator", async () => {
    mockCatalog(["builtin_tools.read"])
    renderPage()

    expect(await screen.findByText("查询数据库")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "安装对账" })).toBeDisabled()
    expect(
      await screen.findByRole("button", { name: "机器验证" }),
    ).toBeDisabled()
    expect(screen.getByRole("button", { name: "发布 Release" })).toBeDisabled()
    expect(screen.getByText(/只有目录读取权限/)).toBeInTheDocument()
  })

  it("publishes only after confirming the exact current PASSED evidence", async () => {
    const requests: Array<{ url: string; body: unknown }> = []
    mockCatalog(
      ["builtin_tools.read", "builtin_tools.publish"],
      builtinTool(),
      (url, init) => {
        if (url.endsWith("/query_database/publish")) {
          requests.push({
            url,
            body: JSON.parse(String(init?.body)),
          })
          return response({
            release: {
              ...builtinTool({ releaseStatus: "ACTIVE" }).releases[0],
              dependencies: undefined,
              lifecycle_audit: undefined,
            },
          })
        }
      }
    )
    renderPage()

    fireEvent.click(await screen.findByRole("button", { name: "发布 Release" }))
    expect(
      screen.getByText(/冻结精确版本、digest、Schema 与验证证据/)
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "确认执行" }))

    await waitFor(() => expect(requests).toHaveLength(1))
    expect(requests[0]?.body).toEqual({
      handler_version: "1.0.0",
      verification_id: evidence.id,
      idempotency_key: `ui:${evidence.id}`,
    })
  })

  it("prevents archive while immutable history still has active dependencies", async () => {
    mockCatalog(
      ["builtin_tools.read", "builtin_tools.lifecycle"],
      builtinTool({ releaseStatus: "ACTIVE", dependencies: 1 })
    )
    renderPage()

    fireEvent.click(await screen.findByRole("tab", { name: /Release/ }))
    expect(screen.getByText("PUBLISHED")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "归档" })).toBeDisabled()
    expect(screen.getByText("builtin-tool-test")).toBeInTheDocument()
  })

  it("shows a safe concurrency error and keeps the lifecycle dialog open", async () => {
    mockCatalog(
      ["builtin_tools.read", "builtin_tools.lifecycle"],
      builtinTool({ releaseStatus: "ACTIVE" }),
      (url) => {
        if (
          url.includes("/builtin-tool-releases/") &&
          url.endsWith("/lifecycle")
        ) {
          return response(
            {
              detail: {
                code: "revision_conflict",
                message: "配置已被其他管理员更新，请刷新后重试。",
              },
            },
            409
          )
        }
      }
    )
    renderPage()

    fireEvent.click(await screen.findByRole("tab", { name: /Release/ }))
    fireEvent.click(screen.getByRole("button", { name: "弃用" }))
    fireEvent.click(screen.getByRole("button", { name: "确认执行" }))

    expect(
      await screen.findByText("配置已被其他管理员更新，请刷新后重试。")
    ).toBeInTheDocument()
    expect(screen.getByRole("alertdialog")).toBeInTheDocument()
  })
})
