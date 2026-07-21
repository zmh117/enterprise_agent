import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { ProtectedRoute, useAuth } from "./app/providers/auth-provider";
import { AdminLayout } from "./app/shell/admin-layout";
import type { Principal } from "./contexts/identity/domain/models";
import { Card, EmptyState } from "./shared/presentation/ui";
const AgentPage = lazy(() => import("./contexts/agent-management/presentation/AgentPage").then((module) => ({ default: module.AgentPage })));
const AuditPage = lazy(() => import("./contexts/authorization/presentation/AuditPage").then((module) => ({ default: module.AuditPage })));
const LoginPage = lazy(() => import("./contexts/identity/presentation/LoginPage").then((module) => ({ default: module.LoginPage })));
const RolesPage = lazy(() => import("./contexts/authorization/presentation/RolesPage").then((module) => ({ default: module.RolesPage })));
const UsersPage = lazy(() => import("./contexts/identity/presentation/UsersPage").then((module) => ({ default: module.UsersPage })));
const WebhooksPage = lazy(() => import("./contexts/webhooks/presentation/WebhooksPage").then((module) => ({ default: module.WebhooksPage })));
const WebhookEditorPage = lazy(() => import("./contexts/webhooks/presentation/WebhooksPage").then((module) => ({ default: module.WebhookEditorPage })));
const WebhookEventsPage = lazy(() => import("./contexts/webhooks/presentation/WebhooksPage").then((module) => ({ default: module.WebhookEventsPage })));
const DashboardPage = lazy(() => import("./contexts/operations/presentation/pages").then((module) => ({ default: module.DashboardPage })));
const QueuesPage = lazy(() => import("./contexts/operations/presentation/pages").then((module) => ({ default: module.QueuesPage })));
const JobsPage = lazy(() => import("./contexts/operations/presentation/pages").then((module) => ({ default: module.JobsPage })));
const ConversationsPage = lazy(() => import("./contexts/operations/presentation/pages").then((module) => ({ default: module.ConversationsPage })));
const AttachmentsPage = lazy(() => import("./contexts/operations/presentation/pages").then((module) => ({ default: module.AttachmentsPage })));
const SkillsPage = lazy(() => import("./contexts/catalog/presentation/pages").then((module) => ({ default: module.SkillsPage })));
const ToolsPage = lazy(() => import("./contexts/catalog/presentation/pages").then((module) => ({ default: module.ToolsPage })));
const ChannelsPage = lazy(() => import("./contexts/catalog/presentation/pages").then((module) => ({ default: module.ChannelsPage })));

export function App() {
  return (
    <Suspense fallback={<div className="app-loading">正在加载管理模块…</div>}><Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/admin" element={<ProtectedRoute><AdminLayout /></ProtectedRoute>}>
        <Route index element={<Navigate to="dashboard" replace />} />
        <Route path="dashboard" element={<AdminCapabilityRoute capability="dashboard.read"><DashboardPage /></AdminCapabilityRoute>} />
        <Route path="users" element={<CapabilityRoute capability="users_manage"><UsersPage /></CapabilityRoute>} />
        <Route path="roles" element={<CapabilityRoute capability="roles_manage"><RolesPage /></CapabilityRoute>} />
        <Route path="agents/default-diagnostic-agent" element={<CapabilityRoute capability="agent_edit"><AgentPage /></CapabilityRoute>} />
        <Route path="agents/default-diagnostic-agent/publications" element={<CapabilityRoute capability="agent_edit"><AgentPage /></CapabilityRoute>} />
        <Route path="agents/:agentCode" element={<Navigate to="/admin/agents/default-diagnostic-agent" replace />} />
        <Route path="skills" element={<AdminCapabilityRoute capability="skills.read"><SkillsPage /></AdminCapabilityRoute>} />
        <Route path="tools" element={<AdminCapabilityRoute capability="tools.read"><ToolsPage /></AdminCapabilityRoute>} />
        <Route path="channels" element={<AdminCapabilityRoute capability="channels.read"><ChannelsPage /></AdminCapabilityRoute>} />
        <Route path="webhooks" element={<CapabilityRoute capability="webhook_read"><WebhooksPage /></CapabilityRoute>} />
        <Route path="webhooks/new" element={<CapabilityRoute capability="webhook_edit"><WebhookEditorPage /></CapabilityRoute>} />
        <Route path="webhooks/:code" element={<CapabilityRoute capability="webhook_read"><WebhookEditorPage /></CapabilityRoute>} />
        <Route path="webhooks/:code/events" element={<CapabilityRoute capability="webhook_read"><WebhookEventsPage /></CapabilityRoute>} />
        <Route path="audit" element={<CapabilityRoute capability="audit_read"><AuditPage /></CapabilityRoute>} />
        <Route path="queues" element={<AdminCapabilityRoute capability="queues.read"><QueuesPage /></AdminCapabilityRoute>} />
        <Route path="jobs" element={<AdminCapabilityRoute capability="jobs.read"><JobsPage /></AdminCapabilityRoute>} />
        <Route path="conversations" element={<AdminCapabilityRoute capability="conversations.read"><ConversationsPage /></AdminCapabilityRoute>} />
        <Route path="attachments" element={<AdminCapabilityRoute capability="attachments.read"><AttachmentsPage /></AdminCapabilityRoute>} />
        <Route path="*" element={<AdminIndex />} />
      </Route>
      <Route path="*" element={<Navigate to="/admin" replace />} />
    </Routes></Suspense>
  );
}

type Capability = keyof Principal["capabilities"];

function AdminIndex() {
  const { user, can } = useAuth();
  if (can("dashboard.read")) return <Navigate to="dashboard" replace />;
  if (user?.capabilities.agent_edit) return <Navigate to="agents/default-diagnostic-agent" replace />;
  if (user?.capabilities.webhook_read) return <Navigate to="webhooks" replace />;
  if (user?.capabilities.users_manage) return <Navigate to="users" replace />;
  if (user?.capabilities.roles_manage) return <Navigate to="roles" replace />;
  if (user?.capabilities.audit_read) return <Navigate to="audit" replace />;
  return <AccessDenied />;
}

function AdminCapabilityRoute({ capability, children }: { capability: string; children: ReactNode }) {
  const { can } = useAuth();
  return can(capability) ? children : <AccessDenied />;
}

function CapabilityRoute({ capability, children }: { capability: Capability; children: ReactNode }) {
  const { user } = useAuth();
  return user?.capabilities[capability] ? children : <AccessDenied />;
}

function AccessDenied() {
  return <Card><EmptyState title="无管理权限" message="当前账号已登录，但没有该管理资源的授权。请联系平台管理员分配明确角色。" /></Card>;
}
