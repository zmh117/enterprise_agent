import { useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet"
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
} from "@/components/ui/alert-dialog"
import { useAdminCapabilitySummary } from "@/contexts/auth/application/admin-capability-query"
import {
  useKnowledgeCommand,
  useKnowledgeInventory,
} from "@/contexts/platform-governance/application/knowledge-resource-queries"
import {
  canPublishKnowledge,
  knowledgeStatus,
  newKnowledgeResourceSchema,
  type KnowledgeResource,
  type KnowledgeInventory,
  type KnowledgeCommand,
} from "@/contexts/platform-governance/domain/knowledge-resource"
import {
  KnowledgeError,
  KnowledgeField,
  knowledgeInputClass,
} from "@/contexts/platform-governance/presentation/knowledge-resource-ui"

export function KnowledgeResourcesPage() {
  const capabilities = useAdminCapabilitySummary()
  const canRead = Boolean(
    capabilities.data?.capabilities.includes("platform.read")
  )
  const canManage = Boolean(
    capabilities.data?.capabilities.includes("platform.manage")
  )
  const inventory = useKnowledgeInventory(canRead)
  const mutation = useKnowledgeCommand()
  const [editing, setEditing] = useState<KnowledgeResource | null | undefined>()
  const [editorGeneration, setEditorGeneration] = useState(0)
  const [confirmation, setConfirmation] = useState<{
    command: KnowledgeCommand
    message: string
  } | null>(null)
  const [notice, setNotice] = useState("")
  const [search, setSearch] = useState("")
  function confirm(command: KnowledgeCommand, message: string) {
    mutation.reset()
    setNotice("")
    setConfirmation({ command, message })
  }
  async function execute(command: KnowledgeCommand) {
    if (!canManage || mutation.isPending) return false
    setNotice("")
    try {
      const result = await mutation.mutateAsync(command)
      if (result && "knowledge_base_id" in result) setEditing(result)
      setConfirmation(null)
      setNotice("操作完成。配置发布不等于用户已获业务授权。")
      return true
    } catch {
      return false
    }
  }
  async function reloadEditor() {
    const result = await inventory.refetch()
    if (result.isSuccess && result.data && editing) {
      const latest = result.data.resources.find((r) => r.id === editing.id)
      if (latest) {
        setEditing(latest)
        setEditorGeneration((value) => value + 1)
        mutation.reset()
      }
    }
  }
  if (capabilities.isPending)
    return (
      <p role="status" className="p-6">
        正在检查管理权限…
      </p>
    )
  if (capabilities.error)
    return (
      <section className="p-6">
        <KnowledgeError error={capabilities.error} />
        <Button onClick={() => void capabilities.refetch()}>
          重试权限检查
        </Button>
      </section>
    )
  if (!canRead)
    return (
      <p role="alert" className="p-6">
        当前账号没有知识资源查看权限。
      </p>
    )
  const data = inventory.data
  return (
    <div className="mx-auto grid w-full max-w-[1500px] gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">工具资源 · 知识库</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            选择已有知识库与已就绪索引，来源由导入记录提供。
            草稿验证后才可发布；角色仍在各业务应用下选择允许使用的知识库。
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            首版支持 ONES
            工作项；连接由部署固定管理，不配置环境拓扑或数据库密码，不提供上传、OCR
            和自动采集。
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            disabled={inventory.isFetching || mutation.isPending}
            onClick={() => void inventory.refetch()}
          >
            刷新知识资源
          </Button>
          {canManage && (
            <Button
              disabled={!data || inventory.isError || mutation.isPending}
              onClick={() => {
                mutation.reset()
                setEditing(null)
              }}
            >
              新建知识资源
            </Button>
          )}
        </div>
      </header>
      {!canManage && (
        <p className="text-sm text-muted-foreground">
          当前为只读模式；管理按钮不可用，服务端仍独立校验权限。
        </p>
      )}
      <KnowledgeError error={inventory.error} />
      {editing === undefined && !confirmation && (
        <KnowledgeError error={mutation.error} />
      )}
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
      {inventory.isPending && <p role="status">正在加载知识资源…</p>}
      {data && (
        <>
          <KnowledgeField label="筛选知识资源">
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="名称或编码"
            />
          </KnowledgeField>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-left text-sm">
              <caption className="p-3 text-left text-muted-foreground">
                入库、索引和发布是不同状态；发布也不能替代 KB＋本人 ONES
                双重授权。
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
                {data.resources
                  .filter((r) =>
                    `${r.name} ${r.code}`
                      .toLowerCase()
                      .includes(search.toLowerCase())
                  )
                  .map((resource) => {
                    const base = data.bases.find(
                      (b) => b.id === resource.knowledge_base_id
                    )
                    const revision = resource.published ?? resource.draft
                    const index = data.indexes.find(
                      (i) => i.id === revision?.index_id
                    )
                    return (
                      <tr key={resource.id} className="border-b last:border-0">
                        <td className="p-3">
                          <p>{resource.name}</p>
                          <p className="text-xs text-muted-foreground">
                            {resource.code} · {knowledgeStatus(resource.status)}
                          </p>
                        </td>
                        <td className="p-3">
                          {base ? knowledgeStatus(base.state) : "未找到知识库"}
                        </td>
                        <td className="p-3">
                          {base?.source_ids
                            .map(
                              (id) =>
                                data.sources.find((s) => s.id === id)
                                  ?.display_name ?? id
                            )
                            .join("、") || "无已收录数据"}
                        </td>
                        <td className="p-3">
                          {index ? knowledgeStatus(index.state) : "未选择"}
                        </td>
                        <td className="p-3">
                          {resource.published
                            ? `已发布 v${resource.published.revision}`
                            : "未发布"}
                          {resource.draft && (
                            <p className="text-xs">
                              草稿 v{resource.draft.revision} ·{" "}
                              {canPublishKnowledge(resource)
                                ? "验证通过"
                                : "待验证"}
                            </p>
                          )}
                        </td>
                        <td className="p-3">
                          <Button
                            variant="outline"
                            disabled={mutation.isPending}
                            onClick={() => {
                              mutation.reset()
                              setEditing(resource)
                            }}
                            aria-label={`查看 ${resource.name}`}
                          >
                            详情与配置
                          </Button>
                        </td>
                      </tr>
                    )
                  })}
              </tbody>
            </table>
            {data.resources.length === 0 && (
              <p className="p-5 text-sm">
                尚无知识检索资源。已有入库数据不会自动发布。
              </p>
            )}
          </div>
          <Sheet
            open={editing !== undefined}
            onOpenChange={(open) => {
              if (!open && !mutation.isPending) setEditing(undefined)
            }}
          >
            <SheetContent className="overflow-y-auto sm:max-w-xl">
              <SheetHeader>
                <SheetTitle>
                  {editing ? "知识资源详情与草稿" : "新建知识资源"}
                </SheetTitle>
                <SheetDescription>
                  当前存储与向量身份保持不变。只保存明确选择，不自动发布或授权。
                </SheetDescription>
              </SheetHeader>
              <div className="grid gap-4 px-4 pb-6">
                <KnowledgeError error={mutation.error} />
                {editing ? (
                  <KnowledgeResourceEditor
                    key={`${editing.id}:${editing.revision}:${editorGeneration}`}
                    resource={editing}
                    data={data}
                    canManage={canManage}
                    pending={mutation.isPending}
                    execute={execute}
                    confirm={confirm}
                    reload={reloadEditor}
                  />
                ) : (
                  canManage && (
                    <CreateKnowledgeResource
                      data={data}
                      pending={mutation.isPending}
                      execute={execute}
                    />
                  )
                )}
              </div>
            </SheetContent>
          </Sheet>
        </>
      )}
      <AlertDialog
        open={confirmation !== null}
        onOpenChange={(open) => {
          if (!open && !mutation.isPending) setConfirmation(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认知识资源操作</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmation?.message}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <KnowledgeError error={mutation.error} />
          <AlertDialogFooter>
            <AlertDialogCancel disabled={mutation.isPending}>
              取消
            </AlertDialogCancel>
            <Button
              disabled={mutation.isPending}
              onClick={() => {
                if (confirmation) void execute(confirmation.command)
              }}
            >
              确认操作
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

type EditorProps = {
  resource: KnowledgeResource
  data: KnowledgeInventory
  canManage: boolean
  pending: boolean
  execute: (command: KnowledgeCommand) => Promise<boolean>
  confirm: (command: KnowledgeCommand, message: string) => void
  reload: () => Promise<void>
}
function KnowledgeResourceEditor({
  resource,
  data,
  canManage,
  pending,
  execute,
  confirm,
  reload,
}: EditorProps) {
  const initial = resource.draft ?? resource.published
  const sourceIds =
    data.bases.find((b) => b.id === resource.knowledge_base_id)?.source_ids ??
    []
  const [index, setIndex] = useState(initial?.index_id ?? "")
  const writable = canManage && resource.status !== "archived"
  const indexes = data.indexes.filter(
    (i) =>
      i.knowledge_base_id === resource.knowledge_base_id && i.state === "READY"
  )
  const selectedReady = indexes.some((i) => i.id === index)
  const input = { expected_revision: resource.revision }
  return (
    <>
      <dl className="grid gap-2 text-sm break-all">
        <dt>资源</dt>
        <dd>
          {resource.name} · {resource.code}
        </dd>
        <dt>知识库 ID</dt>
        <dd>{resource.knowledge_base_id}</dd>
        <dt>配置修订 / 身份状态</dt>
        <dd>
          {resource.revision} / {knowledgeStatus(resource.status)}
        </dd>
        <dt>当前发布版本</dt>
        <dd>
          {resource.published
            ? `v${resource.published.revision} · 索引 ${resource.published.index_id}`
            : "尚未发布"}
        </dd>
      </dl>
      {initial?.binding_id && (
        <p role="status" className="text-sm">
          此版本使用旧来源确认规则，请重新保存草稿、验证并发布；历史记录保留。
        </p>
      )}
      <Button
        variant="outline"
        disabled={pending}
        onClick={() => void reload()}
      >
        重新载入最新配置（替换本地输入）
      </Button>
      <form
        className="grid gap-3 rounded border p-4"
        onSubmit={(event) => {
          event.preventDefault()
          if (selectedReady)
            void execute({
              kind: "draft",
              id: resource.id,
              input: { ...input, index_id: index },
            })
        }}
      >
        <h3 className="font-medium">草稿配置</h3>
        <fieldset disabled={!writable || pending} className="grid gap-3">
          <div
            className="grid gap-2 text-sm"
            role="group"
            aria-label="数据来源（只读）"
          >
            <p className="font-medium">数据来源（由导入记录提供）</p>
            <p>
              {sourceIds
                .map(
                  (id) =>
                    data.sources.find((s) => s.id === id)?.display_name ?? id
                )
                .join("、") || "无已收录数据"}
            </p>
            <p>
              无需确认 ONES 地址或 Team。实际检索仍使用当前用户的 ONES
              身份检查工作项可读权限。
            </p>
          </div>
          <KnowledgeField label="已就绪向量索引">
            <select
              required
              className={knowledgeInputClass}
              value={index}
              onChange={(e) => setIndex(e.target.value)}
            >
              <option value="">请选择 READY 索引</option>
              {index && !indexes.some((i) => i.id === index) && (
                <option value={index}>当前索引不可用 · {index}</option>
              )}
              {indexes.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.code} · {i.id}
                </option>
              ))}
            </select>
          </KnowledgeField>
          <p className="text-xs text-muted-foreground">
            服务端核对本地数据与索引兼容性，验证时检查 Embedding 和 Qdrant
            服务。修改草稿会使旧验证失效，不改变已发布版本。
          </p>
          {writable && (
            <Button type="submit" disabled={!selectedReady}>
              保存新草稿
            </Button>
          )}
        </fieldset>
      </form>
      {writable && (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            disabled={
              pending || !resource.draft || Boolean(resource.draft.binding_id)
            }
            onClick={() =>
              void execute({ kind: "verify", id: resource.id, input })
            }
          >
            验证草稿
          </Button>
          <Button
            disabled={pending || !canPublishKnowledge(resource)}
            onClick={() =>
              confirm(
                { kind: "publish", id: resource.id, input },
                "发布当前已验证草稿；后续检索使用新版本，仍需应用工具和知识库授权。"
              )
            }
          >
            发布知识资源
          </Button>
          <Button
            variant="outline"
            disabled={pending}
            onClick={() =>
              confirm(
                {
                  kind: "status",
                  id: resource.id,
                  input: {
                    ...input,
                    status:
                      resource.status === "enabled" ? "disabled" : "enabled",
                  },
                },
                resource.status === "enabled"
                  ? "停用后知识检索将被拒绝；不删除已有文本或向量。"
                  : "恢复资源身份；是否可检索仍取决于来源、索引、发布和当前权限。"
              )
            }
          >
            {resource.status === "enabled" ? "停用资源" : "恢复资源"}
          </Button>
          <Button
            variant="outline"
            disabled={pending}
            onClick={() =>
              confirm(
                {
                  kind: "status",
                  id: resource.id,
                  input: { ...input, status: "archived" },
                },
                "归档不可恢复为启用；不删除原始数据或向量。请确认不再使用此资源。"
              )
            }
          >
            归档资源
          </Button>
        </div>
      )}
    </>
  )
}

function CreateKnowledgeResource({
  data,
  pending,
  execute,
}: {
  data: KnowledgeInventory
  pending: boolean
  execute: EditorProps["execute"]
}) {
  const [base, setBase] = useState("")
  const [code, setCode] = useState("")
  const [name, setName] = useState("")
  const [invalid, setInvalid] = useState(false)
  function submit(event: FormEvent) {
    event.preventDefault()
    const result = newKnowledgeResourceSchema.safeParse({
      knowledge_base_id: base,
      code,
      name,
    })
    setInvalid(!result.success)
    if (result.success) void execute({ kind: "create", input: result.data })
  }
  return (
    <form onSubmit={submit} className="grid gap-4">
      <fieldset disabled={pending} className="grid gap-4">
        <KnowledgeField label="已有知识库">
          <select
            required
            className={knowledgeInputClass}
            value={base}
            onChange={(e) => setBase(e.target.value)}
          >
            <option value="">请选择已入库知识库</option>
            {data.bases
              .filter((b) => b.state === "storage_only")
              .map((b) => (
                <option
                  key={b.id}
                  value={b.id}
                  disabled={data.resources.some(
                    (r) =>
                      r.knowledge_base_id === b.id && r.status === "enabled"
                  )}
                >
                  {b.display_name} · {b.id}
                  {data.resources.some(
                    (r) =>
                      r.knowledge_base_id === b.id && r.status === "enabled"
                  )
                    ? "（已有启用资源）"
                    : ""}
                </option>
              ))}
          </select>
        </KnowledgeField>
        <KnowledgeField label="资源编码">
          <Input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            maxLength={128}
            required
          />
        </KnowledgeField>
        <KnowledgeField label="管理名称">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={120}
            required
          />
        </KnowledgeField>
        {invalid && (
          <p role="alert" className="text-sm text-destructive">
            请填写合法编码、名称并选择知识库。
          </p>
        )}
        <Button type="submit">创建资源身份</Button>
      </fieldset>
    </form>
  )
}
