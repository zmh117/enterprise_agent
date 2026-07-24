import { createBrowserRouter } from "react-router-dom"

import { PlatformShell } from "@/app/shell/platform-shell"
import { ApplicationDetailPage } from "@/contexts/applications/presentation/application-detail-page"
import { ApplicationsPage } from "@/contexts/applications/presentation/applications-page"
import { DashboardPage } from "@/contexts/overview/presentation/dashboard-page"
import {
  ConversationDetailPage,
  RuntimeJobDetailPage,
  RuntimeRecordsPage,
} from "@/contexts/operations/presentation/runtime-records-page"
import { UserDetailPage, UsersPage } from "@/contexts/users"

export const appRouter = createBrowserRouter([
  {
    element: <PlatformShell />,
    children: [
      { path: "/", element: <DashboardPage /> },
      { path: "/applications", element: <ApplicationsPage /> },
      { path: "/applications/:code", element: <ApplicationDetailPage /> },
      { path: "/operations/jobs", element: <RuntimeRecordsPage /> },
      { path: "/operations/jobs/:jobId", element: <RuntimeJobDetailPage /> },
      {
        path: "/operations/conversations/:sessionId",
        element: <ConversationDetailPage />,
      },
      { path: "/users", element: <UsersPage /> },
      { path: "/users/:userId", element: <UserDetailPage /> },
    ],
  },
])
