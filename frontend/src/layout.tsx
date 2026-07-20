import { Bot, ChevronRight, LogOut, ScrollText, ShieldCheck, UsersRound, Webhook } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "./auth";
import { Button } from "./components/ui";
import type { Principal } from "./lib/types";

const navigation = [
  { to: "/admin/users", label: "用户与身份", icon: UsersRound, capability: "users_manage" },
  { to: "/admin/roles", label: "角色与权限", icon: ShieldCheck, capability: "roles_manage" },
  { to: "/admin/agents/default-diagnostic-agent", label: "默认诊断 Agent", icon: Bot, capability: "agent_edit" },
  { to: "/admin/webhooks", label: "Webhook 触发器", icon: Webhook, capability: "webhook_read" },
  { to: "/admin/audit", label: "安全审计", icon: ScrollText, capability: "audit_read" },
] as const;

export function AdminLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark">EA</div><div><strong>Enterprise Agent</strong><span>治理与运行控制台</span></div></div>
        <nav>
          {navigation.filter((item) => Boolean(user?.capabilities[item.capability as keyof Principal["capabilities"]])).map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <Icon size={18} /><span>{label}</span><ChevronRight size={15} />
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-note"><span className="status-dot" />只读诊断运行时<p>Web 只开放一个默认 Agent；底层保持多 Agent 模型。</p></div>
      </aside>
      <main className="main-shell">
        <div className="topbar">
          <div><span className="environment-pill">本地管理环境</span></div>
          <div className="account"><div className="avatar">{user?.display_name?.slice(0, 1) || "管"}</div><div><strong>{user?.display_name}</strong><span>{user?.username}</span></div><Button variant="ghost" aria-label="退出" onClick={async () => { await logout(); navigate("/login"); }}><LogOut size={17} /></Button></div>
        </div>
        <div className="page"><Outlet /></div>
      </main>
    </div>
  );
}
