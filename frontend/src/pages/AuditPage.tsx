import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { Badge, Button, Card, ErrorNotice, PageHeader, formatTime } from "../components/ui";
import { api } from "../lib/api";
import type { AuditEvent } from "../lib/types";

export function AuditPage() {
  const query = useQuery({ queryKey: ["audit-events"], queryFn: () => api<{ events: AuditEvent[] }>("/api/admin/audit-events?limit=300") });
  return <><PageHeader eyebrow="Security evidence" title="安全审计" description="只显示内部 actor、脱敏摘要和授权/发布生命周期事件。" actions={<Button variant="secondary" onClick={() => query.refetch()}><RefreshCw size={16} />刷新</Button>} /><ErrorNotice error={query.error} /><Card><div className="table-wrap"><table><thead><tr><th>时间</th><th>状态</th><th>事件</th><th>Actor</th><th>摘要</th></tr></thead><tbody>{query.data?.events.map((event) => <tr key={event.id}><td>{formatTime(event.created_at)}</td><td><Badge tone={event.status === "SUCCEEDED" ? "good" : event.status === "DENIED" || event.status === "FAILED" ? "bad" : "neutral"}>{event.status}</Badge></td><td><code>{event.event_type}</code></td><td>{event.actor_id || "system"}</td><td>{event.summary}</td></tr>)}</tbody></table></div></Card></>;
}
