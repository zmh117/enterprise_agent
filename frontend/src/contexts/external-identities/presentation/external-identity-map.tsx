import {
  ArrowRightIcon,
  CheckCircle2Icon,
  CircleAlertIcon,
  Link2Icon,
  ShieldAlertIcon,
  UserRoundIcon,
  UsersRoundIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import {
  groupIdentityExamples,
  identityFixture,
  identityStatuses,
  managementArchitecture,
} from "@/mocks/dashboard"
import { DisabledAction } from "@/shared/presentation/disabled-action"
import { SectionHeading } from "@/shared/presentation/section-heading"

const statusStyles: Record<string, string> = {
  已验证:
    "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300",
  待关联:
    "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
}

export function ExternalIdentityMap() {
  return (
    <section aria-labelledby="identity-map-title" className="space-y-4">
      <SectionHeading
        eyebrow="Identity & governance"
        title="一个内部用户，多个外部系统身份"
        description="钉钉、ONES 与未来系统账号只映射到统一内部人员；身份映射负责找到可信主体，不直接授予平台或外部系统权限。"
        prototype
        action={
          <DisabledAction variant="outline" size="sm">
            关联身份 · 规划中
          </DisabledAction>
        }
      />

      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.4fr]">
        <Card className="shadow-none">
          <CardHeader className="border-b">
            <div className="flex items-center gap-2">
              <UserRoundIcon
                className="size-4 text-indigo-600"
                aria-hidden="true"
              />
              <h3 className="font-semibold">统一内部人员</h3>
              <Badge className="ml-auto bg-indigo-50 text-indigo-700 hover:bg-indigo-50 dark:bg-indigo-950 dark:text-indigo-300">
                唯一授权主体
              </Badge>
            </div>
          </CardHeader>
          <CardContent>
            <div className="rounded-xl border border-indigo-200 bg-indigo-50/50 p-4 dark:border-indigo-900 dark:bg-indigo-950/30">
              <div className="flex items-center gap-3">
                <span className="flex size-11 items-center justify-center rounded-full bg-indigo-600 font-semibold text-white">
                  示
                </span>
                <div>
                  <h4 className="font-semibold">
                    {identityFixture.internalUser.name}
                  </h4>
                  <p className="text-xs text-muted-foreground">
                    {identityFixture.internalUser.id}
                  </p>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {identityFixture.internalUser.roles.map((role) => (
                  <Badge key={role} variant="outline">
                    {role}
                  </Badge>
                ))}
              </div>
            </div>
            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50/60 p-3 dark:border-amber-900 dark:bg-amber-950/30">
              <div className="flex items-center gap-2 font-medium text-amber-900 dark:text-amber-200">
                <ShieldAlertIcon className="size-4" aria-hidden="true" />
                身份关联不等于授权
              </div>
              <p className="mt-1.5 text-xs leading-5 text-amber-900/75 dark:text-amber-200/75">
                内部角色、应用权限、Capability、API 平台数据权限以及 ONES
                原生权限仍分别校验。
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-none">
          <CardHeader className="border-b">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h3 className="font-semibold">外部身份映射</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  Provider、连接、外部主体、用途与验证状态独立记录
                </p>
              </div>
              <Badge variant="outline">1 : N</Badge>
            </div>
          </CardHeader>
          <CardContent className="grid gap-3 lg:grid-cols-3">
            {identityFixture.identities.map((identity) => (
              <article
                key={identity.subject}
                className="relative rounded-lg border bg-muted/25 p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="flex size-8 items-center justify-center rounded-lg bg-background ring-1 ring-border">
                    <Link2Icon
                      className="size-4 text-indigo-600"
                      aria-hidden="true"
                    />
                  </span>
                  <Badge
                    variant="outline"
                    className={statusStyles[identity.status] ?? ""}
                  >
                    {identity.status}
                  </Badge>
                </div>
                <h4 className="mt-3 text-sm font-semibold">
                  {identity.provider}身份
                </h4>
                <p className="mt-1 font-mono text-[11px] break-all text-muted-foreground">
                  {identity.subject}
                </p>
                <dl className="mt-3 space-y-2 text-xs">
                  <IdentityField
                    label="租户 / 连接"
                    value={identity.connection}
                  />
                  <IdentityField label="关联来源" value={identity.source} />
                </dl>
                <div className="mt-3 flex flex-wrap gap-1">
                  {identity.purposes.map((purpose) => (
                    <Badge
                      key={purpose}
                      variant="secondary"
                      className="font-normal"
                    >
                      {purpose}
                    </Badge>
                  ))}
                </div>
                <DisabledAction
                  variant="ghost"
                  size="xs"
                  className="mt-3 w-full"
                >
                  管理关联 · 规划中
                </DisabledAction>
              </article>
            ))}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="shadow-none">
          <CardHeader className="border-b">
            <div className="flex items-center gap-2">
              <UsersRoundIcon
                className="size-4 text-indigo-600"
                aria-hidden="true"
              />
              <h3 className="font-semibold">群会话与人员权限分离</h3>
            </div>
            <p className="text-xs leading-5 text-muted-foreground">
              Conversation 只承载群上下文；每条消息按当前发送人的内部用户与 ONES
              身份解析数据范围。
            </p>
          </CardHeader>
          <CardContent className="space-y-2">
            {groupIdentityExamples.map((example) => (
              <div
                key={example.internal}
                className="grid gap-2 rounded-lg border bg-muted/25 p-3 text-xs sm:grid-cols-[1fr_auto_1fr] sm:items-center"
              >
                <div>
                  <p className="font-medium">{example.member}</p>
                  <p className="mt-1 text-muted-foreground">
                    {example.internal}
                  </p>
                </div>
                <ArrowRightIcon
                  className="hidden size-4 text-muted-foreground sm:block"
                  aria-hidden="true"
                />
                <div className="sm:text-right">
                  <p className="font-medium">{example.ones}</p>
                  <p className="mt-1 text-muted-foreground">
                    数据范围：{example.scope}
                  </p>
                </div>
              </div>
            ))}
            <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50/60 p-3 text-xs text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200">
              <CircleAlertIcon
                className="mt-0.5 size-4 shrink-0"
                aria-hidden="true"
              />
              不创建群级共享 ONES 身份，也不因同群会话共享业务数据权限。
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-none">
          <CardHeader className="border-b">
            <h3 className="font-semibold">身份生命周期与治理入口</h3>
            <p className="text-xs text-muted-foreground">
              以下数量仅用于评审状态设计。
            </p>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {identityStatuses.map((status) => (
                <div
                  key={status.label}
                  className="rounded-lg border bg-muted/25 p-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-medium">{status.label}</span>
                    <span className="text-lg font-semibold">
                      {status.value}
                    </span>
                  </div>
                  <p className="mt-2 text-[11px] leading-4 text-muted-foreground">
                    {status.note}
                  </p>
                </div>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {managementArchitecture.map((item) => (
                <Badge
                  key={item}
                  variant="outline"
                  className="gap-1 font-normal"
                >
                  <CheckCircle2Icon aria-hidden="true" />
                  {item}
                </Badge>
              ))}
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {["解除绑定", "自动匹配", "处理冲突", "迁移身份"].map(
                (action) => (
                  <DisabledAction key={action} variant="outline" size="xs">
                    {action} · 规划中
                  </DisabledAction>
                )
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  )
}

function IdentityField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10px] text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 leading-4">{value}</dd>
    </div>
  )
}
