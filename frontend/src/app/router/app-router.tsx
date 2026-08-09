import {
  Navigate,
  createBrowserRouter,
  type RouteObject,
} from "react-router-dom"

import { PlatformShell } from "@/app/shell/platform-shell"
import { AccountSecurityPage } from "@/contexts/auth/presentation/account-security-page"
import { MyExternalIdentitiesPage } from "@/contexts/external-identities"
import {
  ConversationDetailPage,
  RuntimeJobDetailPage,
  RuntimeRecordsPage,
} from "@/contexts/operations/presentation/runtime-records-page"
import { RetiredManagementPage } from "@/shared/presentation/retired-management-page"

export const appRoutes: RouteObject[] = [
  {
    element: <PlatformShell />,
    children: [
      { path: "/", element: <Navigate to="/operations/jobs" replace /> },
      { path: "/operations/jobs", element: <RuntimeRecordsPage /> },
      { path: "/operations/jobs/:jobId", element: <RuntimeJobDetailPage /> },
      {
        path: "/operations/conversations/:sessionId",
        element: <ConversationDetailPage />,
      },
      {
        path: "/me/external-identities",
        element: <MyExternalIdentitiesPage />,
      },
      { path: "/account/security", element: <AccountSecurityPage /> },
      {
        path: "/applications",
        lazy: async () => ({
          Component: (
            await import("@/contexts/applications/presentation/business-application-pages")
          ).BusinessApplicationListPage,
        }),
      },
      {
        path: "/applications/:applicationCode",
        lazy: async () => ({
          Component: (
            await import("@/contexts/applications/presentation/business-application-pages")
          ).BusinessApplicationDetailPage,
        }),
      },
      {
        path: "/agent-profiles",
        lazy: async () => ({
          Component: (
            await import("@/contexts/agents/presentation/agent-management-pages")
          ).AgentListPage,
        }),
      },
      {
        path: "/agent-profiles/:agentCode",
        lazy: async () => ({
          Component: (
            await import("@/contexts/agents/presentation/agent-management-pages")
          ).AgentDetailPage,
        }),
      },
      {
        path: "/agent-profiles/:agentCode/model-connections/:connectionCode",
        lazy: async () => ({
          Component: (
            await import("@/contexts/agents/presentation/agent-management-pages")
          ).ModelConnectionPage,
        }),
      },
      { path: "/operations/debug", element: <RetiredManagementPage /> },
      { path: "/users/*", element: <RetiredManagementPage /> },
      { path: "/platform/*", element: <RetiredManagementPage /> },
      { path: "*", element: <RetiredManagementPage unknown /> },
    ],
  },
]

export const appRouter = createBrowserRouter(appRoutes)
