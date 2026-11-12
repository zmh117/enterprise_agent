import { checkoutStages } from "./code-checkout-errors"

const operations: Record<string, string> = {
  info: "检查仓库或工作副本信息（info）",
  list: "读取文件清单（list）",
  propget: "检查属性与外部引用（propget）",
  checkout: "创建工作副本（checkout）",
  update: "下载文件或更新版本（update）",
  status: "核验工作副本状态（status）",
  log: "读取提交记录（log）",
  diff: "读取版本差异（diff）",
  blame: "读取行历史（blame）",
  cat: "读取版本文件（cat）",
}

export function CodeSvnFailureDetails({
  operationId,
  diagnostic,
}: {
  operationId: string
  diagnostic?: {
    stage?: string
    stream?: string
    observed_bytes?: number
    limit_bytes?: number
    operation: string
    exit_code: number | null
    svn_error_codes: string[]
  }
}) {
  return (
    <div className="text-xs break-all text-muted-foreground">
      <p>任务 ID：{operationId}</p>
      {diagnostic?.observed_bytes !== undefined && (
        <p>
          已处理输出：{diagnostic.observed_bytes.toLocaleString()} 字节
          {diagnostic.limit_bytes !== undefined &&
            ` · 输出上限：${diagnostic.limit_bytes.toLocaleString()} 字节`}
          （不是检出文件大小）
        </p>
      )}
      {diagnostic && (
        <p>
          失败步骤：
          {checkoutStages[diagnostic.stage ?? ""] ??
            operations[diagnostic.operation] ??
            "未知步骤"}
          {" · "}SVN 错误号：
          {diagnostic.svn_error_codes.join("、") || "未提供"}
          {" · "}退出码：{diagnostic.exit_code ?? "未提供"}
        </p>
      )}
    </div>
  )
}
