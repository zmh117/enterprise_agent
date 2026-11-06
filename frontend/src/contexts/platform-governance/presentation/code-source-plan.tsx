import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useCodeKnowledgeCommand } from "../application/code-knowledge-query"
import type { CodeSource, CodeKnowledge } from "../domain/code-knowledge"
import {
  KnowledgeError,
  KnowledgeField,
  knowledgeInputClass,
} from "./knowledge-resource-ui"

type Props = {
  source: CodeSource
  data: CodeKnowledge
  canManage: boolean
}

export function CodeSourcePlan(props: Props) {
  return (
    <details className="space-y-4 rounded-lg border p-4">
      <summary className="cursor-pointer font-medium">
        {props.source.display_name} · SVN 与更新计划
      </summary>
      <SourcePlanFields key={props.source.plan.revision ?? 0} {...props} />
    </details>
  )
}

function SourcePlanFields({ source, data, canManage }: Props) {
  const command = useCodeKnowledgeCommand()
  const [application, setApplication] = useState(
    source.plan.application_publication_id ?? ""
  )
  const [account, setAccount] = useState(source.plan.service_account_id ?? "")
  const [enabled, setEnabled] = useState(source.plan.schedule?.enabled ?? false)
  const [demand, setDemand] = useState(Boolean(source.demand_enabled))
  const [time, setTime] = useState(source.plan.schedule?.local_time ?? "02:00")
  const [timezone, setTimezone] = useState(
    source.plan.schedule?.timezone ?? "Asia/Shanghai"
  )
  const [revision, setRevision] = useState("")
  const [site, setSite] = useState("")
  const [snapshot, setSnapshot] = useState("")
  const [notice, setNotice] = useState("")
  const choices = data.builds.filter(
    (build) =>
      build.source_id === source.source_id &&
      ["READY", "ACTIVATED"].includes(build.stage) &&
      data.source_snapshots.some(
        (s) => s.id === build.source_snapshot_id && s.source_kind === "svn"
      )
  )
  const pending = data.demands.filter(
    (item) => item.source_id === source.source_id
  )
  const ready = source.svn_verified && !command.isPending
  const planRevision = source.plan.revision ?? 0
  return (
    <>
      <p className="text-sm text-muted-foreground">
        {source.svn_verified
          ? "SVN 来源已核验"
          : "SVN 未配置：先由部署人员登记来源并核验一个明确版本。"}{" "}
        · 配置版本 {source.config_revision} · 历史账本起点{" "}
        {source.collected_from_revision ?? "未核实"}
      </p>
      {source.collection.baseline_mapping && (
        <p className="text-sm">
          本地基线映射：
          {source.collection.baseline_mapping.state === "VERIFIED"
            ? "同范围源码摘要一致"
            : "未映射，保留独立本地身份"}
        </p>
      )}
      <p className="text-sm">
        采集阶段：{source.collection.state ?? "未启动"}
        {source.collection.target_revision !== undefined
          ? ` · 固定目标 r${source.collection.target_revision}`
          : ""}{" "}
        · 下次计划：
        {source.next_run_at
          ? new Date(source.next_run_at).toLocaleString()
          : "未启用"}
      </p>
      {source.collection.error_code && (
        <p role="alert" className="text-sm text-destructive">
          采集未完成：{source.collection.error_code}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      <KnowledgeError error={command.error} />
      {canManage && (
        <>
          <form
            className="grid gap-3 md:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault()
              void command
                .mutateAsync({
                  action: "plan",
                  id: source.source_id,
                  input: {
                    expected_plan_revision: planRevision,
                    application_publication_id: application.trim(),
                    service_account_id: account.trim(),
                    schedule_enabled: enabled,
                    demand_enabled: demand,
                    local_time: time,
                    timezone,
                  },
                })
                .then(() => setNotice("更新计划已保存。"))
                .catch(() => {})
            }}
          >
            <KnowledgeField label="计划使用的提取应用发布 ID">
              <Input
                value={application}
                onChange={(e) => setApplication(e.target.value)}
              />
            </KnowledgeField>
            <KnowledgeField label="计划使用的服务账号 ID">
              <Input
                value={account}
                onChange={(e) => setAccount(e.target.value)}
              />
            </KnowledgeField>
            <KnowledgeField label="每日执行时间">
              <Input
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
              />
            </KnowledgeField>
            <KnowledgeField label="时区">
              <Input
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
              />
            </KnowledgeField>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              启用每日采集
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={demand}
                onChange={(e) => setDemand(e.target.checked)}
              />
              允许问答触发历史缓存构建
            </label>
            <Button
              type="submit"
              disabled={!ready || !application.trim() || !account.trim()}
            >
              保存更新计划
            </Button>
          </form>
          <form
            className="flex flex-wrap items-end gap-3 border-t pt-4"
            onSubmit={(event) => {
              event.preventDefault()
              void command
                .mutateAsync({
                  action: "version",
                  id: source.source_id,
                  input: { revision: Number(revision) },
                })
                .then(() => setNotice("版本需求已登记，请查看持久进度。"))
                .catch(() => {})
            }}
          >
            <KnowledgeField label="预构建 SVN 版本">
              <Input
                type="number"
                min="0"
                step="1"
                value={revision}
                onChange={(e) => setRevision(e.target.value)}
              />
            </KnowledgeField>
            <Button
              type="submit"
              disabled={!ready || !source.enabled || !/^\d+$/.test(revision)}
            >
              登记精确版本
            </Button>
          </form>
          <form
            className="grid gap-3 border-t pt-4 md:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault()
              void command
                .mutateAsync({
                  action: "site",
                  id: source.source_id,
                  input: {
                    site_id: site.trim(),
                    snapshot_id: snapshot,
                    expected_plan_revision: planRevision,
                  },
                })
                .then(() =>
                  setNotice("现场版本已绑定，后续开发更新不会自动改变此绑定。")
                )
                .catch(() => {})
            }}
          >
            <KnowledgeField label="现场标识">
              <Input value={site} onChange={(e) => setSite(e.target.value)} />
            </KnowledgeField>
            <KnowledgeField label="现场使用的已就绪版本">
              <select
                className={knowledgeInputClass}
                value={snapshot}
                onChange={(e) => setSnapshot(e.target.value)}
              >
                <option value="">选择已核验的现场版本</option>
                {choices.map((build) => (
                  <option key={build.id} value={build.snapshot_id}>
                    r
                    {
                      data.source_snapshots.find(
                        (s) => s.id === build.source_snapshot_id
                      )?.svn_revision
                    }{" "}
                    · {build.snapshot_id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </KnowledgeField>
            <Button
              type="submit"
              disabled={!ready || !site.trim() || !snapshot}
            >
              绑定现场版本
            </Button>
          </form>
          {source.collection.state === "FAILED" && (
            <Button
              variant="outline"
              disabled={command.isPending}
              onClick={() => {
                void command
                  .mutateAsync({ action: "retry_source", id: source.source_id })
                  .catch(() => {})
              }}
            >
              从固定目标恢复采集
            </Button>
          )}
        </>
      )}
      {Object.entries(source.plan.sites ?? {}).map(([key, value]) => (
        <p key={key} className="text-sm break-all">
          现场 {key}：r{value.revision} · {value.snapshot_id}
        </p>
      ))}
      {pending.length > 0 && (
        <div className="space-y-1 border-t pt-3">
          <h4 className="font-medium">历史版本需求</h4>
          {pending.map((item) => (
            <p key={item.id} className="text-sm">
              r{item.revision} ·{" "}
              {(
                {
                  PENDING: "等待构建",
                  BUILDING: "正在构建或核验",
                  READY: "版本可查询",
                  UNAVAILABLE: "构建未完成",
                  CANCELLED: "已取消",
                } as Record<string, string>
              )[item.state] ?? item.state}
            </p>
          ))}
        </div>
      )}
      {data.history_checks
        .filter((item) => item.source_id === source.source_id)
        .map((item) => (
          <p
            key={`${item.document_id}:${item.from_revision}:${item.to_revision}`}
            className="text-sm break-all"
          >
            规则历史 r{item.from_revision} → r{item.to_revision}：已检查{" "}
            {item.checked_count} 个相关版本，{item.unresolved_count} 个未决区间
            · {item.complete ? "区间已核实" : "尚不完整"}
          </p>
        ))}
    </>
  )
}
