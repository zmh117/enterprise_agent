import { createHash } from "node:crypto";
import { isIP } from "node:net";
import { lookup } from "node:dns/promises";

import type {
  DraftModelProbeRequest,
  ModelConnectionBinding
} from "./generated/contracts.js";
import { assertSafeRemoteUrl, type RuntimeConfig } from "./config.js";
import {
  PlatformSecretDecryptor,
  type EncryptedPlatformSecret
} from "./platform-secret.js";
import {
  ModelProbeEnvelopeDecryptor,
  ModelProbeEnvelopeError
} from "./model-probe-envelope.js";

export interface RuntimeSqlClient {
  query<T extends Record<string, unknown>>(
    sql: string,
    values: readonly unknown[]
  ): Promise<{ rows: T[] }>;
}

export interface ResolvedModelBinding {
  readonly protocol: "anthropic_compatible";
  readonly baseUrl: string;
  readonly model: string;
  readonly defaultOpusModel: string;
  readonly defaultSonnetModel: string;
  readonly defaultHaikuModel: string;
  readonly subagentModel: string;
  readonly effortLevel: "low" | "medium" | "high" | "max";
  readonly connectionRevisionId: string;
  readonly configHash: string;
  readonly apiKey: string;
}

export interface ModelBindingRequest {
  readonly model_connection: ModelConnectionBinding;
}

interface ModelBindingRow extends Record<string, unknown> {
  revision_id: string;
  revision_status: string;
  connection_status: string;
  connection_protocol: string;
  config_json: string;
  config_hash: string;
  secret_id: string;
  secret_provider: string;
  secret_status: string;
  active_version: number;
  ciphertext: string;
  nonce: string;
  key_id: string;
  algorithm: string;
  version_status: string;
}

type DnsLookup = (hostname: string) => Promise<readonly string[]>;

const CONFIG_FIELDS = new Set([
  "schema_version",
  "protocol",
  "base_url",
  "model",
  "default_opus_model",
  "default_sonnet_model",
  "default_haiku_model",
  "subagent_model",
  "effort_level"
]);

export class ModelBindingError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = "ModelBindingError";
  }
}

function canonicalConfigHash(config: Record<string, unknown>): string {
  const canonical = JSON.stringify(
    Object.fromEntries(Object.entries(config).sort(([left], [right]) => left.localeCompare(right)))
  );
  return createHash("sha256").update(canonical, "utf8").digest("hex");
}

function requiredModel(config: Record<string, unknown>, field: string): string {
  const value = String(config[field] ?? "").trim();
  if (!value || value.length > 200 || [...value].some((character) => character.charCodeAt(0) < 32)) {
    throw new ModelBindingError("runtime_model_config_invalid", `${field} is invalid`);
  }
  return value;
}

function addressIsPublic(address: string): boolean {
  const family = isIP(address);
  if (family === 4) {
    const parts = address.split(".").map(Number);
    const [a = -1, b = -1] = parts;
    return !(
      a === 0 ||
      a === 10 ||
      a === 127 ||
      (a === 100 && b >= 64 && b <= 127) ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) ||
      (a === 198 && (b === 18 || b === 19)) ||
      a >= 224
    );
  }
  if (family === 6) {
    const normalized = address.toLowerCase();
    return !(
      normalized === "::" ||
      normalized === "::1" ||
      normalized.startsWith("fc") ||
      normalized.startsWith("fd") ||
      /^fe[89ab]/.test(normalized) ||
      normalized.startsWith("ff")
    );
  }
  return false;
}

async function defaultDnsLookup(hostname: string): Promise<readonly string[]> {
  return (await lookup(hostname, { all: true, verbatim: true })).map((item) => item.address);
}

export class ModelBindingResolver {
  constructor(
    private readonly database: RuntimeSqlClient,
    private readonly decryptor: PlatformSecretDecryptor,
    private readonly config: RuntimeConfig,
    private readonly dnsLookup: DnsLookup = defaultDnsLookup,
    private readonly probeEnvelopes?: ModelProbeEnvelopeDecryptor
  ) {}

