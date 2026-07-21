import { describe, expect, it } from "vitest";

const presentationSources = import.meta.glob("./contexts/**/presentation/**/*.{ts,tsx}", {
  eager: true,
  import: "default",
  query: "?raw",
}) as Record<string, string>;

const domainSources = import.meta.glob("./contexts/**/domain/**/*.{ts,tsx}", {
  eager: true,
  import: "default",
  query: "?raw",
}) as Record<string, string>;

describe("frontend DDD dependency boundaries", () => {
  it("keeps presentation independent from HTTP transport and infrastructure adapters", () => {
    for (const [path, source] of Object.entries(presentationSources)) {
      expect(source, path).not.toContain("@enterprise-agent/api-client");
      expect(source, path).not.toMatch(/from\s+["'][^"']*\/infrastructure\//);
    }
  });

  it("keeps domain models independent from React and infrastructure", () => {
    for (const [path, source] of Object.entries(domainSources)) {
      expect(source, path).not.toMatch(/from\s+["']react/);
      expect(source, path).not.toContain("@enterprise-agent/api-client");
      expect(source, path).not.toMatch(/from\s+["'][^"']*\/infrastructure\//);
    }
  });
});
