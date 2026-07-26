import { createBrowserRouter } from "react-router-dom"

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
import { UserDetailPage, UsersPage } from "@/contexts/users"
import { DingTalkIdentityDiscoveryPage } from "@/contexts/dingtalk-identity-discovery"

export const appRouter = createBrowserRouter([
  {
    element: <PlatformShell />,
    children: [
      { path: "/", element: <DashboardPage /> },
      { path: "/applications", element: <ApplicationsPage /> },
      {
        path: "/applications/channels",
        element: <ManagedChannelsPage />,
      },
      { path: "/applications/:code", element: <ApplicationDetailPage /> },
      {
        path: "/agent-profiles",
        element: <AgentProfilesPage />,
      },
      {
        path: "/agent-profiles/:code",
        element: <AgentProfilePage />,
      },
      { path: "/operations/jobs", element: <RuntimeRecordsPage /> },
      { path: "/operations/jobs/:jobId", element: <RuntimeJobDetailPage /> },
      {
        path: "/operations/conversations/:sessionId",
        element: <ConversationDetailPage />,
      },
      { path: "/users", element: <UsersPage /> },
      {
        path: "/users/dingtalk-discovery",
        element: <DingTalkIdentityDiscoveryPage />,
      },
      { path: "/users/:userId", element: <UserDetailPage /> },
    ],
  },
])
