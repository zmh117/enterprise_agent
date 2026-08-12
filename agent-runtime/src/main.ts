import { once } from "node:events";

import { Pool } from "pg";

import { ClaudeAgentRuntimeExecutor } from "./claude-runtime.js";
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
const claudeRuntime = new ClaudeAgentRuntimeExecutor(
  modelBindings,
  undefined,
  undefined,
  undefined,
  config.mcpServerUrl,
  config.onesMcpServerUrl
);
const runtimeExecutor = config.fakeProviderMode
  ? new DeterministicFakeProviderRuntimeExecutor(modelBindings).execute
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
  protocol_version: "1.0",
  sdk_version: "0.3.226",
  cli_version: "2.1.226"
});

async function shutdown(signal: string): Promise<void> {
  logger.log("info", "runtime_stopping", { signal });
  server.close();
  await once(server, "close");
  await modelPool.end();
  await readiness.close();
}

process.once("SIGTERM", () => void shutdown("SIGTERM"));
process.once("SIGINT", () => void shutdown("SIGINT"));
