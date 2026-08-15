import { useQuery } from "@tanstack/react-query"

import {
  getConversation,
  getFileOperations,
  getRuntimeJob,
  listRuntimeJobs,
  type RuntimeJobFilters,
} from "@/contexts/operations/infrastructure/runtime-record-api"

export function useRuntimeJobs(filters: RuntimeJobFilters = {}) {
  return useQuery({
    queryKey: ["operations", "jobs", filters],
    queryFn: () => listRuntimeJobs(filters),
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

export function useFileOperations() {
  return useQuery({
    queryKey: ["operations", "file-operations"],
    queryFn: getFileOperations,
    refetchInterval: 30_000,
  })
}
