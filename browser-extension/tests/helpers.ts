import { DEFAULT_POLICY } from '../shared/policy';
import { now, SCHEMA_VERSION, uuid, type Recording } from '../shared/contracts';
export function recording(): Recording {
  return { schemaVersion: SCHEMA_VERSION, recordingId: uuid(), browserRunId: uuid(), state: 'RECORDING', scopeVersion: 1,
    environmentId: 'fixture', browserVersion: 'test', extensionVersion: '0.1.0', rrwebVersion: '2.2.2', startedAt: now(),
    policy: { ...structuredClone(DEFAULT_POLICY), pageOrigins: ['http://mes.test'], apiRules: [{ origin: 'http://mes.test', pathPrefix: '/api/' }] }, gaps: [], rootTabInstanceIds: [], commands: [], bytesAccepted: 0, bytesPersisted: 0, eventsPersisted: 0, checkpoint: 0, saveState: 'saved',
    versions: { frontendBuildId: 'unknown', backendBuildId: 'unknown', serviceInstance: 'unknown', codeSnapshotMatch: 'unresolved', sources: {} }, capabilities: {} };
}
