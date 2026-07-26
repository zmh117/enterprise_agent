import { useQuery } from "@tanstack/react-query"
import { z } from "zod"

import { apiRequest } from "@/shared/api/api-client"

const capabilitySummarySchema = z.object({
  capabilities: z.array(z.string()),
  modules: z.record(z.string(), z.array(z.string())),
})

export type AdminCapabilitySummary = z.infer<typeof capabilitySummarySchema>

export function useAdminCapabilitySummary() {
  return useQuery({
    queryKey: ["auth", "admin-capabilities"],
    queryFn: async () =>
      capabilitySummarySchema.parse(
        await apiRequest("/api/admin/capabilities"),
      ),
    retry: false,
    staleTime: 10_000,
  })
}
