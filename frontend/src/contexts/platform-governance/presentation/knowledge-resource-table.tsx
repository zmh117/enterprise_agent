import { Button } from "@/components/ui/button"
import { useKnowledgeContentCatalog } from "@/contexts/platform-governance/application/knowledge-storage-query"
import {
  canPublishKnowledge,
  knowledgeStatus,
  knowledgeListStatus,
  type KnowledgeInventory,
  type KnowledgeResource,
} from "@/contexts/platform-governance/domain/knowledge-resource"
import { KnowledgeError } from "./knowledge-resource-ui"
import type { KnowledgePlan } from "../domain/knowledge-operations"

type TableProps = {
  resources: KnowledgeResource[]
  data: KnowledgeInventory
  canManage: boolean
  pending: boolean
  onOpen: (resource: KnowledgeResource) => void
  plans?: KnowledgePlan[]
}

export function KnowledgeResourceTable(props: TableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] text-left text-sm">
        <caption className="sr-only">知识资源</caption>
        <thead className="border-b bg-muted/40">
          <tr>
            {[
              "知识资源",
              "检索发布",
              "存储",
              "来源",
              "SVN 检出目录",
              "索引",
              "同步处理",
            ].map((x) => (
              <th key={x} className="p-3 font-medium">
                {x}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {props.resources.map((resource) => (
            <KnowledgeResourceRow
              key={resource.id}
              {...props}
              resource={resource}
            />
          ))}
        </tbody>
      </table>
      {props.resources.length === 0 && (
        <p className="p-5 text-sm">没有匹配的知识资源。</p>
      )}
    </div>
  )
}

function KnowledgeResourceRow({
  resource,
  data,
  canManage,
  pending,
  onOpen,
  plans,
}: TableProps & { resource: KnowledgeResource }) {
  const revision = resource.published ?? resource.draft
  const external = revision?.storage?.postgres.mode === "external"
  const plan = !external
    ? plans?.find((p) =>
        p.bases.some((b) => b.knowledge_base_id === resource.knowledge_base_id)
      )
    : undefined
  const metrics = plan?.bases.find(
    (b) => b.knowledge_base_id === resource.knowledge_base_id
  )?.metrics
  const catalog = useKnowledgeContentCatalog(
    external ? revision.storage! : null,
    canManage
  )
  // 自定义内容连接只采用目标目录；同 UUID 的平台来源不能作为回退。
  const content = external ? catalog.data : data
  const base = content?.bases.find((b) => b.id === resource.knowledge_base_id)
  const sourceNames = base?.source_ids
    .map(
      (id) =>
        content?.sources.find((s) => s.id === id)?.display_name ||
        `来源名称缺失（${id}）`
    )
    .join("、")
  return (
    <tr className="border-b last:border-0">
      <td className="p-3">
        <button
          type="button"
          className="max-w-52 truncate text-left font-medium hover:underline"
          disabled={pending}
          onClick={() => onOpen(resource)}
          aria-label={`查看 ${resource.name}`}
        >
          {resource.name}
        </button>
        <p className="text-xs text-muted-foreground">
          {resource.kind === "code" ? "代码知识库" : "ONES 知识库"} ·{" "}
          {resource.code} · {knowledgeStatus(knowledgeListStatus(resource))}
        </p>
      </td>
      <td className="p-3">
        {resource.published
          ? `${resource.status === "archived" ? "历史发布" : "已发布"} v${resource.published.revision}`
          : "未发布"}
        {resource.draft && (
          <p className="text-xs">
            草稿 v{resource.draft.revision} ·{" "}
            {canPublishKnowledge(resource) ? "验证通过" : "待验证"}
          </p>
        )}
      </td>
      <td className="p-3">{external ? "自定义内容连接" : "平台内容库"}</td>
      <td className="p-3">
        {external && !canManage ? (
          "需管理权限读取来源"
        ) : external && catalog.isError ? (
          <div className="grid gap-2">
            <p>来源读取失败</p>
            <KnowledgeError error={catalog.error} />
            <Button
              variant="outline"
              disabled={catalog.isFetching}
              aria-label={`重试 ${resource.name} 来源`}
              onClick={() => void catalog.refetch()}
            >
              重试读取来源
            </Button>
          </div>
        ) : external && catalog.isPending ? (
          "正在读取来源…"
        ) : !base ? (
          "未找到知识库"
        ) : resource.kind === "code" && resource.status === "archived" ? (
          sourceNames ||
          (revision?.code_configuration?.source_id
            ? "历史 SVN 来源"
            : "未配置 SVN 来源")
        ) : (
          sourceNames ||
          (resource.kind === "code"
            ? revision?.code_configuration?.source_id
              ? "SVN 来源已绑定"
              : "待绑定 SVN 来源"
            : "无已收录数据")
        )}
      </td>
      <td className="p-3">
        {resource.kind === "code"
          ? (revision?.checkout_relative_dir ?? "未绑定")
          : "—"}
        {resource.kind === "code" &&
          resource.status === "archived" &&
          (revision?.checkout_relative_dir ||
            resource.draft?.checkout_relative_dir) && (
            <p className="text-xs text-muted-foreground">
              历史目录 · 已解除绑定
            </p>
          )}
        {resource.kind === "code" &&
          resource.published &&
          resource.draft &&
          resource.draft.checkout_relative_dir !==
            revision?.checkout_relative_dir && (
            <p className="text-xs text-muted-foreground">
              草稿目录：{resource.draft.checkout_relative_dir ?? "未绑定"}
            </p>
          )}
      </td>
      <td className="p-3">
        {revision?.index_id
          ? `已绑定 ${revision.index_id}`
          : "未初始化 / 未选择"}
      </td>
      <td className="p-3">
        {resource.kind === "code" ? (
          "问答后增量索引"
        ) : plan ? (
          <>
            <a className="underline" href={`#knowledge-plan-${plan.id}`}>
              {plan.code}
            </a>
            {metrics ? (
              <p className="mt-1 text-xs">
                {metrics.total === 0
                  ? "本轮无需处理"
                  : `新增 ${metrics.created} · 修订 ${metrics.revised} · 完成 ${metrics.completed}/${metrics.total} · 失败 ${metrics.failed}`}
              </p>
            ) : (
              <p className="text-xs">尚未采集</p>
            )}
          </>
        ) : external ? (
          "自定义连接，需核实受管目标"
        ) : (
          "未关联采集计划"
        )}
      </td>
    </tr>
  )
}
