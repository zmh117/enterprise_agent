import { useQuery } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { knowledgeStorageSchema } from "@/contexts/platform-governance/domain/knowledge-resource"
import type { useKnowledgeStorage } from "@/contexts/platform-governance/application/knowledge-storage-query"
import { listPlatformSecrets } from "@/contexts/platform-governance/infrastructure/platform-governance-api"
import {
  KnowledgeError,
  KnowledgeField,
  knowledgeInputClass,
} from "./knowledge-resource-ui"

export function KnowledgeStorageFields({
  control,
  disabled,
}: {
  control: ReturnType<typeof useKnowledgeStorage>
  disabled: boolean
}) {
  const { storage, setStorage, probe } = control
  const secrets = useQuery({
    queryKey: ["platform-governance", "secrets"],
    queryFn: listPlatformSecrets,
    enabled: !disabled && storage !== null,
    retry: false,
  })
  function reference(
    label: string,
    value: string,
    onChange: (value: string) => void,
    optional = false
  ) {
    return (
      <KnowledgeField label={label}>
        <select
          className={knowledgeInputClass}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required={!optional}
        >
          <option value="">
            {optional ? "不使用 API Key" : "请选择凭据中心的密码"}
          </option>
          {value && !secrets.data?.some((s) => s.secret_ref === value) && (
            <option value={value}>{value}（请核对状态）</option>
          )}
          {secrets.data
            ?.filter((s) => s.status === "enabled" && s.configured)
            .map((s) => (
              <option key={s.code} value={s.secret_ref}>
                {s.code}
              </option>
            ))}
        </select>
      </KnowledgeField>
    )
  }
  return (
    <fieldset
      className="grid gap-3 rounded border p-3"
      disabled={disabled || probe.isPending}
    >
      <legend className="text-sm font-medium">知识内容存储</legend>
      <KnowledgeField label="连接配置方式">
        <select
          className={knowledgeInputClass}
          value={storage ? "custom" : "default"}
          onChange={(e) =>
            setStorage(
              e.target.value === "default"
                ? null
                : {
                    postgres: { mode: "platform" },
                    qdrant: {
                      url: "http://knowledge-qdrant:6333",
                      api_key_ref: "",
                    },
                  }
            )
          }
        >
          <option value="default">使用原部署连接</option>
          <option value="custom">为此知识库配置连接</option>
        </select>
      </KnowledgeField>
      {storage && (
        <>
          <KnowledgeField label="内容 PostgreSQL">
            <select
              className={knowledgeInputClass}
              value={storage.postgres.mode}
              onChange={(e) =>
                setStorage({
                  ...storage,
                  postgres:
                    e.target.value === "platform"
                      ? { mode: "platform" }
                      : {
                          mode: "external",
                          host: "",
                          port: 5432,
                          database: "",
                          username: "",
                          password_ref: "",
                          sslmode: "require",
                        },
                })
              }
            >
              <option value="platform">当前平台实例的 knowledge schema</option>
              <option value="external">
                独立 PostgreSQL 实例的 knowledge schema
              </option>
            </select>
          </KnowledgeField>
          {storage.postgres.mode === "external" &&
            (() => {
              const pg = storage.postgres
              const change = (patch: Partial<typeof pg>) =>
                setStorage({ ...storage, postgres: { ...pg, ...patch } })
              return (
                <>
                  <KnowledgeField label="PostgreSQL 主机">
                    <Input
                      value={pg.host}
                      onChange={(e) => change({ host: e.target.value })}
                      required
                    />
                  </KnowledgeField>
                  <KnowledgeField label="PostgreSQL 端口">
                    <Input
                      type="number"
                      min={1}
                      max={65535}
                      value={pg.port}
                      onChange={(e) => change({ port: Number(e.target.value) })}
                      required
                    />
                  </KnowledgeField>
                  <KnowledgeField label="内容数据库名">
                    <Input
                      value={pg.database}
                      onChange={(e) => change({ database: e.target.value })}
                      required
                    />
                  </KnowledgeField>
                  <KnowledgeField label="内容数据库用户名">
                    <Input
                      value={pg.username}
                      onChange={(e) => change({ username: e.target.value })}
                      required
                    />
                  </KnowledgeField>
                  <p className="text-xs text-muted-foreground">
                    支持管理员、读写或只读账号；当前目录读取和检索仍使用只读事务，不修改知识内容。
                  </p>
                  {reference("PostgreSQL 密码凭据", pg.password_ref, (value) =>
                    change({ password_ref: value })
                  )}
                  <KnowledgeField label="PostgreSQL TLS">
                    <select
                      className={knowledgeInputClass}
                      value={pg.sslmode}
                      onChange={(e) =>
                        change({ sslmode: e.target.value as typeof pg.sslmode })
                      }
                    >
                      <option value="require">要求加密</option>
                      <option value="verify-full">校验证书与主机名</option>
                      <option value="disable">不加密（仅受信内网）</option>
                    </select>
                  </KnowledgeField>
                </>
              )
            })()}
          <KnowledgeField label="Qdrant 地址">
            <Input
              value={storage.qdrant.url}
              onChange={(e) =>
                setStorage({
                  ...storage,
                  qdrant: { ...storage.qdrant, url: e.target.value },
                })
              }
              required
            />
          </KnowledgeField>
          {reference(
            "Qdrant API Key 凭据",
            storage.qdrant.api_key_ref,
            (value) =>
              setStorage({
                ...storage,
                qdrant: { ...storage.qdrant, api_key_ref: value },
              }),
            true
          )}
          <KnowledgeError error={secrets.error} />
          <Button
            type="button"
            variant="outline"
            disabled={!knowledgeStorageSchema.safeParse(storage).success}
            onClick={() => probe.mutate(storage)}
          >
            读取内容库与索引目录
          </Button>
          <KnowledgeError error={probe.error} />
          {control.catalog && (
            <p role="status" className="text-xs">
              内容目录已读取；保存后仍需验证并发布。
            </p>
          )}
        </>
      )}
      <p className="text-xs text-muted-foreground">
        平台授权、发布和审计连接不变。目标库需已具备 knowledge
        内容表及索引；不会自动建库或搬迁数据。密码与 Key
        请先在凭据中心创建，此处只保存引用。
      </p>
    </fieldset>
  )
}
