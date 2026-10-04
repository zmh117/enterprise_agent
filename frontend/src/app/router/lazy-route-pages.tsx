import { lazy } from "react"

export const ApplicationDetailPage = lazy(() =>
  import("@/contexts/applications/presentation/application-detail-page").then(
    (module) => ({ default: module.ApplicationDetailPage })
  )
)
export const ApplicationsPage = lazy(() =>
  import("@/contexts/applications/presentation/applications-page").then(
    (module) => ({ default: module.ApplicationsPage })
  )
)
export const ManagedChannelsPage = lazy(() =>
  import("@/contexts/applications/presentation/managed-channels-page").then(
    (module) => ({ default: module.ManagedChannelsPage })
  )
)
export const AgentProfilePage = lazy(() =>
  import("@/contexts/agent-profiles/presentation/agent-profile-page").then(
    (module) => ({ default: module.AgentProfilePage })
  )
)
export const AgentProfilesPage = lazy(() =>
  import("@/contexts/agent-profiles/presentation/agent-profile-page").then(
    (module) => ({ default: module.AgentProfilesPage })
  )
)
export const DashboardPage = lazy(() =>
  import("@/contexts/overview/presentation/dashboard-page").then((module) => ({
    default: module.DashboardPage,
  }))
)
export const ConversationDetailPage = lazy(() =>
  import("@/contexts/operations/presentation/runtime-records-page").then(
    (module) => ({ default: module.ConversationDetailPage })
  )
)
export const RuntimeJobDetailPage = lazy(() =>
  import("@/contexts/operations/presentation/runtime-records-page").then(
    (module) => ({ default: module.RuntimeJobDetailPage })
  )
)
export const RuntimeRecordsPage = lazy(() =>
  import("@/contexts/operations/presentation/runtime-records-page").then(
    (module) => ({ default: module.RuntimeRecordsPage })
  )
)
export const DebugJobPage = lazy(() =>
  import("@/contexts/operations/presentation/debug-job-page").then(
    (module) => ({
      default: module.DebugJobPage,
    })
  )
)
export const CredentialCenterPage = lazy(() =>
  import("@/contexts/platform-governance/presentation/credential-center-page").then(
    (module) => ({ default: module.CredentialCenterPage })
  )
)
export const ToolResourcesPage = lazy(() =>
  import("@/contexts/platform-governance/presentation/tool-resources-page").then(
    (module) => ({ default: module.ToolResourcesPage })
  )
)
export const RuntimeConfigPage = lazy(() =>
  import("@/contexts/platform-governance/presentation/runtime-config-page").then(
    (module) => ({ default: module.RuntimeConfigPage })
  )
)
export const UserDetailPage = lazy(() =>
  import("@/contexts/users").then((module) => ({
    default: module.UserDetailPage,
  }))
)
export const UsersPage = lazy(() =>
  import("@/contexts/users").then((module) => ({ default: module.UsersPage }))
)
export const DingTalkIdentityDiscoveryPage = lazy(() =>
  import("@/contexts/dingtalk-identity-discovery").then((module) => ({
    default: module.DingTalkIdentityDiscoveryPage,
  }))
)
export const RoleAuthorizationPage = lazy(() =>
  import("@/contexts/authorization").then((module) => ({
    default: module.RoleAuthorizationPage,
  }))
)
export const RoleDetailPage = lazy(() =>
  import("@/contexts/authorization").then((module) => ({
    default: module.RoleDetailPage,
  }))
)
export const MyExternalIdentitiesPage = lazy(() =>
  import("@/contexts/external-identities").then((module) => ({
    default: module.MyExternalIdentitiesPage,
  }))
)
