import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import type {
  DingTalkChannelInput,
  WebhookChannelInput,
} from "@/contexts/applications/domain/managed-channel"
import {
  createDingTalkChannel,
  createWebhookChannel,
  deleteManagedChannel,
  listEligibleChannels,
  listManagedChannels,
  listWebhookConnectorOptions,
  restartManagedChannel,
  setManagedChannelEnabled,
  testManagedChannel,
  updateDingTalkChannel,
} from "@/contexts/applications/infrastructure/managed-channel-api"

export const managedChannelKeys = {
  all: ["managed-channels"] as const,
  list: () => [...managedChannelKeys.all, "list"] as const,
  eligible: (triggerType: string) =>
    [...managedChannelKeys.all, "eligible", triggerType] as const,
  webhookConnectorOptions: () =>
    [...managedChannelKeys.all, "webhook-connector-options"] as const,
}

export function useManagedChannels(enabled = true) {
  return useQuery({
    queryKey: managedChannelKeys.list(),
    queryFn: listManagedChannels,
    enabled,
    retry: false,
    refetchInterval: enabled ? 3000 : false,
  })
}

export function useEligibleChannels(triggerType: string) {
  return useQuery({
    queryKey: managedChannelKeys.eligible(triggerType),
    queryFn: () => listEligibleChannels(triggerType),
    enabled: Boolean(triggerType),
    retry: false,
  })
}

export function useWebhookConnectorOptions() {
  return useQuery({
    queryKey: managedChannelKeys.webhookConnectorOptions(),
    queryFn: listWebhookConnectorOptions,
    retry: false,
  })
}

export function useCreateDingTalkChannel() {
  return useRefreshChannelsMutation(createDingTalkChannel)
}

export function useUpdateDingTalkChannel(connectorId: string) {
  return useRefreshChannelsMutation((input: DingTalkChannelInput) =>
    updateDingTalkChannel(connectorId, input)
  )
}

export function useCreateWebhookChannel() {
  return useRefreshChannelsMutation((input: WebhookChannelInput) =>
    createWebhookChannel(input)
  )
}

export function useSetManagedChannelEnabled() {
  return useRefreshChannelsMutation(
    (input: { channelId: string; revision: number; enabled: boolean }) =>
      setManagedChannelEnabled(input.channelId, input.revision, input.enabled)
  )
}

export function useRestartManagedChannel() {
  return useRefreshChannelsMutation(
    (input: { channelId: string; revision: number }) =>
      restartManagedChannel(input.channelId, input.revision)
  )
}

export function useTestManagedChannel() {
  return useRefreshChannelsMutation((channelId: string) =>
    testManagedChannel(channelId)
  )
}

export function useDeleteManagedChannel() {
  return useRefreshChannelsMutation(
    (input: { channelId: string; revision: number }) =>
      deleteManagedChannel(input.channelId, input.revision)
  )
}

function useRefreshChannelsMutation<TInput, TResult>(
  mutationFn: (input: TInput) => Promise<TResult>
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: managedChannelKeys.all })
      void queryClient.invalidateQueries({
        queryKey: ["business-applications"],
      })
    },
  })
}
