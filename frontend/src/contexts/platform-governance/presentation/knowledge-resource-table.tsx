import { Button } from "@/components/ui/button"
import { useKnowledgeContentCatalog } from "@/contexts/platform-governance/application/knowledge-storage-query"
import {
  canPublishKnowledge,
  knowledgeStatus,
  type KnowledgeInventory,
  type KnowledgeResource,
} from "@/contexts/platform-governance/domain/knowledge-resource"
import { KnowledgeError } from "./knowledge-resource-ui"

type TableProps = {
  resources: KnowledgeResource[]
  data: KnowledgeInventory
  canManage: boolean
  pending: boolean
  onOpen: (resource: KnowledgeResource) => void
}

export function KnowledgeResourceTable(props: TableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-left text-sm">
        <caption className="p-3 text-left text-muted-foreground">
          入库、索引和发布是不同状态；发布也不能替代 KB＋本人 ONES 双重授权。
        </caption>
        <thead className="border-b bg-muted/40">
          <tr>
            {["知识资源", "存储", "来源", "索引", "检索发布", "操作"].map(
              (x) => (
                <th key={x} className="p-3 font-medium">
                  {x}
                </th>
              )
            )}
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
        <p className="p-5 text-sm">
          没有匹配的知识资源。已有入库数据不会自动发布。
        </p>
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
}: TableProps & { resource: KnowledgeResource }) {
  const revision = resource.published ?? resource.draft
  const external = revision?.storage?.postgres.mode === "external"
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
        <p>{resource.name}</p>
        <p className="text-xs text-muted-foreground">
          {resource.code} · {knowledgeStatus(resource.status)}
        </p>
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
        ) : (
          sourceNames || "无已收录数据"
        )}
      </td>
      <td className="p-3">
        {revision ? `已绑定 ${revision.index_id}` : "未选择"}
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
      <td className="p-3">
        <Button
          variant="outline"
          disabled={pending}
          onClick={() => onOpen(resource)}
          aria-label={`查看 ${resource.name}`}
        >
          详情与配置
        </Button>
      </td>
    </tr>
  )
}
