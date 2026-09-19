import type { ReactNode } from "react"
import { ApiError } from "@/shared/api/api-client"

export const knowledgeInputClass =
  "h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
export function KnowledgeField({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <label className="grid gap-2 text-sm font-medium">
      {label}
      {children}
    </label>
  )
}
export function KnowledgeError({ error }: { error: unknown }) {
  if (!error) return null
  let message = "知识管理服务暂不可用，请刷新核对状态；系统不会自动重试。"
  if (error instanceof ApiError) {
    const messages: Record<string, string> = {
      knowledge_revision_conflict:
        "配置已被其他操作修改。本地输入已保留，请重新载入最新配置后再保存。",
      knowledge_input_invalid: "知识配置参数无效，请检查输入。",
      knowledge_source_unavailable:
        "本地数据来源或文档身份不完整，请检查导入数据。",
      knowledge_source_changed:
        "本地数据已变化，请检查数据并重新保存、验证和发布。",
      knowledge_verifier_unavailable: "受信 ONES 核验服务尚未配置。",
      knowledge_verification_failed:
        "技术验证失败，请检查本地数据、索引，以及 Embedding/Qdrant 服务。无需核验 ONES 地址或 Team。",
      knowledge_resource_unavailable:
        "资源状态不允许此操作，请检查来源、草稿验证和启停状态。",
      knowledge_resource_conflict: "该知识库已有启用资源，或资源编码已存在。",
      knowledge_index_unavailable: "索引未就绪或与知识库、来源不匹配。",
    }
    message =
      error.status === 401
        ? "登录已失效，请重新登录。"
        : error.status === 403
          ? "当前账号没有此知识管理操作权限。"
          : (messages[error.code] ?? message)
  }
  return (
    <p
      role="alert"
      className="rounded-md border border-destructive/30 p-3 text-sm text-destructive"
    >
      {message}
    </p>
  )
}