  async resolve(request: ModelBindingRequest): Promise<ResolvedModelBinding> {
    const result = await this.database.query<ModelBindingRow>(
      `SELECT
         r.id AS revision_id,
         r.status AS revision_status,
         c.status AS connection_status,
         c.protocol AS connection_protocol,
         r.config_json,
         r.config_hash,
         s.id AS secret_id,
         s.provider AS secret_provider,
         s.status AS secret_status,
         s.active_version,
         v.ciphertext,
         v.nonce,
         v.key_id,
         v.algorithm,
         v.status AS version_status
       FROM model_connection_revision r
       JOIN model_connection c ON c.id = r.connection_id
       JOIN platform_secret s ON s.id = r.api_key_secret_id
       JOIN platform_secret_version v
         ON v.secret_id = s.id AND v.version = s.active_version
       WHERE r.id = $1`,
      [request.model_connection.revision_id]
    );
    if (result.rows.length !== 1) {
      throw new ModelBindingError(
        "runtime_model_binding_unavailable",
        "Frozen model connection revision is unavailable"
      );
    }
    const row = result.rows[0] as ModelBindingRow;
    if (
      row.revision_status !== "ready" ||
      row.connection_status !== "ready" ||
      row.secret_provider !== "encrypted_db" ||
      row.secret_status !== "enabled" ||
      row.version_status !== "active"
    ) {
      throw new ModelBindingError(
        "runtime_model_binding_disabled",
        "Frozen model connection or credential is not active"
      );
    }
    if (
      row.revision_id !== request.model_connection.revision_id ||
      row.config_hash !== request.model_connection.config_hash
    ) {
      throw new ModelBindingError(
        "runtime_model_binding_mismatch",
        "Frozen model connection does not match the execution request"
      );
    }
    let modelConfig: Record<string, unknown>;
    try {
      const parsed = JSON.parse(row.config_json) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
      modelConfig = parsed as Record<string, unknown>;
    } catch {
      throw new ModelBindingError(
        "runtime_model_config_invalid",
        "Model connection configuration is not valid JSON"
      );
    }
    if (row.connection_protocol !== "anthropic_compatible") {
      throw new ModelBindingError(
        "runtime_model_config_integrity_failed",
        "Model connection configuration failed integrity validation"
      );
    }
    const encryptedSecret: EncryptedPlatformSecret = {
      secretId: row.secret_id,
      version: Number(row.active_version),
      ciphertext: row.ciphertext,
      nonce: row.nonce,
      keyId: row.key_id,
      algorithm: row.algorithm
    };
    return this.resolveConfig(
      modelConfig,
      row.revision_id,
      row.config_hash,
      this.decryptor.decrypt(encryptedSecret)
    );
  }

  async resolveDraft(request: DraftModelProbeRequest): Promise<ResolvedModelBinding> {
    if (!this.probeEnvelopes) {
      throw new ModelBindingError(
        "model_connection_test_unavailable",
        "Draft model probe encryption is unavailable"
      );
    }
    try {
      const decrypted = this.probeEnvelopes.decrypt(request);
      return await this.resolveConfig(
        decrypted.config,
        `draft-${request.probe_id}`,
        request.config_hash,
        decrypted.apiKey
      );
    } catch (error) {
      if (error instanceof ModelBindingError) throw error;
      if (error instanceof ModelProbeEnvelopeError) {
        throw new ModelBindingError(error.code, error.message);
      }
      throw new ModelBindingError(
        "model_connection_probe_envelope_invalid",
        "Draft model probe envelope is invalid"
      );
    }
  }

  private async resolveConfig(
    modelConfig: Record<string, unknown>,
    connectionRevisionId: string,
    configHash: string,
    apiKey: string
  ): Promise<ResolvedModelBinding> {
    if (
      [...Object.keys(modelConfig)].some((field) => !CONFIG_FIELDS.has(field)) ||
      Object.keys(modelConfig).length !== CONFIG_FIELDS.size ||
      modelConfig.schema_version !== 1 ||
      modelConfig.protocol !== "anthropic_compatible" ||
      canonicalConfigHash(modelConfig) !== configHash
    ) {
      throw new ModelBindingError(
        "runtime_model_config_integrity_failed",
        "Model connection configuration failed integrity validation"
      );
    }
    const providerUrl = assertSafeRemoteUrl(
      String(modelConfig.base_url ?? ""),
      this.config.providerAllowedHosts,
      "model"
    );
    if (
      providerUrl.port &&
      providerUrl.port !== "443" ||
      providerUrl.search ||
      !providerUrl.pathname.endsWith("/anthropic") ||
      providerUrl.pathname.includes("//")
    ) {
      throw new ModelBindingError(
        "runtime_model_url_invalid",
        "Model provider URL does not satisfy the Anthropic-compatible boundary"
      );
    }
    const addresses = await this.dnsLookup(providerUrl.hostname);
    if (addresses.length === 0 || addresses.some((address) => !addressIsPublic(address))) {
      throw new ModelBindingError(
        "runtime_model_dns_rejected",
        "Model provider DNS resolved outside the public network boundary"
      );
    }
    const effort = String(modelConfig.effort_level ?? "");
    if (!new Set(["low", "medium", "high", "max"]).has(effort)) {
      throw new ModelBindingError(
        "runtime_model_config_invalid",
        "Model effort level is invalid"
      );
    }
    return {
      protocol: "anthropic_compatible",
      baseUrl: providerUrl.toString().replace(/\/$/, ""),
      model: requiredModel(modelConfig, "model"),
      defaultOpusModel: requiredModel(modelConfig, "default_opus_model"),
      defaultSonnetModel: requiredModel(modelConfig, "default_sonnet_model"),
      defaultHaikuModel: requiredModel(modelConfig, "default_haiku_model"),
      subagentModel: requiredModel(modelConfig, "subagent_model"),
      effortLevel: effort as ResolvedModelBinding["effortLevel"],
      connectionRevisionId,
      configHash,
      apiKey
    };
  }
}
