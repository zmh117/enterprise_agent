import { InfoIcon, SparklesIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { BusinessApplications } from "@/contexts/applications/presentation/business-applications"
import { CapabilityGovernance } from "@/contexts/api-capabilities/presentation/capability-governance"
import { ExternalIdentityMap } from "@/contexts/external-identities/presentation/external-identity-map"
import { OperationsPreview } from "@/contexts/operations/presentation/operations-preview"
import { OverviewMetrics } from "@/contexts/overview/presentation/overview-metrics"
import { PlatformFlow } from "@/contexts/overview/presentation/platform-flow"
import { WorkflowPreview } from "@/contexts/workflows/presentation/workflow-preview"
import { prototypeMeta } from "@/mocks/dashboard"

export function DashboardPage() {
  return (
    <div className="mx-auto flex w-full max-w-[1680px] flex-col gap-7 px-4 py-5 sm:px-6 lg:gap-8 lg:px-8 lg:py-7">
      <section
        aria-labelledby="page-title"
        className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between"
      >
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge className="gap-1 bg-indigo-600 text-white hover:bg-indigo-600">
              <SparklesIcon aria-hidden="true" />
              控制面信息架构
            </Badge>
            <Badge variant="outline">MVP 界面评审</Badge>
          </div>
          <h1
            id="page-title"
            className="text-2xl font-semibold tracking-tight sm:text-3xl"
          >
            Agent 应用平台
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground sm:text-base">
            以业务应用为中心，装配 Agent Profile、Workflow、Channel 与受控 API
            Capability；同一 Runtime 支撑多个业务入口。
          </p>
        </div>
        <div className="max-w-xl rounded-lg border border-indigo-200 bg-indigo-50/70 px-4 py-3 text-xs leading-5 text-indigo-950 dark:border-indigo-900 dark:bg-indigo-950/40 dark:text-indigo-100">
          <div className="flex items-start gap-2">
            <InfoIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <p>
              <strong>{prototypeMeta.label}：</strong>
              {prototypeMeta.fixturePolicy}{" "}
              所有创建、编辑、绑定、测试、保存、发布和回滚入口均不可操作。
            </p>
          </div>
        </div>
      </section>

      <OverviewMetrics />
      <BusinessApplications />
      <PlatformFlow />

      <section className="space-y-4" aria-labelledby="control-plane-title">
        <div>
          <h2
            id="control-plane-title"
            className="text-lg font-semibold tracking-tight"
          >
            控制面预览
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            工作流负责确定性步骤，Capability Gateway
            负责能力、主体、版本和审计边界。
          </p>
        </div>
        <WorkflowPreview />
        <CapabilityGovernance />
        <OperationsPreview />
      </section>

      <ExternalIdentityMap />

      <footer className="border-t py-5 text-xs leading-5 text-muted-foreground">
        本页仅用于评审产品结构。未连接登录、路由业务页、后端
        API、数据库或实时运行数据。
      </footer>
    </div>
  )
}
