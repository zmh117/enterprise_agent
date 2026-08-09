import { ArchiveXIcon } from "lucide-react"
import { Link } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"

export function RetiredManagementPage({ unknown = false }: { unknown?: boolean }) {
  return (
    <main className="mx-auto flex min-h-[60vh] w-full max-w-2xl items-center px-4 py-10">
      <Card className="w-full shadow-none">
        <CardHeader>
          <div className="mb-3 flex size-10 items-center justify-center rounded-lg bg-muted">
            <ArchiveXIcon className="size-5" aria-hidden="true" />
          </div>
          <h1 className="font-heading text-base font-medium leading-snug">
            {unknown ? "页面不存在" : "管理工作台已退役"}
          </h1>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <p>
            {unknown
              ? "该地址不存在，或对应能力已经从轻量门户移除。"
              : "Agent、API Capability、Handler、Connection、Resource、Secret、角色授权、Runtime Config 与 Business Application 前端入口已永久移除。"}
          </p>
          {!unknown ? (
            <p>
              MCP Resource、Secret、发布、取消发布和状态检查请使用受 RBAC、审计与 expected revision 保护的
              <code className="mx-1 rounded bg-muted px-1.5 py-0.5">platformctl</code>。
            </p>
          ) : null}
          <Button nativeButton={false} render={<Link to="/operations/jobs" />}>返回 Job 历史</Button>
        </CardContent>
      </Card>
    </main>
  )
}
