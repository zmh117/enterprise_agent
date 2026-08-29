import {
  DWClient,
  TOPIC_CARD,
  TOPIC_ROBOT,
  type DWClientDownStream,
} from "dingtalk-stream";
import type {
  DesiredConnector,
  StreamClient,
  StreamEnvelope,
} from "./contracts.js";

export class DingTalkSdkClient implements StreamClient {
  readonly client: DWClient;

  constructor(connector: DesiredConnector) {
    this.client = new DWClient({
      clientId: connector.client_id,
      clientSecret: connector.client_secret,
      keepAlive: true,
      debug: false,
    });
  }

  get connected(): boolean {
    return this.client.connected;
  }

  get registered(): boolean {
    return this.client.registered;
  }

  get reconnecting(): boolean {
    return this.client.reconnecting;
  }

  connect(): Promise<void> {
    return this.client.connect();
  }

  disconnect(): void {
    this.client.disconnect();
  }

  onRobotMessage(handler: (message: StreamEnvelope) => Promise<void>): void {
    this.client.registerCallbackListener(
      TOPIC_ROBOT,
      (message: DWClientDownStream) => {
        const headers: StreamEnvelope["headers"] = {
          messageId: message.headers.messageId,
          topic: message.headers.topic,
        };
        if (message.headers.eventId) headers.eventId = message.headers.eventId;
        void handler({
          headers,
          data: message.data,
        });
      }
    );
  }

  onCardCallback(handler: (message: StreamEnvelope) => Promise<void>): void {
    this.client.registerCallbackListener(
      TOPIC_CARD,
      (message: DWClientDownStream) => {
        const headers: StreamEnvelope["headers"] = {
          messageId: message.headers.messageId,
          topic: message.headers.topic,
        };
        if (message.headers.eventId) headers.eventId = message.headers.eventId;
        void handler({ headers, data: message.data });
      }
    );
  }

  acknowledge(messageId: string, data: unknown): void {
    this.client.socketCallBackResponse(messageId, data);
  }
}
