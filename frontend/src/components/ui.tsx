import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, PropsWithChildren, ReactNode } from "react";

export function Button({ className = "", variant = "primary", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" }) {
  return <button className={`button button-${variant} ${className}`} {...props} />;
}

export function Card({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`card ${className}`} {...props} />;
}

export function Badge({ tone = "neutral", children }: PropsWithChildren<{ tone?: "good" | "bad" | "warn" | "neutral" }>) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input className="input" {...props} />;
}

export function EmptyState({ title, message }: { title: string; message: string }) {
  return <div className="empty-state"><strong>{title}</strong><span>{message}</span></div>;
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const value = error as { message?: string; code?: string; fieldErrors?: Array<{ field?: string; message?: string }> };
  return (
    <div className="notice notice-error" role="alert">
      <strong>{value.code === "revision_conflict" ? "版本已经变化，请刷新后重试" : value.message ?? "请求未完成"}</strong>
      {value.fieldErrors?.map((item, index) => <span key={`${item.field}-${index}`}>{item.field ? `${item.field}：` : ""}{item.message}</span>)}
    </div>
  );
}

export function formatTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}
