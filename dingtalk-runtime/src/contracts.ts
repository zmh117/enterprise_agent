export interface DesiredConnector {
  connector_id: string;
  revision: number;
  name: string;
  client_id: string;
  client_secret: string;
  tenant_code: string;
  allow_private_chat: boolean;
  allow_group_chat: boolean;
  require_group_at: boolean;
}

export interface DesiredSnapshot {
  revision: number;
  connectors: DesiredConnector[];
}

export type ConnectorStatus =
  | "STOPPED"
  | "STARTING"
  | "CONNECTED"
  | "REGISTERED"
  | "RECONNECTING"
  | "AUTH_FAILED"
  | "ERROR";

export interface ConnectorState {
  connector_id: string;
  revision: number;
  status: ConnectorStatus;
  connected: boolean;
  registered: boolean;
  error_code: string;
  error_summary: string;
}

export interface RuntimeLease {
  lease_name: string;
  runtime_id: string;
  lease_token: string;
  expires_at: string;
}

export interface StreamEnvelope {
  headers: {
    messageId: string;
    eventId?: string;
    topic: string;
  };
  data: string;
}

export interface StreamClient {
  readonly connected: boolean;
  readonly registered: boolean;
  readonly reconnecting: boolean;
  connect(): Promise<void>;
  disconnect(): void;
  onRobotMessage(handler: (message: StreamEnvelope) => Promise<void>): void;
  onCardCallback(handler: (message: StreamEnvelope) => Promise<void>): void;
  acknowledge(messageId: string, data: unknown): void;
}

export type StreamClientFactory = (
  connector: DesiredConnector
) => StreamClient;
