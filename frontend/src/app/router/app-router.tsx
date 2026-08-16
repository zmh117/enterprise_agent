import { createBrowserRouter } from "react-router-dom"
import type { ReactNode } from "react"

import { AppErrorFallback } from "@/app/errors/app-error-boundary"
import { PlatformShell } from "@/app/shell/platform-shell"
import { ApplicationDetailPage } from "@/contexts/applications/presentation/application-detail-page"
import { ApplicationsPage } from "@/contexts/applications/presentation/applications-page"
import { ManagedChannelsPage } from "@/contexts/applications/presentation/managed-channels-page"
import {
  AgentProfilePage,
  AgentProfilesPage,
} from "@/contexts/agent-profiles/presentation/agent-profile-page"
import { DashboardPage } from "@/contexts/overview/presentation/dashboard-page"
import {
  ConversationDetailPage,
  RuntimeJobDetailPage,
  RuntimeRecordsPage,
} from "@/contexts/operations/presentation/runtime-records-page"
import { DebugJobPage } from "@/contexts/operations/presentation/debug-job-page"
import { CredentialCenterPage } from "@/contexts/platform-governance/presentation/credential-center-page"
import { ToolResourcesPage } from "@/contexts/platform-governance/presentation/tool-resources-page"
import { UserDetailPage, UsersPage } from "@/contexts/users"
import { DingTalkIdentityDiscoveryPage } from "@/contexts/dingtalk-identity-discovery"
import { RoleAuthorizationPage, RoleDetailPage } from "@/contexts/authorization"
import { CapabilityGate } from "@/contexts/auth/presentation/capability-gate"
import { MyExternalIdentitiesPage } from "@/contexts/external-identities"

function protectedPage(capability: string, page: ReactNode) {
  return <CapabilityGate capability={capability}>{page}</CapabilityGate>
}

export const appRouter = createBrowserRouter([
  {
    element: <PlatformShell />,
    errorElement: <AppErrorFallback />,
    children: [
      {
        path: "/",
        element: protectedPage("dashboard.read", <DashboardPage />),
      },
      {
        path: "/applications",
        element: protectedPage("applications.read", <ApplicationsPage />),
      },
      {
        path: "/applications/channels",
        element: protectedPage("channels.read", <ManagedChannelsPage />),
      },
      {
        path: "/applications/:code",
        element: protectedPage("applications.read", <ApplicationDetailPage />),
      },
      {
        path: "/agent-profiles",
        element: protectedPage("agents.read", <AgentProfilesPage />),
      },
      {
        path: "/agent-profiles/:code",
        element: protectedPage("agents.read", <AgentProfilePage />),
      },
      {
        path: "/operations/jobs",
        element: protectedPage("jobs.read", <RuntimeRecordsPage />),
      },
      {
        path: "/operations/debug",
        element: protectedPage("agent.debug.execute", <DebugJobPage />),
      },
      {
        path: "/operations/jobs/:jobId",
        element: protectedPage("jobs.read", <RuntimeJobDetailPage />),
      },
      {
        path: "/operations/conversations/:sessionId",
        element: protectedPage(
          "conversations.read",
          <ConversationDetailPage />
        ),
      },
      {
        path: "/users",
        element: protectedPage("users.read", <UsersPage />),
      },
      {
        path: "/users/roles",
        element: protectedPage("authorization.read", <RoleAuthorizationPage />),
      },
      {
        path: "/users/roles/:roleId",
        element: protectedPage("authorization.read", <RoleDetailPage />),
      },
      {
        path: "/users/dingtalk-discovery",
        element: protectedPage(
          "identity.discovery.read",
          <DingTalkIdentityDiscoveryPage />
        ),
      },
      {
        path: "/users/:userId",
        element: protectedPage("users.read", <UserDetailPage />),
      },
      {
        path: "/me/external-identities",
        element: <MyExternalIdentitiesPage />,
      },
      {
        path: "/platform/secrets",
        element: protectedPage("secrets.read", <CredentialCenterPage />),
      },
      {
        path: "/platform/resources",
        element: protectedPage("platform.read", <ToolResourcesPage />),
      },
    ],
  },
])
