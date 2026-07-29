export type ProviderFieldType =
  "integer" | "secret_ref" | "string" | "tls" | "url"

export type ProviderField = {
  name: string
  type: ProviderFieldType
  required: boolean
  minimum?: number
  maximum?: number
}

export type ProviderContract = {
  provider_type: string
  contract_version: string
  resource_kind: "database" | "loki" | "redis"
  available: boolean
  unavailable_reason: string
  schema: {
    type: "object"
    additionalProperties: false
    fields: ProviderField[]
  }
}

export function parseProviderContractCatalog(
  payload: unknown
): ProviderContract[] {
  if (
    !payload ||
    typeof payload !== "object" ||
    !Array.isArray((payload as { contracts?: unknown }).contracts)
  ) {
    throw new Error("Provider 契约响应无效")
  }
  return (payload as { contracts: unknown[] }).contracts.map((item) => {
    if (
      !item ||
      typeof item !== "object" ||
      typeof (item as ProviderContract).provider_type !== "string" ||
      typeof (item as ProviderContract).contract_version !== "string" ||
      typeof (item as ProviderContract).available !== "boolean" ||
      !Array.isArray((item as ProviderContract).schema?.fields)
    ) {
      throw new Error("Provider 契约条目无效")
    }
    return item as ProviderContract
  })
}
