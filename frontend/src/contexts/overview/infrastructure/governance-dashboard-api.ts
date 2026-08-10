import { apiRequest } from "@/shared/api/api-client"

export type GovernanceDashboard = {
  captured_at: string
  modules: Array<{ code: string; count: number }>
  data_chain: string[]
}

export async function getGovernanceDashboard() {
  return apiRequest<GovernanceDashboard>("/api/admin/dashboard")
}
