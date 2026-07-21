export type Availability = "available" | "unavailable";
export type Dashboard = {
  window: { start: string; end: string };
  generated_at: string;
  summary: { users: number; agents: number; channels: number; jobs: number; exceptions: number };
  jobs: { counts: Record<string, number>; retry_wait: number; failed: number; timeout: number; delivery_failed: number; recent_exceptions: JobSummary[] };
  queues: QueueSnapshot;
  recent_conversations: ConversationSummary[];
  recent_webhooks: Array<Record<string, unknown>>;
};
export type JobSummary = { id: string; status: string; project_code: string; source_channel: string; error_summary: string; created_at: string };
export type JobDetail = { job: JobSummary & { session_id: string; agent_code: string; retry_count: number; max_retry_count: number; finished_at?: string; correlation_id?: string }; session_ref: {id:string}; steps: Array<Record<string, unknown>>; tool_calls: Array<Record<string, unknown>>; delivery_attempts: Array<Record<string, unknown>>; webhook_events: Array<Record<string, unknown>>; retry: {count:number;max:number;waiting:boolean} };
export type QueueItem = { name: string; purpose: string; ready: number | null; unacked: number | null; consumers: number | null; availability: Availability; retry_of: string | null; dead_letter_of: string | null };
export type QueueSnapshot = { availability: Availability; collected_at: string; error: { code: string; message: string } | null; items: QueueItem[] };
export type ConversationSummary = { id: string; requester_display_name?: string; requester_id: string; source_channel: string; external_conversation_id: string; updated_at: string; job_count?: number; latest_job_status?: string };
export type AttachmentSummary = { id: string; file_name: string; declared_mime: string; detected_mime: string; size_bytes: number | null; status: string; created_at: string; storage_configured: boolean; text_preview: string };
export type ConversationDetail = { session: ConversationSummary & {created_at?:string}; messages:Array<{id:string;role:string;content:string;message_type:string;created_at:string}>; jobs:JobSummary[]; attachments:AttachmentSummary[]; delivery_refs:Array<{job_id:string;href:string}> };
export type OperationsFilters = Record<string, string | number | undefined>;
export type Page<T> = { items: T[]; page: { limit: number; has_more: boolean; next_cursor: string | null } };
