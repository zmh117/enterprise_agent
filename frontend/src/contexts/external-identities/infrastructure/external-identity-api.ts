import { z } from "zod"

import {
  dingTalkBindingChallengeSchema,
  onesBindingChallengeSchema,
  selfExternalIdentityOverviewSchema,
  selfOnesStatusSchema,
} from "@/contexts/external-identities/domain/external-identity"
import { apiRequest } from "@/shared/api/api-client"

export async function getSelfExternalIdentities() {
  return selfExternalIdentityOverviewSchema.parse(
    await apiRequest("/api/me/external-identities")
  )
}

export async function beginSelfOnesBinding(input: {
  email: string
  password: string
}) {
  return z.object({ challenge: onesBindingChallengeSchema }).parse(
    await apiRequest("/api/me/external-identities/ones/challenges", {
      method: "POST",
      body: input,
    })
  ).challenge
}

export async function confirmSelfOnesBinding(input: {
  challenge_id: string
  default_team_id: string
  replace_existing: boolean
}) {
  return selfOnesStatusSchema.parse(
    await apiRequest("/api/me/external-identities/ones/confirm", {
      method: "POST",
      body: input,
    })
  )
}

export async function changeSelfOnesDefaultTeam(input: {
  default_team_id: string
  expected_identity_revision: number
}) {
  return selfOnesStatusSchema.parse(
    await apiRequest("/api/me/external-identities/ones/default-team", {
      method: "PUT",
      body: input,
    })
  )
}

export async function unbindSelfOnesBinding() {
  return z.object({ status: z.literal("unbound") }).parse(
    await apiRequest("/api/me/external-identities/ones", {
      method: "DELETE",
    })
  )
}

export async function beginSelfDingTalkBinding() {
  return z.object({ challenge: dingTalkBindingChallengeSchema }).parse(
    await apiRequest("/api/me/external-identities/dingtalk/challenges", {
      method: "POST",
    })
  ).challenge
}
