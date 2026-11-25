export const PACKAGE_VERSION = '4.0.0';
export const SCHEMA_VERSION = '3.0.0';
export const CHANNELS = ['page', 'semantic', 'network', 'runtime', 'screenshot'] as const;
export type Channel = typeof CHANNELS[number];
export type SessionState = 'STARTING' | 'RECORDING' | 'STOPPING' | 'FINALIZING' | 'READY' | 'INTERRUPTED' | 'FAILED';
export const terminal = (state: SessionState) => ['READY', 'INTERRUPTED', 'FAILED'].includes(state);
export const active = (state: SessionState) => state === 'STARTING' || state === 'RECORDING';
export const uuid = () => crypto.randomUUID();
export const now = () => new Date().toISOString();
export const bytes = (value: unknown) => new TextEncoder().encode(typeof value === 'string' ? value : JSON.stringify(value)).byteLength;

export type CorrelationField = 'frontendBuildId' | 'backendBuildId' | 'serviceInstance' | 'requestId' | 'traceId' | 'spanId';
export interface CorrelationSource { field: CorrelationField; source: 'response_header' | 'response_json' | 'page_meta'; key: string; component: string; origin?: string; pathPrefix?: string }
export interface CorrelationFact { field: CorrelationField; value: string; source: string; component: string; observedAt: string }
export interface Policy {
  policyVersion: string;
  pageOrigins: string[];
  apiRules: { origin: string; pathPrefix: string }[];
  requestTypes: string[];
  allowedInputNames: string[];
  allowedQueryKeys: string[];
  sensitiveSelectors: string[];
  maskAllText: boolean;
  screenshots: 'disabled'; // Pixel redaction cannot be guaranteed across a changing page.
  captureStreaming: boolean;
  businessRules: { origin: string; pathPrefix: string; codePath: string; successValues: (string | number)[] }[];
  correlationSources: CorrelationSource[];
  sourceMappings: { environmentId: string; component: string; buildId: string; codeSnapshot: string }[];
  budgets: { softTabs: number; hardTabs: number; reminderMinutes: number; ipcBytes: number; baselineBytes: number; bodyBytes: number; softBytes: number; hardBytes: number; queueBytes: number; bodyConcurrency: number };
  logTimeMarginSeconds: number;
}

