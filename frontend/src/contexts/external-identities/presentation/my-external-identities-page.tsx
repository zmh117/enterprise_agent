import { ExternalIdentityPanel } from "@/contexts/external-identities/presentation/dingtalk-identity-panel"

export function MyExternalIdentitiesPage() {
  return (
    <main className="mx-auto w-full max-w-[1100px] space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">我的外部身份</h1>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">
          这里只展示当前会话用户已经绑定的钉钉身份，不读取其他用户数据。
        </p>
      </header>
      <ExternalIdentityPanel mode="self" />
    </main>
  )
}
