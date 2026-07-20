import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { ProtectedRoute, useAuth } from "./auth";
import { Card, EmptyState } from "./components/ui";
import { AdminLayout } from "./layout";
import type { Principal } from "./lib/types";
import { AgentPage } from "./pages/AgentPage";
import { AuditPage } from "./pages/AuditPage";
import { LoginPage } from "./pages/LoginPage";
import { RolesPage } from "./pages/RolesPage";
import { UsersPage } from "./pages/UsersPage";
import { WebhookEditorPage, WebhookEventsPage, WebhooksPage } from "./pages/WebhooksPage";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/admin" element={<ProtectedRoute><AdminLayout /></ProtectedRoute>}>
        <Route index element={<AdminIndex />} />
        <Route path="users" element={<CapabilityRoute capability="users_manage"><UsersPage /></CapabilityRoute>} />
        <Route path="roles" element={<CapabilityRoute capability="roles_manage"><RolesPage /></CapabilityRoute>} />
        <Route path="agents/default-diagnostic-agent" element={<CapabilityRoute capability="agent_edit"><AgentPage /></CapabilityRoute>} />
        <Route path="agents/default-diagnostic-agent/publications" element={<CapabilityRoute capability="agent_edit"><AgentPage /></CapabilityRoute>} />
        <Route path="webhooks" element={<CapabilityRoute capability="webhook_read"><WebhooksPage /></CapabilityRoute>} />
        <Route path="webhooks/new" element={<CapabilityRoute capability="webhook_edit"><WebhookEditorPage /></CapabilityRoute>} />
        <Route path="webhooks/:code" element={<CapabilityRoute capability="webhook_read"><WebhookEditorPage /></CapabilityRoute>} />
        <Route path="webhooks/:code/events" element={<CapabilityRoute capability="webhook_read"><WebhookEventsPage /></CapabilityRoute>} />
        <Route path="audit" element={<CapabilityRoute capability="audit_read"><AuditPage /></CapabilityRoute>} />
        <Route path="*" element={<AdminIndex />} />
      </Route>
      <Route path="*" element={<Navigate to="/admin" replace />} />
    </Routes>
  );
}

type Capability = keyof Principal["capabilities"];

function AdminIndex() {
  const { user } = useAuth();
  if (user?.capabilities.agent_edit) return <Navigate to="agents/default-diagnostic-agent" replace />;
  if (user?.capabilities.webhook_read) return <Navigate to="webhooks" replace />;
  if (user?.capabilities.users_manage) return <Navigate to="users" replace />;
  if (user?.capabilities.roles_manage) return <Navigate to="roles" replace />;
  if (user?.capabilities.audit_read) return <Navigate to="audit" replace />;
  return <AccessDenied />;
}

function CapabilityRoute({ capability, children }: { capability: Capability; children: ReactNode }) {
  const { user } = useAuth();
  return user?.capabilities[capability] ? children : <AccessDenied />;
}

function AccessDenied() {
  return <Card><EmptyState title="无管理权限" message="当前账号已登录，但没有该管理资源的授权。请联系平台管理员分配明确角色。" /></Card>;
}
