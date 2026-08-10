import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";

export const EXPECTED_SDK_VERSION = "0.3.226";
export const EXPECTED_CLI_VERSION = "2.1.226";

const require = createRequire(import.meta.url);

function installedSdkVersion(): string {
  const entrypoint = require.resolve("@anthropic-ai/claude-agent-sdk");
  const packagePath = resolve(dirname(entrypoint), "package.json");
  const payload = JSON.parse(readFileSync(packagePath, "utf8")) as { version?: unknown };
  return typeof payload.version === "string" ? payload.version : "unknown";
}

export interface RuntimeConfig {
  readonly host: string;
  readonly port: number;
  readonly logLevel: "debug" | "info" | "warn" | "error";
  readonly grantPublicKeyFile: string;
  readonly modelProbeTokenFile: string;
  readonly databaseUrl: string;
  readonly masterKeyFile: string;
  readonly providerAllowedHosts: ReadonlySet<string>;
  readonly mcpAllowedHosts: ReadonlySet<string>;
  readonly ledgerTtlSeconds: number;
  readonly cliVersion: typeof EXPECTED_CLI_VERSION;
}

const RUNTIME_ENV_PREFIXES = [
  "AGENT_RUNTIME_",
  "RUNTIME_GRANT_",
  "MODEL_PROVIDER_",
  "MODEL_PROBE_",
  "MCP_SERVER_",
  "APP_CONFIG_"
];

const ALLOWED_ENV = new Set([
  "AGENT_RUNTIME_HOST",
  "AGENT_RUNTIME_PORT",
  "AGENT_RUNTIME_LOG_LEVEL",
  "AGENT_RUNTIME_LEDGER_TTL_SECONDS",
  "AGENT_RUNTIME_CLI_VERSION",
  "RUNTIME_GRANT_PUBLIC_KEY_FILE",
  "MODEL_PROBE_AUTH_TOKEN_FILE",
  "DATABASE_URL",
  "APP_CONFIG_MASTER_KEY_FILE",
  "MODEL_PROVIDER_ALLOWED_HOSTS",
  "MCP_SERVER_ALLOWED_HOSTS"
]);

export class RuntimeConfigError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = "RuntimeConfigError";
  }
}

function required(env: NodeJS.ProcessEnv, name: string): string {
  const value = env[name]?.trim();
  if (!value) {
    throw new RuntimeConfigError("runtime_config_missing", `${name} is required`);
  }
  return value;
}

function integer(
  env: NodeJS.ProcessEnv,
  name: string,
  fallback: number,
  minimum: number,
  maximum: number
): number {
  const raw = env[name]?.trim();
  const value = raw ? Number(raw) : fallback;
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new RuntimeConfigError(
      "runtime_config_invalid",
      `${name} must be an integer from ${minimum} to ${maximum}`
    );
  }
  return value;
}

function hostSet(value: string, name: string): ReadonlySet<string> {
  const hosts = value
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
  if (hosts.length === 0 || hosts.some((host) => host.includes(":"))) {
    throw new RuntimeConfigError(
      "runtime_config_invalid",
      `${name} must contain hostnames without schemes or ports`
    );
  }
  return new Set(hosts);
}

export function assertSafeRemoteUrl(
  rawUrl: string,
  allowedHosts: ReadonlySet<string>,
  purpose: "model" | "mcp"
): URL {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new RuntimeConfigError("runtime_remote_url_invalid", `${purpose} URL is invalid`);
  }
  const hostname = url.hostname.toLowerCase();
  const loopback = hostname === "127.0.0.1" || hostname === "localhost" || hostname === "::1";
  const internalMcpHttp = purpose === "mcp" && url.protocol === "http:" && allowedHosts.has(hostname);
  if (
    url.protocol !== "https:" &&
    !(url.protocol === "http:" && loopback) &&
    !internalMcpHttp
  ) {
    throw new RuntimeConfigError(
      "runtime_remote_url_insecure",
      `${purpose} URL must use HTTPS outside loopback or an explicitly allowlisted MCP service`
    );
  }
  if (url.username || url.password || url.hash) {
    throw new RuntimeConfigError(
      "runtime_remote_url_credentials_forbidden",
      `${purpose} URL cannot contain credentials or fragments`
    );
  }
  if (!allowedHosts.has(hostname)) {
    throw new RuntimeConfigError(
      "runtime_remote_host_not_allowed",
      `${purpose} host is outside the deployment allowlist`
    );
  }
  return url;
}