export interface Gap { id: string; code: string; observedAt: string; tabInstanceId?: string; channel?: Channel; detail: string }
export interface ChannelState { state: 'PENDING' | 'ACTIVE' | 'BLOCKED' | 'LOST' | 'STOPPED'; generation: number; readyAt?: string; stoppedAt?: string; reason?: string }
export interface LineageEvidence { source: string; sourceBrowserTabId: number; targetBrowserTabId: number; sourceFrameId?: number; observedAt: string; observedSeq: number; sourceTime?: number; sourceClock?: string }
export interface DocumentRecord { documentId: string; chromeFrameId: number; parentFrameId: number; url: string; observedAt: string; recorderStreamId?: string; recorderStartedAt?: string; firstBaselineAt?: string; status: string; subjectMapping: string; endedAt?: string; baselineRef?: { eventId: string; recorderStreamId: string; nodeId: number }; }
export interface Target {
  recordingId: string; browserRunId: string; tabInstanceId: string; browserTabId: number; windowId: number;
  title: string; url: string; parentTabInstanceId: string | null; rootTabInstanceIds: string[]; replacesTabInstanceId?: string;
  membershipReason: 'root' | 'manual_add' | 'derived' | 'replacement'; lineageEvidence: LineageEvidence[];
  scopeGrantedAt: string; scopeGrantedSeq: number; grantCommandId: string; createdObservedAt?: string; lineageConfirmedAt: string;
  lifecycle: 'OPEN' | 'CLOSED' | 'REPLACED'; captureState: 'PENDING' | 'ATTACHING' | 'ACTIVE' | 'DEGRADED' | 'BLOCKED' | 'STOPPED';
  captureGeneration: number; accepting: boolean; channels: Record<Channel, ChannelState>;
  quality: 'complete_within_declared_scope' | 'partial' | 'unavailable'; possibleInitialGap: boolean;
  networkReadyAt?: string; runtimeReadyAt?: string; firstBaselineAt?: string; cutoffObservedAt?: string; cutoffSeq?: number; stopReason?: string;
  finalFlushConfirmed: boolean; lateResults: number; documents: DocumentRecord[];
  debuggerBlocked?: boolean;
}
export interface Recording {
  schemaVersion: string; recordingId: string; browserRunId: string; state: SessionState; scopeVersion: number;
  environmentId: string;
  rootEnvironments?: Record<string, string>;
  browserVersion: string; extensionVersion: string; rrwebVersion: string; startedAt: string; stoppedAt?: string;
  policy: Policy; gaps: Gap[]; rootTabInstanceIds: string[]; commands: string[];
  bytesAccepted: number; bytesPersisted: number; eventsPersisted: number; checkpoint: number;
  saveState: 'saved' | 'pending' | 'error'; saveError?: string;
  stopProgress?: { startedAt: string; cutoff: 'complete'; marker: 'pending' | 'complete' | 'error'; cleanup: 'pending' | 'complete' | 'error'; drain: 'pending' | 'complete' | 'error'; terminal: 'pending' | 'complete' | 'error'; deadlineExceeded: boolean };
  versions: { frontendBuildId: string; backendBuildId: string; serviceInstance: string; codeSnapshotMatch: string; sources: Record<string, string> };
  capabilities: Record<string, unknown>; stopReason?: string;
}
export interface Context { chromeFrameId: number | null; documentId: string | null; verifiedBy?: string; status?: string; reason?: string }
export interface EvidenceEvent {
  schemaVersion: string; eventId: string; recordingId: string; browserRunId: string;
  tabInstanceId: string | null; browserTabId: number | null; windowId: number | null;
  emitterContext: Context | null; subjectContext: Context | null; streamId: string; source: string;
  recorderStreamId?: string; sourceSeq: number; kind: string; sourceTime: number | null; sourceClock: string;
  observedAt: string; normalizedAt: null; captureGeneration: number; channel: Channel | 'control'; channelGeneration: number;
  payload: Record<string, any>; quality: { redacted: boolean; truncated: boolean; limitations: string[] };
}
export type BodyStatus = 'captured' | 'empty' | 'not_applicable' | 'truncated' | 'excluded_by_policy' | 'unavailable' | 'incomplete_target_closed' | 'incomplete_session_stopped';
export interface BodyFields { bodyCaptureStatus: BodyStatus; bodyRef: string | null; bodyCaptureReason: string | null; redactionStatus: 'none' | 'applied' | 'fully_masked' | 'failed_excluded'; originalBytes?: number; savedBytes?: number }
export interface NetworkRecord {
  schemaVersion: string; requestKey: string; recordingId: string; browserRunId: string; tabInstanceId: string;
  debuggerSessionKey: string; cdpRequestId: string; redirectOrdinal: number; cdpFrameId?: string; loaderId?: string; chromeFrameId: number | null; documentId?: string | null; frameMappingReason?: string;
  request: BodyFields & { method: string; url: string; headers: Record<string, string>; type: string; initiator?: unknown };
  response: BodyFields & { httpStatus: number | 'unknown'; headers: Record<string, string>; mimeType?: string; fromDiskCache?: boolean; fromServiceWorker?: boolean };
  networkOutcome: 'finished' | 'failed' | 'incomplete'; businessOutcome: 'success' | 'failure' | 'unknown'; businessCode?: unknown;
  correlationFacts?: CorrelationFact[];
  serverCorrelation: { requestId: string | null; requestIdSource: string | null; traceId: string | null; traceIdSource: string | null; spanId?: string | null };
  startedAt: string; endedAt?: string; sourceTime?: number; sourceClock: string; error?: string;
  evidenceRefs: string[]; actionCandidates: { actionId: string; basis: string; confirmed: false }[]; extraInfoStatus: string;
}
export interface BlobRecord { id: string; recordingId: string; path: string; mime: string; data: string; encoding: 'utf8' | 'base64' }
export interface Chunk { id: string; recordingId: string; browserRunId: string; streamId: string; chunkSeq: number; firstSeq: number; lastSeq: number; sha256: string; events: EvidenceEvent[] }
export interface CaptureToken { recordingId: string; browserRunId: string; tabInstanceId: string; captureGeneration: number; channel: Channel; channelGeneration: number }
export interface PageTicket {
  id: string; recordingId: string; browserRunId: string; tabInstanceId: string; captureGeneration: number;
  pageGeneration: number; semanticGeneration: number; documentId: string; chromeFrameId: number;
  recorderStreamId: string; nonce: string; policy: Policy; mode: 'top' | 'cross-origin' | 'semantic-only';
}
export interface PagePacket { seq: number; kind: 'rrweb.event' | 'ui.observation' | 'capture.page_diagnostic'; sourceTime: number; payload: Record<string, any> }
export interface CaptureFragment { type: 'capture.batch'; ticketId: string; packetId: number; index: number; total: number; data: string }
export interface BundleData { recording: Recording; targets: Target[]; chunks: Chunk[]; blobs: BlobRecord[]; network: NetworkRecord[] }
