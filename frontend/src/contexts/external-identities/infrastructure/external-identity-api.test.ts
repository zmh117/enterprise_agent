import { afterEach, describe, expect, it, vi } from "vitest"

import {
  beginSelfDingTalkBinding,
  beginSelfOnesBinding,
  changeSelfOnesDefaultTeam,
} from "@/contexts/external-identities/infrastructure/external-identity-api"

function jsonResponse(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      headers: { "Content-Type": "application/json" },
    })
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("本人外部身份 API", () => {
  it("ONES 登录请求不接受目标用户，响应中的未知凭据字段会被剥离", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      jsonResponse({
        challenge: {
          id: "challenge-1",
          provider: "ones",
          external_user_id: "ones-user-1",
          display_name: "ONES User",
          teams: [{ id: "team-1", name: "Team 1" }],
          team_ids: ["team-1"],
          expires_at: "2026-08-08T10:00:00Z",
          status: "PENDING",
          created_at: "2026-08-08T09:55:00Z",
          token: "must-not-reach-ui",
          authorization_header: "Bearer must-not-reach-ui",
        },
      })
    )

    const challenge = await beginSelfOnesBinding({
      email: "user@example.com",
      password: "one-time-password",
    })

    const [, init] = fetch.mock.calls[0]
    expect(JSON.parse(String(init?.body))).toEqual({
      email: "user@example.com",
      password: "one-time-password",
    })
    expect(String(init?.body)).not.toContain("user_id")
    expect(challenge).not.toHaveProperty("token")
    expect(challenge).not.toHaveProperty("authorization_header")
  })

  it("钉钉 Challenge 不从浏览器提交 subject 或目标用户", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      jsonResponse({
        challenge: {
          id: "challenge-2",
          code: "DT-ONE-TIME",
          expires_at: "2026-08-08T10:00:00Z",
          status: "PENDING",
        },
      })
    )

    await beginSelfDingTalkBinding()

    const [, init] = fetch.mock.calls[0]
    expect(init?.method).toBe("POST")
    expect(init?.body).toBeUndefined()
  })

  it("默认 Team 更新携带并发 revision 且不携带目标用户", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      jsonResponse({
        user: { id: "app-user-1", display_name: "User" },
        ones: null,
      })
    )

    await changeSelfOnesDefaultTeam({
      default_team_id: "team-2",
      expected_identity_revision: 7,
    })

    const [, init] = fetch.mock.calls[0]
    expect(JSON.parse(String(init?.body))).toEqual({
      default_team_id: "team-2",
      expected_identity_revision: 7,
    })
    expect(String(init?.body)).not.toContain("user_id")
  })
})
