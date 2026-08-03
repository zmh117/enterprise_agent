import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import type {
  DingTalkChannelInput,
  WebhookChannelInput,
} from "@/contexts/applications/domain/managed-channel"
import {
  createDingTalkEnterprise,
  createDingTalkChannel,
  createWebhookChannel,
  deleteManagedChannel,
  getDingTalkEnterprise,
  governDingTalkEnterprise,
  listDingTalkEnterprises,
  listEligibleChannels,
  listManagedChannels,
  listWebhookConnectorOptions,
  restartManagedChannel,
  renameDingTalkEnterprise,
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
  enterprises: () =>
    [...managedChannelKeys.all, "dingtalk-enterprises"] as const,
  enterprise: (enterpriseId: string) =>
    [...managedChannelKeys.enterprises(), enterpriseId] as const,
}

export function useDingTalkEnterprises() {
  return useQuery({
    queryKey: managedChannelKeys.enterprises(),
    queryFn: listDingTalkEnterprises,
    retry: false,
  })
}

export function useDingTalkEnterprise(enterpriseId: string) {
  return useQuery({
    queryKey: managedChannelKeys.enterprise(enterpriseId),
    queryFn: () => getDingTalkEnterprise(enterpriseId),
    enabled: Boolean(enterpriseId),
    retry: false,
  })
}

export function useCreateDingTalkEnterprise() {
  return useRefreshChannelsMutation((name: string) =>
    createDingTalkEnterprise(name)
  )
}

export function useRenameDingTalkEnterprise() {
  return useRefreshChannelsMutation(
    (input: { enterpriseId: string; name: string; expectedRevision: number }) =>
      renameDingTalkEnterprise(
        input.enterpriseId,
        input.name,
        input.expectedRevision
      )
  )
}

export function useGovernDingTalkEnterprise() {
  return useRefreshChannelsMutation(
    (input: {
      enterpriseId: string
      action: "disable" | "archive" | "restore"
      expectedRevision: number
    }) =>
      governDingTalkEnterprise(
        input.enterpriseId,
        input.action,
        input.expectedRevision
      )
  )
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
