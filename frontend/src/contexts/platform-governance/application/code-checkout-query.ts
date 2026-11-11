import { useQuery } from "@tanstack/react-query"
import { z } from "zod"
import { apiRequest } from "@/shared/api/api-client"

export const codeOperationSchema = z.object({
  id: z.string(),
  operation_kind: z.string(),
  state: z.string(),
  error_code: z.string().nullable(),
  result_expired: z.boolean().optional(),
  result: z.object({
    revision: z.number().optional(),
    operative_revision: z.number().optional(),
    directories: z.array(z.string()).optional(),
    files: z.array(z.string()).optional(),
    directory_path: z.string().optional(),
    depth: z.literal("immediates").optional(),
    relative_dir: z.string().optional(),
    checkout_id: z.string().optional(),
    diagnostic: z
      .object({
        operation: z.enum([
          "info",
          "log",
          "cat",
          "diff",
          "propget",
          "list",
          "blame",
          "status",
          "checkout",
          "update",
          "unknown",
        ]),
        exit_code: z.number().int().min(-255).max(255).nullable(),
        svn_error_codes: z.array(z.string().regex(/^E[0-9]{6}$/)).max(8),
      })
      .optional(),
  }),
})
const snapshotSchema = z.object({
  enabled: z.boolean(),
  registrations: z.array(
    z.object({
      id: z.string(),
      url: z.string(),
      kind: z.enum(["deployment", "account", "anonymous"]),
    })
  ),
  jobs: z.array(codeOperationSchema),
  checkouts: z.array(
    z.object({
      id: z.string(),
      source_id: z.string(),
      relative_dir: z.string(),
      state: z.string(),
      verified_revision: z.number().nullable(),
      generation: z.number(),
      writer_operation_id: z.string().nullable(),
      selected_paths: z.array(z.string()),
      readers: z.number(),
      connection: z
        .object({
          id: z.string(),
          url: z.string(),
          kind: z.enum(["deployment", "account", "anonymous"]),
        })
        .nullable(),
      connection_error: z.string().nullable(),
    })
  ),
})
export function useCodeCheckouts(resourceId: string, enabled = true) {
  return useQuery({
    queryKey: ["code-checkouts", resourceId],
    enabled,
    retry: false,
    refetchInterval: 3000,
    queryFn: async () =>
      snapshotSchema.parse(
        await apiRequest(
          `/api/platform/knowledge/code/resources/${encodeURIComponent(resourceId)}/checkouts`
        )
      ),
  })
}
