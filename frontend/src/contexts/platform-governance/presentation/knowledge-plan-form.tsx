import { useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { KnowledgeError, KnowledgeField } from "./knowledge-resource-ui"
import {
  useKnowledgeOperationsCommand,
  useKnowledgePlanConfiguration,
} from "../application/knowledge-operations-query"

const fields = [
  ["code", "计划编码"],
  ["source_code", "来源编码"],
  ["provider_origin", "ONES 地址"],
  ["team_id", "团队 ID"],
  ["project_ids", "项目 ID（逗号分隔）"],
  ["credential_ref", "凭据中心引用"],
  ["first_date", "首次采集起始日期"],
  ["defect_base", "缺陷知识库编码"],
  ["requirement_base", "需求知识库编码"],
  ["ticket_base", "工单知识库编码"],
  ["defect_types", "缺陷类型 ID（逗号分隔）"],
  ["requirement_types", "需求类型 ID（逗号分隔）"],
  ["ticket_types", "工单类型 ID（逗号分隔）"],
  ["child_type_ids", "子任务类型 ID（逗号分隔）"],
] as const

export function KnowledgePlanForm({
  onClose,
  bindingId,
}: {
  onClose: () => void
  bindingId?: string
}) {
  const command = useKnowledgeOperationsCommand()
  const configuration = useKnowledgePlanConfiguration(bindingId)
  const [edited, setValues] = useState<Record<string, string> | null>(null)
  const stored = configuration.data
  const collector = stored?.configuration.collector
  const initial: Record<string, string> = stored
    ? {
        code: stored.code,
        source_code: stored.source_code,
        provider_origin: collector?.provider_origin ?? "",
        team_id: collector?.team_id ?? "",
        credential_ref: collector?.credential_ref ?? "",
        first_date: collector?.first_date ?? "",
        project_ids: collector?.project_ids.join(",") ?? "",
        child_type_ids: collector?.child_type_ids.join(",") ?? "",
        ...Object.fromEntries(
          ["defect", "requirement", "ticket"].flatMap((kind) => [
            [`${kind}_base`, stored.configuration.base_codes[kind]],
            [`${kind}_types`, collector?.issue_types[kind]?.join(",") ?? ""],
          ])
        ),
      }
    : {}
  const values = edited ?? initial
  const list = (key: string) =>
    (values[key] ?? "")
      .split(/[,，]/)
      .map((x) => x.trim())
      .filter(Boolean)
  async function submit(event: FormEvent) {
    event.preventDefault()
    try {
      await command.mutateAsync({
        action: "configure",
        input: {
          code: values.code,
          source_code: values.source_code,
          expected_revision: stored?.expected_revision ?? 0,
          configuration: {
            base_codes: {
              defect: values.defect_base,
              requirement: values.requirement_base,
              ticket: values.ticket_base,
            },
            resource_ids: stored?.configuration.resource_ids ?? [],
            collector: {
              provider_origin: values.provider_origin,
              team_id: values.team_id,
              project_ids: list("project_ids"),
              credential_ref: values.credential_ref,
              first_date: values.first_date,
              issue_types: {
                defect: list("defect_types"),
                requirement: list("requirement_types"),
                ticket: list("ticket_types"),
              },
              child_type_ids: list("child_type_ids"),
            },
          },
        },
      })
      onClose()
    } catch {
      /* 表单保留，错误由统一组件展示。 */
    }
  }
  if (bindingId && !stored)
    return (
      <div className="p-5">
        <KnowledgeError error={configuration.error} />
        <p>正在读取采集配置…</p>
      </div>
    )
  return (
    <form
      onSubmit={(e) => void submit(e)}
      className="grid gap-4 p-5"
      data-testid="knowledge-plan-form"
    >
      <p className="text-sm text-muted-foreground">
        一条 ONES
        采集计划按类型更新三个知识库。保存后默认关闭，开启自动同步后开始首次采集。首次配置需要
        ONES 管理员提供范围和类型 ID。
        已有运行记录的来源范围保持固定；变更范围需要新建计划。
      </p>
      <KnowledgeError error={command.error} />
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map(([key, label]) => (
          <KnowledgeField key={key} label={label}>
            <Input
              required
              aria-label={label}
              value={values[key] ?? ""}
              type={key === "first_date" ? "date" : "text"}
              placeholder={
                key === "credential_ref"
                  ? "secret://platform/凭据编码"
                  : undefined
              }
              onChange={(e) => setValues({ ...values, [key]: e.target.value })}
              readOnly={Boolean(
                bindingId && ["code", "source_code"].includes(key)
              )}
              disabled={command.isPending}
            />
          </KnowledgeField>
        ))}
      </div>
      <div className="flex gap-2">
        <Button type="submit" disabled={command.isPending}>
          保存采集计划
        </Button>
        <Button type="button" variant="outline" onClick={onClose}>
          关闭
        </Button>
      </div>
    </form>
  )
}
