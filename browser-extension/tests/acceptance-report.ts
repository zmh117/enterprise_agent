import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import os from "node:os";

export interface AcceptanceCheck {
  name: string;
  passed: boolean;
  detail?: unknown;
  tIds?: string[];
  category?: string;
  method?: string;
}
export async function writeAcceptance(
  output: string,
  extension: string,
  browser: string,
  checks: AcceptanceCheck[],
  extra: Record<string, unknown> = {},
) {
  const build = JSON.parse(
    await readFile(resolve(extension, "build-info.json"), "utf8"),
  );
  const assertions = checks.map((c) => {
    const tIds = c.tIds ?? [...new Set(c.name.match(/T\d{2}(?![\d.])/g) ?? [])];
    const category =
      c.category ??
      (tIds.some((t) => ["T41", "T47", "T48", "T49", "T50"].includes(t))
        ? "导出与消费"
        : tIds.some((t) =>
              ["T36", "T37", "T38", "T39", "T42", "T43", "T45"].includes(t),
            )
          ? "权限与故障"
          : tIds.some((t) => +t.slice(1) <= 16 || t === "T21")
            ? "范围"
            : "生命周期与数据");
    return {
      ...c,
      tIds,
      category,
      status: c.passed ? "通过" : "失败",
      method: c.method ?? "独立 profile 真实浏览器自动化",
    };
  });
  const mentionedTIds = [...new Set(assertions.flatMap((c) => c.tIds))].sort();
  const result = {
    at: new Date().toISOString(),
    build,
    browser,
    system: { platform: os.platform(), release: os.release(), arch: os.arch() },
    permissionMode: "复制构建，仅 fixture host 预授权；不计原生权限验收",
    checks: assertions,
    counts: {
      assertions: assertions.length,
      passedAssertions: assertions.filter((c) => c.passed).length,
      mentionedTIds: mentionedTIds.length,
    },
    mentionedTIds,
    coverageMeaning:
      "断言数和涉及 T 编号数均不代表完整 T 验收通过数；完整状态以 docs/acceptance.md 为准。",
    ...extra,
  };
  await writeFile(
    resolve(output, "acceptance.json"),
    JSON.stringify(result, null, 2),
  );
  return result;
}
