import { createBrowserRouter } from "react-router-dom"

import { PlatformShell } from "@/app/shell/platform-shell"
import { ApplicationDetailPage } from "@/contexts/applications/presentation/application-detail-page"
import { ApplicationsPage } from "@/contexts/applications/presentation/applications-page"
import { DashboardPage } from "@/contexts/overview/presentation/dashboard-page"

export const appRouter = createBrowserRouter([
  {
    element: <PlatformShell />,
    children: [
      { path: "/", element: <DashboardPage /> },
      { path: "/applications", element: <ApplicationsPage /> },
      { path: "/applications/:code", element: <ApplicationDetailPage /> },
    ],
  },
])
