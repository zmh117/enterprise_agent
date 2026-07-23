import { CheckIcon, EqualIcon, ShieldCheckIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import {
  capabilities,
  permissionIntersection,
  releaseSnapshot,
} from "@/mocks/dashboard"
import { DisabledAction } from "@/shared/presentation/disabled-action"

export function CapabilityGovernance() {
  return (
    <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
      <Card className="shadow-none">
        <CardHeader className="border-b">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <ShieldCheckIcon
                  className="size-4 text-indigo-600"
                  aria-hidden="true"
                />
                <h3 className="font-semibold">API Capability 目录</h3>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                展示业务能力，不展示底层数据源实现。
              </p>
            </div>
            <DisabledAction size="xs" variant="outline">
              调用测试 · 规划中
            </DisabledAction>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div className="hidden grid-cols-[1.2fr_1fr_0.8fr_0.7fr] gap-3 border-b bg-muted/35 px-4 py-2 text-[11px] font-medium text-muted-foreground md:grid">
            <span>能力</span>
            <span>说明</span>
            <span>风险 / 环境</span>
            <span>状态</span>
          </div>
          <div className="divide-y">
            {capabilities.map((capability) => (
              <div
                key={capability.code}
                className="grid gap-2 px-4 py-3 md:grid-cols-[1.2fr_1fr_0.8fr_0.7fr] md:items-center md:gap-3"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium">{capability.name}</p>
                  <code className="mt-0.5 block truncate text-[11px] text-indigo-700 dark:text-indigo-300">
                    {capability.code}
                  </code>
                </div>
                <p className="text-xs leading-5 text-muted-foreground">
                  {capability.description}
                </p>
                <div className="flex flex-wrap gap-1 md:flex-col md:items-start">
                  <Badge variant="outline" className="font-normal">
                    {capability.risk}
                  </Badge>
                  <span className="text-[11px] text-muted-foreground">
                    {capability.environment}
                  </span>
                </div>
                <Badge variant="secondary" className="font-normal">
                  {capability.status}
                </Badge>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4">
        <Card className="shadow-none">
          <CardHeader>
            <h3 className="font-semibold">有效权限 = 五层交集</h3>
            <p className="text-xs leading-5 text-muted-foreground">
              不存在“Agent 可以调用全部 API”的全局开关。
            </p>
          </CardHeader>
          <CardContent className="space-y-1.5">
            {permissionIntersection.map((item, index) => (
              <div
                key={item}
                className="flex items-center gap-2 rounded-md border bg-muted/25 px-3 py-2 text-xs"
              >
                <CheckIcon
                  className="size-3.5 text-emerald-600"
                  aria-hidden="true"
                />
                <span>{item}</span>
                {index < permissionIntersection.length - 1 ? (
                  <span className="ml-auto text-muted-foreground">∩</span>
                ) : (
                  <EqualIcon
                    className="ml-auto size-3 text-muted-foreground"
                    aria-hidden="true"
                  />
                )}
              </div>
            ))}
            <div className="mt-2 rounded-md bg-indigo-600 px-3 py-2 text-center text-xs font-medium text-white">
              本次请求的有效只读能力
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-none">
          <CardHeader className="border-b">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-semibold">发布快照示例</h3>
              <Badge variant="outline">版本冻结</Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {releaseSnapshot.map(([label, value]) => (
              <div
                key={label}
                className="flex items-start justify-between gap-4 text-xs"
              >
                <span className="text-muted-foreground">{label}</span>
                <span className="text-right font-medium">{value}</span>
              </div>
            ))}
            <div className="grid grid-cols-2 gap-2 pt-2">
              <DisabledAction variant="outline" size="sm">
                发布 · 规划中
              </DisabledAction>
              <DisabledAction variant="outline" size="sm">
                回滚 · 规划中
              </DisabledAction>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
