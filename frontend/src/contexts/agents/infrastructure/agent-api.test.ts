import { afterEach, describe, expect, it, vi } from "vitest"

import {
  saveAgentDraft,
  validateAgent,
} from "@/contexts/agents/infrastructure/agent-api"
import { ApiError, apiRequest } from "@/shared/api/api-client"

const config = {
  business_role: "诊断助手",
  business_instructions: "只读分析",
  model_policy: {
    runtime: "claude_agent_sdk",
    model: "claude-sonnet",
    model_connection_revision_id: "model-revision-1",
  },
  execution: { max_turns: 8, timeout_seconds: 120 },
  skills: ["diagnostics"],
  routing: { project_code: "default" },
  channels: { ingress: ["dingtalk"], delivery: ["dingtalk"] },
  mcp_tool_publication_ids: ["tool-publication-1"],
}

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })
  )
}

afterEach(() => {
  vi.restoreAllMocks()
  document.cookie = "enterprise_agent_csrf=; Max-Age=0; path=/"
})

describe("Agent management API", () => {
  it("sends CSRF, expected revision and an operation idempotency key", async () => {
    document.cookie = "enterprise_agent_csrf=csrf-test; path=/"
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => json({ revision: { id: "r2" } }))

    await saveAgentDraft("default-diagnostic-agent", 1, config)

    const [url, init] = fetch.mock.calls[0]
    expect(String(url)).toBe("/api/admin/agents/default-diagnostic-agent/draft")
    const headers = new Headers(init?.headers)
    expect(headers.get("X-CSRF-Token")).toBe("csrf-test")
    expect(headers.get("Idempotency-Key")).toMatch(/^agent-draft:/)
    expect(JSON.parse(String(init?.body))).toEqual({
      expected_revision: 1,
      config,
    })
  })

  it("creates a new idempotency scope per explicit validate action", async () => {
    const keys: string[] = []
    vi.spyOn(globalThis, "fetch").mockImplementation((_url, init) => {
      keys.push(new Headers(init?.headers).get("Idempotency-Key") ?? "")
      return json({ revision: { id: "r1" } })
    })

    await validateAgent("agent-a", "revision-a", 3)
    await validateAgent("agent-a", "revision-a", 3)

    expect(keys[0]).toMatch(/^agent-validate:/)
    expect(keys[1]).toMatch(/^agent-validate:/)
    expect(keys[0]).not.toBe(keys[1])
  })

  it.each([
    [401, "authentication_required"],
    [403, "forbidden"],
    [404, "not_found"],
  ])(
    "maps %s without exposing server existence details",
    async (status, code) => {
      vi.spyOn(globalThis, "fetch").mockImplementation(() =>
        json({ detail: "resource-specific internal detail" }, status)
      )

      const error = await apiRequest("/api/admin/agents/private").catch(
        (value) => value
      )
      expect(error).toBeInstanceOf(ApiError)
      expect(error).toMatchObject({ status, code })
      expect(String((error as ApiError).message)).not.toContain(
        "resource-specific"
      )
    }
  )

  it("maps revision conflicts to an explicit refresh state", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      json(
        {
          detail: {
            code: "revision_conflict",
            message: "Agent 已发生变化，请刷新后重试",
            current_revision: 7,
          },
        },
        409
      )
    )

    const error = await validateAgent("agent-a", "revision-a", 3).catch(
      (value) => value
    )
    expect(error).toMatchObject({
      code: "revision_conflict",
      currentRevision: 7,
    })
  })
})
