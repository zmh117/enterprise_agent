import type {
  ConnectorState,
  DesiredConnector,
  DesiredSnapshot,
  StreamClient,
  StreamClientFactory,
} from "./contracts.js";
import { ControlApiError, type ControlApi } from "./control-api.js";

interface ManagedClient {
  config: DesiredConnector;
  client: StreamClient;
  status: ConnectorState["status"];
  registrationConfirmed: boolean;
  errorCode: string;
  errorSummary: string;
  operation: Promise<void>;
}

export class RuntimeManager {
  private readonly clients = new Map<string, ManagedClient>();

  constructor(
    private readonly runtimeId: string,
    private readonly controlApi: ControlApi,
    private readonly factory: StreamClientFactory,
    private leaseToken: string
  ) {}

  setLeaseToken(value: string): void {
    this.leaseToken = value;
  }

  async reconcile(snapshot: DesiredSnapshot): Promise<void> {
    const desired = new Map(
      snapshot.connectors.map((connector) => [connector.connector_id, connector])
    );
    const operations: Promise<void>[] = [];
    for (const connector of snapshot.connectors) {
      const current = this.clients.get(connector.connector_id);
      if (!current) {
        operations.push(this.start(connector));
      } else if (current.config.revision !== connector.revision) {
        operations.push(this.restart(current, connector));
      }
    }
    for (const [connectorId, current] of this.clients) {
      if (!desired.has(connectorId)) operations.push(this.stop(current));
    }
    await Promise.all(operations);
  }

  states(): ConnectorState[] {
    return [...this.clients.values()].map((managed) => {
      if (!managed.client.connected || managed.client.reconnecting) {
        managed.registrationConfirmed = false;
      }
      const registered =
        managed.client.registered || managed.registrationConfirmed;
      let status = managed.status;
      if (managed.client.reconnecting) status = "RECONNECTING";
      else if (registered) status = "REGISTERED";
      else if (managed.client.connected) status = "CONNECTED";
      return {
        connector_id: managed.config.connector_id,
        revision: managed.config.revision,
        status,
        connected: managed.client.connected,
        registered,
        error_code: managed.errorCode,
        error_summary: managed.errorSummary,
      };
    });
  }

  counts(): { total: number; connected: number; registered: number } {
    const states = this.states();
    return {
      total: states.length,
      connected: states.filter((state) => state.connected).length,
      registered: states.filter((state) => state.registered).length,
    };
  }

  async shutdown(): Promise<void> {
    await Promise.all([...this.clients.values()].map((managed) => this.stop(managed)));
  }

  private start(config: DesiredConnector): Promise<void> {
    const client = this.factory(config);
    const managed: ManagedClient = {
      config,
      client,
      status: "STARTING",
      registrationConfirmed: false,
      errorCode: "",
      errorSummary: "",
      operation: Promise.resolve(),
    };
    this.clients.set(config.connector_id, managed);
    client.onRobotMessage(async (message) => {
      try {
        const result = await this.controlApi.submit(
          this.runtimeId,
          this.leaseToken,
          config.connector_id,
          message
        );
        if (result.acknowledged) {
          managed.registrationConfirmed = true;
          managed.errorCode = "";
          managed.errorSummary = "";
          client.acknowledge(message.headers.messageId, {
            status: result.created ? "ACCEPTED" : "DUPLICATE",
            eventId: result.event_id,
          });
        }
      } catch (error) {
        const failure = inboxFailure(error);
        managed.errorCode = failure.code;
        managed.errorSummary = failure.summary;
        console.warn(
          JSON.stringify({
            event: "dingtalk_inbox_rejected",
            connector_id: config.connector_id,
            status: failure.status,
            error_code: failure.code,
          })
        );
        // No ACK: DingTalk can redeliver. Secrets and payloads are intentionally not logged.
      }
    });
    managed.operation = managed.operation.then(async () => {
      try {
        await client.connect();
        managed.status = client.registered
          ? "REGISTERED"
          : client.connected
            ? "CONNECTED"
            : "RECONNECTING";
      } catch (error) {
        const authenticationFailure = isAuthenticationFailure(error);
        managed.status = authenticationFailure ? "AUTH_FAILED" : "ERROR";
        managed.errorCode = authenticationFailure
          ? "auth_failed"
          : "connect_failed";
        managed.errorSummary = authenticationFailure
          ? "DingTalk credentials were rejected"
          : "DingTalk connection failed";
      }
    });
    return managed.operation;
  }

  private restart(
    current: ManagedClient,
    config: DesiredConnector
  ): Promise<void> {
    current.operation = current.operation.then(async () => {
      current.client.disconnect();
      this.clients.delete(current.config.connector_id);
      await this.start(config);
    });
    return current.operation;
  }

  private stop(current: ManagedClient): Promise<void> {
    current.operation = current.operation.then(() => {
      current.client.disconnect();
      this.clients.delete(current.config.connector_id);
    });
    return current.operation;
  }
}

function isAuthenticationFailure(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  const message = error.message.toLowerCase();
  return [
    "auth",
    "credential",
    "client id",
    "clientid",
    "secret",
    "unauthorized",
    "forbidden",
  ].some((marker) => message.includes(marker));
}

function inboxFailure(error: unknown): {
  code: string;
  summary: string;
  status: number;
} {
  if (error instanceof ControlApiError) {
    const suffix = error.code || `http_${error.status}`;
    return {
      code: `inbox_${suffix}`.slice(0, 120),
      summary: `Control API rejected DingTalk inbox status=${error.status}`.slice(
        0,
        500
      ),
      status: error.status,
    };
  }
  return {
    code: "inbox_submit_failed",
    summary: "DingTalk inbox submission failed",
    status: 0,
  };
}
