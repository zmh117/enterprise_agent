import { LockKeyhole, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../../../app/providers/auth-provider";
import { Button, ErrorNotice, Field, Input } from "../../../shared/presentation/ui";
import { identityService } from "../application/services";

export function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const { refresh } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await identityService.login(username, password);
      await refresh();
      const state = location.state as { from?: string } | null;
      navigate(state?.from ?? "/admin/agents/default-diagnostic-agent", { replace: true });
    } catch (value) {
      setError(value);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-page">
      <section className="login-story">
        <div className="brand brand-login"><div className="brand-mark">EA</div><div><strong>Enterprise Agent</strong><span>治理与运行控制台</span></div></div>
        <div className="login-copy"><span className="eyebrow">Secure control plane</span><h1>把身份、权限与 Agent 发布放在同一条可信链路里。</h1><p>这里管理内部用户、钉钉身份、只读工具范围和默认诊断 Agent。所有运行任务都固定到不可变发布版本。</p></div>
        <div className="trust-list"><div><ShieldCheck /><span><strong>统一身份主体</strong>Web 与钉钉共享角色和数据范围</span></div><div><LockKeyhole /><span><strong>服务端安全会话</strong>Cookie、CSRF 与 revision 冲突保护</span></div></div>
      </section>
      <section className="login-panel">
        <form className="login-form" onSubmit={submit}>
          <div><span className="eyebrow">Administrator access</span><h2>登录管理台</h2><p>使用显式 bootstrap 或本地 seed 创建的管理员账户。</p></div>
          <ErrorNotice error={error} />
          <Field label="用户名"><Input autoFocus autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></Field>
          <Field label="密码"><Input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></Field>
          <Button type="submit" disabled={submitting}>{submitting ? "正在验证…" : "安全登录"}</Button>
          <p className="login-footnote">登录失败统一返回相同提示，避免泄露账户状态。</p>
        </form>
      </section>
    </div>
  );
}
