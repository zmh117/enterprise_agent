import { createPublicKey, type KeyObject } from "node:crypto";

import { jwtVerify } from "jose";

import type {
  AgentExecutionRequestV1,
  RuntimeGrantClaims
} from "./generated/contracts.js";
import { assertContract } from "./generated/validators.js";

export class RuntimeGrantError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = "RuntimeGrantError";
  }
}

interface UsedGrant {
  readonly invocationId: string;
  readonly requestDigest: string;
  readonly expiresAt: number;
}

export class RuntimeGrantVerifier {
  private readonly usedJti = new Map<string, UsedGrant>();

  constructor(
    private readonly publicKey: KeyObject,
    private readonly now: () => number = () => Math.floor(Date.now() / 1000)
  ) {
    if (publicKey.asymmetricKeyType !== "ed25519") {
      throw new RuntimeGrantError(
        "runtime_grant_key_invalid",
        "Runtime Grant public key must use Ed25519"
      );
    }
  }

  static fromPem(pem: string, now?: () => number): RuntimeGrantVerifier {
    try {
      return new RuntimeGrantVerifier(createPublicKey(pem), now);
    } catch (error) {
      if (error instanceof RuntimeGrantError) throw error;
      throw new RuntimeGrantError(
        "runtime_grant_key_invalid",
        "Runtime Grant public key cannot be loaded"
      );
    }
  }

  async verify(token: string, request: AgentExecutionRequestV1): Promise<RuntimeGrantClaims> {
    if (!token || token.length > 16384) {
      throw new RuntimeGrantError("runtime_grant_invalid", "Runtime Grant is missing or too large");
    }
    let payload: unknown;
    try {
      ({ payload } = await jwtVerify(token, this.publicKey, {
        algorithms: ["EdDSA"],
        issuer: "enterprise-agent-worker",
        audience: "agent-runtime",
        clockTolerance: 5,
        currentDate: new Date(this.now() * 1000)
      }));
      assertContract("RuntimeGrantClaims", payload);
    } catch {
      throw new RuntimeGrantError(
        "runtime_grant_invalid",
        "Runtime Grant signature or claims are invalid"
      );
    }
    const claims = payload as RuntimeGrantClaims;
    if (
      claims.azp !== "agent-worker" ||
      claims.runtime_kind !== request.runtime_kind ||
      claims.sub !== request.app_user_id ||
      claims.job_id !== request.job_id ||
      claims.invocation_id !== request.invocation_id ||
      claims.agent_publication_id !== request.agent_publication_id ||
      claims.application_publication_id !== request.application_publication_id ||
      claims.request_digest !== request.request_digest
    ) {
      throw new RuntimeGrantError(
        "runtime_grant_binding_mismatch",
        "Runtime Grant is not bound to this execution request"
      );
    }
    if (
      claims.exp - claims.iat > request.limits.timeout_seconds + 60 ||
      claims.exp - claims.iat > 15 * 60
    ) {
      throw new RuntimeGrantError(
        "runtime_grant_ttl_invalid",
        "Runtime Grant lifetime exceeds the execution boundary"
      );
    }
    this.pruneExpiredJti();
    const existing = this.usedJti.get(claims.jti);
    if (
      existing &&
      (existing.invocationId !== request.invocation_id ||
        existing.requestDigest !== request.request_digest)
    ) {
      throw new RuntimeGrantError(
        "runtime_grant_replayed",
        "Runtime Grant JTI was already used by another execution"
      );
    }
    this.usedJti.set(claims.jti, {
      invocationId: request.invocation_id,
      requestDigest: request.request_digest,
      expiresAt: claims.exp
    });
    return claims;
  }

  private pruneExpiredJti(): void {
    const now = this.now();
    for (const [jti, binding] of this.usedJti) {
      if (binding.expiresAt < now - 5) this.usedJti.delete(jti);
    }
  }
}
