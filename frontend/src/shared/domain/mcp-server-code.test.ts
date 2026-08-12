import { describe, expect, it } from "vitest"

import { mcpServerCodeSchema } from "@/shared/domain/mcp-server-code"

describe("mcpServerCodeSchema", () => {
  it.each(["tool-mcp", "ones-mcp", "gitlab-mcp", "jira-cloud-mcp"])(
    "accepts governed server code %s without a frontend enumeration",
    (serverCode) => {
      expect(mcpServerCodeSchema.parse(serverCode)).toBe(serverCode)
    }
  )

  it.each([
    "",
    "ONES-MCP",
    "ones_mcp",
    "https://mcp.example.com",
    `m${"c".repeat(120)}`,
  ])("rejects malformed or URL-like server code %s", (serverCode) => {
    expect(mcpServerCodeSchema.safeParse(serverCode).success).toBe(false)
  })
})
