import { readFile, stat, statfs } from "node:fs/promises";

import { Pool } from "pg";

import type { RuntimeConfig } from "./config.js";

export interface DependencyStatus {
  readonly ready: boolean;
  readonly database: "ready" | "unavailable";
  readonly master_key: "ready" | "unavailable";
  readonly sandbox: "ready" | "unavailable";
  readonly sandbox_capacity_bytes: number;
  readonly sandbox_max_file_bytes: number;
  readonly sandbox_max_files: number;
}

export interface ReadinessProbe {
  check(): Promise<DependencyStatus>;
  close(): Promise<void>;
}

export class RuntimeReadinessProbe implements ReadinessProbe {
  private readonly pool: Pool;

  constructor(private readonly config: RuntimeConfig) {
    this.pool = new Pool({
      connectionString: config.databaseUrl,
      max: 2,
      connectionTimeoutMillis: 1500,
      idleTimeoutMillis: 10000,
      application_name: "enterprise-agent-runtime-readiness"
    });
  }

  async check(): Promise<DependencyStatus> {
    const [database, masterKey, sandbox] = await Promise.all([
      this.checkDatabase(),
      this.checkMasterKey(),
      this.checkSandbox()
    ]);
    return {
      ready: database && masterKey && sandbox,
      database: database ? "ready" : "unavailable",
      master_key: masterKey ? "ready" : "unavailable",
      sandbox: sandbox ? "ready" : "unavailable",
      sandbox_capacity_bytes: this.config.sandboxCapacityBytes,
      sandbox_max_file_bytes: this.config.sandboxMaxFileBytes,
      sandbox_max_files: this.config.sandboxMaxFiles
    };
  }

  async close(): Promise<void> {
    await this.pool.end();
  }

  private async checkDatabase(): Promise<boolean> {
    try {
      await this.pool.query("SELECT 1 AS runtime_ready");
      return true;
    } catch {
      return false;
    }
  }

  private async checkMasterKey(): Promise<boolean> {
    try {
      const metadata = await stat(this.config.masterKeyFile);
      if (!metadata.isFile() || (metadata.mode & 0o022) !== 0) return false;
      const value = (await readFile(this.config.masterKeyFile, "utf8")).trim();
      return /^EA_MASTER_KEY_V1:[A-Za-z0-9_-]{43}$/.test(value);
    } catch {
      return false;
    }
  }

  private async checkSandbox(): Promise<boolean> {
    try {
      const metadata = await stat(this.config.sandboxRoot);
      if (!metadata.isDirectory()) return false;
      const filesystem = await statfs(this.config.sandboxRoot);
      const availableBytes = filesystem.bavail * filesystem.bsize;
      return (
        this.config.sandboxCapacityBytes >= 64 * 1024 * 1024 &&
        availableBytes >= 64 * 1024 * 1024
      );
    } catch {
      return false;
    }
  }
}
