import { Activity, Bot, Boxes, Cable, ChevronRight, FileArchive, FileCode2, ListChecks, LogOut, Menu, MessagesSquare, ScrollText, ShieldCheck, UsersRound, Webhook, type LucideIcon } from "lucide-react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useState } from "react";
import { Breadcrumb, BreadcrumbItem, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from "@enterprise-agent/ui/components/breadcrumb";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@enterprise-agent/ui/components/dropdown-menu";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@enterprise-agent/ui/components/sheet";

import { useAuth } from "../providers/auth-provider";
import type { Principal } from "../../contexts/identity/domain/models";
import { Button } from "../../shared/presentation/ui";

type NavItem = { to:string; label:string; icon:LucideIcon; admin?:string; legacy?:keyof Principal["capabilities"] };
type NavSection = { group:string; items:NavItem[] };

const navigation:NavSection[] = [
  { group: "概览", items: [{ to: "/admin/dashboard", label: "Dashboard", icon: Activity, admin: "dashboard.read" }] },
  { group: "身份与治理", items: [
    { to: "/admin/users", label: "用户管理", icon: UsersRound, legacy: "users_manage" },
    { to: "/admin/roles", label: "授权管理", icon: ShieldCheck, legacy: "roles_manage" },
    { to: "/admin/audit", label: "安全审计", icon: ScrollText, legacy: "audit_read" },
  ]},
  { group: "Agent 能力", items: [
    { to: "/admin/agents/default-diagnostic-agent", label: "Agent 管理", icon: Bot, legacy: "agent_edit" },
    { to: "/admin/skills", label: "Skill 管理", icon: FileCode2, admin: "skills.read" },
    { to: "/admin/tools", label: "API 工具", icon: Boxes, admin: "tools.read" },
  ]},
  { group: "连接与运行", items: [
    { to: "/admin/channels", label: "Channel 管理", icon: Cable, admin: "channels.read" },
    { to: "/admin/webhooks", label: "Webhook 触发器", icon: Webhook, legacy: "webhook_read" },
    { to: "/admin/queues", label: "队列管理", icon: Boxes, admin: "queues.read" },
    { to: "/admin/jobs", label: "任务追踪", icon: ListChecks, admin: "jobs.read" },
    { to: "/admin/conversations", label: "历史对话", icon: MessagesSquare, admin: "conversations.read" },
    { to: "/admin/attachments", label: "附件管理", icon: FileArchive, admin: "attachments.read" },
  ]},
];

export function AdminLayout() {
  const { user, logout, can } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const active = navigation.flatMap((section) => section.items).find((item) => location.pathname.startsWith(item.to));
  const navigationContent = <Navigation onNavigate={() => setMobileOpen(false)} user={user} can={can} />;
  return (
    <div className="app-shell">
      <aside className="sidebar">{navigationContent}</aside>
      <main className="main-shell">
        <div className="topbar">
          <div className="topbar-leading">
            <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
              <SheetTrigger render={<Button variant="ghost" className="mobile-menu" aria-label="打开导航"/>}><Menu size={18}/></SheetTrigger>
              {mobileOpen?<SheetContent side="left" className="mobile-navigation"><SheetHeader className="sr-only"><SheetTitle>管理导航</SheetTitle></SheetHeader>{navigationContent}</SheetContent>:null}
            </Sheet>
            <Breadcrumb><BreadcrumbList><BreadcrumbItem>管理控制台</BreadcrumbItem><BreadcrumbSeparator/><BreadcrumbItem><BreadcrumbPage>{`当前：${active?.label ?? "概览"}`}</BreadcrumbPage></BreadcrumbItem></BreadcrumbList></Breadcrumb>
            <span className="environment-pill">本地管理环境</span>
          </div>
          <DropdownMenu><DropdownMenuTrigger render={<button className="account account-button" aria-label="打开用户菜单"/>}><div className="avatar">{user?.display_name?.slice(0, 1) || "管"}</div><div><strong>{user?.display_name}</strong><span>{user?.username}</span></div></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuLabel>{user?.display_name}</DropdownMenuLabel><DropdownMenuSeparator/><DropdownMenuItem onClick={async () => { await logout(); navigate("/login"); }}><LogOut size={15}/>退出登录</DropdownMenuItem></DropdownMenuContent></DropdownMenu>
        </div>
        <div className="page"><Outlet /></div>
      </main>
    </div>
  );
}

function Navigation({ onNavigate, user, can }: { onNavigate: () => void; user: Principal | null; can: (code: string) => boolean }) {
  return <>
    <div className="brand"><div className="brand-mark">EA</div><div><strong>Enterprise Agent</strong><span>治理与运行控制台</span></div></div>
    <nav>{navigation.map(section => { const visible=section.items.filter(item => item.admin ? can(item.admin) : item.legacy ? Boolean(user?.capabilities[item.legacy]) : false); return visible.length ? <div className="nav-group" key={section.group}><small>{section.group}</small>{visible.map(({to,label,icon:Icon})=><NavLink key={to} to={to} onClick={onNavigate} className={({isActive})=>`nav-item ${isActive?"active":""}`}><Icon size={17}/><span>{label}</span><ChevronRight size={14}/></NavLink>)}</div> : null; })}</nav>
    <div className="sidebar-note"><span className="status-dot" />只读诊断运行时<p>Web 只开放一个默认 Agent；底层保持多 Agent 模型。</p></div>
  </>;
}
