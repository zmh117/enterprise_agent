import { useState } from "react"
import { CodeSourcePlan } from "./code-source-plan"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
} from "@/components/ui/alert-dialog"
import {
  KnowledgeError,
  KnowledgeField,
  knowledgeInputClass,
} from "./knowledge-resource-ui"
import {
  useCodeKnowledge,
  useCodeKnowledgeCommand,
  useCodeKnowledgeDetail,
} from "../application/code-knowledge-query"
import {
  codeStage,
  type CodeBuild,
  type CodeDetail,
} from "../domain/code-knowledge"

export function CodeKnowledgePanel({
  canRead,
  canManage,
}: {
  canRead: boolean
  canManage: boolean
}) {
  const query = useCodeKnowledge(canRead)
  const command = useCodeKnowledgeCommand()
  const [sourceSnapshot, setSourceSnapshot] = useState("")
  const [application, setApplication] = useState("")
  const [account, setAccount] = useState("")
  const [selected, setSelected] = useState<string>()
  const [rollback, setRollback] = useState<{
    build: CodeBuild
    current: string
  }>()
  const [notice, setNotice] = useState("")
  const data = query.data
  const snapshot = data?.source_snapshots.find((s) => s.id === sourceSnapshot)
  const build = data?.builds.find((b) => b.id === selected)
  if (!canRead) return null
  async function start() {
    if (!snapshot) return
    try {
      await command.mutateAsync({
        action: "start",
        input: {
          source_id: snapshot.source_id,
          source_snapshot_id: snapshot.id,
          application_publication_id: application.trim(),
          service_account_id: account.trim(),
        },
      })
      setNotice("构建已登记，进度保存在服务器。")
    } catch {
      /* Keep inputs for a safe idempotent retry. */
    }
  }
  return (
    <section
      className="space-y-4 rounded-xl border p-5"
      aria-label="代码业务知识"
    >
      <div>
        <h2 className="text-lg font-semibold">代码业务知识</h2>
        <p className="text-sm text-muted-foreground">
          后端 set_server · 工厂端 EBR · 集团端 JTH。未核实 SVN
          的本地基线会保留版本未知标记。
        </p>
      </div>
      <KnowledgeError error={query.error || command.error} />
      {data?.sources.map((source) => (
        <CodeSourcePlan
          key={source.source_id}
          source={source}
          data={data}
          canManage={canManage}
        />
      ))}
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
      {data?.sources.length === 0 && (
        <p className="text-sm text-muted-foreground">
          尚未登记代码基线。部署人员准入固定源码快照后，可在此启动提取。
        </p>
      )}
      {data?.sources.map((source) => (
        <p key={source.source_id} className="text-sm">
          {source.display_name} · 已采集 SVN：
          {source.collected_revision === null
            ? "未核实"
            : `r${source.collected_revision}`}
          {" · "}开发快照：{source.active_snapshot_id ?? "未激活"}
        </p>
      ))}
      {canManage && Boolean(data?.source_snapshots.length) && (
        <div className="grid gap-3 md:grid-cols-3">
          <KnowledgeField label="已登记源码快照">
            <select
              aria-label="已登记源码快照"
              className={knowledgeInputClass}
              value={sourceSnapshot}
              onChange={(e) => setSourceSnapshot(e.target.value)}
            >
              <option value="">选择待提取的基线</option>
              {data?.source_snapshots
                .filter((s) => !s.retired_at)
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.source_kind === "local_bundle"
                      ? "本地基线（SVN 未知）"
                      : `SVN r${s.svn_revision}`}{" "}
                    · {s.created_at}
                  </option>
                ))}
            </select>
          </KnowledgeField>
          <KnowledgeField label="提取应用发布 ID">
            <Input
              aria-label="提取应用发布 ID"
              value={application}
              onChange={(e) => setApplication(e.target.value)}
            />
          </KnowledgeField>
          <KnowledgeField label="执行服务账号 ID">
            <Input
              aria-label="执行服务账号 ID"
              value={account}
              onChange={(e) => setAccount(e.target.value)}
            />
          </KnowledgeField>
          <Button
            disabled={
              !snapshot ||
              !application.trim() ||
              !account.trim() ||
              command.isPending
            }
            onClick={() => void start()}
          >
            启动基线提取
          </Button>
        </div>
      )}
      {data?.partial && (
        <p className="text-sm">
          此页仅展示最近一批构建，当前计数不代表全部历史。
        </p>
      )}
      {data?.builds.map((item) => (
        <div
          key={item.id}
          className="flex flex-wrap items-center gap-3 rounded border p-3 text-sm"
        >
          <span>{codeStage[item.stage] ?? item.stage}</span>
          {canManage &&
            ["READY", "ACTIVATED"].includes(item.stage) &&
            data.sources.some(
              (s) =>
                s.source_id === item.source_id &&
                s.active_snapshot_id &&
                s.active_snapshot_id !== item.snapshot_id
            ) && (
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  setRollback({
                    build: item,
                    current: data.sources.find(
                      (s) => s.source_id === item.source_id
                    )!.active_snapshot_id!,
                  })
                }
              >
                回滚开发快照
              </Button>
            )}
          <span>
            {item.unit_count
              ? `已校验单元 ${item.validated_units} / ${item.unit_count}`
              : "尚未生成工作单元"}
          </span>
          {item.error_code && (
            <span role="status">原因：{item.error_code}</span>
          )}
          {item.stage === "VALIDATING" &&
            item.validation.activation_blocked && <span>关键依赖尚未核实</span>}
          {canManage && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSelected(item.id)}
            >
              查看候选与进度
            </Button>
          )}
          {canManage && ["FAILED", "INTERRUPTED"].includes(item.stage) && (
            <Button
              variant="outline"
              size="sm"
              disabled={command.isPending}
              onClick={() =>
                void command
                  .mutateAsync({ action: "retry", id: item.id })
                  .catch(() => {})
              }
            >
              重试已停止的构建
            </Button>
          )}
        </div>
      ))}
      {build && canManage && (
        <CandidateReview
          key={build.id}
          build={build}
          onClose={() => setSelected(undefined)}
        />
      )}
      <AlertDialog
        open={Boolean(rollback)}
        onOpenChange={(open) => {
          if (!open) setRollback(undefined)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>回滚开发知识快照</AlertDialogTitle>
            <AlertDialogDescription>
              将最新规则查询指向所选已核验快照。确认前请核对来源和版本。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <KnowledgeError error={command.error} />
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <Button
              disabled={command.isPending}
              onClick={() => {
                if (rollback)
                  void command
                    .mutateAsync({
                      action: "rollback",
                      id: rollback.build.source_id,
                      input: {
                        snapshot_id: rollback.build.snapshot_id,
                        expected_current: rollback.current,
                      },
                    })
                    .then(() => {
                      setRollback(undefined)
                      setNotice("开发快照已回滚。")
                    })
                    .catch(() => {})
              }}
            >
              确认回滚
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}

function CandidateReview({
  build,
  onClose,
}: {
  build: CodeBuild
  onClose: () => void
}) {
  const [after, setAfter] = useState("")
  const [reference, setReference] = useState("")
  const [attested, setAttested] = useState(false)
  const query = useCodeKnowledgeDetail(build.id, after)
  const command = useCodeKnowledgeCommand()
  const page = query.data
  const ready =
    build.stage === "VALIDATING" &&
    build.validation.machine_valid &&
    !build.validation.activation_blocked
  async function review() {
    if (!page) return
    try {
      await command.mutateAsync({
        action: "review",
        id: build.id,
        input: {
          review_reference: reference.trim(),
          processing_hash: build.processing_hash,
          candidate_digest: page.review_digest,
          checked_unit_ids: page.units
            .filter((unit) => !unit.result.replacement_unit_id)
            .map((unit) => unit.id),
        },
      })
      onClose()
    } catch {
      /* Keep independent review details for correction. */
    }
  }
  return (
    <div
      className="space-y-3 rounded border bg-muted/20 p-4"
      aria-label="候选业务核验"
    >
      <div className="flex justify-between">
        <h3 className="font-semibold">候选业务核验</h3>
        <Button variant="ghost" onClick={onClose}>
          关闭
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        核对实际代码或独立业务样本。结构校验通过不代表业务结论正确。
      </p>
      <KnowledgeError error={query.error || command.error} />
      {page?.units.map((unit) => (
        <div className="space-y-1 text-sm" key={unit.id}>
          <p>
            {unit.unit_key} · {unit.state}
            {unit.error_code ? ` · ${unit.error_code}` : ""}
          </p>
          {unit.result.removed_keys?.map((item) => (
            <p key={item.business_key} className="break-all">
              待核验的移除项：{item.business_key} · 证据：
              {item.evidence_ids.join("、")}
            </p>
          ))}
          {unit.result.removal_evidence?.map((e) => (
            <p key={e.id} className="break-all">
              {e.id} · {e.path}:{e.start_line}–{e.end_line} · {e.symbol}
            </p>
          ))}
        </div>
      ))}
      {build.validation.continuity?.missing_keys.map((key) => (
        <p
          key={key}
          role="alert"
          className="text-sm break-all text-destructive"
        >
          旧知识缺失，尚未核实：{key}
        </p>
      ))}
      {page?.records.map((record) => (
        <BusinessRecord key={record.knowledge_id} record={record} />
      ))}
      {page?.relations.map((relation) => (
        <p key={relation.id} className="text-sm break-all">
          {relation.from_key} → {relation.to_key} · {relation.kind} ·{" "}
          {relation.required ? "必要依赖" : "关联"} · 读取方式：
          {relation.reading_mode} · {relation.read_at}
        </p>
      ))}
      {page?.has_more && (
        <Button
          variant="outline"
          onClick={() => {
            setAfter(page.next_cursor!)
            setAttested(false)
          }}
        >
          继续阅读下一页
        </Button>
      )}
      {ready && page && !page.has_more && (
        <div className="space-y-3">
          <KnowledgeField label="独立核验记录编号">
            <Input
              aria-label="独立核验记录编号"
              maxLength={128}
              value={reference}
              onChange={(e) => setReference(e.target.value)}
            />
          </KnowledgeField>
          <label className="flex gap-2 text-sm">
            <input
              type="checkbox"
              checked={attested}
              onChange={(e) => setAttested(e.target.checked)}
            />
            我已独立核验所有工作单元、规则条件及必要依赖，核验依据保存在上述记录中。
          </label>
          <Button
            disabled={!attested || !reference.trim() || command.isPending}
            onClick={() => void review()}
          >
            记录核验通过并继续构建
          </Button>
        </div>
      )}
    </div>
  )
}

const labels: Record<string, string> = {
  role: "业务端",
  states: "来源状态",
  trigger: "触发操作",
  guard: "完整条件",
  check_order: "校验顺序",
  effects: "操作影响",
  outcomes: "执行结果",
  success_boundary: "成功确认点",
  configuration: "配置条件",
  required_runtime_facts: "现场需核验数据",
  unknowns: "未核实事项",
  object_version: "业务对象版本",
  coverage: "覆盖状态",
}
function describe(value: unknown): string {
  if (value === null || value === undefined) return "未提供"
  if (Array.isArray(value))
    return value.length ? value.map(describe).join("\n") : "无记录"
  if (typeof value !== "object") return String(value)
  const row = value as Record<string, unknown>
  return Object.entries(row)
    .filter(([key]) => key !== "evidence_ids")
    .map(([key, item]) => `${key}：${describe(item)}`)
    .join("；")
}
function BusinessRecord({ record }: { record: CodeDetail["records"][number] }) {
  return (
    <article className="space-y-2 rounded border bg-background p-3">
      <h4 className="font-semibold">{record.knowledge.title}</h4>
      <p className="text-sm">{record.knowledge.summary}</p>
      <dl className="grid gap-2 text-sm">
        {Object.entries(labels).map(([field, label]) => (
          <div key={field}>
            <dt className="font-medium">{label}</dt>
            <dd className="break-words whitespace-pre-wrap">
              {describe(record.knowledge[field])}
            </dd>
          </div>
        ))}
      </dl>
      <p className="text-sm font-medium">源码证据位置</p>
      {record.evidence.map((e, index) => (
        <p className="text-xs break-all" key={index}>
          {e.path}:{e.start_line}–{e.end_line} · {e.symbol}
        </p>
      ))}
    </article>
  )
}
