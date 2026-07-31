import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiCapabilityConfigurationPage } from "@/contexts/api-capabilities/presentation/api-capability-configuration-page"
import { assertSafePreview } from "@/contexts/api-capabilities/domain/api-capability"

function response(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  )
}

const authentication = {
  schema_version: 1,
  login: {
    method: "POST",
    relative_path: "/api/project/auth/login",
    email_field: "email",
    password_field: "password",
  },
  extract: {
    token_path: "$.token",
    user_id_path: "$.user.uuid",
    display_name_path: "$.user.name",
    teams_path: "$.teams",
    team_id_field: "uuid",
    team_name_field: "name",
  },
  inject: { header_name: "Authorization", value_prefix: "Bearer " },
}

const connection = {
  id: "connection-1",
  code: "ones-main",
  name: "ONES 主实例",
  provider: "ones",
  status: "enabled",
  revision: 1,
  draft: {
    id: "connection-draft-1",
    draft_revision: 1,
    status: "VERIFIED",
    origin_scheme: "https",
    origin_host: "ones.example.test",
    origin_port: 443,
    allow_insecure_local_http: false,
    connect_timeout_ms: 3000,
    read_timeout_ms: 10000,
    max_response_bytes: 1048576,
    content_hash: "a".repeat(64),
    authentication_profile: {
      id: "profile-draft-1",
      draft_revision: 1,
      status: "VERIFIED",
      config: authentication,
      content_hash: "b".repeat(64),
    },
  },
  published_revisions: [
    {
      id: "connection-revision-1",
      connection_id: "connection-1",
      revision: 1,
      status: "PUBLISHED",
      origin_scheme: "https",
      origin_host: "ones.example.test",
      origin_port: 443,
      allow_insecure_local_http: false,
      connect_timeout_ms: 3000,
      read_timeout_ms: 10000,
      max_response_bytes: 1048576,
      authentication_profile_revision_id: "profile-revision-1",
      authentication,
      content_hash: "c".repeat(64),
      published_at: "2026-07-31T00:00:00Z",
    },
  ],
}

const capability = {
  id: "capability-1",
  identifier: "cap__ones__work_item__search",
  name: "搜索 ONES 工作项",
  status: "enabled",
  revision: 1,
  draft: {
    id: "capability-draft-1",
    draft_revision: 1,
    status: "VERIFIED",
    connection_revision_id: "connection-revision-1",
    authentication_profile_revision_id: "profile-revision-1",
    capability: {
      name: "搜索 ONES 工作项",
      description: "搜索当前用户默认 Team 的 ONES 工作项",
      operation_semantics: "QUERY",
      data_classification: "INTERNAL",
      input_schema: {
        type: "object",
        properties: {
          keyword: { type: "string" },
          issue_type: { type: "string" },
          limit: { type: "integer" },
        },
        required: ["keyword", "issue_type", "limit"],
        additionalProperties: false,
      },
      output_schema: {
        type: "object",
        properties: { items: { type: "array" } },
        required: ["items"],
        additionalProperties: false,
      },
    },
    handler: {
      method: "POST",
      relative_path: "/project/api/project/items/graphql",
      graphql_document: "query SearchWorkItems { workItems { total } }",
    },
    mapping_ast: {
      schema_version: 1,
      request: { op: "object", fields: {} },
      response: { op: "object", fields: {} },
    },
    content_hash: "d".repeat(64),
  },
  releases: [],
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
      <ApiCapabilityConfigurationPage />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("API Capability configuration workbench", () => {
  it("renders five regions and displays only the structured safe preview", async () => {
    let testBody: Record<string, unknown> | undefined
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith("/api/admin/api-connections")) {
        return response({ items: [connection] })
      }
      if (url.endsWith("/api/admin/api-capabilities")) {
        return response({ items: [capability] })
      }
      if (url.endsWith("/capability-1/test") && init?.method === "POST") {
        testBody = JSON.parse(String(init.body))
        return response({
          preview: {
            method: "POST",
            relative_path: "/project/api/project/items/graphql",
            query: {},
            body: {
              variables: {
                keyword: "登录",
                issue_type: "task",
                limit: 10,
                user_id: "ones-user-1",
                team_id: "team-a",
              },
            },
            normalized_output: {
              items: [{ number: 101, name: "登录异常", type: "task" }],
              total: 1,
              truncated: false,
            },
          },
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    renderPage()

    for (const title of [
      "Capability 业务契约",
      "固定 Connection",
      "Authentication Profile",
      "Handler",
      "公开 Schema 与受限 Mapping",
    ]) {
      expect(await screen.findByText(title)).toBeInTheDocument()
    }
    fireEvent.click(screen.getByRole("button", { name: "Test" }))

    expect(await screen.findByText("结构化安全预览")).toBeInTheDocument()
    await waitFor(() =>
      expect(testBody).toMatchObject({
        draft_revision: 1,
        draft_hash: "d".repeat(64),
        agent_input: { keyword: "登录", issue_type: "task", limit: 10 },
      }),
    )
    const page = document.body.textContent?.toLowerCase() ?? ""
    expect(page).not.toContain("secret-token")
    expect(page).not.toContain("raw_response")
    expect(page).toContain("ones-user-1")
    expect(page).toContain("team-a")
  })

  it("rejects a preview structure that contains authentication material", () => {
    expect(() =>
      assertSafePreview({
        method: "POST",
        authorization: "Bearer secret-token",
      }),
    ).toThrow(/禁止字段/)
  })
})
