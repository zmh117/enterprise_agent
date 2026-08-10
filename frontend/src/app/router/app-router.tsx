import {
  Navigate,
  createBrowserRouter,
  type RouteObject,
} from "react-router-dom"

import { PlatformShell } from "@/app/shell/platform-shell"
import { AccountSecurityPage } from "@/contexts/auth/presentation/account-security-page"
import { CapabilityGate } from "@/contexts/auth/presentation/capability-gate"
import { useAuthenticatedUser } from "@/contexts/auth/presentation/authenticated-user-state"
import { ManagedChannelsPage } from "@/contexts/channels/presentation/managed-channels-page"
import { MyExternalIdentitiesPage } from "@/contexts/external-identities"
import { IdentityDiscoveryPage } from "@/contexts/dingtalk-identity-discovery/presentation/identity-discovery-page"
import {
  RoleDetailPage,
  RolesPage,
  UserDetailPage,
  UsersPage,
} from "@/contexts/identity-governance/presentation/identity-governance-pages"
import {
  CredentialsPage,
  McpResourcesPage,
  McpServersPage,
  McpToolsPage,
} from "@/contexts/mcp-governance/presentation/mcp-governance-pages"
import {
  AdminRuntimeJobDetailPage,
  AdminRuntimeRecordsPage,
  DebugJobPage,
} from "@/contexts/operations/presentation/admin-runtime-pages"
import {
  ConversationDetailPage,
  RuntimeJobDetailPage,
  RuntimeRecordsPage,
} from "@/contexts/operations/presentation/runtime-records-page"
import { GovernanceDashboardPage } from "@/contexts/overview/presentation/governance-dashboard-page"
import { RetiredManagementPage } from "@/shared/presentation/retired-management-page"

export const appRoutes: RouteObject[] = [
  {
    element: <PlatformShell />,
    children: [
      { path: "/", element: <HomeRedirect /> },
      {
        path: "/dashboard",
        element: (
          <CapabilityGate capability="dashboard_read">
            <GovernanceDashboardPage />
          </CapabilityGate>
        ),
      },
      { path: "/operations/jobs", element: <RuntimeRecordsPage /> },
      { path: "/operations/jobs/:jobId", element: <RuntimeJobDetailPage /> },
      {
        path: "/operations/conversations/:sessionId",
        element: <ConversationDetailPage />,
      },
      {
        path: "/operations/history",
        element: (
          <CapabilityGate capability="jobs_read">
            <AdminRuntimeRecordsPage />
          </CapabilityGate>
        ),
      },
      {
        path: "/operations/history/:jobId",
        element: (
          <CapabilityGate capability="jobs_read">
            <AdminRuntimeJobDetailPage />
          </CapabilityGate>
        ),
      },
      {
        path: "/operations/debug",
        element: (
          <CapabilityGate capability="jobs_debug">
            <DebugJobPage />
          </CapabilityGate>
        ),
      },
      {
        path: "/me/external-identities",
        element: <MyExternalIdentitiesPage />,
      },
      { path: "/account/security", element: <AccountSecurityPage /> },
      {
        path: "/applications",
        lazy: async () => {
          const module = await import(
            "@/contexts/applications/presentation/business-application-pages"
          )
          return {
            Component: () => {
              const Page = module.BusinessApplicationListPage
              return (
                <CapabilityGate capability="applications_read">
                  <Page />
                </CapabilityGate>
              )
            },
          }
        },
      },
      {
        path: "/applications/channels",
        element: (
          <CapabilityGate capability="channels_read">
            <ManagedChannelsPage />
          </CapabilityGate>
        ),
      },
      {
        path: "/applications/:applicationCode",
        lazy: async () => {
          const module = await import(
            "@/contexts/applications/presentation/business-application-pages"
          )
          return {
            Component: () => {
              const Page = module.BusinessApplicationDetailPage
              return (
                <CapabilityGate capability="applications_read">
                  <Page />
                </CapabilityGate>
              )
            },
          }
        },
      },
      {
        path: "/agent-profiles",
        lazy: async () => {
          const module = await import(
            "@/contexts/agents/presentation/agent-management-pages"
          )
          return {
            Component: () => {
              const Page = module.AgentListPage
              return (
                <CapabilityGate capability="agents_read">
                  <Page />
                </CapabilityGate>
              )
            },
          }
        },
      },
      {
        path: "/agent-profiles/:agentCode",
        lazy: async () => {
          const module = await import(
            "@/contexts/agents/presentation/agent-management-pages"
          )
          return {
            Component: () => {
              const Page = module.AgentDetailPage
              return (
                <CapabilityGate capability="agents_read">
                  <Page />
                </CapabilityGate>
              )
            },
          }
        },
      },
      {
        path: "/agent-profiles/:agentCode/model-connections/:connectionCode",
        lazy: async () => {
          const module = await import(
            "@/contexts/agents/presentation/agent-management-pages"
          )
          return {
            Component: () => {
              const Page = module.ModelConnectionPage
              return (
                <CapabilityGate capability="agents_read">
                  <Page />
                </CapabilityGate>
              )
            },
          }
        },
      },
      {
        path: "/mcp/servers",
        element: (
          <CapabilityGate capability="mcp_servers_read">
            <McpServersPage />
          </CapabilityGate>
        ),
      },
      {
        path: "/mcp/tools",
        element: (
          <CapabilityGate capability="mcp_tools_read">
            <McpToolsPage />
          </CapabilityGate>
        ),
      },
      {
        path: "/mcp/resources",
        element: (
          <CapabilityGate capability="mcp_resources_read">
            <McpResourcesPage />
          </CapabilityGate>
        ),
      },
      {
        path: "/mcp/credentials",
        element: (
          <CapabilityGate capability="secrets_read">
            <CredentialsPage />
          </CapabilityGate>
        ),
      },
      {
        path: "/users",
        element: (
          <CapabilityGate capability="users_read">
            <UsersPage />
          </CapabilityGate>
        ),
      },
      {
        path: "/users/roles",
        element: (
          <CapabilityGate capability="roles_read">
            <RolesPage />
          </CapabilityGate>
        ),
      },
      {
        path: "/users/roles/:roleId",
        element: (
          <CapabilityGate capability="roles_read">
            <RoleDetailPage />
          </CapabilityGate>
        ),
      },
      {
        path: "/users/dingtalk-candidates",
        element: (
          <CapabilityGate capability="identities_read">
            <IdentityDiscoveryPage />
          </CapabilityGate>
        ),
      },
      {
        path: "/users/:userId",
        element: (
          <CapabilityGate capability="users_read">
            <UserDetailPage />
          </CapabilityGate>
        ),
      },
      { path: "*", element: <RetiredManagementPage unknown /> },
    ],
  },
]

export const appRouter = createBrowserRouter(appRoutes)

function HomeRedirect() {
  const user = useAuthenticatedUser()
  return (
    <Navigate
      to={user.capabilities.dashboard_read ? "/dashboard" : "/operations/jobs"}
      replace
    />
  )
}
