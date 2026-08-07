import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { GovernedResource } from "@/contexts/platform-governance/domain/platform-governance"
import { ResourcePolicySheet } from "@/contexts/platform-governance/presentation/resource-policy-sheet"

function response(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })
  )
}

function renderSheet(resource: GovernedResource) {
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
        <ResourcePolicySheet
          resource={resource}
          resources={[resource]}
          onOpenChange={() => undefined}
        />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

function globalLokiResource(): GovernedResource {
  return {
    id: "resource-loki-global",
    code: "loki-global",
    name: "统一 Loki",
    resource_kind: "loki",
    scope_type: "global",
    environment_code: "",
    base_code: "",
    workshop_code: "",
    status: "enabled",
    draft: {
      id: "resource-draft-loki-global",
      resource_id: "resource-loki-global",
      draft_revision: 2,
      provider_type: "loki",
      config: {
        base_url: "http://must-not-render.internal:3100",
        tenant_id: "must-not-render-tenant",
      },
      secret_refs: {
        token_ref: "secret://platform/must-not-render-token",
      },
      status: "VERIFIED",
      updated_at: "2026-08-06T04:00:00Z",
    },
    draft_verification: null,
    published_revision: {
      id: "resource-revision-loki-global-1",
      resource_id: "resource-loki-global",
      revision: 1,
      provider_type: "loki",
      provider_contract_version: "loki_v1",
      config: {},
      secret_refs: {},
      status: "PUBLISHED",
      published_at: "2026-08-06T03:00:00Z",
    },
    effective_revision_id: "resource-revision-loki-global-1",
    activation_status: "READY",
    last_known_good_generation_id: "generation-1",
    safe_error_summary: "",
    affected_applications: [],
  }
}

const policyIdentity = {
  id: "loki-scope-policy-guanlan",
  code: "loki-guanlan-scope",
  environment_code: "prod-a",
  base_code: "guanlan",
  status: "enabled",
  revision: 1,
}

const policyDetail = {
  ...policyIdentity,
  draft: {
    policy_id: policyIdentity.id,
    draft_revision: 2,
    resource_revision_id: "resource-revision-loki-global-1",
    conditions: [
      { key: "customer", value: "prod-a" },
      { key: "base", value: "guanlan" },
    ],
    content_hash: "a".repeat(64),
    status: "DRAFT",
    updated_at: "2026-08-06T04:00:00Z",
  },
  revisions: [],
}

afterEach(() => vi.restoreAllMocks())

describe("Resource policy management", () => {
  it("discovers bounded Loki labels without rendering connection or Secret values", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url === "/api/platform/loki-scope-policies") {
        return response({ policies: [policyIdentity] })
      }
      if (url.endsWith("/loki-scope-policies/loki-guanlan-scope")) {
        return response({ policy: policyDetail })
      }
      if (url.endsWith("/resources/loki-global/loki/test")) {
        return response({
          test_session_id: "loki-draft-test-1",
          draft_revision: 2,
          labels: ["customer", "base", "workshop"],
          label_count: 3,
          truncated: false,
          expires_at: "2026-08-06T04:05:00Z",
        })
      }
      if (url === "/api/platform/secrets") return response({ secrets: [] })
      if (url.startsWith("/api/platform/environments")) {
        return response({ environments: [] })
      }
      if (url.startsWith("/api/platform/bases")) return response({ bases: [] })
      if (url.startsWith("/api/platform/workshops")) {
        return response({ workshops: [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderSheet(globalLokiResource())

    fireEvent.click(
      await screen.findByRole("button", { name: "测试并发现标签" })
    )
    expect(await screen.findByText("workshop")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "添加 key-value" })
    ).toBeInTheDocument()
    expect(screen.queryByText(/must-not-render/)).not.toBeInTheDocument()
  })

  it("shows zero-match as an explicit warning without widening the selector", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url === "/api/platform/loki-scope-policies") {
        return response({ policies: [policyIdentity] })
      }
      if (url.endsWith("/loki-scope-policies/loki-guanlan-scope/verify")) {
        return response({
          verification: {
            id: "loki-verification-zero",
            policy_id: policyIdentity.id,
            draft_revision: 2,
            resource_revision_id: "resource-revision-loki-global-1",
            status: "PASSED",
            match_count: 0,
            truncated: false,
            zero_match_warning: true,
            result_summary: { match_hash: "0".repeat(64) },
            safe_error_summary: "Loki selector 当前未匹配到日志流",
            verified_at: "2026-08-06T04:02:00Z",
          },
        })
      }
      if (url.endsWith("/loki-scope-policies/loki-guanlan-scope")) {
        return response({ policy: policyDetail })
      }
      if (url === "/api/platform/secrets") return response({ secrets: [] })
      if (url.startsWith("/api/platform/environments")) {
        return response({ environments: [] })
      }
      if (url.startsWith("/api/platform/bases")) return response({ bases: [] })
      if (url.startsWith("/api/platform/workshops")) {
        return response({ workshops: [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderSheet(globalLokiResource())

    fireEvent.click(await screen.findByRole("button", { name: "验证" }))
    expect(await screen.findByText(/zero-match warning/)).toBeInTheDocument()
    expect(screen.getByText(/不会自动放宽前缀或 selector/)).toBeInTheDocument()
    expect(screen.getAllByText("customer=prod-a")).toHaveLength(1)
    expect(screen.getAllByText("base=guanlan")).toHaveLength(1)
  })

  it("keeps Published history immutable and copies it into a new Draft", async () => {
    let copyBody: Record<string, unknown> | undefined
    const immutablePolicy = {
      ...policyIdentity,
      draft: null,
      revisions: [
        {
          id: "loki-scope-policy-revision-1",
          policy_id: policyIdentity.id,
          revision: 1,
          resource_revision_id: "resource-revision-loki-global-1",
          conditions: [
            { key: "customer", value: "prod-a" },
            { key: "base", value: "guanlan" },
          ],
          content_hash: "c".repeat(64),
          verification_id: "loki-verification-1",
          status: "PUBLISHED",
          health_status: "HEALTHY",
          published_at: "2026-08-06T04:00:00Z",
        },
      ],
    }
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url === "/api/platform/loki-scope-policies") {
        return response({ policies: [policyIdentity] })
      }
      if (
        url.endsWith(
          "/loki-scope-policies/loki-guanlan-scope/draft/from-revision"
        )
      ) {
        copyBody = JSON.parse(String(init?.body)) as Record<string, unknown>
        return response({
          draft: {
            policy_id: policyIdentity.id,
            draft_revision: 2,
            resource_revision_id: "resource-revision-loki-global-1",
            conditions: immutablePolicy.revisions[0].conditions,
            content_hash: "d".repeat(64),
            status: "DRAFT",
            updated_at: "2026-08-06T04:05:00Z",
          },
        })
      }
      if (url.endsWith("/loki-scope-policies/loki-guanlan-scope")) {
        return response({ policy: immutablePolicy })
      }
      if (url === "/api/platform/secrets") return response({ secrets: [] })
      if (url.startsWith("/api/platform/environments")) {
        return response({ environments: [] })
      }
      if (url.startsWith("/api/platform/bases")) return response({ bases: [] })
      if (url.startsWith("/api/platform/workshops")) {
        return response({ workshops: [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderSheet(globalLokiResource())

    expect(
      await screen.findByText("不可变 Published Revisions")
    ).toBeInTheDocument()
    expect(screen.getByText("customer=prod-a")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "从 r1 复制新 Draft" }))
    await waitFor(() =>
      expect(copyBody).toEqual({
        source_revision_id: "loki-scope-policy-revision-1",
        expected_policy_revision: 1,
      })
    )
    expect(screen.getByText("不可变 Published Revisions")).toBeInTheDocument()
  })
})
