import { once } from "node:events";

import { Pool } from "pg";

import {
  ClaudeAgentRuntimeExecutor,
  JobSandboxWorkspaceFactory
} from "./claude-runtime.js";
import { loadRuntimeConfig, readRequiredSecretFile } from "./config.js";
import { DeterministicFakeProviderRuntimeExecutor } from "./fake-provider.js";
import { RuntimeGrantVerifier } from "./grant.js";
import { InvocationRegistry } from "./invocation-registry.js";
import { StructuredLogger } from "./logger.js";
import { ModelBindingResolver } from "./model-binding.js";
import { ModelConnectionProbe } from "./model-probe.js";
import { ModelProbeEnvelopeDecryptor } from "./model-probe-envelope.js";
import { PlatformSecretDecryptor } from "./platform-secret.js";
import { RuntimeReadinessProbe } from "./readiness.js";
import { createRuntimeServer } from "./server.js";
import { PostgresTerminalLedger } from "./terminal-ledger.js";
import {
  CURRENT_PROTOCOL_VERSION,
  SUPPORTED_PROTOCOL_VERSIONS
} from "./runtime-contracts.js";

const config = loadRuntimeConfig();
const logger = new StructuredLogger(config.logLevel);
const readiness = new RuntimeReadinessProbe(config);
const grantVerifier = RuntimeGrantVerifier.fromPem(
  readRequiredSecretFile(config.grantPublicKeyFile)
);
const modelPool = new Pool({
  connectionString: config.databaseUrl,
  max: 4,
  connectionTimeoutMillis: 3000,
  idleTimeoutMillis: 10000,
  application_name: "enterprise-agent-runtime-model-binding"
});
const secretDecryptor = await PlatformSecretDecryptor.fromFile(config.masterKeyFile);
const probeEnvelopeDecryptor = await ModelProbeEnvelopeDecryptor.fromFile(
  config.masterKeyFile
);
const modelBindings = new ModelBindingResolver(
  modelPool,
  secretDecryptor,
  config,
  undefined,
  probeEnvelopeDecryptor
);
const modelProbe = new ModelConnectionProbe(modelBindings);
const sandboxWorkspaces = new JobSandboxWorkspaceFactory(config.sandboxRoot, {
  capacityBytes: config.sandboxCapacityBytes,
  maxFiles: config.sandboxMaxFiles,
  maxFileBytes: config.sandboxMaxFileBytes
});
const jobIsRunning = async (jobId: string): Promise<boolean> => {
  const result = await modelPool.query(
    "select 1 from agent_job where id = $1 and status = 'RUNNING' limit 1",
    [jobId]
  );
  return result.rowCount === 1;
};
const cleanupResidualSandboxes = async (): Promise<void> => {
  try {
    const cleaned = await sandboxWorkspaces.cleanupResiduals(jobIsRunning);
    if (cleaned.length > 0) {
      logger.log("info", "runtime_sandbox_residuals_cleaned", {
        cleaned_count: cleaned.length
      });
    }
  } catch {
    logger.log("warn", "runtime_sandbox_residual_scan_failed", {});
  }
};
await cleanupResidualSandboxes();
const sandboxCleanupTimer = setInterval(
  () => void cleanupResidualSandboxes(),
  config.sandboxCleanupIntervalSeconds * 1000
);
sandboxCleanupTimer.unref();
const claudeRuntime = new ClaudeAgentRuntimeExecutor(
  modelBindings,
  undefined,
  sandboxWorkspaces,
  undefined,
  config.mcpServerUrl,
  config.onesMcpServerUrl,
  config.fileMcpServerUrl
);
const runtimeExecutor = config.fakeProviderMode
  ? new DeterministicFakeProviderRuntimeExecutor(
      modelBindings,
      config.mcpServerUrl,
      config.onesMcpServerUrl
    ).execute
  : claudeRuntime.execute;
const terminalLedger = new PostgresTerminalLedger(modelPool, config.ledgerTtlSeconds);

const registry = new InvocationRegistry(
  runtimeExecutor,
  config.ledgerTtlSeconds * 1000,
  undefined,
  terminalLedger
);
const server = createRuntimeServer({
  config,
  grantVerifier,
  registry,
  readiness,
  logger,
  modelProbe,
  modelProbeToken: readRequiredSecretFile(config.modelProbeTokenFile)
});
server.listen(config.port, config.host);
await once(server, "listening");
logger.log("info", "runtime_started", {
  host: config.host,
  port: config.port,
  protocol_version: CURRENT_PROTOCOL_VERSION,
  supported_protocol_versions: SUPPORTED_PROTOCOL_VERSIONS,
  sdk_version: "0.3.226",
  cli_version: "2.1.226"
});

async function shutdown(signal: string): Promise<void> {
  logger.log("info", "runtime_stopping", { signal });
  server.close();
  clearInterval(sandboxCleanupTimer);
  await once(server, "close");
  await modelPool.end();
  await readiness.close();
}

process.once("SIGTERM", () => void shutdown("SIGTERM"));
process.once("SIGINT", () => void shutdown("SIGINT"));
