import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import type {
  ApplicationDraftInput,
  Environment,
} from "@/contexts/applications/domain/business-application"
import {
  activateBusinessApplication,
  deactivateBusinessApplication,
  getApplicationCatalog,
  getApplicationEffective,
  getBusinessApplication,
  listBusinessApplications,
  publishBusinessApplication,
  saveApplicationDraft,
  updateBusinessApplication,
  validateBusinessApplication,
} from "@/contexts/applications/infrastructure/business-application-api"

export const applicationKeys = {
  all: ["admin", "business-applications"] as const,
  detail: (code: string) => ["admin", "business-applications", code] as const,
  catalog: (code: string) =>
    ["admin", "business-applications", code, "catalog"] as const,
  effective: (code: string, environment: Environment) =>
    ["admin", "business-applications", code, environment, "effective"] as const,
}

export function useBusinessApplications() {
  return useQuery({
    queryKey: applicationKeys.all,
    queryFn: listBusinessApplications,
  })
}

export function useBusinessApplication(code: string) {
  return useQuery({
    queryKey: applicationKeys.detail(code),
    queryFn: () => getBusinessApplication(code),
    enabled: Boolean(code),
  })
}

export function useApplicationCatalog(code: string) {
  return useQuery({
    queryKey: applicationKeys.catalog(code),
    queryFn: () => getApplicationCatalog(code),
    enabled: Boolean(code),
  })
}

export function useApplicationEffective(
  code: string,
  environment: Environment,
  enabled = true
) {
  return useQuery({
    queryKey: applicationKeys.effective(code, environment),
    queryFn: () => getApplicationEffective(code, environment),
    enabled: enabled && Boolean(code),
    retry: false,
  })
}

export function useBusinessApplicationActions(code: string) {
  const client = useQueryClient()
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: applicationKeys.all }),
      client.invalidateQueries({ queryKey: applicationKeys.detail(code) }),
      client.invalidateQueries({
        queryKey: applicationKeys.effective(code, "test"),
      }),
      client.invalidateQueries({
        queryKey: applicationKeys.effective(code, "production"),
      }),
    ])
  }
  return {
    update: useMutation({
      mutationFn: (input: Parameters<typeof updateBusinessApplication>[1]) =>
        updateBusinessApplication(code, input),
      onSuccess: refresh,
    }),
    saveDraft: useMutation({
      mutationFn: (input: {
        expectedRevision: number
        draft: ApplicationDraftInput
      }) => saveApplicationDraft(code, input.expectedRevision, input.draft),
      onSuccess: refresh,
    }),
    validate: useMutation({
      mutationFn: (input: { revisionId: string; expectedRevision: number }) =>
        validateBusinessApplication(
          code,
          input.revisionId,
          input.expectedRevision
        ),
      onSuccess: refresh,
    }),
    publish: useMutation({
      mutationFn: (input: { revisionId: string; expectedRevision: number }) =>
        publishBusinessApplication(
          code,
          input.revisionId,
          input.expectedRevision
        ),
      onSuccess: refresh,
    }),
    activate: useMutation({
      mutationFn: (input: {
        environment: Environment
        publicationId: string
        expectedRevision: number
      }) =>
        activateBusinessApplication(
          code,
          input.environment,
          input.publicationId,
          input.expectedRevision
        ),
      onSuccess: refresh,
    }),
    deactivate: useMutation({
      mutationFn: (input: {
        environment: Environment
        expectedRevision: number
      }) =>
        deactivateBusinessApplication(
          code,
          input.environment,
          input.expectedRevision
        ),
      onSuccess: refresh,
    }),
  }
}
