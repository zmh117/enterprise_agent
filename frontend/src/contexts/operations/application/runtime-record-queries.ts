import { useQuery } from "@tanstack/react-query"

import {
  getAdminRuntimeJob,
  getConversation,
  getRuntimeJob,
  listAdminRuntimeJobs,
  listRuntimeJobs,
} from "@/contexts/operations/infrastructure/runtime-record-api"

export function useRuntimeJobs() {
  return useQuery({
    queryKey: ["operations", "jobs"],
    queryFn: listRuntimeJobs,
  })
}

export function useRuntimeJob(jobId: string) {
  return useQuery({
    queryKey: ["operations", "jobs", jobId],
    queryFn: () => getRuntimeJob(jobId),
    enabled: Boolean(jobId),
  })
}

export function useConversation(sessionId: string) {
  return useQuery({
    queryKey: ["operations", "conversations", sessionId],
    queryFn: () => getConversation(sessionId),
    enabled: Boolean(sessionId),
  })
}

export function useAdminRuntimeJobs() {
  return useQuery({
    queryKey: ["admin", "operations", "jobs"],
    queryFn: listAdminRuntimeJobs,
  })
}

export function useAdminRuntimeJob(jobId: string) {
  return useQuery({
    queryKey: ["admin", "operations", "jobs", jobId],
    queryFn: () => getAdminRuntimeJob(jobId),
    enabled: Boolean(jobId),
  })
}
