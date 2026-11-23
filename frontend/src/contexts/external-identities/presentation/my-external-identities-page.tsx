import { ListPage } from "@/shared/presentation/list-page"
import { ExternalIdentityPanel } from "@/contexts/external-identities/presentation/external-identity-panel"

export function MyExternalIdentitiesPage() {
  return (
    <ListPage title="我的外部身份">
      <ExternalIdentityPanel mode="self" />
    </ListPage>
  )
}
