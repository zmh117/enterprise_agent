import { request, withQuery } from "@enterprise-agent/api-client";
import type { AttachmentSummary, ConversationDetail, ConversationSummary, Dashboard, JobDetail, JobSummary, OperationsFilters, Page, QueueSnapshot } from "../domain/models";

export const operationsRepository = {
  dashboard: (filters: OperationsFilters = {}) => request<Dashboard>(withQuery("/api/admin/dashboard", filters)),
  queues: () => request<QueueSnapshot>("/api/admin/queues"),
  jobs: (filters: OperationsFilters = {}) => request<Page<JobSummary>>(withQuery("/api/admin/jobs", filters)),
  job: (id: string) => request<JobDetail>(`/api/admin/jobs/${id}`),
  conversations: (filters: OperationsFilters = {}) => request<Page<ConversationSummary>>(withQuery("/api/admin/conversations", filters)),
  conversation: (id: string) => request<ConversationDetail>(`/api/admin/conversations/${id}`),
  attachments: (filters: OperationsFilters = {}) => request<Page<AttachmentSummary>>(withQuery("/api/admin/attachments", filters)),
  attachment: (id: string) => request<{ attachment: AttachmentSummary }>(`/api/admin/attachments/${id}`),
};
