import { createBrowserRouter } from "react-router-dom"
import { Suspense, type ReactNode } from "react"
import { LoaderCircleIcon } from "lucide-react"

import { AppErrorFallback } from "@/app/errors/app-error-boundary"
import { PlatformShell } from "@/app/shell/platform-shell"
import { CapabilityGate } from "@/contexts/auth/presentation/capability-gate"

import {
  ApplicationDetailPage,
  ApplicationsPage,
  ManagedChannelsPage,
  AgentProfilePage,
  AgentProfilesPage,
  DashboardPage,
  ConversationDetailPage,
  RuntimeJobDetailPage,
  RuntimeRecordsPage,
  DebugJobPage,
  CredentialCenterPage,
  ToolResourcesPage,
  RuntimeConfigPage,
  UserDetailPage,
  UsersPage,
  DingTalkIdentityDiscoveryPage,
  RoleAuthorizationPage,
  RoleDetailPage,
  MyExternalIdentitiesPage,
} from "@/app/router/lazy-route-pages"

function pageWithLoadingState(page: ReactNode) {
  return (
    <Suspense
      fallback={
        <div
          role="status"
          aria-live="polite"
          className="flex min-h-64 items-center justify-center gap-2 text-sm text-muted-foreground"
        >
          <LoaderCircleIcon
            className="size-4 animate-spin"
            aria-hidden="true"
          />
          正在加载管理页面…
        </div>
      }
    >
      {page}
    </Suspense>
  )
}

function protectedPage(capability: string, page: ReactNode) {
  return (
    <CapabilityGate capability={capability}>
      {pageWithLoadingState(page)}
    </CapabilityGate>
  )
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
        element: pageWithLoadingState(<MyExternalIdentitiesPage />),
      },
      {
        path: "/platform/secrets",
        element: protectedPage("secrets.read", <CredentialCenterPage />),
      },
      {
        path: "/platform/resources",
        element: protectedPage("platform.read", <ToolResourcesPage />),
      },
      {
        path: "/platform/runtime-config",
        element: protectedPage("platform.read", <RuntimeConfigPage />),
      },
    ],
  },
])
