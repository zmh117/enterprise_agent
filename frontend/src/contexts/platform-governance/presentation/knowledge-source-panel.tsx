import { useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  knowledgeStatus,
  newKnowledgeBindingSchema,
  type KnowledgeCommand,
  type KnowledgeInventory,
} from "@/contexts/platform-governance/domain/knowledge-resource"
import {
  KnowledgeField,
  knowledgeInputClass,
} from "@/contexts/platform-governance/presentation/knowledge-resource-ui"

type Props = {
  data: KnowledgeInventory
  canManage: boolean
  pending: boolean
  execute: (command: KnowledgeCommand) => Promise<boolean>
  confirm: (command: KnowledgeCommand, message: string) => void
}

export function KnowledgeSourcePanel({
  data,
  canManage,
  pending,
  execute,
  confirm,
}: Props) {
  const [source, setSource] = useState("")
  const [instance, setInstance] = useState("")
  const [team, setTeam] = useState("")
  const [attestation, setAttestation] = useState("")
  const [attested, setAttested] = useState(false)
  const [invalid, setInvalid] = useState(false)
  // 打开/选择来源时冻结修订，不在后台刷新后静默接受新版本。
  const [expectedRevision, setExpectedRevision] = useState(0)
  function selectSource(id: string) {
    setSource(id)
    setExpectedRevision(
      Math.max(
        0,
        ...data.bindings
          .filter((b) => b.source_id === id)
          .map((b) => b.revision)
      )
    )
    setAttested(false)
  }
  function create(event: FormEvent) {
    event.preventDefault()
    const parsed = newKnowledgeBindingSchema.safeParse({
      source_id: source,
      instance_code: instance,
      team_id: team,
      attestation_hash: attestation,
      batch_attested: attested,
      expected_revision: expectedRevision,
    })
    setInvalid(!parsed.success)
    if (parsed.success)
      confirm(
        { kind: "source-create", input: parsed.data },
        "建立新来源修订会立即撤销该来源的旧核验，依赖旧绑定的检索将被拒绝。新修订需要重新核验和发布资源。"
      )
  }
  return (
    <details className="rounded-lg border p-4">
      <summary className="cursor-pointer font-medium">来源确认与核验</summary>
      <p className="my-3 text-sm text-muted-foreground">
        人工确认完整批次属于哪个 ONES 实例与原生 Team，再用本人 RUNNING 业务应用
        Job 交叉核验。抽样成功不代替批次来源证明；不要输入
        Token、原始正文或密码。
      </p>
      <div className="space-y-3">
        {data.sources.map((item) => (
          <section key={item.id} className="rounded border p-3">
            <h3 className="font-medium">
              {item.display_name} · {item.code}
            </h3>
            <p className="text-xs text-muted-foreground">
              {item.id} · {knowledgeStatus(item.origin_state)}
            </p>
            {data.bindings
              .filter((b) => b.source_id === item.id)
              .map((binding) => (
                <div key={binding.id} className="mt-3 grid gap-2 border-t pt-3">
                  <p className="text-sm break-all">
                    修订 {binding.revision} · {knowledgeStatus(binding.state)} ·
                    实例 {binding.instance_code} · Team {binding.team_id}
                  </p>
                  <p className="text-xs break-all text-muted-foreground">
                    绑定 ID：{binding.id}
                  </p>
                  {canManage && binding.state !== "REVOKED" && (
                    <div className="flex flex-wrap items-end gap-3">
                      <SourceVerification
                        key={binding.id}
                        bindingId={binding.id}
                        pending={pending}
                        execute={execute}
                      />
                      <Button
                        variant="outline"
                        disabled={pending}
                        onClick={() =>
                          confirm(
                            {
                              kind: "source-revoke",
                              id: binding.id,
                              input: {},
                            },
                            "撤销来源核验后，依赖此绑定的知识检索将立即拒绝。已有文本和向量不会删除。"
                          )
                        }
                      >
                        撤销核验
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            {!data.bindings.some((b) => b.source_id === item.id) && (
              <p className="mt-2 text-sm">尚未绑定可信来源</p>
            )}
          </section>
        ))}
      </div>
      {canManage && (
        <form onSubmit={create} className="mt-5 grid gap-3 rounded border p-4">
          <h3 className="font-medium">新增来源绑定修订</h3>
          <fieldset disabled={pending} className="grid gap-3 sm:grid-cols-2">
            <KnowledgeField label="离线来源">
              <select
                className={knowledgeInputClass}
                value={source}
                onChange={(e) => selectSource(e.target.value)}
                required
              >
                <option value="">请选择来源</option>
                {data.sources
                  .filter((s) => s.source_system === "ones")
                  .map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.display_name} · {s.id}
                    </option>
                  ))}
              </select>
            </KnowledgeField>
            <KnowledgeField label="受信 ONES 实例编码">
              <Input
                value={instance}
                onChange={(e) => setInstance(e.target.value)}
                maxLength={128}
                required
              />
            </KnowledgeField>
            <KnowledgeField label="ONES 原生 Team ID">
              <Input
                value={team}
                onChange={(e) => setTeam(e.target.value)}
                maxLength={128}
                required
              />
            </KnowledgeField>
            <KnowledgeField label="批次来源证明 SHA-256 摘要">
              <Input
                value={attestation}
                onChange={(e) => setAttestation(e.target.value)}
                pattern="[0-9a-f]{64}"
                maxLength={64}
                required
              />
            </KnowledgeField>
          </fieldset>
          <p className="text-xs text-muted-foreground">
            当前选择的来源修订：{expectedRevision}
            。如发生并发冲突，请重新选择来源并核对后提交。
          </p>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={attested}
              onChange={(e) => setAttested(e.target.checked)}
              disabled={pending}
              required
            />
            我已确认完整批次来源，证明原件保留在受限位置
          </label>
          {invalid && (
            <p role="alert" className="text-sm text-destructive">
              请填写合法来源标识、64 位小写摘要并确认批次归属。
            </p>
          )}
          <Button type="submit" disabled={pending || !attested}>
            建立来源绑定
          </Button>
        </form>
      )}
    </details>
  )
}

function SourceVerification({
  bindingId,
  pending,
  execute,
}: {
  bindingId: string
  pending: boolean
  execute: Props["execute"]
}) {
  const [job, setJob] = useState("")
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        void execute({
          kind: "source-verify",
          id: bindingId,
          input: { job_id: job },
        })
      }}
    >
      <KnowledgeField label={`本人 RUNNING Job ID（${bindingId}）`}>
        <Input
          value={job}
          onChange={(e) => setJob(e.target.value)}
          maxLength={128}
          pattern="[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}"
          required
          disabled={pending}
        />
      </KnowledgeField>
      <Button type="submit" variant="outline" disabled={pending}>
        核验来源
      </Button>
    </form>
  )
}
