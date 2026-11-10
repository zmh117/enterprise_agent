import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { listEnvironments } from "../infrastructure/platform-governance-api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  KnowledgeField,
  KnowledgeError,
  knowledgeInputClass,
} from "./knowledge-resource-ui"
import { CodeCheckoutPanel } from "./code-checkout-panel"
import { CodeIndexStatus } from "./code-index-status"
import { useCodeCheckouts } from "../application/code-checkout-query"
import {
  canPublishKnowledge,
  type KnowledgeCommand,
  type KnowledgeResource,
} from "../domain/knowledge-resource"

type Execute = (command: KnowledgeCommand) => Promise<boolean>
export function CreateCodeResource({
  pending,
  execute,
}: {
  pending: boolean
  execute: Execute
}) {
  const [code, setCode] = useState("")
  const [name, setName] = useState("")
  return (
    <form
      className="grid gap-3"
      onSubmit={(event) => {
        event.preventDefault()
        void execute({ kind: "create-code", input: { code, name } })
      }}
    >
      <p className="text-sm text-muted-foreground">
        先创建空代码知识库，再配置 SVN 与检出目录。回答按 SVN
        版本保存，后续问题可检索复用。
      </p>
      <KnowledgeField label="知识库名称">
        <Input
          required
          maxLength={120}
          value={name}
          onChange={(event) => setName(event.target.value)}
          disabled={pending}
          data-testid="code-kb-name"
        />
      </KnowledgeField>
      <KnowledgeField label="知识库编码">
        <Input
          required
          pattern="[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}"
          value={code}
          onChange={(event) => setCode(event.target.value)}
          disabled={pending}
          data-testid="code-kb-code"
        />
      </KnowledgeField>
      <p className="text-sm">
        PostgreSQL：平台内容库 · Qdrant：现有受管服务，每个代码库使用独立集合。
      </p>
      <Button disabled={pending || !name.trim() || !code} type="submit">
        创建代码知识库
      </Button>
    </form>
  )
}

