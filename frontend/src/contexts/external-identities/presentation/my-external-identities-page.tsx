import { ExternalIdentityPanel } from "@/contexts/external-identities/presentation/external-identity-panel"

export function MyExternalIdentitiesPage() {
  return (
    <main className="mx-auto w-full max-w-[1100px] space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">我的外部身份</h1>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">
          管理当前会话用户自己的钉钉与 ONES 身份；ONES 邮箱和密码只用于单次验证。
        </p>
      </header>
      <ExternalIdentityPanel mode="self" />
    </main>
  )
}
