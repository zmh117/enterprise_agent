import { useMutation, useQuery } from "@tanstack/react-query"

import {
  createDebugJob,
  getDebugJobOptions,
} from "@/contexts/operations/infrastructure/debug-job-api"

export function useDebugJobOptions() {
  return useQuery({
    queryKey: ["operations", "debug-job-options"],
    queryFn: getDebugJobOptions,
  })
}

export function useCreateDebugJob() {
  return useMutation({ mutationFn: createDebugJob })
}
