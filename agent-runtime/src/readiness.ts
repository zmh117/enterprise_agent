import { readFile, stat } from "node:fs/promises";

import { Pool } from "pg";

import type { RuntimeConfig } from "./config.js";

export interface DependencyStatus {
  readonly ready: boolean;
  readonly database: "ready" | "unavailable";
  readonly master_key: "ready" | "unavailable";
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
    const [database, masterKey] = await Promise.all([
      this.checkDatabase(),
      this.checkMasterKey()
    ]);
    return {
      ready: database && masterKey,
      database: database ? "ready" : "unavailable",
      master_key: masterKey ? "ready" : "unavailable"
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
}
