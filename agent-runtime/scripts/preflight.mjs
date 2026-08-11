import { spawnSync } from "node:child_process";
import { access, readFile, stat } from "node:fs/promises";
import { constants } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import pg from "pg";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(root, "..");
const expected = {
  runtime: "0.1.0",
  protocol: "1.0",
  sdk: "0.3.226",
  cli: "2.1.226",
  nodeMajor: 22,
};
const staticOnly = process.argv.includes("--static");

function fail(code, message) {
  const error = new Error(message);
  error.code = code;
  throw error;
}

async function json(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

async function checkStaticContract() {
  const packageJson = await json(resolve(root, "package.json"));
  const lock = await json(resolve(root, "package-lock.json"));
  const schema = await json(resolve(root, "contracts/v1/protocol.schema.json"));
  const sdkPackage = await json(
    resolve(root, "node_modules/@anthropic-ai/claude-agent-sdk/package.json")
  );
  const lockedSdk =
    lock.packages?.["node_modules/@anthropic-ai/claude-agent-sdk"]?.version;
  if (Number(process.versions.node.split(".")[0]) !== expected.nodeMajor) {
    fail("preflight_node_version_mismatch", `Node ${expected.nodeMajor} is required`);
  }
  if (
    packageJson.version !== expected.runtime ||
    packageJson.dependencies?.["@anthropic-ai/claude-agent-sdk"] !== expected.sdk ||
    sdkPackage.version !== expected.sdk ||
    lockedSdk !== expected.sdk
  ) {
    fail("preflight_sdk_version_mismatch", "Runtime or SDK version is not exactly pinned");
  }
  const schemaText = JSON.stringify(schema);
  const runtimeKinds = schema.$defs?.RuntimeKind?.enum;
  if (!schemaText.includes(`"const":"${expected.protocol}"`) ||
      !Array.isArray(runtimeKinds) ||
      !runtimeKinds.includes("python-v1") ||
      !runtimeKinds.includes("typescript-v1")) {
    fail("preflight_contract_version_mismatch", "Protocol schema version constants do not match");
  }
  if (staticOnly) {
    const compose = await readFile(resolve(repositoryRoot, "docker-compose.yml"), "utf8");
    if (!compose.includes(`AGENT_RUNTIME_CLI_VERSION: "${expected.cli}"`)) {
      fail("preflight_compose_cli_version_mismatch", "Compose CLI version is not exact");
    }
  } else if (process.env.AGENT_RUNTIME_CLI_VERSION?.trim() !== expected.cli) {
    fail("preflight_cli_config_mismatch", "Runtime CLI version configuration is not exact");
  }

  const platform = process.platform === "win32" ? "win32" : process.platform;
  const architecture = process.arch === "x64" ? "x64" : process.arch;
  const binary = resolve(
    root,
    `node_modules/@anthropic-ai/claude-agent-sdk-${platform}-${architecture}/claude${platform === "win32" ? ".exe" : ""}`
  );
  await access(binary, constants.X_OK);
  const cli = spawnSync(binary, ["--version"], { encoding: "utf8", timeout: 10_000 });
  if (cli.status !== 0 || !String(cli.stdout).trim().startsWith(expected.cli)) {
    fail("preflight_cli_version_mismatch", "Bundled Claude CLI version does not match");
  }
}

async function checkSecretFile(name, { masterKey = false } = {}) {
  const path = process.env[name]?.trim();
  if (!path || !path.startsWith("/")) {
    fail("preflight_secret_path_invalid", `${name} must be an absolute path`);
  }
  const metadata = await stat(path);
  if (!metadata.isFile() || (metadata.mode & 0o022) !== 0) {
    fail("preflight_secret_permission_invalid", `${name} must be a non-writable regular file`);
  }
  const value = (await readFile(path, "utf8")).trim();
  if (!value || (masterKey && !/^EA_MASTER_KEY_V1:[A-Za-z0-9_-]{43}$/.test(value))) {
    fail("preflight_secret_format_invalid", `${name} has an invalid format`);
  }
}

const readColumns = {
  model_connection: new Set(["id", "protocol", "status"]),
  model_connection_revision: new Set([
    "id", "connection_id", "status", "config_json", "config_hash", "api_key_secret_id",
  ]),
  platform_secret: new Set(["id", "provider", "status", "active_version"]),
  platform_secret_version: new Set([
    "secret_id", "version", "ciphertext", "nonce", "key_id", "algorithm", "status",
  ]),
};

async function checkDatabaseGrants() {
  const databaseUrl = process.env.DATABASE_URL?.trim();
  if (!databaseUrl) fail("preflight_database_url_missing", "DATABASE_URL is required");
  const pool = new pg.Pool({ connectionString: databaseUrl, max: 1, connectionTimeoutMillis: 3000 });
  try {
    const schema = await pool.query("select has_schema_privilege(current_user, 'public', 'USAGE') allowed");
    if (!schema.rows[0]?.allowed) fail("preflight_database_grant_missing", "public schema USAGE is missing");
    for (const [table, allowedColumns] of Object.entries(readColumns)) {
      const columns = await pool.query(
        "select column_name from information_schema.columns where table_schema = 'public' and table_name = $1",
        [table]
      );
      if (columns.rowCount === 0) fail("preflight_database_schema_missing", `${table} is missing`);
      for (const { column_name: column } of columns.rows) {
        const permission = await pool.query(
          "select has_column_privilege(current_user, $1, $2, 'SELECT') allowed",
          [table, column]
        );
        if (Boolean(permission.rows[0]?.allowed) !== allowedColumns.has(column)) {
          fail("preflight_database_column_grant_invalid", `${table}.${column} SELECT boundary is invalid`);
        }
      }
      const mutation = await pool.query(
        "select bool_or(has_table_privilege(current_user, $1, privilege)) forbidden from unnest($2::text[]) privilege",
        [table, ["INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"]]
      );
      if (mutation.rows[0]?.forbidden) fail("preflight_database_write_grant_invalid", `${table} grants writes`);
    }
    const ledger = await pool.query(
      "select bool_and(has_table_privilege(current_user, 'agent_runtime_terminal_ledger', privilege)) filter (where expected) allowed, bool_or(has_table_privilege(current_user, 'agent_runtime_terminal_ledger', privilege)) filter (where not expected) forbidden from (values ('SELECT', true), ('INSERT', true), ('DELETE', true), ('UPDATE', false), ('TRUNCATE', false), ('REFERENCES', false), ('TRIGGER', false)) grants(privilege, expected)"
    );
    const claim = await pool.query(
      "select bool_and(has_table_privilege(current_user, 'agent_runtime_invocation_claim', privilege)) filter (where expected) allowed, bool_or(has_table_privilege(current_user, 'agent_runtime_invocation_claim', privilege)) filter (where not expected) forbidden from (values ('SELECT', true), ('INSERT', true), ('DELETE', true), ('UPDATE', false), ('TRUNCATE', false), ('REFERENCES', false), ('TRIGGER', false)) grants(privilege, expected)"
    );
    const invocationEvents = await pool.query(
      "select bool_and(has_table_privilege(current_user, 'agent_runtime_invocation_event', privilege)) filter (where expected) allowed, bool_or(has_table_privilege(current_user, 'agent_runtime_invocation_event', privilege)) filter (where not expected) forbidden from (values ('SELECT', true), ('INSERT', true), ('DELETE', true), ('UPDATE', false), ('TRUNCATE', false), ('REFERENCES', false), ('TRIGGER', false)) grants(privilege, expected)"
    );
    if (
      !ledger.rows[0]?.allowed || ledger.rows[0]?.forbidden ||
      !claim.rows[0]?.allowed || claim.rows[0]?.forbidden ||
      !invocationEvents.rows[0]?.allowed || invocationEvents.rows[0]?.forbidden
    ) {
      fail("preflight_ledger_grant_invalid", "Runtime ledger grants are invalid");
    }
  } finally {
    await pool.end();
  }
}

try {
  await checkStaticContract();
  if (!staticOnly) {
    await Promise.all([
      checkSecretFile("APP_CONFIG_MASTER_KEY_FILE", { masterKey: true }),
      checkSecretFile("MODEL_PROBE_AUTH_TOKEN_FILE"),
      checkDatabaseGrants(),
    ]);
    const publicKey = process.env.RUNTIME_GRANT_PUBLIC_KEY_FILE?.trim();
    if (!publicKey || !publicKey.startsWith("/")) {
      fail("preflight_runtime_grant_key_missing", "RUNTIME_GRANT_PUBLIC_KEY_FILE is required");
    }
    await access(publicKey, constants.R_OK);
  }
  process.stdout.write(
    JSON.stringify({ status: "SUCCEEDED", mode: staticOnly ? "static" : "deployment", ...expected }) + "\n"
  );
} catch (error) {
  process.stderr.write(
    JSON.stringify({ status: "FAILED", code: error?.code ?? "preflight_failed" }) + "\n"
  );
  process.exitCode = 1;
}