export function CodeResourceEditor({
  resource,
  canManage,
  pending,
  execute,
  reload,
}: {
  resource: KnowledgeResource
  canManage: boolean
  pending: boolean
  execute: Execute
  reload: () => Promise<void>
}) {
  const initial = resource.draft ?? resource.published
  const config = initial?.code_configuration
  const environments = useQuery({
    queryKey: ["platform-governance", "environments"],
    queryFn: listEnvironments,
    enabled: canManage,
  })
  const [environmentIds, setEnvironmentIds] = useState<string[]>(
    config?.environment_ids ?? []
  )
  const checkouts = useCodeCheckouts(resource.id, canManage)
  const [selected, setSelected] = useState(config?.checkout_id ?? "")
  const [paths, setPaths] = useState(
    config?.allowed_paths_json.map((path) => path || "/").join("\n") ?? ""
  )
  const selectedCheckout = checkouts.data?.checkouts.find(
    (item) => item.id === selected
  )
  const ready =
    selectedCheckout?.state === "ready" &&
    !selectedCheckout.writer_operation_id &&
    Boolean(selectedCheckout.connection)
  const writable = canManage && resource.status !== "archived"
  const input = { expected_revision: resource.revision }
  return (
    <div className="grid gap-4" data-testid="code-resource-editor">
      <div className="text-sm">
        <strong>{resource.name}</strong> · 代码知识库
        <p>
          {resource.published
            ? `已发布 v${resource.published.revision}`
            : "尚未发布"}{" "}
          · 配置修订 {resource.revision}
        </p>
      </div>
      <p className="text-sm">
        用户提问须提供 SVN
        数字版本。先检索相同版本；最近的更高版本仅作线索，需核验目标版本代码后回答。
      </p>
      <Button
        variant="outline"
        disabled={pending}
        onClick={() => void reload()}
      >
        重新载入最新配置（替换本地输入）
      </Button>
      <KnowledgeError error={checkouts.error} />
      {writable && resource.draft && (
        <CodeCheckoutPanel resourceId={resource.id} />
      )}
      {writable && !resource.draft && (
        <p className="text-sm">
          保存源码配置为新草稿后，可浏览 SVN 或新增检出。
        </p>
      )}
      <form
        className="grid gap-3 rounded border p-4"
        onSubmit={(event) => {
          event.preventDefault()
          if (!ready) return
          void execute({
            kind: "code-draft",
            id: resource.id,
            input: {
              ...input,
              checkout_id: selected,
              environment_ids: environmentIds,
              allowed_paths: paths
                .split("\n")
                .map((path) => path.trim())
                .filter(Boolean)
                .map((path) => (path === "/" ? "" : path)),
              ...(initial?.index_id &&
              selectedCheckout?.source_id === config?.source_id
                ? { index_id: initial.index_id }
                : {}),
            },
          })
        }}
      >
        <h3 className="font-medium">源码与目录绑定</h3>
        <fieldset disabled={!writable || pending} className="grid gap-3">
          <KnowledgeField label="已完成的检出目录">
            <select
              className={knowledgeInputClass}
              value={selected}
              onChange={(event) => {
                const next = checkouts.data?.checkouts.find(
                  (item) => item.id === event.target.value
                )
                setSelected(event.target.value)
                setPaths(
                  next?.selected_paths.map((path) => path || "/").join("\n") ??
                    ""
                )
              }}
              data-testid="code-kb-checkout"
            >
              <option value="">请选择检出目录</option>
              {checkouts.data?.checkouts.map((item) => (
                <option
                  key={item.id}
                  value={item.id}
                  disabled={
                    item.state !== "ready" || Boolean(item.writer_operation_id)
                  }
                >
                  {item.relative_dir} · SVN r
                  {item.verified_revision ?? "未核实"} · {item.readers}{" "}
                  个读取任务{item.writer_operation_id ? " · 更新中" : ""}
                </option>
              ))}
            </select>
          </KnowledgeField>
          {selectedCheckout?.connection ? (
            <div
              className="space-y-2 text-sm"
              data-testid="code-kb-checkout-connection"
            >
              <dl className="grid gap-1">
                <dt className="font-medium">关联的 SVN 地址</dt>
                <dd className="break-all">{selectedCheckout.connection.url}</dd>
                <dt className="font-medium">认证方式</dt>
                <dd>
                  {selectedCheckout.connection.kind === "account"
                    ? "用户名密码（已保存）"
                    : selectedCheckout.connection.kind === "anonymous"
                      ? "无需认证"
                      : "部署配置"}
                </dd>
              </dl>
              <p className="text-muted-foreground">
                自动使用该目录检出时的连接。需要更换连接时，在上方配置并检出后选择新目录。
              </p>
            </div>
          ) : selectedCheckout ? (
            <p role="alert" className="text-sm text-destructive">
              该目录的原始 SVN 连接不可用，请在当前知识库重新检出后再绑定。
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">
              选择检出目录后，自动关联其 SVN 地址和认证方式。
            </p>
          )}
          <fieldset className="space-y-2" aria-label="关联环境">
            <legend className="font-medium">关联环境（可多选）</legend>
            <p className="text-sm text-muted-foreground">
              复用工具资源的环境作为项目归属，同一代码知识库可供多个环境使用。
            </p>
            <KnowledgeError error={environments.error} />
            {environments.data?.map((environment) => (
              <label key={environment.id} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={environmentIds.includes(environment.id)}
                  data-testid={`code-kb-environment-${environment.code}`}
                  onChange={(event) =>
                    setEnvironmentIds((ids) =>
                      event.target.checked
                        ? [...ids, environment.id]
                        : ids.filter((id) => id !== environment.id)
                    )
                  }
                />
                {environment.display_name || environment.code} ·{" "}
                {environment.code}
              </label>
            ))}
            {environments.data?.length === 0 && (
              <p className="text-sm">请先在工具资源中创建环境。</p>
            )}
          </fieldset>
          <KnowledgeField label="允许分析的路径（每行一个，/ 表示整个仓库）">
            <textarea
              className={`${knowledgeInputClass} h-auto min-h-24`}
              rows={4}
              value={paths}
              onChange={(event) => setPaths(event.target.value)}
              data-testid="code-kb-paths"
            />
          </KnowledgeField>
          {writable && (
            <Button type="submit" disabled={!ready || !paths.trim()}>
              保存源码配置
            </Button>
          )}
        </fieldset>
      </form>
      <section
        className="grid gap-2 rounded border p-4"
        aria-label="代码知识存储与索引"
      >
        <h3 className="font-medium">存储与增量索引</h3>
        <p className="text-sm">PostgreSQL：平台内容库</p>
        <p className="text-sm">Qdrant：现有受管服务 · 独立代码答案集合</p>
        <p className="text-sm">
          分块：保留业务结论、条件和 SVN 版本。Embedding 与重排复用现有服务。
        </p>
        <p className="text-sm">
          {initial?.index_id
            ? `索引已初始化：${initial.index_id}`
            : "索引尚未初始化"}
        </p>
        <p className="text-sm text-muted-foreground">
          每次有效问答记录到
          PostgreSQL；新的受支持答案增量分块与编码。重复命中只增加问答记录。
        </p>
        {writable && (
          <Button
            variant="outline"
            disabled={
              pending || !resource.draft?.code_configuration?.checkout_id
            }
            onClick={() =>
              void execute({ kind: "initialize-index", id: resource.id, input })
            }
          >
            初始化代码索引
          </Button>
        )}
        {canManage && <CodeIndexStatus resourceId={resource.id} />}
      </section>
      {writable && (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            disabled={pending || !resource.draft?.index_id}
            onClick={() =>
              void execute({ kind: "verify", id: resource.id, input })
            }
          >
            验证草稿
          </Button>
          <Button
            disabled={pending || !canPublishKnowledge(resource)}
            onClick={() =>
              void execute({ kind: "publish", id: resource.id, input })
            }
          >
            发布代码知识库
          </Button>
          <Button
            variant="outline"
            disabled={pending}
            onClick={() =>
              void execute({
                kind: "status",
                id: resource.id,
                input: {
                  ...input,
                  status:
                    resource.status === "enabled" ? "disabled" : "enabled",
                },
              })
            }
          >
            {resource.status === "enabled" ? "停用资源" : "恢复资源"}
          </Button>
        </div>
      )}
    </div>
  )
}