export function loadRuntimeConfig(env: NodeJS.ProcessEnv = process.env): RuntimeConfig {
  const unknown = Object.keys(env)
    .filter((name) => RUNTIME_ENV_PREFIXES.some((prefix) => name.startsWith(prefix)))
    .filter((name) => !ALLOWED_ENV.has(name));
  if (unknown.length > 0) {
    throw new RuntimeConfigError(
      "runtime_config_unknown",
      `unknown runtime environment settings: ${unknown.sort().join(", ")}`
    );
  }
  const sdkVersion = installedSdkVersion();
  if (sdkVersion !== EXPECTED_SDK_VERSION) {
    throw new RuntimeConfigError(
      "runtime_sdk_version_mismatch",
      `installed Claude Agent SDK ${sdkVersion} does not match ${EXPECTED_SDK_VERSION}`
    );
  }
  const cliVersion = env.AGENT_RUNTIME_CLI_VERSION?.trim() || EXPECTED_CLI_VERSION;
  if (cliVersion !== EXPECTED_CLI_VERSION) {
    throw new RuntimeConfigError(
      "runtime_cli_version_mismatch",
      `Claude CLI ${cliVersion} does not match ${EXPECTED_CLI_VERSION}`
    );
  }
  const logLevel = env.AGENT_RUNTIME_LOG_LEVEL?.trim() || "info";
  if (!new Set(["debug", "info", "warn", "error"]).has(logLevel)) {
    throw new RuntimeConfigError(
      "runtime_config_invalid",
      "AGENT_RUNTIME_LOG_LEVEL is invalid"
    );
  }
  const databaseUrl = required(env, "DATABASE_URL");
  const database = new URL(databaseUrl);
  if (!new Set(["postgres:", "postgresql:"]).has(database.protocol)) {
    throw new RuntimeConfigError(
      "runtime_database_url_invalid",
      "DATABASE_URL must use PostgreSQL"
    );
  }
  const grantPublicKeyFile = required(env, "RUNTIME_GRANT_PUBLIC_KEY_FILE");
  const modelProbeTokenFile = required(env, "MODEL_PROBE_AUTH_TOKEN_FILE");
  const masterKeyFile = required(env, "APP_CONFIG_MASTER_KEY_FILE");
  if (
    !grantPublicKeyFile.startsWith("/") ||
    !modelProbeTokenFile.startsWith("/") ||
    !masterKeyFile.startsWith("/")
  ) {
    throw new RuntimeConfigError(
      "runtime_secret_path_invalid",
      "Runtime key files must use absolute paths"
    );
  }
  return {
    host: env.AGENT_RUNTIME_HOST?.trim() || "0.0.0.0",
    port: integer(env, "AGENT_RUNTIME_PORT", 8090, 1, 65535),
    logLevel: logLevel as RuntimeConfig["logLevel"],
    grantPublicKeyFile,
    modelProbeTokenFile,
    databaseUrl,
    masterKeyFile,
    providerAllowedHosts: hostSet(
      required(env, "MODEL_PROVIDER_ALLOWED_HOSTS"),
      "MODEL_PROVIDER_ALLOWED_HOSTS"
    ),
    mcpAllowedHosts: hostSet(
      required(env, "MCP_SERVER_ALLOWED_HOSTS"),
      "MCP_SERVER_ALLOWED_HOSTS"
    ),
    ledgerTtlSeconds: integer(
      env,
      "AGENT_RUNTIME_LEDGER_TTL_SECONDS",
      3600,
      300,
      86400
    ),
    cliVersion
  };
}

export function readRequiredSecretFile(path: string): string {
  const value = readFileSync(path, { encoding: "utf8", flag: "r" }).trim();
  if (!value) {
    throw new RuntimeConfigError("runtime_secret_file_empty", "Runtime key file is empty");
  }
  return value;
}
