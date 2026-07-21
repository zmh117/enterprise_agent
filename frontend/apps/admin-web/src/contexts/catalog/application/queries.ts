import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { catalogRepository } from "../infrastructure/catalog-repository";

export const useSkillCatalog = () => useQuery({ queryKey: ["catalog", "skills"], queryFn: catalogRepository.skills });
export const useToolCatalog = () => ({
  providers: useQuery({ queryKey: ["catalog", "tool-providers"], queryFn: catalogRepository.toolProviders }),
  resources: useQuery({ queryKey: ["catalog", "tool-resources"], queryFn: catalogRepository.toolResources }),
});
export const useChannelCatalog = () => ({
  providers: useQuery({ queryKey: ["catalog", "channel-providers"], queryFn: catalogRepository.channelProviders }),
  connectors: useQuery({ queryKey: ["catalog", "connectors"], queryFn: catalogRepository.connectors }),
});

export function useManagedSecrets() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["catalog", "managed-secrets"], queryFn: catalogRepository.secrets });
  const create = useMutation({ mutationFn: catalogRepository.createSecret, onSuccess: () => client.invalidateQueries({ queryKey: ["catalog", "managed-secrets"] }) });
  return { query, create };
}

export function useToolCommands() {
  const client = useQueryClient();
  const invalidate = () => client.invalidateQueries({ queryKey: ["catalog", "tool-resources"] });
  return {
    save: useMutation({ mutationFn: catalogRepository.saveToolResource, onSuccess: invalidate }),
    status: useMutation({ mutationFn: catalogRepository.setToolResourceStatus, onSuccess: invalidate }),
    test: useMutation({ mutationFn: catalogRepository.testToolResource }),
  };
}

export function useChannelCommands() {
  const client = useQueryClient();
  const invalidate = () => client.invalidateQueries({ queryKey: ["catalog", "connectors"] });
  return {
    save: useMutation({ mutationFn: catalogRepository.saveConnector, onSuccess: invalidate }),
    status: useMutation({ mutationFn: catalogRepository.setConnectorStatus, onSuccess: invalidate }),
    validate: useMutation({ mutationFn: catalogRepository.validateConnector }),
  };
}
