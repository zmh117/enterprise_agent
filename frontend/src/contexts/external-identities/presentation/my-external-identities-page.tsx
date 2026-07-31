import { ExternalIdentityPanel } from "@/contexts/external-identities/presentation/external-identity-panel"

export function MyExternalIdentitiesPage() {
  return (
    <main className="mx-auto w-full max-w-[1100px] space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">我的外部身份</h1>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">
          这里只请求当前会话用户自己的 ONES 状态，不读取人员列表、角色、会话或其他用户数据。
        </p>
      </header>
      <ExternalIdentityPanel mode="self" />
    </main>
  )
}
