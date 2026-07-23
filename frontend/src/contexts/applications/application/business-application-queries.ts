import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"

import type {
  CreateApplicationInput,
  SaveDraftInput,
} from "@/contexts/applications/domain/business-application"
import {
  activatePublication,
  createApplication,
  deactivateEnvironment,
  getApplication,
  getCatalog,
  listApplications,
  publishDraft,
  saveDraft,
  updateApplication,
  validateDraft,
} from "@/contexts/applications/infrastructure/business-application-api"

export const applicationKeys = {
  all: ["business-applications"] as const,
  list: () => [...applicationKeys.all, "list"] as const,
  detail: (code: string) => [...applicationKeys.all, "detail", code] as const,
  catalog: (code: string) => [...applicationKeys.all, "catalog", code] as const,
}

export function useApplications() {
  return useQuery({
    queryKey: applicationKeys.list(),
    queryFn: listApplications,
    retry: false,
  })
}

export function useApplication(code: string) {
  return useQuery({
    queryKey: applicationKeys.detail(code),
    queryFn: () => getApplication(code),
    enabled: Boolean(code),
    retry: false,
  })
}

export function useApplicationCatalog(code: string) {
  return useQuery({
    queryKey: applicationKeys.catalog(code),
    queryFn: () => getCatalog(code),
    enabled: Boolean(code),
    retry: false,
  })
}

export function useCreateApplication() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateApplicationInput) => createApplication(input),
    onSuccess: (application) => {
      queryClient.setQueryData(applicationKeys.detail(application.code), application)
      void queryClient.invalidateQueries({ queryKey: applicationKeys.list() })
    },
  })
}

export function useUpdateApplication(code: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: Parameters<typeof updateApplication>[1]) =>
      updateApplication(code, input),
    onSuccess: (application) => {
      queryClient.setQueryData(applicationKeys.detail(code), application)
      void queryClient.invalidateQueries({ queryKey: applicationKeys.list() })
    },
  })
}

export function useSaveDraft(code: string) {
  return useRefreshApplicationMutation(code, (input: SaveDraftInput) =>
    saveDraft(code, input),
  )
}

export function useValidateDraft(code: string) {
  return useRefreshApplicationMutation(code, (revisionId: string) =>
    validateDraft(code, revisionId),
  )
}

export function usePublishDraft(code: string) {
  return useRefreshApplicationMutation(code, (revisionId: string) =>
    publishDraft(code, revisionId),
  )
}

export function useActivatePublication(code: string) {
  return useRefreshApplicationMutation(
    code,
    (input: {
      environment: string
      publicationId: string
      expectedRevision: number
    }) =>
      activatePublication(
        code,
        input.environment,
        input.publicationId,
        input.expectedRevision,
      ),
  )
}

export function useDeactivateEnvironment(code: string) {
  return useRefreshApplicationMutation(
    code,
    (input: { environment: string; expectedRevision: number }) =>
      deactivateEnvironment(code, input.environment, input.expectedRevision),
  )
}

function useRefreshApplicationMutation<TInput, TResult>(
  code: string,
  mutationFn: (input: TInput) => Promise<TResult>,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: applicationKeys.detail(code) })
      void queryClient.invalidateQueries({ queryKey: applicationKeys.list() })
    },
  })
}

