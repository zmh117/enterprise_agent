import { Navigate, createBrowserRouter, type RouteObject } from "react-router-dom"

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
      { path: "/me/external-identities", element: <MyExternalIdentitiesPage /> },
      { path: "/account/security", element: <AccountSecurityPage /> },
      { path: "/applications/*", element: <RetiredManagementPage /> },
      { path: "/agent-profiles/*", element: <RetiredManagementPage /> },
      { path: "/operations/debug", element: <RetiredManagementPage /> },
      { path: "/users/*", element: <RetiredManagementPage /> },
      { path: "/platform/*", element: <RetiredManagementPage /> },
      { path: "*", element: <RetiredManagementPage unknown /> },
    ],
  },
]

export const appRouter = createBrowserRouter(appRoutes)
