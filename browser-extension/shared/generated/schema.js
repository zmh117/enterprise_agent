// 由 npm run schema:generate 生成，请修改 problem-package.schema.json。
var __getOwnPropNames = Object.getOwnPropertyNames;
var __commonJS = (cb, mod) => function __require() {
  try {
    return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
  } catch (e) {
    throw mod = 0, e;
  }
};

// node_modules/ajv/dist/runtime/ucs2length.js
var require_ucs2length = __commonJS({
  "node_modules/ajv/dist/runtime/ucs2length.js"(exports) {
    "use strict";
    Object.defineProperty(exports, "__esModule", { value: true });
    function ucs2length(str) {
      const len = str.length;
      let length = 0;
      let pos = 0;
      let value;
      while (pos < len) {
        length++;
        value = str.charCodeAt(pos++);
        if (value >= 55296 && value <= 56319 && pos < len) {
          value = str.charCodeAt(pos);
          if ((value & 64512) === 56320)
            pos++;
        }
      }
      return length;
    }
    exports.default = ucs2length;
    ucs2length.code = 'require("ajv/dist/runtime/ucs2length").default';
  }
});

// <stdin>
var require_stdin = __commonJS({
  "<stdin>"(exports) {
    exports.manifest = validate20;
    var schema31 = { "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:browser-capture:manifest:4.0.0", "title": "\u6D4F\u89C8\u5668\u91C7\u96C6\u5305", "type": "object", "required": ["schemaVersion", "recording", "capabilities", "gaps", "files", "integrity"], "properties": { "schemaVersion": { "enum": ["3.0.0", "4.0.0"] }, "recording": { "$ref": "#/$defs/recording" }, "capabilities": { "type": "object" }, "gaps": { "type": "array", "items": { "$ref": "#/$defs/gap" } }, "files": { "type": "array", "items": { "$ref": "#/$defs/file" } }, "integrity": { "type": "object", "required": ["status", "meaning"], "properties": { "status": { "type": "string" }, "meaning": { "type": "string" } } } }, "$defs": { "context": { "type": "object", "required": ["chromeFrameId", "documentId"], "properties": { "chromeFrameId": { "type": ["integer", "null"] }, "documentId": { "type": ["string", "null"] }, "verifiedBy": { "type": "string" }, "status": { "type": "string" }, "reason": { "type": "string" } } }, "contextOrNull": { "anyOf": [{ "$ref": "#/$defs/context" }, { "type": "null" }] }, "gap": { "type": "object", "required": ["id", "code", "observedAt", "detail"], "properties": { "id": { "type": "string", "minLength": 1, "maxLength": 256 }, "code": { "type": "string" }, "observedAt": { "type": "string" }, "detail": { "type": "string" }, "tabInstanceId": { "type": "string" }, "channel": { "enum": ["page", "semantic", "network", "runtime", "screenshot"] } } }, "body": { "type": "object", "required": ["bodyCaptureStatus", "bodyRef", "bodyCaptureReason", "redactionStatus"], "properties": { "bodyCaptureStatus": { "enum": ["captured", "empty", "not_applicable", "truncated", "excluded_by_policy", "unavailable", "incomplete_target_closed", "incomplete_session_stopped"] }, "bodyRef": { "type": ["string", "null"] }, "bodyCaptureReason": { "type": ["string", "null"] }, "redactionStatus": { "enum": ["none", "applied", "fully_masked", "failed_excluded"] }, "originalBytes": { "type": "integer", "minimum": 0 }, "savedBytes": { "type": "integer", "minimum": 0 } } }, "policy": { "type": "object", "required": ["policyVersion", "pageOrigins", "apiRules", "requestTypes", "allowedInputNames", "allowedQueryKeys", "sensitiveSelectors", "maskAllText", "screenshots", "captureStreaming", "businessRules", "budgets", "logTimeMarginSeconds", "correlationSources", "sourceMappings"], "properties": { "policyVersion": { "type": "string" }, "pageOrigins": { "type": "array", "items": { "type": "string" } }, "apiRules": { "type": "array", "items": { "type": "object", "required": ["origin", "pathPrefix"], "properties": { "origin": { "type": "string" }, "pathPrefix": { "type": "string" } } } }, "requestTypes": { "type": "array", "items": { "type": "string" } }, "allowedInputNames": { "type": "array", "items": { "type": "string" } }, "allowedQueryKeys": { "type": "array", "items": { "type": "string" } }, "sensitiveSelectors": { "type": "array", "items": { "type": "string" } }, "maskAllText": { "type": "boolean" }, "screenshots": { "const": "disabled" }, "captureStreaming": { "type": "boolean" }, "businessRules": { "type": "array", "items": { "type": "object", "required": ["origin", "pathPrefix", "codePath", "successValues"], "properties": { "origin": { "type": "string" }, "pathPrefix": { "type": "string" }, "codePath": { "type": "string" }, "successValues": { "type": "array", "items": { "type": ["string", "number"] } } } } }, "budgets": { "type": "object", "required": ["softTabs", "hardTabs", "reminderMinutes", "ipcBytes", "baselineBytes", "bodyBytes", "softBytes", "hardBytes", "queueBytes", "bodyConcurrency"], "properties": { "softTabs": { "type": "integer", "minimum": 1 }, "hardTabs": { "type": "integer", "minimum": 1 }, "reminderMinutes": { "type": "integer", "minimum": 1 }, "ipcBytes": { "type": "integer", "minimum": 1 }, "baselineBytes": { "type": "integer", "minimum": 1 }, "bodyBytes": { "type": "integer", "minimum": 1 }, "softBytes": { "type": "integer", "minimum": 1 }, "hardBytes": { "type": "integer", "minimum": 1 }, "queueBytes": { "type": "integer", "minimum": 1 }, "bodyConcurrency": { "type": "integer", "minimum": 1 } } }, "logTimeMarginSeconds": { "type": "integer", "minimum": 0 }, "correlationSources": { "type": "array", "maxItems": 32, "items": { "type": "object", "required": ["field", "source", "key", "component"], "properties": { "field": { "enum": ["frontendBuildId", "backendBuildId", "serviceInstance", "requestId", "traceId", "spanId"] }, "source": { "enum": ["response_header", "response_json", "page_meta"] }, "key": { "type": "string", "minLength": 1, "maxLength": 200 }, "component": { "type": "string", "minLength": 1, "maxLength": 80 }, "origin": { "type": "string", "minLength": 1, "pattern": "^https?://[^/?#]+$" }, "pathPrefix": { "type": "string", "minLength": 1, "maxLength": 499, "pattern": "^/" } }, "allOf": [{ "if": { "properties": { "source": { "const": "response_header" } } }, "then": { "properties": { "key": { "pattern": "^[a-zA-Z0-9-]{1,80}$" } } } }, { "if": { "properties": { "source": { "const": "response_json" } } }, "then": { "properties": { "key": { "pattern": "^(\\/([^~]|~[01])*)+$" } } } }, { "if": { "properties": { "source": { "const": "page_meta" } } }, "then": { "properties": { "key": { "pattern": `^meta\\[name=(?:"[a-zA-Z0-9_.-]+"|'[a-zA-Z0-9_.-]+')\\]$` } } } }] } }, "sourceMappings": { "type": "array", "maxItems": 100, "items": { "type": "object", "required": ["environmentId", "component", "buildId", "codeSnapshot"], "properties": { "environmentId": { "type": "string", "minLength": 1, "maxLength": 500 }, "component": { "type": "string", "minLength": 1, "maxLength": 500 }, "buildId": { "type": "string", "minLength": 1, "maxLength": 500 }, "codeSnapshot": { "type": "string", "minLength": 1, "maxLength": 500 } } } } } }, "recording": { "type": "object", "required": ["schemaVersion", "recordingId", "browserRunId", "state", "scopeVersion", "environmentId", "browserVersion", "extensionVersion", "rrwebVersion", "startedAt", "policy", "gaps", "rootTabInstanceIds", "commands", "bytesAccepted", "bytesPersisted", "eventsPersisted", "checkpoint", "saveState", "versions", "capabilities"], "properties": { "schemaVersion": { "const": "3.0.0" }, "recordingId": { "type": "string", "minLength": 1, "maxLength": 256 }, "browserRunId": { "type": "string", "minLength": 1, "maxLength": 256 }, "state": { "enum": ["STARTING", "RECORDING", "STOPPING", "FINALIZING", "READY", "INTERRUPTED", "FAILED"] }, "scopeVersion": { "type": "integer", "minimum": 0 }, "environmentId": { "type": "string" }, "browserVersion": { "type": "string" }, "extensionVersion": { "type": "string" }, "rrwebVersion": { "type": "string" }, "startedAt": { "type": "string" }, "stoppedAt": { "type": "string" }, "policy": { "$ref": "#/$defs/policy" }, "gaps": { "type": "array", "items": { "$ref": "#/$defs/gap" } }, "rootTabInstanceIds": { "type": "array", "items": { "type": "string", "minLength": 1, "maxLength": 256 } }, "commands": { "type": "array", "items": { "type": "string", "minLength": 1, "maxLength": 256 } }, "bytesAccepted": { "type": "integer", "minimum": 0 }, "bytesPersisted": { "type": "integer", "minimum": 0 }, "eventsPersisted": { "type": "integer", "minimum": 0 }, "checkpoint": { "type": "integer", "minimum": 0 }, "saveState": { "enum": ["saved", "pending", "error"] }, "saveError": { "type": "string" }, "versions": { "type": "object", "required": ["frontendBuildId", "backendBuildId", "serviceInstance", "codeSnapshotMatch", "sources"], "properties": { "frontendBuildId": { "type": "string" }, "backendBuildId": { "type": "string" }, "serviceInstance": { "type": "string" }, "codeSnapshotMatch": { "type": "string" }, "sources": { "type": "object", "additionalProperties": { "type": "string" } } } }, "capabilities": { "type": "object" }, "stopReason": { "type": "string" }, "stopProgress": { "type": "object", "required": ["startedAt", "cutoff", "marker", "cleanup", "drain", "terminal", "deadlineExceeded"], "properties": { "startedAt": { "type": "string" }, "cutoff": { "const": "complete" }, "marker": { "enum": ["pending", "complete", "error"] }, "cleanup": { "enum": ["pending", "complete", "error"] }, "drain": { "enum": ["pending", "complete", "error"] }, "terminal": { "enum": ["pending", "complete", "error"] }, "deadlineExceeded": { "type": "boolean" } } }, "rootEnvironments": { "type": "object", "additionalProperties": { "type": "string" } } } }, "channel": { "type": "object", "required": ["state", "generation"], "properties": { "state": { "enum": ["PENDING", "ACTIVE", "BLOCKED", "LOST", "STOPPED"] }, "generation": { "type": "integer", "minimum": 0 }, "readyAt": { "type": "string" }, "stoppedAt": { "type": "string" }, "reason": { "type": "string" } } }, "baseline": { "type": "object", "required": ["eventId", "recorderStreamId", "nodeId"], "properties": { "eventId": { "type": "string", "minLength": 1, "maxLength": 256 }, "recorderStreamId": { "type": "string", "minLength": 1, "maxLength": 256 }, "nodeId": { "type": "integer", "minimum": 0 } } }, "document": { "type": "object", "required": ["documentId", "chromeFrameId", "parentFrameId", "url", "observedAt", "status", "subjectMapping"], "properties": { "documentId": { "type": "string", "minLength": 1, "maxLength": 256 }, "chromeFrameId": { "type": "integer", "minimum": 0 }, "parentFrameId": { "type": "integer" }, "url": { "type": "string" }, "observedAt": { "type": "string" }, "recorderStreamId": { "type": "string", "minLength": 1, "maxLength": 256 }, "recorderStartedAt": { "type": "string" }, "firstBaselineAt": { "type": "string" }, "status": { "type": "string" }, "subjectMapping": { "type": "string" }, "endedAt": { "type": "string" }, "baselineRef": { "$ref": "#/$defs/baseline" } } }, "target": { "type": "object", "required": ["recordingId", "browserRunId", "tabInstanceId", "browserTabId", "windowId", "title", "url", "parentTabInstanceId", "rootTabInstanceIds", "membershipReason", "lineageEvidence", "scopeGrantedAt", "scopeGrantedSeq", "grantCommandId", "lineageConfirmedAt", "lifecycle", "captureState", "captureGeneration", "accepting", "channels", "quality", "possibleInitialGap", "finalFlushConfirmed", "lateResults", "documents"], "properties": { "recordingId": { "type": "string", "minLength": 1, "maxLength": 256 }, "browserRunId": { "type": "string", "minLength": 1, "maxLength": 256 }, "tabInstanceId": { "type": "string", "minLength": 1, "maxLength": 256 }, "browserTabId": { "type": "integer" }, "windowId": { "type": "integer" }, "title": { "type": "string" }, "url": { "type": "string" }, "parentTabInstanceId": { "type": ["string", "null"] }, "rootTabInstanceIds": { "type": "array", "items": { "type": "string", "minLength": 1, "maxLength": 256 } }, "replacesTabInstanceId": { "type": "string", "minLength": 1, "maxLength": 256 }, "membershipReason": { "enum": ["root", "manual_add", "derived", "replacement"] }, "lineageEvidence": { "type": "array", "items": { "type": "object", "required": ["source", "sourceBrowserTabId", "targetBrowserTabId", "observedAt", "observedSeq"], "properties": { "source": { "type": "string" }, "sourceBrowserTabId": { "type": "integer" }, "targetBrowserTabId": { "type": "integer" }, "observedAt": { "type": "string" }, "observedSeq": { "type": "integer", "minimum": 0 } } } }, "scopeGrantedAt": { "type": "string" }, "scopeGrantedSeq": { "type": "integer", "minimum": 0 }, "grantCommandId": { "type": "string", "minLength": 1, "maxLength": 256 }, "lineageConfirmedAt": { "type": "string" }, "lifecycle": { "enum": ["OPEN", "CLOSED", "REPLACED"] }, "captureState": { "enum": ["PENDING", "ATTACHING", "ACTIVE", "DEGRADED", "BLOCKED", "STOPPED"] }, "captureGeneration": { "type": "integer", "minimum": 0 }, "accepting": { "type": "boolean" }, "channels": { "type": "object", "required": ["page", "semantic", "network", "runtime", "screenshot"], "properties": { "page": { "$ref": "#/$defs/channel" }, "semantic": { "$ref": "#/$defs/channel" }, "network": { "$ref": "#/$defs/channel" }, "runtime": { "$ref": "#/$defs/channel" }, "screenshot": { "$ref": "#/$defs/channel" } } }, "quality": { "enum": ["complete_within_declared_scope", "partial", "unavailable"] }, "possibleInitialGap": { "type": "boolean" }, "finalFlushConfirmed": { "type": "boolean" }, "lateResults": { "type": "integer", "minimum": 0 }, "documents": { "type": "array", "items": { "$ref": "#/$defs/document" } } } }, "elementRef": { "type": "object", "required": ["recorderStreamId", "nodeId"], "properties": { "recorderStreamId": { "type": "string", "minLength": 1, "maxLength": 256 }, "nodeId": { "type": "integer", "minimum": 0 } } }, "semanticTarget": { "anyOf": [{ "type": "object", "required": [], "properties": { "elementRef": { "anyOf": [{ "$ref": "#/$defs/elementRef" }, { "type": "null" }] } } }, { "type": "null" }] }, "payload": { "type": "object", "required": [], "properties": { "action": { "type": "string" }, "evidenceRefs": { "type": "array", "items": { "type": "string", "minLength": 1, "maxLength": 256 } }, "target": { "$ref": "#/$defs/semanticTarget" }, "nodeContexts": { "type": "array", "items": { "type": "object", "required": ["nodeId", "recorderStreamId", "context"], "properties": { "nodeId": { "type": "integer", "minimum": 0 }, "recorderStreamId": { "type": "string", "minLength": 1, "maxLength": 256 }, "documentRoot": { "type": "boolean" }, "context": { "$ref": "#/$defs/context" } } } }, "before": { "type": "object" }, "after": { "type": "object" }, "context": { "type": "object" }, "phase": { "type": "string" }, "omissions": { "type": "array", "maxItems": 4096, "items": { "type": "object", "required": ["scope", "count", "exact", "reason"], "properties": { "scope": { "type": "string" }, "count": { "type": "integer", "minimum": 1 }, "exact": { "type": "boolean" }, "reason": { "type": "string" } } } }, "observation": { "type": "object", "required": ["sourceTime", "sourceClock"], "properties": { "sourceTime": { "type": "number" }, "sourceClock": { "const": "document_performance_ms" } } }, "documentContext": { "anyOf": [{ "$ref": "#/$defs/context" }, { "type": "null" }] } } }, "event": { "type": "object", "required": ["schemaVersion", "eventId", "recordingId", "browserRunId", "streamId", "tabInstanceId", "browserTabId", "windowId", "emitterContext", "subjectContext", "source", "sourceSeq", "kind", "sourceTime", "sourceClock", "observedAt", "normalizedAt", "captureGeneration", "channel", "channelGeneration", "payload", "quality"], "properties": { "schemaVersion": { "const": "3.0.0" }, "eventId": { "type": "string", "minLength": 1, "maxLength": 256 }, "recordingId": { "type": "string", "minLength": 1, "maxLength": 256 }, "browserRunId": { "type": "string", "minLength": 1, "maxLength": 256 }, "streamId": { "type": "string", "minLength": 1, "maxLength": 256 }, "tabInstanceId": { "type": ["string", "null"] }, "browserTabId": { "type": ["integer", "null"] }, "windowId": { "type": ["integer", "null"] }, "emitterContext": { "$ref": "#/$defs/contextOrNull" }, "subjectContext": { "$ref": "#/$defs/contextOrNull" }, "source": { "type": "string" }, "recorderStreamId": { "type": "string", "minLength": 1, "maxLength": 256 }, "sourceSeq": { "type": "integer", "minimum": 1 }, "kind": { "type": "string" }, "sourceTime": { "type": ["number", "null"] }, "sourceClock": { "type": "string" }, "observedAt": { "type": "string" }, "normalizedAt": { "type": "null" }, "captureGeneration": { "type": "integer", "minimum": 0 }, "channel": { "enum": ["control", "page", "semantic", "network", "runtime", "screenshot"] }, "channelGeneration": { "type": "integer", "minimum": 0 }, "payload": { "$ref": "#/$defs/payload" }, "quality": { "type": "object", "required": ["redacted", "truncated", "limitations"], "properties": { "redacted": { "type": "boolean" }, "truncated": { "type": "boolean" }, "limitations": { "type": "array", "items": { "type": "string" } } } } }, "allOf": [{ "if": { "properties": { "kind": { "const": "ui.action" } } }, "then": { "properties": { "payload": { "required": ["action", "evidenceRefs"] } } } }, { "if": { "properties": { "kind": { "const": "rrweb.event" } } }, "then": { "properties": { "payload": { "required": ["rrwebEvent"], "properties": { "rrwebEvent": { "type": "object", "required": ["type", "timestamp"], "properties": { "type": { "type": "integer", "minimum": 0, "maximum": 6 }, "timestamp": { "type": "number" }, "data": { "type": "object" } } } } } } } }, { "if": { "properties": { "kind": { "enum": ["ui.state_snapshot", "ui.action"] } } }, "then": { "properties": { "payload": { "properties": { "before": { "$ref": "#/$defs/semanticBefore" }, "after": { "properties": { "metadataFacts": { "type": "array", "maxItems": 32, "items": { "$ref": "#/$defs/correlationFact" } } } } } } } } }] }, "network": { "type": "object", "required": ["schemaVersion", "requestKey", "recordingId", "browserRunId", "tabInstanceId", "debuggerSessionKey", "cdpRequestId", "redirectOrdinal", "chromeFrameId", "request", "response", "networkOutcome", "businessOutcome", "serverCorrelation", "startedAt", "sourceClock", "evidenceRefs", "actionCandidates", "extraInfoStatus"], "properties": { "schemaVersion": { "const": "3.0.0" }, "requestKey": { "type": "string", "minLength": 1, "maxLength": 256 }, "recordingId": { "type": "string", "minLength": 1, "maxLength": 256 }, "browserRunId": { "type": "string", "minLength": 1, "maxLength": 256 }, "tabInstanceId": { "type": "string", "minLength": 1, "maxLength": 256 }, "debuggerSessionKey": { "type": "string", "minLength": 1, "maxLength": 256 }, "cdpRequestId": { "type": "string", "minLength": 1, "maxLength": 256 }, "redirectOrdinal": { "type": "integer", "minimum": 0 }, "cdpFrameId": { "type": "string" }, "loaderId": { "type": "string" }, "chromeFrameId": { "type": ["integer", "null"] }, "documentId": { "type": ["string", "null"] }, "frameMappingReason": { "type": "string" }, "request": { "allOf": [{ "$ref": "#/$defs/body" }, { "type": "object", "required": ["method", "url", "headers", "type"], "properties": { "method": { "type": "string" }, "url": { "type": "string" }, "headers": { "type": "object", "additionalProperties": { "type": "string" } }, "type": { "type": "string" } } }] }, "response": { "allOf": [{ "$ref": "#/$defs/body" }, { "type": "object", "required": ["httpStatus", "headers"], "properties": { "httpStatus": { "anyOf": [{ "type": "number" }, { "const": "unknown" }] }, "headers": { "type": "object", "additionalProperties": { "type": "string" } } } }] }, "networkOutcome": { "enum": ["finished", "failed", "incomplete"] }, "businessOutcome": { "enum": ["success", "failure", "unknown"] }, "serverCorrelation": { "type": "object", "required": ["requestId", "requestIdSource", "traceId", "traceIdSource"], "properties": { "requestId": { "type": ["string", "null"] }, "requestIdSource": { "type": ["string", "null"] }, "traceId": { "type": ["string", "null"] }, "traceIdSource": { "type": ["string", "null"] }, "spanId": { "type": ["string", "null"] } } }, "startedAt": { "type": "string" }, "sourceClock": { "type": "string" }, "evidenceRefs": { "type": "array", "items": { "type": "string", "minLength": 1, "maxLength": 256 } }, "actionCandidates": { "type": "array", "items": { "type": "object", "required": ["actionId", "basis", "confirmed"], "properties": { "actionId": { "type": "string", "minLength": 1, "maxLength": 256 }, "basis": { "type": "string" }, "confirmed": { "const": false } } } }, "extraInfoStatus": { "type": "string" }, "correlationFacts": { "type": "array", "items": { "$ref": "#/$defs/correlationFact" } } } }, "file": { "type": "object", "required": ["path", "mime", "bytes", "sha256", "streamId", "firstSeq", "lastSeq", "events"], "properties": { "path": { "type": "string", "pattern": "^[a-zA-Z0-9_./-]+$" }, "mime": { "type": "string" }, "bytes": { "type": "integer", "minimum": 0 }, "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" }, "streamId": { "type": ["string", "null"] }, "firstSeq": { "type": ["integer", "null"] }, "lastSeq": { "type": ["integer", "null"] }, "events": { "type": "integer", "minimum": 0 } } }, "pagePacket": { "type": "object", "required": ["seq", "kind", "sourceTime", "payload"], "properties": { "seq": { "type": "integer", "minimum": 1 }, "kind": { "enum": ["rrweb.event", "ui.observation", "capture.page_diagnostic"] }, "sourceTime": { "type": "number" }, "payload": { "type": "object" } } }, "correlationFact": { "type": "object", "required": ["field", "source", "value", "component", "observedAt"], "properties": { "field": { "enum": ["frontendBuildId", "backendBuildId", "serviceInstance", "requestId", "traceId", "spanId"] }, "source": { "type": "string" }, "value": { "type": "string", "minLength": 1, "maxLength": 256 }, "component": { "type": "string", "minLength": 1, "maxLength": 80 }, "observedAt": { "type": "string" } } }, "semanticBefore": { "oneOf": [{ "type": "object", "required": ["status", "reason"], "properties": { "status": { "const": "unavailable" }, "reason": { "type": "string" } } }, { "type": "object", "required": ["status", "snapshotRef", "observedAt", "sourceTime"], "properties": { "status": { "const": "observed" }, "snapshotRef": { "type": "string", "minLength": 1 }, "observedAt": { "type": "string" }, "sourceTime": { "type": "number" } } }] } } };
    var schema34 = { "type": "object", "required": ["id", "code", "observedAt", "detail"], "properties": { "id": { "type": "string", "minLength": 1, "maxLength": 256 }, "code": { "type": "string" }, "observedAt": { "type": "string" }, "detail": { "type": "string" }, "tabInstanceId": { "type": "string" }, "channel": { "enum": ["page", "semantic", "network", "runtime", "screenshot"] } } };
    var schema36 = { "type": "object", "required": ["path", "mime", "bytes", "sha256", "streamId", "firstSeq", "lastSeq", "events"], "properties": { "path": { "type": "string", "pattern": "^[a-zA-Z0-9_./-]+$" }, "mime": { "type": "string" }, "bytes": { "type": "integer", "minimum": 0 }, "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" }, "streamId": { "type": ["string", "null"] }, "firstSeq": { "type": ["integer", "null"] }, "lastSeq": { "type": ["integer", "null"] }, "events": { "type": "integer", "minimum": 0 } } };
    var schema32 = { "type": "object", "required": ["schemaVersion", "recordingId", "browserRunId", "state", "scopeVersion", "environmentId", "browserVersion", "extensionVersion", "rrwebVersion", "startedAt", "policy", "gaps", "rootTabInstanceIds", "commands", "bytesAccepted", "bytesPersisted", "eventsPersisted", "checkpoint", "saveState", "versions", "capabilities"], "properties": { "schemaVersion": { "const": "3.0.0" }, "recordingId": { "type": "string", "minLength": 1, "maxLength": 256 }, "browserRunId": { "type": "string", "minLength": 1, "maxLength": 256 }, "state": { "enum": ["STARTING", "RECORDING", "STOPPING", "FINALIZING", "READY", "INTERRUPTED", "FAILED"] }, "scopeVersion": { "type": "integer", "minimum": 0 }, "environmentId": { "type": "string" }, "browserVersion": { "type": "string" }, "extensionVersion": { "type": "string" }, "rrwebVersion": { "type": "string" }, "startedAt": { "type": "string" }, "stoppedAt": { "type": "string" }, "policy": { "$ref": "#/$defs/policy" }, "gaps": { "type": "array", "items": { "$ref": "#/$defs/gap" } }, "rootTabInstanceIds": { "type": "array", "items": { "type": "string", "minLength": 1, "maxLength": 256 } }, "commands": { "type": "array", "items": { "type": "string", "minLength": 1, "maxLength": 256 } }, "bytesAccepted": { "type": "integer", "minimum": 0 }, "bytesPersisted": { "type": "integer", "minimum": 0 }, "eventsPersisted": { "type": "integer", "minimum": 0 }, "checkpoint": { "type": "integer", "minimum": 0 }, "saveState": { "enum": ["saved", "pending", "error"] }, "saveError": { "type": "string" }, "versions": { "type": "object", "required": ["frontendBuildId", "backendBuildId", "serviceInstance", "codeSnapshotMatch", "sources"], "properties": { "frontendBuildId": { "type": "string" }, "backendBuildId": { "type": "string" }, "serviceInstance": { "type": "string" }, "codeSnapshotMatch": { "type": "string" }, "sources": { "type": "object", "additionalProperties": { "type": "string" } } } }, "capabilities": { "type": "object" }, "stopReason": { "type": "string" }, "stopProgress": { "type": "object", "required": ["startedAt", "cutoff", "marker", "cleanup", "drain", "terminal", "deadlineExceeded"], "properties": { "startedAt": { "type": "string" }, "cutoff": { "const": "complete" }, "marker": { "enum": ["pending", "complete", "error"] }, "cleanup": { "enum": ["pending", "complete", "error"] }, "drain": { "enum": ["pending", "complete", "error"] }, "terminal": { "enum": ["pending", "complete", "error"] }, "deadlineExceeded": { "type": "boolean" } } }, "rootEnvironments": { "type": "object", "additionalProperties": { "type": "string" } } } };
    var schema33 = { "type": "object", "required": ["policyVersion", "pageOrigins", "apiRules", "requestTypes", "allowedInputNames", "allowedQueryKeys", "sensitiveSelectors", "maskAllText", "screenshots", "captureStreaming", "businessRules", "budgets", "logTimeMarginSeconds", "correlationSources", "sourceMappings"], "properties": { "policyVersion": { "type": "string" }, "pageOrigins": { "type": "array", "items": { "type": "string" } }, "apiRules": { "type": "array", "items": { "type": "object", "required": ["origin", "pathPrefix"], "properties": { "origin": { "type": "string" }, "pathPrefix": { "type": "string" } } } }, "requestTypes": { "type": "array", "items": { "type": "string" } }, "allowedInputNames": { "type": "array", "items": { "type": "string" } }, "allowedQueryKeys": { "type": "array", "items": { "type": "string" } }, "sensitiveSelectors": { "type": "array", "items": { "type": "string" } }, "maskAllText": { "type": "boolean" }, "screenshots": { "const": "disabled" }, "captureStreaming": { "type": "boolean" }, "businessRules": { "type": "array", "items": { "type": "object", "required": ["origin", "pathPrefix", "codePath", "successValues"], "properties": { "origin": { "type": "string" }, "pathPrefix": { "type": "string" }, "codePath": { "type": "string" }, "successValues": { "type": "array", "items": { "type": ["string", "number"] } } } } }, "budgets": { "type": "object", "required": ["softTabs", "hardTabs", "reminderMinutes", "ipcBytes", "baselineBytes", "bodyBytes", "softBytes", "hardBytes", "queueBytes", "bodyConcurrency"], "properties": { "softTabs": { "type": "integer", "minimum": 1 }, "hardTabs": { "type": "integer", "minimum": 1 }, "reminderMinutes": { "type": "integer", "minimum": 1 }, "ipcBytes": { "type": "integer", "minimum": 1 }, "baselineBytes": { "type": "integer", "minimum": 1 }, "bodyBytes": { "type": "integer", "minimum": 1 }, "softBytes": { "type": "integer", "minimum": 1 }, "hardBytes": { "type": "integer", "minimum": 1 }, "queueBytes": { "type": "integer", "minimum": 1 }, "bodyConcurrency": { "type": "integer", "minimum": 1 } } }, "logTimeMarginSeconds": { "type": "integer", "minimum": 0 }, "correlationSources": { "type": "array", "maxItems": 32, "items": { "type": "object", "required": ["field", "source", "key", "component"], "properties": { "field": { "enum": ["frontendBuildId", "backendBuildId", "serviceInstance", "requestId", "traceId", "spanId"] }, "source": { "enum": ["response_header", "response_json", "page_meta"] }, "key": { "type": "string", "minLength": 1, "maxLength": 200 }, "component": { "type": "string", "minLength": 1, "maxLength": 80 }, "origin": { "type": "string", "minLength": 1, "pattern": "^https?://[^/?#]+$" }, "pathPrefix": { "type": "string", "minLength": 1, "maxLength": 499, "pattern": "^/" } }, "allOf": [{ "if": { "properties": { "source": { "const": "response_header" } } }, "then": { "properties": { "key": { "pattern": "^[a-zA-Z0-9-]{1,80}$" } } } }, { "if": { "properties": { "source": { "const": "response_json" } } }, "then": { "properties": { "key": { "pattern": "^(\\/([^~]|~[01])*)+$" } } } }, { "if": { "properties": { "source": { "const": "page_meta" } } }, "then": { "properties": { "key": { "pattern": `^meta\\[name=(?:"[a-zA-Z0-9_.-]+"|'[a-zA-Z0-9_.-]+')\\]$` } } } }] } }, "sourceMappings": { "type": "array", "maxItems": 100, "items": { "type": "object", "required": ["environmentId", "component", "buildId", "codeSnapshot"], "properties": { "environmentId": { "type": "string", "minLength": 1, "maxLength": 500 }, "component": { "type": "string", "minLength": 1, "maxLength": 500 }, "buildId": { "type": "string", "minLength": 1, "maxLength": 500 }, "codeSnapshot": { "type": "string", "minLength": 1, "maxLength": 500 } } } } } };
    var func1 = require_ucs2length().default;
    var pattern4 = new RegExp("^[a-zA-Z0-9-]{1,80}$", "u");
    var pattern5 = new RegExp("^(\\/([^~]|~[01])*)+$", "u");
    var pattern6 = new RegExp(`^meta\\[name=(?:"[a-zA-Z0-9_.-]+"|'[a-zA-Z0-9_.-]+')\\]$`, "u");
    var pattern7 = new RegExp("^https?://[^/?#]+$", "u");
    var pattern8 = new RegExp("^/", "u");
    function validate21(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate21.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.schemaVersion === void 0 && (missing0 = "schemaVersion") || data.recordingId === void 0 && (missing0 = "recordingId") || data.browserRunId === void 0 && (missing0 = "browserRunId") || data.state === void 0 && (missing0 = "state") || data.scopeVersion === void 0 && (missing0 = "scopeVersion") || data.environmentId === void 0 && (missing0 = "environmentId") || data.browserVersion === void 0 && (missing0 = "browserVersion") || data.extensionVersion === void 0 && (missing0 = "extensionVersion") || data.rrwebVersion === void 0 && (missing0 = "rrwebVersion") || data.startedAt === void 0 && (missing0 = "startedAt") || data.policy === void 0 && (missing0 = "policy") || data.gaps === void 0 && (missing0 = "gaps") || data.rootTabInstanceIds === void 0 && (missing0 = "rootTabInstanceIds") || data.commands === void 0 && (missing0 = "commands") || data.bytesAccepted === void 0 && (missing0 = "bytesAccepted") || data.bytesPersisted === void 0 && (missing0 = "bytesPersisted") || data.eventsPersisted === void 0 && (missing0 = "eventsPersisted") || data.checkpoint === void 0 && (missing0 = "checkpoint") || data.saveState === void 0 && (missing0 = "saveState") || data.versions === void 0 && (missing0 = "versions") || data.capabilities === void 0 && (missing0 = "capabilities")) {
            validate21.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.schemaVersion !== void 0) {
              const _errs1 = errors;
              if ("3.0.0" !== data.schemaVersion) {
                validate21.errors = [{ instancePath: instancePath + "/schemaVersion", schemaPath: "#/properties/schemaVersion/const", keyword: "const", params: { allowedValue: "3.0.0" }, message: "must be equal to constant" }];
                return false;
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.recordingId !== void 0) {
                let data1 = data.recordingId;
                const _errs2 = errors;
                if (errors === _errs2) {
                  if (typeof data1 === "string") {
                    if (func1(data1) > 256) {
                      validate21.errors = [{ instancePath: instancePath + "/recordingId", schemaPath: "#/properties/recordingId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                      return false;
                    } else {
                      if (func1(data1) < 1) {
                        validate21.errors = [{ instancePath: instancePath + "/recordingId", schemaPath: "#/properties/recordingId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                        return false;
                      }
                    }
                  } else {
                    validate21.errors = [{ instancePath: instancePath + "/recordingId", schemaPath: "#/properties/recordingId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                    return false;
                  }
                }
                var valid0 = _errs2 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.browserRunId !== void 0) {
                  let data2 = data.browserRunId;
                  const _errs4 = errors;
                  if (errors === _errs4) {
                    if (typeof data2 === "string") {
                      if (func1(data2) > 256) {
                        validate21.errors = [{ instancePath: instancePath + "/browserRunId", schemaPath: "#/properties/browserRunId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                        return false;
                      } else {
                        if (func1(data2) < 1) {
                          validate21.errors = [{ instancePath: instancePath + "/browserRunId", schemaPath: "#/properties/browserRunId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                          return false;
                        }
                      }
                    } else {
                      validate21.errors = [{ instancePath: instancePath + "/browserRunId", schemaPath: "#/properties/browserRunId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                      return false;
                    }
                  }
                  var valid0 = _errs4 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.state !== void 0) {
                    let data3 = data.state;
                    const _errs6 = errors;
                    if (!(data3 === "STARTING" || data3 === "RECORDING" || data3 === "STOPPING" || data3 === "FINALIZING" || data3 === "READY" || data3 === "INTERRUPTED" || data3 === "FAILED")) {
                      validate21.errors = [{ instancePath: instancePath + "/state", schemaPath: "#/properties/state/enum", keyword: "enum", params: { allowedValues: schema32.properties.state.enum }, message: "must be equal to one of the allowed values" }];
                      return false;
                    }
                    var valid0 = _errs6 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.scopeVersion !== void 0) {
                      let data4 = data.scopeVersion;
                      const _errs7 = errors;
                      if (!(typeof data4 == "number" && (!(data4 % 1) && !isNaN(data4)))) {
                        validate21.errors = [{ instancePath: instancePath + "/scopeVersion", schemaPath: "#/properties/scopeVersion/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                        return false;
                      }
                      if (errors === _errs7) {
                        if (typeof data4 == "number") {
                          if (data4 < 0 || isNaN(data4)) {
                            validate21.errors = [{ instancePath: instancePath + "/scopeVersion", schemaPath: "#/properties/scopeVersion/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                            return false;
                          }
                        }
                      }
                      var valid0 = _errs7 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.environmentId !== void 0) {
                        const _errs9 = errors;
                        if (typeof data.environmentId !== "string") {
                          validate21.errors = [{ instancePath: instancePath + "/environmentId", schemaPath: "#/properties/environmentId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                          return false;
                        }
                        var valid0 = _errs9 === errors;
                      } else {
                        var valid0 = true;
                      }
                      if (valid0) {
                        if (data.browserVersion !== void 0) {
                          const _errs11 = errors;
                          if (typeof data.browserVersion !== "string") {
                            validate21.errors = [{ instancePath: instancePath + "/browserVersion", schemaPath: "#/properties/browserVersion/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                            return false;
                          }
                          var valid0 = _errs11 === errors;
                        } else {
                          var valid0 = true;
                        }
                        if (valid0) {
                          if (data.extensionVersion !== void 0) {
                            const _errs13 = errors;
                            if (typeof data.extensionVersion !== "string") {
                              validate21.errors = [{ instancePath: instancePath + "/extensionVersion", schemaPath: "#/properties/extensionVersion/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                              return false;
                            }
                            var valid0 = _errs13 === errors;
                          } else {
                            var valid0 = true;
                          }
                          if (valid0) {
                            if (data.rrwebVersion !== void 0) {
                              const _errs15 = errors;
                              if (typeof data.rrwebVersion !== "string") {
                                validate21.errors = [{ instancePath: instancePath + "/rrwebVersion", schemaPath: "#/properties/rrwebVersion/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                return false;
                              }
                              var valid0 = _errs15 === errors;
                            } else {
                              var valid0 = true;
                            }
                            if (valid0) {
                              if (data.startedAt !== void 0) {
                                const _errs17 = errors;
                                if (typeof data.startedAt !== "string") {
                                  validate21.errors = [{ instancePath: instancePath + "/startedAt", schemaPath: "#/properties/startedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                  return false;
                                }
                                var valid0 = _errs17 === errors;
                              } else {
                                var valid0 = true;
                              }
                              if (valid0) {
                                if (data.stoppedAt !== void 0) {
                                  const _errs19 = errors;
                                  if (typeof data.stoppedAt !== "string") {
                                    validate21.errors = [{ instancePath: instancePath + "/stoppedAt", schemaPath: "#/properties/stoppedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                    return false;
                                  }
                                  var valid0 = _errs19 === errors;
                                } else {
                                  var valid0 = true;
                                }
                                if (valid0) {
                                  if (data.policy !== void 0) {
                                    let data11 = data.policy;
                                    const _errs21 = errors;
                                    const _errs22 = errors;
                                    if (errors === _errs22) {
                                      if (data11 && typeof data11 == "object" && !Array.isArray(data11)) {
                                        let missing1;
                                        if (data11.policyVersion === void 0 && (missing1 = "policyVersion") || data11.pageOrigins === void 0 && (missing1 = "pageOrigins") || data11.apiRules === void 0 && (missing1 = "apiRules") || data11.requestTypes === void 0 && (missing1 = "requestTypes") || data11.allowedInputNames === void 0 && (missing1 = "allowedInputNames") || data11.allowedQueryKeys === void 0 && (missing1 = "allowedQueryKeys") || data11.sensitiveSelectors === void 0 && (missing1 = "sensitiveSelectors") || data11.maskAllText === void 0 && (missing1 = "maskAllText") || data11.screenshots === void 0 && (missing1 = "screenshots") || data11.captureStreaming === void 0 && (missing1 = "captureStreaming") || data11.businessRules === void 0 && (missing1 = "businessRules") || data11.budgets === void 0 && (missing1 = "budgets") || data11.logTimeMarginSeconds === void 0 && (missing1 = "logTimeMarginSeconds") || data11.correlationSources === void 0 && (missing1 = "correlationSources") || data11.sourceMappings === void 0 && (missing1 = "sourceMappings")) {
                                          validate21.errors = [{ instancePath: instancePath + "/policy", schemaPath: "#/$defs/policy/required", keyword: "required", params: { missingProperty: missing1 }, message: "must have required property '" + missing1 + "'" }];
                                          return false;
                                        } else {
                                          if (data11.policyVersion !== void 0) {
                                            const _errs24 = errors;
                                            if (typeof data11.policyVersion !== "string") {
                                              validate21.errors = [{ instancePath: instancePath + "/policy/policyVersion", schemaPath: "#/$defs/policy/properties/policyVersion/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                              return false;
                                            }
                                            var valid2 = _errs24 === errors;
                                          } else {
                                            var valid2 = true;
                                          }
                                          if (valid2) {
                                            if (data11.pageOrigins !== void 0) {
                                              let data13 = data11.pageOrigins;
                                              const _errs26 = errors;
                                              if (errors === _errs26) {
                                                if (Array.isArray(data13)) {
                                                  var valid3 = true;
                                                  const len0 = data13.length;
                                                  for (let i0 = 0; i0 < len0; i0++) {
                                                    const _errs28 = errors;
                                                    if (typeof data13[i0] !== "string") {
                                                      validate21.errors = [{ instancePath: instancePath + "/policy/pageOrigins/" + i0, schemaPath: "#/$defs/policy/properties/pageOrigins/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                      return false;
                                                    }
                                                    var valid3 = _errs28 === errors;
                                                    if (!valid3) {
                                                      break;
                                                    }
                                                  }
                                                } else {
                                                  validate21.errors = [{ instancePath: instancePath + "/policy/pageOrigins", schemaPath: "#/$defs/policy/properties/pageOrigins/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                  return false;
                                                }
                                              }
                                              var valid2 = _errs26 === errors;
                                            } else {
                                              var valid2 = true;
                                            }
                                            if (valid2) {
                                              if (data11.apiRules !== void 0) {
                                                let data15 = data11.apiRules;
                                                const _errs30 = errors;
                                                if (errors === _errs30) {
                                                  if (Array.isArray(data15)) {
                                                    var valid4 = true;
                                                    const len1 = data15.length;
                                                    for (let i1 = 0; i1 < len1; i1++) {
                                                      let data16 = data15[i1];
                                                      const _errs32 = errors;
                                                      if (errors === _errs32) {
                                                        if (data16 && typeof data16 == "object" && !Array.isArray(data16)) {
                                                          let missing2;
                                                          if (data16.origin === void 0 && (missing2 = "origin") || data16.pathPrefix === void 0 && (missing2 = "pathPrefix")) {
                                                            validate21.errors = [{ instancePath: instancePath + "/policy/apiRules/" + i1, schemaPath: "#/$defs/policy/properties/apiRules/items/required", keyword: "required", params: { missingProperty: missing2 }, message: "must have required property '" + missing2 + "'" }];
                                                            return false;
                                                          } else {
                                                            if (data16.origin !== void 0) {
                                                              const _errs34 = errors;
                                                              if (typeof data16.origin !== "string") {
                                                                validate21.errors = [{ instancePath: instancePath + "/policy/apiRules/" + i1 + "/origin", schemaPath: "#/$defs/policy/properties/apiRules/items/properties/origin/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                return false;
                                                              }
                                                              var valid5 = _errs34 === errors;
                                                            } else {
                                                              var valid5 = true;
                                                            }
                                                            if (valid5) {
                                                              if (data16.pathPrefix !== void 0) {
                                                                const _errs36 = errors;
                                                                if (typeof data16.pathPrefix !== "string") {
                                                                  validate21.errors = [{ instancePath: instancePath + "/policy/apiRules/" + i1 + "/pathPrefix", schemaPath: "#/$defs/policy/properties/apiRules/items/properties/pathPrefix/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                  return false;
                                                                }
                                                                var valid5 = _errs36 === errors;
                                                              } else {
                                                                var valid5 = true;
                                                              }
                                                            }
                                                          }
                                                        } else {
                                                          validate21.errors = [{ instancePath: instancePath + "/policy/apiRules/" + i1, schemaPath: "#/$defs/policy/properties/apiRules/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                          return false;
                                                        }
                                                      }
                                                      var valid4 = _errs32 === errors;
                                                      if (!valid4) {
                                                        break;
                                                      }
                                                    }
                                                  } else {
                                                    validate21.errors = [{ instancePath: instancePath + "/policy/apiRules", schemaPath: "#/$defs/policy/properties/apiRules/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                    return false;
                                                  }
                                                }
                                                var valid2 = _errs30 === errors;
                                              } else {
                                                var valid2 = true;
                                              }
                                              if (valid2) {
                                                if (data11.requestTypes !== void 0) {
                                                  let data19 = data11.requestTypes;
                                                  const _errs38 = errors;
                                                  if (errors === _errs38) {
                                                    if (Array.isArray(data19)) {
                                                      var valid6 = true;
                                                      const len2 = data19.length;
                                                      for (let i2 = 0; i2 < len2; i2++) {
                                                        const _errs40 = errors;
                                                        if (typeof data19[i2] !== "string") {
                                                          validate21.errors = [{ instancePath: instancePath + "/policy/requestTypes/" + i2, schemaPath: "#/$defs/policy/properties/requestTypes/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                          return false;
                                                        }
                                                        var valid6 = _errs40 === errors;
                                                        if (!valid6) {
                                                          break;
                                                        }
                                                      }
                                                    } else {
                                                      validate21.errors = [{ instancePath: instancePath + "/policy/requestTypes", schemaPath: "#/$defs/policy/properties/requestTypes/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                      return false;
                                                    }
                                                  }
                                                  var valid2 = _errs38 === errors;
                                                } else {
                                                  var valid2 = true;
                                                }
                                                if (valid2) {
                                                  if (data11.allowedInputNames !== void 0) {
                                                    let data21 = data11.allowedInputNames;
                                                    const _errs42 = errors;
                                                    if (errors === _errs42) {
                                                      if (Array.isArray(data21)) {
                                                        var valid7 = true;
                                                        const len3 = data21.length;
                                                        for (let i3 = 0; i3 < len3; i3++) {
                                                          const _errs44 = errors;
                                                          if (typeof data21[i3] !== "string") {
                                                            validate21.errors = [{ instancePath: instancePath + "/policy/allowedInputNames/" + i3, schemaPath: "#/$defs/policy/properties/allowedInputNames/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                            return false;
                                                          }
                                                          var valid7 = _errs44 === errors;
                                                          if (!valid7) {
                                                            break;
                                                          }
                                                        }
                                                      } else {
                                                        validate21.errors = [{ instancePath: instancePath + "/policy/allowedInputNames", schemaPath: "#/$defs/policy/properties/allowedInputNames/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                        return false;
                                                      }
                                                    }
                                                    var valid2 = _errs42 === errors;
                                                  } else {
                                                    var valid2 = true;
                                                  }
                                                  if (valid2) {
                                                    if (data11.allowedQueryKeys !== void 0) {
                                                      let data23 = data11.allowedQueryKeys;
                                                      const _errs46 = errors;
                                                      if (errors === _errs46) {
                                                        if (Array.isArray(data23)) {
                                                          var valid8 = true;
                                                          const len4 = data23.length;
                                                          for (let i4 = 0; i4 < len4; i4++) {
                                                            const _errs48 = errors;
                                                            if (typeof data23[i4] !== "string") {
                                                              validate21.errors = [{ instancePath: instancePath + "/policy/allowedQueryKeys/" + i4, schemaPath: "#/$defs/policy/properties/allowedQueryKeys/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                              return false;
                                                            }
                                                            var valid8 = _errs48 === errors;
                                                            if (!valid8) {
                                                              break;
                                                            }
                                                          }
                                                        } else {
                                                          validate21.errors = [{ instancePath: instancePath + "/policy/allowedQueryKeys", schemaPath: "#/$defs/policy/properties/allowedQueryKeys/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                          return false;
                                                        }
                                                      }
                                                      var valid2 = _errs46 === errors;
                                                    } else {
                                                      var valid2 = true;
                                                    }
                                                    if (valid2) {
                                                      if (data11.sensitiveSelectors !== void 0) {
                                                        let data25 = data11.sensitiveSelectors;
                                                        const _errs50 = errors;
                                                        if (errors === _errs50) {
                                                          if (Array.isArray(data25)) {
                                                            var valid9 = true;
                                                            const len5 = data25.length;
                                                            for (let i5 = 0; i5 < len5; i5++) {
                                                              const _errs52 = errors;
                                                              if (typeof data25[i5] !== "string") {
                                                                validate21.errors = [{ instancePath: instancePath + "/policy/sensitiveSelectors/" + i5, schemaPath: "#/$defs/policy/properties/sensitiveSelectors/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                return false;
                                                              }
                                                              var valid9 = _errs52 === errors;
                                                              if (!valid9) {
                                                                break;
                                                              }
                                                            }
                                                          } else {
                                                            validate21.errors = [{ instancePath: instancePath + "/policy/sensitiveSelectors", schemaPath: "#/$defs/policy/properties/sensitiveSelectors/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                            return false;
                                                          }
                                                        }
                                                        var valid2 = _errs50 === errors;
                                                      } else {
                                                        var valid2 = true;
                                                      }
                                                      if (valid2) {
                                                        if (data11.maskAllText !== void 0) {
                                                          const _errs54 = errors;
                                                          if (typeof data11.maskAllText !== "boolean") {
                                                            validate21.errors = [{ instancePath: instancePath + "/policy/maskAllText", schemaPath: "#/$defs/policy/properties/maskAllText/type", keyword: "type", params: { type: "boolean" }, message: "must be boolean" }];
                                                            return false;
                                                          }
                                                          var valid2 = _errs54 === errors;
                                                        } else {
                                                          var valid2 = true;
                                                        }
                                                        if (valid2) {
                                                          if (data11.screenshots !== void 0) {
                                                            const _errs56 = errors;
                                                            if ("disabled" !== data11.screenshots) {
                                                              validate21.errors = [{ instancePath: instancePath + "/policy/screenshots", schemaPath: "#/$defs/policy/properties/screenshots/const", keyword: "const", params: { allowedValue: "disabled" }, message: "must be equal to constant" }];
                                                              return false;
                                                            }
                                                            var valid2 = _errs56 === errors;
                                                          } else {
                                                            var valid2 = true;
                                                          }
                                                          if (valid2) {
                                                            if (data11.captureStreaming !== void 0) {
                                                              const _errs57 = errors;
                                                              if (typeof data11.captureStreaming !== "boolean") {
                                                                validate21.errors = [{ instancePath: instancePath + "/policy/captureStreaming", schemaPath: "#/$defs/policy/properties/captureStreaming/type", keyword: "type", params: { type: "boolean" }, message: "must be boolean" }];
                                                                return false;
                                                              }
                                                              var valid2 = _errs57 === errors;
                                                            } else {
                                                              var valid2 = true;
                                                            }
                                                            if (valid2) {
                                                              if (data11.businessRules !== void 0) {
                                                                let data30 = data11.businessRules;
                                                                const _errs59 = errors;
                                                                if (errors === _errs59) {
                                                                  if (Array.isArray(data30)) {
                                                                    var valid10 = true;
                                                                    const len6 = data30.length;
                                                                    for (let i6 = 0; i6 < len6; i6++) {
                                                                      let data31 = data30[i6];
                                                                      const _errs61 = errors;
                                                                      if (errors === _errs61) {
                                                                        if (data31 && typeof data31 == "object" && !Array.isArray(data31)) {
                                                                          let missing3;
                                                                          if (data31.origin === void 0 && (missing3 = "origin") || data31.pathPrefix === void 0 && (missing3 = "pathPrefix") || data31.codePath === void 0 && (missing3 = "codePath") || data31.successValues === void 0 && (missing3 = "successValues")) {
                                                                            validate21.errors = [{ instancePath: instancePath + "/policy/businessRules/" + i6, schemaPath: "#/$defs/policy/properties/businessRules/items/required", keyword: "required", params: { missingProperty: missing3 }, message: "must have required property '" + missing3 + "'" }];
                                                                            return false;
                                                                          } else {
                                                                            if (data31.origin !== void 0) {
                                                                              const _errs63 = errors;
                                                                              if (typeof data31.origin !== "string") {
                                                                                validate21.errors = [{ instancePath: instancePath + "/policy/businessRules/" + i6 + "/origin", schemaPath: "#/$defs/policy/properties/businessRules/items/properties/origin/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                return false;
                                                                              }
                                                                              var valid11 = _errs63 === errors;
                                                                            } else {
                                                                              var valid11 = true;
                                                                            }
                                                                            if (valid11) {
                                                                              if (data31.pathPrefix !== void 0) {
                                                                                const _errs65 = errors;
                                                                                if (typeof data31.pathPrefix !== "string") {
                                                                                  validate21.errors = [{ instancePath: instancePath + "/policy/businessRules/" + i6 + "/pathPrefix", schemaPath: "#/$defs/policy/properties/businessRules/items/properties/pathPrefix/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                  return false;
                                                                                }
                                                                                var valid11 = _errs65 === errors;
                                                                              } else {
                                                                                var valid11 = true;
                                                                              }
                                                                              if (valid11) {
                                                                                if (data31.codePath !== void 0) {
                                                                                  const _errs67 = errors;
                                                                                  if (typeof data31.codePath !== "string") {
                                                                                    validate21.errors = [{ instancePath: instancePath + "/policy/businessRules/" + i6 + "/codePath", schemaPath: "#/$defs/policy/properties/businessRules/items/properties/codePath/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                    return false;
                                                                                  }
                                                                                  var valid11 = _errs67 === errors;
                                                                                } else {
                                                                                  var valid11 = true;
                                                                                }
                                                                                if (valid11) {
                                                                                  if (data31.successValues !== void 0) {
                                                                                    let data35 = data31.successValues;
                                                                                    const _errs69 = errors;
                                                                                    if (errors === _errs69) {
                                                                                      if (Array.isArray(data35)) {
                                                                                        var valid12 = true;
                                                                                        const len7 = data35.length;
                                                                                        for (let i7 = 0; i7 < len7; i7++) {
                                                                                          let data36 = data35[i7];
                                                                                          const _errs71 = errors;
                                                                                          if (typeof data36 !== "string" && !(typeof data36 == "number")) {
                                                                                            validate21.errors = [{ instancePath: instancePath + "/policy/businessRules/" + i6 + "/successValues/" + i7, schemaPath: "#/$defs/policy/properties/businessRules/items/properties/successValues/items/type", keyword: "type", params: { type: schema33.properties.businessRules.items.properties.successValues.items.type }, message: "must be string,number" }];
                                                                                            return false;
                                                                                          }
                                                                                          var valid12 = _errs71 === errors;
                                                                                          if (!valid12) {
                                                                                            break;
                                                                                          }
                                                                                        }
                                                                                      } else {
                                                                                        validate21.errors = [{ instancePath: instancePath + "/policy/businessRules/" + i6 + "/successValues", schemaPath: "#/$defs/policy/properties/businessRules/items/properties/successValues/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                                                        return false;
                                                                                      }
                                                                                    }
                                                                                    var valid11 = _errs69 === errors;
                                                                                  } else {
                                                                                    var valid11 = true;
                                                                                  }
                                                                                }
                                                                              }
                                                                            }
                                                                          }
                                                                        } else {
                                                                          validate21.errors = [{ instancePath: instancePath + "/policy/businessRules/" + i6, schemaPath: "#/$defs/policy/properties/businessRules/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                          return false;
                                                                        }
                                                                      }
                                                                      var valid10 = _errs61 === errors;
                                                                      if (!valid10) {
                                                                        break;
                                                                      }
                                                                    }
                                                                  } else {
                                                                    validate21.errors = [{ instancePath: instancePath + "/policy/businessRules", schemaPath: "#/$defs/policy/properties/businessRules/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                                    return false;
                                                                  }
                                                                }
                                                                var valid2 = _errs59 === errors;
                                                              } else {
                                                                var valid2 = true;
                                                              }
                                                              if (valid2) {
                                                                if (data11.budgets !== void 0) {
                                                                  let data37 = data11.budgets;
                                                                  const _errs73 = errors;
                                                                  if (errors === _errs73) {
                                                                    if (data37 && typeof data37 == "object" && !Array.isArray(data37)) {
                                                                      let missing4;
                                                                      if (data37.softTabs === void 0 && (missing4 = "softTabs") || data37.hardTabs === void 0 && (missing4 = "hardTabs") || data37.reminderMinutes === void 0 && (missing4 = "reminderMinutes") || data37.ipcBytes === void 0 && (missing4 = "ipcBytes") || data37.baselineBytes === void 0 && (missing4 = "baselineBytes") || data37.bodyBytes === void 0 && (missing4 = "bodyBytes") || data37.softBytes === void 0 && (missing4 = "softBytes") || data37.hardBytes === void 0 && (missing4 = "hardBytes") || data37.queueBytes === void 0 && (missing4 = "queueBytes") || data37.bodyConcurrency === void 0 && (missing4 = "bodyConcurrency")) {
                                                                        validate21.errors = [{ instancePath: instancePath + "/policy/budgets", schemaPath: "#/$defs/policy/properties/budgets/required", keyword: "required", params: { missingProperty: missing4 }, message: "must have required property '" + missing4 + "'" }];
                                                                        return false;
                                                                      } else {
                                                                        if (data37.softTabs !== void 0) {
                                                                          let data38 = data37.softTabs;
                                                                          const _errs75 = errors;
                                                                          if (!(typeof data38 == "number" && (!(data38 % 1) && !isNaN(data38)))) {
                                                                            validate21.errors = [{ instancePath: instancePath + "/policy/budgets/softTabs", schemaPath: "#/$defs/policy/properties/budgets/properties/softTabs/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                            return false;
                                                                          }
                                                                          if (errors === _errs75) {
                                                                            if (typeof data38 == "number") {
                                                                              if (data38 < 1 || isNaN(data38)) {
                                                                                validate21.errors = [{ instancePath: instancePath + "/policy/budgets/softTabs", schemaPath: "#/$defs/policy/properties/budgets/properties/softTabs/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                return false;
                                                                              }
                                                                            }
                                                                          }
                                                                          var valid13 = _errs75 === errors;
                                                                        } else {
                                                                          var valid13 = true;
                                                                        }
                                                                        if (valid13) {
                                                                          if (data37.hardTabs !== void 0) {
                                                                            let data39 = data37.hardTabs;
                                                                            const _errs77 = errors;
                                                                            if (!(typeof data39 == "number" && (!(data39 % 1) && !isNaN(data39)))) {
                                                                              validate21.errors = [{ instancePath: instancePath + "/policy/budgets/hardTabs", schemaPath: "#/$defs/policy/properties/budgets/properties/hardTabs/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                              return false;
                                                                            }
                                                                            if (errors === _errs77) {
                                                                              if (typeof data39 == "number") {
                                                                                if (data39 < 1 || isNaN(data39)) {
                                                                                  validate21.errors = [{ instancePath: instancePath + "/policy/budgets/hardTabs", schemaPath: "#/$defs/policy/properties/budgets/properties/hardTabs/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                  return false;
                                                                                }
                                                                              }
                                                                            }
                                                                            var valid13 = _errs77 === errors;
                                                                          } else {
                                                                            var valid13 = true;
                                                                          }
                                                                          if (valid13) {
                                                                            if (data37.reminderMinutes !== void 0) {
                                                                              let data40 = data37.reminderMinutes;
                                                                              const _errs79 = errors;
                                                                              if (!(typeof data40 == "number" && (!(data40 % 1) && !isNaN(data40)))) {
                                                                                validate21.errors = [{ instancePath: instancePath + "/policy/budgets/reminderMinutes", schemaPath: "#/$defs/policy/properties/budgets/properties/reminderMinutes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                return false;
                                                                              }
                                                                              if (errors === _errs79) {
                                                                                if (typeof data40 == "number") {
                                                                                  if (data40 < 1 || isNaN(data40)) {
                                                                                    validate21.errors = [{ instancePath: instancePath + "/policy/budgets/reminderMinutes", schemaPath: "#/$defs/policy/properties/budgets/properties/reminderMinutes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                    return false;
                                                                                  }
                                                                                }
                                                                              }
                                                                              var valid13 = _errs79 === errors;
                                                                            } else {
                                                                              var valid13 = true;
                                                                            }
                                                                            if (valid13) {
                                                                              if (data37.ipcBytes !== void 0) {
                                                                                let data41 = data37.ipcBytes;
                                                                                const _errs81 = errors;
                                                                                if (!(typeof data41 == "number" && (!(data41 % 1) && !isNaN(data41)))) {
                                                                                  validate21.errors = [{ instancePath: instancePath + "/policy/budgets/ipcBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/ipcBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                  return false;
                                                                                }
                                                                                if (errors === _errs81) {
                                                                                  if (typeof data41 == "number") {
                                                                                    if (data41 < 1 || isNaN(data41)) {
                                                                                      validate21.errors = [{ instancePath: instancePath + "/policy/budgets/ipcBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/ipcBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                      return false;
                                                                                    }
                                                                                  }
                                                                                }
                                                                                var valid13 = _errs81 === errors;
                                                                              } else {
                                                                                var valid13 = true;
                                                                              }
                                                                              if (valid13) {
                                                                                if (data37.baselineBytes !== void 0) {
                                                                                  let data42 = data37.baselineBytes;
                                                                                  const _errs83 = errors;
                                                                                  if (!(typeof data42 == "number" && (!(data42 % 1) && !isNaN(data42)))) {
                                                                                    validate21.errors = [{ instancePath: instancePath + "/policy/budgets/baselineBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/baselineBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                    return false;
                                                                                  }
                                                                                  if (errors === _errs83) {
                                                                                    if (typeof data42 == "number") {
                                                                                      if (data42 < 1 || isNaN(data42)) {
                                                                                        validate21.errors = [{ instancePath: instancePath + "/policy/budgets/baselineBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/baselineBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                        return false;
                                                                                      }
                                                                                    }
                                                                                  }
                                                                                  var valid13 = _errs83 === errors;
                                                                                } else {
                                                                                  var valid13 = true;
                                                                                }
                                                                                if (valid13) {
                                                                                  if (data37.bodyBytes !== void 0) {
                                                                                    let data43 = data37.bodyBytes;
                                                                                    const _errs85 = errors;
                                                                                    if (!(typeof data43 == "number" && (!(data43 % 1) && !isNaN(data43)))) {
                                                                                      validate21.errors = [{ instancePath: instancePath + "/policy/budgets/bodyBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/bodyBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                      return false;
                                                                                    }
                                                                                    if (errors === _errs85) {
                                                                                      if (typeof data43 == "number") {
                                                                                        if (data43 < 1 || isNaN(data43)) {
                                                                                          validate21.errors = [{ instancePath: instancePath + "/policy/budgets/bodyBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/bodyBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                          return false;
                                                                                        }
                                                                                      }
                                                                                    }
                                                                                    var valid13 = _errs85 === errors;
                                                                                  } else {
                                                                                    var valid13 = true;
                                                                                  }
                                                                                  if (valid13) {
                                                                                    if (data37.softBytes !== void 0) {
                                                                                      let data44 = data37.softBytes;
                                                                                      const _errs87 = errors;
                                                                                      if (!(typeof data44 == "number" && (!(data44 % 1) && !isNaN(data44)))) {
                                                                                        validate21.errors = [{ instancePath: instancePath + "/policy/budgets/softBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/softBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                        return false;
                                                                                      }
                                                                                      if (errors === _errs87) {
                                                                                        if (typeof data44 == "number") {
                                                                                          if (data44 < 1 || isNaN(data44)) {
                                                                                            validate21.errors = [{ instancePath: instancePath + "/policy/budgets/softBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/softBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                            return false;
                                                                                          }
                                                                                        }
                                                                                      }
                                                                                      var valid13 = _errs87 === errors;
                                                                                    } else {
                                                                                      var valid13 = true;
                                                                                    }
                                                                                    if (valid13) {
                                                                                      if (data37.hardBytes !== void 0) {
                                                                                        let data45 = data37.hardBytes;
                                                                                        const _errs89 = errors;
                                                                                        if (!(typeof data45 == "number" && (!(data45 % 1) && !isNaN(data45)))) {
                                                                                          validate21.errors = [{ instancePath: instancePath + "/policy/budgets/hardBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/hardBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                          return false;
                                                                                        }
                                                                                        if (errors === _errs89) {
                                                                                          if (typeof data45 == "number") {
                                                                                            if (data45 < 1 || isNaN(data45)) {
                                                                                              validate21.errors = [{ instancePath: instancePath + "/policy/budgets/hardBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/hardBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                              return false;
                                                                                            }
                                                                                          }
                                                                                        }
                                                                                        var valid13 = _errs89 === errors;
                                                                                      } else {
                                                                                        var valid13 = true;
                                                                                      }
                                                                                      if (valid13) {
                                                                                        if (data37.queueBytes !== void 0) {
                                                                                          let data46 = data37.queueBytes;
                                                                                          const _errs91 = errors;
                                                                                          if (!(typeof data46 == "number" && (!(data46 % 1) && !isNaN(data46)))) {
                                                                                            validate21.errors = [{ instancePath: instancePath + "/policy/budgets/queueBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/queueBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                            return false;
                                                                                          }
                                                                                          if (errors === _errs91) {
                                                                                            if (typeof data46 == "number") {
                                                                                              if (data46 < 1 || isNaN(data46)) {
                                                                                                validate21.errors = [{ instancePath: instancePath + "/policy/budgets/queueBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/queueBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                                return false;
                                                                                              }
                                                                                            }
                                                                                          }
                                                                                          var valid13 = _errs91 === errors;
                                                                                        } else {
                                                                                          var valid13 = true;
                                                                                        }
                                                                                        if (valid13) {
                                                                                          if (data37.bodyConcurrency !== void 0) {
                                                                                            let data47 = data37.bodyConcurrency;
                                                                                            const _errs93 = errors;
                                                                                            if (!(typeof data47 == "number" && (!(data47 % 1) && !isNaN(data47)))) {
                                                                                              validate21.errors = [{ instancePath: instancePath + "/policy/budgets/bodyConcurrency", schemaPath: "#/$defs/policy/properties/budgets/properties/bodyConcurrency/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                              return false;
                                                                                            }
                                                                                            if (errors === _errs93) {
                                                                                              if (typeof data47 == "number") {
                                                                                                if (data47 < 1 || isNaN(data47)) {
                                                                                                  validate21.errors = [{ instancePath: instancePath + "/policy/budgets/bodyConcurrency", schemaPath: "#/$defs/policy/properties/budgets/properties/bodyConcurrency/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                                  return false;
                                                                                                }
                                                                                              }
                                                                                            }
                                                                                            var valid13 = _errs93 === errors;
                                                                                          } else {
                                                                                            var valid13 = true;
                                                                                          }
                                                                                        }
                                                                                      }
                                                                                    }
                                                                                  }
                                                                                }
                                                                              }
                                                                            }
                                                                          }
                                                                        }
                                                                      }
                                                                    } else {
                                                                      validate21.errors = [{ instancePath: instancePath + "/policy/budgets", schemaPath: "#/$defs/policy/properties/budgets/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                      return false;
                                                                    }
                                                                  }
                                                                  var valid2 = _errs73 === errors;
                                                                } else {
                                                                  var valid2 = true;
                                                                }
                                                                if (valid2) {
                                                                  if (data11.logTimeMarginSeconds !== void 0) {
                                                                    let data48 = data11.logTimeMarginSeconds;
                                                                    const _errs95 = errors;
                                                                    if (!(typeof data48 == "number" && (!(data48 % 1) && !isNaN(data48)))) {
                                                                      validate21.errors = [{ instancePath: instancePath + "/policy/logTimeMarginSeconds", schemaPath: "#/$defs/policy/properties/logTimeMarginSeconds/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                      return false;
                                                                    }
                                                                    if (errors === _errs95) {
                                                                      if (typeof data48 == "number") {
                                                                        if (data48 < 0 || isNaN(data48)) {
                                                                          validate21.errors = [{ instancePath: instancePath + "/policy/logTimeMarginSeconds", schemaPath: "#/$defs/policy/properties/logTimeMarginSeconds/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                                          return false;
                                                                        }
                                                                      }
                                                                    }
                                                                    var valid2 = _errs95 === errors;
                                                                  } else {
                                                                    var valid2 = true;
                                                                  }
                                                                  if (valid2) {
                                                                    if (data11.correlationSources !== void 0) {
                                                                      let data49 = data11.correlationSources;
                                                                      const _errs97 = errors;
                                                                      if (errors === _errs97) {
                                                                        if (Array.isArray(data49)) {
                                                                          if (data49.length > 32) {
                                                                            validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources", schemaPath: "#/$defs/policy/properties/correlationSources/maxItems", keyword: "maxItems", params: { limit: 32 }, message: "must NOT have more than 32 items" }];
                                                                            return false;
                                                                          } else {
                                                                            var valid14 = true;
                                                                            const len8 = data49.length;
                                                                            for (let i8 = 0; i8 < len8; i8++) {
                                                                              let data50 = data49[i8];
                                                                              const _errs99 = errors;
                                                                              const _errs101 = errors;
                                                                              const _errs102 = errors;
                                                                              let valid16 = true;
                                                                              const _errs103 = errors;
                                                                              if (data50 && typeof data50 == "object" && !Array.isArray(data50)) {
                                                                                if (data50.source !== void 0) {
                                                                                  if ("response_header" !== data50.source) {
                                                                                    const err0 = {};
                                                                                    if (vErrors === null) {
                                                                                      vErrors = [err0];
                                                                                    } else {
                                                                                      vErrors.push(err0);
                                                                                    }
                                                                                    errors++;
                                                                                  }
                                                                                }
                                                                              }
                                                                              var _valid0 = _errs103 === errors;
                                                                              errors = _errs102;
                                                                              if (vErrors !== null) {
                                                                                if (_errs102) {
                                                                                  vErrors.length = _errs102;
                                                                                } else {
                                                                                  vErrors = null;
                                                                                }
                                                                              }
                                                                              if (_valid0) {
                                                                                const _errs105 = errors;
                                                                                if (data50 && typeof data50 == "object" && !Array.isArray(data50)) {
                                                                                  if (data50.key !== void 0) {
                                                                                    let data52 = data50.key;
                                                                                    if (typeof data52 === "string") {
                                                                                      if (!pattern4.test(data52)) {
                                                                                        validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/key", schemaPath: "#/$defs/policy/properties/correlationSources/items/allOf/0/then/properties/key/pattern", keyword: "pattern", params: { pattern: "^[a-zA-Z0-9-]{1,80}$" }, message: 'must match pattern "^[a-zA-Z0-9-]{1,80}$"' }];
                                                                                        return false;
                                                                                      }
                                                                                    }
                                                                                  }
                                                                                }
                                                                                var _valid0 = _errs105 === errors;
                                                                                valid16 = _valid0;
                                                                                if (valid16) {
                                                                                  var props0 = {};
                                                                                  props0.key = true;
                                                                                  props0.source = true;
                                                                                }
                                                                              }
                                                                              if (!valid16) {
                                                                                const err1 = { instancePath: instancePath + "/policy/correlationSources/" + i8, schemaPath: "#/$defs/policy/properties/correlationSources/items/allOf/0/if", keyword: "if", params: { failingKeyword: "then" }, message: 'must match "then" schema' };
                                                                                if (vErrors === null) {
                                                                                  vErrors = [err1];
                                                                                } else {
                                                                                  vErrors.push(err1);
                                                                                }
                                                                                errors++;
                                                                                validate21.errors = vErrors;
                                                                                return false;
                                                                              }
                                                                              var valid15 = _errs101 === errors;
                                                                              if (valid15) {
                                                                                const _errs107 = errors;
                                                                                const _errs108 = errors;
                                                                                let valid19 = true;
                                                                                const _errs109 = errors;
                                                                                if (data50 && typeof data50 == "object" && !Array.isArray(data50)) {
                                                                                  if (data50.source !== void 0) {
                                                                                    if ("response_json" !== data50.source) {
                                                                                      const err2 = {};
                                                                                      if (vErrors === null) {
                                                                                        vErrors = [err2];
                                                                                      } else {
                                                                                        vErrors.push(err2);
                                                                                      }
                                                                                      errors++;
                                                                                    }
                                                                                  }
                                                                                }
                                                                                var _valid1 = _errs109 === errors;
                                                                                errors = _errs108;
                                                                                if (vErrors !== null) {
                                                                                  if (_errs108) {
                                                                                    vErrors.length = _errs108;
                                                                                  } else {
                                                                                    vErrors = null;
                                                                                  }
                                                                                }
                                                                                if (_valid1) {
                                                                                  const _errs111 = errors;
                                                                                  if (data50 && typeof data50 == "object" && !Array.isArray(data50)) {
                                                                                    if (data50.key !== void 0) {
                                                                                      let data54 = data50.key;
                                                                                      if (typeof data54 === "string") {
                                                                                        if (!pattern5.test(data54)) {
                                                                                          validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/key", schemaPath: "#/$defs/policy/properties/correlationSources/items/allOf/1/then/properties/key/pattern", keyword: "pattern", params: { pattern: "^(\\/([^~]|~[01])*)+$" }, message: 'must match pattern "^(\\/([^~]|~[01])*)+$"' }];
                                                                                          return false;
                                                                                        }
                                                                                      }
                                                                                    }
                                                                                  }
                                                                                  var _valid1 = _errs111 === errors;
                                                                                  valid19 = _valid1;
                                                                                  if (valid19) {
                                                                                    var props1 = {};
                                                                                    props1.key = true;
                                                                                    props1.source = true;
                                                                                  }
                                                                                }
                                                                                if (!valid19) {
                                                                                  const err3 = { instancePath: instancePath + "/policy/correlationSources/" + i8, schemaPath: "#/$defs/policy/properties/correlationSources/items/allOf/1/if", keyword: "if", params: { failingKeyword: "then" }, message: 'must match "then" schema' };
                                                                                  if (vErrors === null) {
                                                                                    vErrors = [err3];
                                                                                  } else {
                                                                                    vErrors.push(err3);
                                                                                  }
                                                                                  errors++;
                                                                                  validate21.errors = vErrors;
                                                                                  return false;
                                                                                }
                                                                                var valid15 = _errs107 === errors;
                                                                                if (valid15) {
                                                                                  if (props0 !== true && props1 !== void 0) {
                                                                                    if (props1 === true) {
                                                                                      props0 = true;
                                                                                    } else {
                                                                                      props0 = props0 || {};
                                                                                      Object.assign(props0, props1);
                                                                                    }
                                                                                  }
                                                                                  const _errs113 = errors;
                                                                                  const _errs114 = errors;
                                                                                  let valid22 = true;
                                                                                  const _errs115 = errors;
                                                                                  if (data50 && typeof data50 == "object" && !Array.isArray(data50)) {
                                                                                    if (data50.source !== void 0) {
                                                                                      if ("page_meta" !== data50.source) {
                                                                                        const err4 = {};
                                                                                        if (vErrors === null) {
                                                                                          vErrors = [err4];
                                                                                        } else {
                                                                                          vErrors.push(err4);
                                                                                        }
                                                                                        errors++;
                                                                                      }
                                                                                    }
                                                                                  }
                                                                                  var _valid2 = _errs115 === errors;
                                                                                  errors = _errs114;
                                                                                  if (vErrors !== null) {
                                                                                    if (_errs114) {
                                                                                      vErrors.length = _errs114;
                                                                                    } else {
                                                                                      vErrors = null;
                                                                                    }
                                                                                  }
                                                                                  if (_valid2) {
                                                                                    const _errs117 = errors;
                                                                                    if (data50 && typeof data50 == "object" && !Array.isArray(data50)) {
                                                                                      if (data50.key !== void 0) {
                                                                                        let data56 = data50.key;
                                                                                        if (typeof data56 === "string") {
                                                                                          if (!pattern6.test(data56)) {
                                                                                            validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/key", schemaPath: "#/$defs/policy/properties/correlationSources/items/allOf/2/then/properties/key/pattern", keyword: "pattern", params: { pattern: `^meta\\[name=(?:"[a-zA-Z0-9_.-]+"|'[a-zA-Z0-9_.-]+')\\]$` }, message: `must match pattern "^meta\\[name=(?:"[a-zA-Z0-9_.-]+"|'[a-zA-Z0-9_.-]+')\\]$"` }];
                                                                                            return false;
                                                                                          }
                                                                                        }
                                                                                      }
                                                                                    }
                                                                                    var _valid2 = _errs117 === errors;
                                                                                    valid22 = _valid2;
                                                                                    if (valid22) {
                                                                                      var props2 = {};
                                                                                      props2.key = true;
                                                                                      props2.source = true;
                                                                                    }
                                                                                  }
                                                                                  if (!valid22) {
                                                                                    const err5 = { instancePath: instancePath + "/policy/correlationSources/" + i8, schemaPath: "#/$defs/policy/properties/correlationSources/items/allOf/2/if", keyword: "if", params: { failingKeyword: "then" }, message: 'must match "then" schema' };
                                                                                    if (vErrors === null) {
                                                                                      vErrors = [err5];
                                                                                    } else {
                                                                                      vErrors.push(err5);
                                                                                    }
                                                                                    errors++;
                                                                                    validate21.errors = vErrors;
                                                                                    return false;
                                                                                  }
                                                                                  var valid15 = _errs113 === errors;
                                                                                  if (valid15) {
                                                                                    if (props0 !== true && props2 !== void 0) {
                                                                                      if (props2 === true) {
                                                                                        props0 = true;
                                                                                      } else {
                                                                                        props0 = props0 || {};
                                                                                        Object.assign(props0, props2);
                                                                                      }
                                                                                    }
                                                                                  }
                                                                                }
                                                                              }
                                                                              if (errors === _errs99) {
                                                                                if (data50 && typeof data50 == "object" && !Array.isArray(data50)) {
                                                                                  let missing5;
                                                                                  if (data50.field === void 0 && (missing5 = "field") || data50.source === void 0 && (missing5 = "source") || data50.key === void 0 && (missing5 = "key") || data50.component === void 0 && (missing5 = "component")) {
                                                                                    validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8, schemaPath: "#/$defs/policy/properties/correlationSources/items/required", keyword: "required", params: { missingProperty: missing5 }, message: "must have required property '" + missing5 + "'" }];
                                                                                    return false;
                                                                                  } else {
                                                                                    if (props0 !== true) {
                                                                                      props0 = props0 || {};
                                                                                      props0.field = true;
                                                                                      props0.source = true;
                                                                                      props0.key = true;
                                                                                      props0.component = true;
                                                                                      props0.origin = true;
                                                                                      props0.pathPrefix = true;
                                                                                    }
                                                                                    if (data50.field !== void 0) {
                                                                                      let data57 = data50.field;
                                                                                      const _errs119 = errors;
                                                                                      if (!(data57 === "frontendBuildId" || data57 === "backendBuildId" || data57 === "serviceInstance" || data57 === "requestId" || data57 === "traceId" || data57 === "spanId")) {
                                                                                        validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/field", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/field/enum", keyword: "enum", params: { allowedValues: schema33.properties.correlationSources.items.properties.field.enum }, message: "must be equal to one of the allowed values" }];
                                                                                        return false;
                                                                                      }
                                                                                      var valid25 = _errs119 === errors;
                                                                                    } else {
                                                                                      var valid25 = true;
                                                                                    }
                                                                                    if (valid25) {
                                                                                      if (data50.source !== void 0) {
                                                                                        let data58 = data50.source;
                                                                                        const _errs120 = errors;
                                                                                        if (!(data58 === "response_header" || data58 === "response_json" || data58 === "page_meta")) {
                                                                                          validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/source", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/source/enum", keyword: "enum", params: { allowedValues: schema33.properties.correlationSources.items.properties.source.enum }, message: "must be equal to one of the allowed values" }];
                                                                                          return false;
                                                                                        }
                                                                                        var valid25 = _errs120 === errors;
                                                                                      } else {
                                                                                        var valid25 = true;
                                                                                      }
                                                                                      if (valid25) {
                                                                                        if (data50.key !== void 0) {
                                                                                          let data59 = data50.key;
                                                                                          const _errs121 = errors;
                                                                                          if (errors === _errs121) {
                                                                                            if (typeof data59 === "string") {
                                                                                              if (func1(data59) > 200) {
                                                                                                validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/key", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/key/maxLength", keyword: "maxLength", params: { limit: 200 }, message: "must NOT have more than 200 characters" }];
                                                                                                return false;
                                                                                              } else {
                                                                                                if (func1(data59) < 1) {
                                                                                                  validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/key", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/key/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                  return false;
                                                                                                }
                                                                                              }
                                                                                            } else {
                                                                                              validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/key", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/key/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                              return false;
                                                                                            }
                                                                                          }
                                                                                          var valid25 = _errs121 === errors;
                                                                                        } else {
                                                                                          var valid25 = true;
                                                                                        }
                                                                                        if (valid25) {
                                                                                          if (data50.component !== void 0) {
                                                                                            let data60 = data50.component;
                                                                                            const _errs123 = errors;
                                                                                            if (errors === _errs123) {
                                                                                              if (typeof data60 === "string") {
                                                                                                if (func1(data60) > 80) {
                                                                                                  validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/component", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/component/maxLength", keyword: "maxLength", params: { limit: 80 }, message: "must NOT have more than 80 characters" }];
                                                                                                  return false;
                                                                                                } else {
                                                                                                  if (func1(data60) < 1) {
                                                                                                    validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/component", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/component/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                    return false;
                                                                                                  }
                                                                                                }
                                                                                              } else {
                                                                                                validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/component", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/component/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                                return false;
                                                                                              }
                                                                                            }
                                                                                            var valid25 = _errs123 === errors;
                                                                                          } else {
                                                                                            var valid25 = true;
                                                                                          }
                                                                                          if (valid25) {
                                                                                            if (data50.origin !== void 0) {
                                                                                              let data61 = data50.origin;
                                                                                              const _errs125 = errors;
                                                                                              if (errors === _errs125) {
                                                                                                if (typeof data61 === "string") {
                                                                                                  if (func1(data61) < 1) {
                                                                                                    validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/origin", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/origin/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                    return false;
                                                                                                  } else {
                                                                                                    if (!pattern7.test(data61)) {
                                                                                                      validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/origin", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/origin/pattern", keyword: "pattern", params: { pattern: "^https?://[^/?#]+$" }, message: 'must match pattern "^https?://[^/?#]+$"' }];
                                                                                                      return false;
                                                                                                    }
                                                                                                  }
                                                                                                } else {
                                                                                                  validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/origin", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/origin/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                                  return false;
                                                                                                }
                                                                                              }
                                                                                              var valid25 = _errs125 === errors;
                                                                                            } else {
                                                                                              var valid25 = true;
                                                                                            }
                                                                                            if (valid25) {
                                                                                              if (data50.pathPrefix !== void 0) {
                                                                                                let data62 = data50.pathPrefix;
                                                                                                const _errs127 = errors;
                                                                                                if (errors === _errs127) {
                                                                                                  if (typeof data62 === "string") {
                                                                                                    if (func1(data62) > 499) {
                                                                                                      validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/pathPrefix", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/pathPrefix/maxLength", keyword: "maxLength", params: { limit: 499 }, message: "must NOT have more than 499 characters" }];
                                                                                                      return false;
                                                                                                    } else {
                                                                                                      if (func1(data62) < 1) {
                                                                                                        validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/pathPrefix", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/pathPrefix/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                        return false;
                                                                                                      } else {
                                                                                                        if (!pattern8.test(data62)) {
                                                                                                          validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/pathPrefix", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/pathPrefix/pattern", keyword: "pattern", params: { pattern: "^/" }, message: 'must match pattern "^/"' }];
                                                                                                          return false;
                                                                                                        }
                                                                                                      }
                                                                                                    }
                                                                                                  } else {
                                                                                                    validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/pathPrefix", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/pathPrefix/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                                    return false;
                                                                                                  }
                                                                                                }
                                                                                                var valid25 = _errs127 === errors;
                                                                                              } else {
                                                                                                var valid25 = true;
                                                                                              }
                                                                                            }
                                                                                          }
                                                                                        }
                                                                                      }
                                                                                    }
                                                                                  }
                                                                                } else {
                                                                                  validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8, schemaPath: "#/$defs/policy/properties/correlationSources/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                                  return false;
                                                                                }
                                                                              }
                                                                              var valid14 = _errs99 === errors;
                                                                              if (!valid14) {
                                                                                break;
                                                                              }
                                                                            }
                                                                          }
                                                                        } else {
                                                                          validate21.errors = [{ instancePath: instancePath + "/policy/correlationSources", schemaPath: "#/$defs/policy/properties/correlationSources/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                                          return false;
                                                                        }
                                                                      }
                                                                      var valid2 = _errs97 === errors;
                                                                    } else {
                                                                      var valid2 = true;
                                                                    }
                                                                    if (valid2) {
                                                                      if (data11.sourceMappings !== void 0) {
                                                                        let data63 = data11.sourceMappings;
                                                                        const _errs129 = errors;
                                                                        if (errors === _errs129) {
                                                                          if (Array.isArray(data63)) {
                                                                            if (data63.length > 100) {
                                                                              validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings", schemaPath: "#/$defs/policy/properties/sourceMappings/maxItems", keyword: "maxItems", params: { limit: 100 }, message: "must NOT have more than 100 items" }];
                                                                              return false;
                                                                            } else {
                                                                              var valid26 = true;
                                                                              const len9 = data63.length;
                                                                              for (let i9 = 0; i9 < len9; i9++) {
                                                                                let data64 = data63[i9];
                                                                                const _errs131 = errors;
                                                                                if (errors === _errs131) {
                                                                                  if (data64 && typeof data64 == "object" && !Array.isArray(data64)) {
                                                                                    let missing6;
                                                                                    if (data64.environmentId === void 0 && (missing6 = "environmentId") || data64.component === void 0 && (missing6 = "component") || data64.buildId === void 0 && (missing6 = "buildId") || data64.codeSnapshot === void 0 && (missing6 = "codeSnapshot")) {
                                                                                      validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9, schemaPath: "#/$defs/policy/properties/sourceMappings/items/required", keyword: "required", params: { missingProperty: missing6 }, message: "must have required property '" + missing6 + "'" }];
                                                                                      return false;
                                                                                    } else {
                                                                                      if (data64.environmentId !== void 0) {
                                                                                        let data65 = data64.environmentId;
                                                                                        const _errs133 = errors;
                                                                                        if (errors === _errs133) {
                                                                                          if (typeof data65 === "string") {
                                                                                            if (func1(data65) > 500) {
                                                                                              validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/environmentId", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/environmentId/maxLength", keyword: "maxLength", params: { limit: 500 }, message: "must NOT have more than 500 characters" }];
                                                                                              return false;
                                                                                            } else {
                                                                                              if (func1(data65) < 1) {
                                                                                                validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/environmentId", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/environmentId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                return false;
                                                                                              }
                                                                                            }
                                                                                          } else {
                                                                                            validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/environmentId", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/environmentId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                            return false;
                                                                                          }
                                                                                        }
                                                                                        var valid27 = _errs133 === errors;
                                                                                      } else {
                                                                                        var valid27 = true;
                                                                                      }
                                                                                      if (valid27) {
                                                                                        if (data64.component !== void 0) {
                                                                                          let data66 = data64.component;
                                                                                          const _errs135 = errors;
                                                                                          if (errors === _errs135) {
                                                                                            if (typeof data66 === "string") {
                                                                                              if (func1(data66) > 500) {
                                                                                                validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/component", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/component/maxLength", keyword: "maxLength", params: { limit: 500 }, message: "must NOT have more than 500 characters" }];
                                                                                                return false;
                                                                                              } else {
                                                                                                if (func1(data66) < 1) {
                                                                                                  validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/component", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/component/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                  return false;
                                                                                                }
                                                                                              }
                                                                                            } else {
                                                                                              validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/component", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/component/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                              return false;
                                                                                            }
                                                                                          }
                                                                                          var valid27 = _errs135 === errors;
                                                                                        } else {
                                                                                          var valid27 = true;
                                                                                        }
                                                                                        if (valid27) {
                                                                                          if (data64.buildId !== void 0) {
                                                                                            let data67 = data64.buildId;
                                                                                            const _errs137 = errors;
                                                                                            if (errors === _errs137) {
                                                                                              if (typeof data67 === "string") {
                                                                                                if (func1(data67) > 500) {
                                                                                                  validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/buildId", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/buildId/maxLength", keyword: "maxLength", params: { limit: 500 }, message: "must NOT have more than 500 characters" }];
                                                                                                  return false;
                                                                                                } else {
                                                                                                  if (func1(data67) < 1) {
                                                                                                    validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/buildId", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/buildId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                    return false;
                                                                                                  }
                                                                                                }
                                                                                              } else {
                                                                                                validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/buildId", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/buildId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                                return false;
                                                                                              }
                                                                                            }
                                                                                            var valid27 = _errs137 === errors;
                                                                                          } else {
                                                                                            var valid27 = true;
                                                                                          }
                                                                                          if (valid27) {
                                                                                            if (data64.codeSnapshot !== void 0) {
                                                                                              let data68 = data64.codeSnapshot;
                                                                                              const _errs139 = errors;
                                                                                              if (errors === _errs139) {
                                                                                                if (typeof data68 === "string") {
                                                                                                  if (func1(data68) > 500) {
                                                                                                    validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/codeSnapshot", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/codeSnapshot/maxLength", keyword: "maxLength", params: { limit: 500 }, message: "must NOT have more than 500 characters" }];
                                                                                                    return false;
                                                                                                  } else {
                                                                                                    if (func1(data68) < 1) {
                                                                                                      validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/codeSnapshot", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/codeSnapshot/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                      return false;
                                                                                                    }
                                                                                                  }
                                                                                                } else {
                                                                                                  validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/codeSnapshot", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/codeSnapshot/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                                  return false;
                                                                                                }
                                                                                              }
                                                                                              var valid27 = _errs139 === errors;
                                                                                            } else {
                                                                                              var valid27 = true;
                                                                                            }
                                                                                          }
                                                                                        }
                                                                                      }
                                                                                    }
                                                                                  } else {
                                                                                    validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9, schemaPath: "#/$defs/policy/properties/sourceMappings/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                                    return false;
                                                                                  }
                                                                                }
                                                                                var valid26 = _errs131 === errors;
                                                                                if (!valid26) {
                                                                                  break;
                                                                                }
                                                                              }
                                                                            }
                                                                          } else {
                                                                            validate21.errors = [{ instancePath: instancePath + "/policy/sourceMappings", schemaPath: "#/$defs/policy/properties/sourceMappings/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                                            return false;
                                                                          }
                                                                        }
                                                                        var valid2 = _errs129 === errors;
                                                                      } else {
                                                                        var valid2 = true;
                                                                      }
                                                                    }
                                                                  }
                                                                }
                                                              }
                                                            }
                                                          }
                                                        }
                                                      }
                                                    }
                                                  }
                                                }
                                              }
                                            }
                                          }
                                        }
                                      } else {
                                        validate21.errors = [{ instancePath: instancePath + "/policy", schemaPath: "#/$defs/policy/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                        return false;
                                      }
                                    }
                                    var valid0 = _errs21 === errors;
                                  } else {
                                    var valid0 = true;
                                  }
                                  if (valid0) {
                                    if (data.gaps !== void 0) {
                                      let data69 = data.gaps;
                                      const _errs141 = errors;
                                      if (errors === _errs141) {
                                        if (Array.isArray(data69)) {
                                          var valid28 = true;
                                          const len10 = data69.length;
                                          for (let i10 = 0; i10 < len10; i10++) {
                                            let data70 = data69[i10];
                                            const _errs143 = errors;
                                            const _errs144 = errors;
                                            if (errors === _errs144) {
                                              if (data70 && typeof data70 == "object" && !Array.isArray(data70)) {
                                                let missing7;
                                                if (data70.id === void 0 && (missing7 = "id") || data70.code === void 0 && (missing7 = "code") || data70.observedAt === void 0 && (missing7 = "observedAt") || data70.detail === void 0 && (missing7 = "detail")) {
                                                  validate21.errors = [{ instancePath: instancePath + "/gaps/" + i10, schemaPath: "#/$defs/gap/required", keyword: "required", params: { missingProperty: missing7 }, message: "must have required property '" + missing7 + "'" }];
                                                  return false;
                                                } else {
                                                  if (data70.id !== void 0) {
                                                    let data71 = data70.id;
                                                    const _errs146 = errors;
                                                    if (errors === _errs146) {
                                                      if (typeof data71 === "string") {
                                                        if (func1(data71) > 256) {
                                                          validate21.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/id", schemaPath: "#/$defs/gap/properties/id/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                                          return false;
                                                        } else {
                                                          if (func1(data71) < 1) {
                                                            validate21.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/id", schemaPath: "#/$defs/gap/properties/id/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                            return false;
                                                          }
                                                        }
                                                      } else {
                                                        validate21.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/id", schemaPath: "#/$defs/gap/properties/id/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                        return false;
                                                      }
                                                    }
                                                    var valid30 = _errs146 === errors;
                                                  } else {
                                                    var valid30 = true;
                                                  }
                                                  if (valid30) {
                                                    if (data70.code !== void 0) {
                                                      const _errs148 = errors;
                                                      if (typeof data70.code !== "string") {
                                                        validate21.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/code", schemaPath: "#/$defs/gap/properties/code/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                        return false;
                                                      }
                                                      var valid30 = _errs148 === errors;
                                                    } else {
                                                      var valid30 = true;
                                                    }
                                                    if (valid30) {
                                                      if (data70.observedAt !== void 0) {
                                                        const _errs150 = errors;
                                                        if (typeof data70.observedAt !== "string") {
                                                          validate21.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/observedAt", schemaPath: "#/$defs/gap/properties/observedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                          return false;
                                                        }
                                                        var valid30 = _errs150 === errors;
                                                      } else {
                                                        var valid30 = true;
                                                      }
                                                      if (valid30) {
                                                        if (data70.detail !== void 0) {
                                                          const _errs152 = errors;
                                                          if (typeof data70.detail !== "string") {
                                                            validate21.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/detail", schemaPath: "#/$defs/gap/properties/detail/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                            return false;
                                                          }
                                                          var valid30 = _errs152 === errors;
                                                        } else {
                                                          var valid30 = true;
                                                        }
                                                        if (valid30) {
                                                          if (data70.tabInstanceId !== void 0) {
                                                            const _errs154 = errors;
                                                            if (typeof data70.tabInstanceId !== "string") {
                                                              validate21.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/tabInstanceId", schemaPath: "#/$defs/gap/properties/tabInstanceId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                              return false;
                                                            }
                                                            var valid30 = _errs154 === errors;
                                                          } else {
                                                            var valid30 = true;
                                                          }
                                                          if (valid30) {
                                                            if (data70.channel !== void 0) {
                                                              let data76 = data70.channel;
                                                              const _errs156 = errors;
                                                              if (!(data76 === "page" || data76 === "semantic" || data76 === "network" || data76 === "runtime" || data76 === "screenshot")) {
                                                                validate21.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/channel", schemaPath: "#/$defs/gap/properties/channel/enum", keyword: "enum", params: { allowedValues: schema34.properties.channel.enum }, message: "must be equal to one of the allowed values" }];
                                                                return false;
                                                              }
                                                              var valid30 = _errs156 === errors;
                                                            } else {
                                                              var valid30 = true;
                                                            }
                                                          }
                                                        }
                                                      }
                                                    }
                                                  }
                                                }
                                              } else {
                                                validate21.errors = [{ instancePath: instancePath + "/gaps/" + i10, schemaPath: "#/$defs/gap/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                return false;
                                              }
                                            }
                                            var valid28 = _errs143 === errors;
                                            if (!valid28) {
                                              break;
                                            }
                                          }
                                        } else {
                                          validate21.errors = [{ instancePath: instancePath + "/gaps", schemaPath: "#/properties/gaps/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                          return false;
                                        }
                                      }
                                      var valid0 = _errs141 === errors;
                                    } else {
                                      var valid0 = true;
                                    }
                                    if (valid0) {
                                      if (data.rootTabInstanceIds !== void 0) {
                                        let data77 = data.rootTabInstanceIds;
                                        const _errs157 = errors;
                                        if (errors === _errs157) {
                                          if (Array.isArray(data77)) {
                                            var valid31 = true;
                                            const len11 = data77.length;
                                            for (let i11 = 0; i11 < len11; i11++) {
                                              let data78 = data77[i11];
                                              const _errs159 = errors;
                                              if (errors === _errs159) {
                                                if (typeof data78 === "string") {
                                                  if (func1(data78) > 256) {
                                                    validate21.errors = [{ instancePath: instancePath + "/rootTabInstanceIds/" + i11, schemaPath: "#/properties/rootTabInstanceIds/items/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                                    return false;
                                                  } else {
                                                    if (func1(data78) < 1) {
                                                      validate21.errors = [{ instancePath: instancePath + "/rootTabInstanceIds/" + i11, schemaPath: "#/properties/rootTabInstanceIds/items/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                      return false;
                                                    }
                                                  }
                                                } else {
                                                  validate21.errors = [{ instancePath: instancePath + "/rootTabInstanceIds/" + i11, schemaPath: "#/properties/rootTabInstanceIds/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                  return false;
                                                }
                                              }
                                              var valid31 = _errs159 === errors;
                                              if (!valid31) {
                                                break;
                                              }
                                            }
                                          } else {
                                            validate21.errors = [{ instancePath: instancePath + "/rootTabInstanceIds", schemaPath: "#/properties/rootTabInstanceIds/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                            return false;
                                          }
                                        }
                                        var valid0 = _errs157 === errors;
                                      } else {
                                        var valid0 = true;
                                      }
                                      if (valid0) {
                                        if (data.commands !== void 0) {
                                          let data79 = data.commands;
                                          const _errs161 = errors;
                                          if (errors === _errs161) {
                                            if (Array.isArray(data79)) {
                                              var valid32 = true;
                                              const len12 = data79.length;
                                              for (let i12 = 0; i12 < len12; i12++) {
                                                let data80 = data79[i12];
                                                const _errs163 = errors;
                                                if (errors === _errs163) {
                                                  if (typeof data80 === "string") {
                                                    if (func1(data80) > 256) {
                                                      validate21.errors = [{ instancePath: instancePath + "/commands/" + i12, schemaPath: "#/properties/commands/items/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                                      return false;
                                                    } else {
                                                      if (func1(data80) < 1) {
                                                        validate21.errors = [{ instancePath: instancePath + "/commands/" + i12, schemaPath: "#/properties/commands/items/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                        return false;
                                                      }
                                                    }
                                                  } else {
                                                    validate21.errors = [{ instancePath: instancePath + "/commands/" + i12, schemaPath: "#/properties/commands/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                    return false;
                                                  }
                                                }
                                                var valid32 = _errs163 === errors;
                                                if (!valid32) {
                                                  break;
                                                }
                                              }
                                            } else {
                                              validate21.errors = [{ instancePath: instancePath + "/commands", schemaPath: "#/properties/commands/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                              return false;
                                            }
                                          }
                                          var valid0 = _errs161 === errors;
                                        } else {
                                          var valid0 = true;
                                        }
                                        if (valid0) {
                                          if (data.bytesAccepted !== void 0) {
                                            let data81 = data.bytesAccepted;
                                            const _errs165 = errors;
                                            if (!(typeof data81 == "number" && (!(data81 % 1) && !isNaN(data81)))) {
                                              validate21.errors = [{ instancePath: instancePath + "/bytesAccepted", schemaPath: "#/properties/bytesAccepted/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                              return false;
                                            }
                                            if (errors === _errs165) {
                                              if (typeof data81 == "number") {
                                                if (data81 < 0 || isNaN(data81)) {
                                                  validate21.errors = [{ instancePath: instancePath + "/bytesAccepted", schemaPath: "#/properties/bytesAccepted/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                  return false;
                                                }
                                              }
                                            }
                                            var valid0 = _errs165 === errors;
                                          } else {
                                            var valid0 = true;
                                          }
                                          if (valid0) {
                                            if (data.bytesPersisted !== void 0) {
                                              let data82 = data.bytesPersisted;
                                              const _errs167 = errors;
                                              if (!(typeof data82 == "number" && (!(data82 % 1) && !isNaN(data82)))) {
                                                validate21.errors = [{ instancePath: instancePath + "/bytesPersisted", schemaPath: "#/properties/bytesPersisted/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                return false;
                                              }
                                              if (errors === _errs167) {
                                                if (typeof data82 == "number") {
                                                  if (data82 < 0 || isNaN(data82)) {
                                                    validate21.errors = [{ instancePath: instancePath + "/bytesPersisted", schemaPath: "#/properties/bytesPersisted/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                    return false;
                                                  }
                                                }
                                              }
                                              var valid0 = _errs167 === errors;
                                            } else {
                                              var valid0 = true;
                                            }
                                            if (valid0) {
                                              if (data.eventsPersisted !== void 0) {
                                                let data83 = data.eventsPersisted;
                                                const _errs169 = errors;
                                                if (!(typeof data83 == "number" && (!(data83 % 1) && !isNaN(data83)))) {
                                                  validate21.errors = [{ instancePath: instancePath + "/eventsPersisted", schemaPath: "#/properties/eventsPersisted/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                  return false;
                                                }
                                                if (errors === _errs169) {
                                                  if (typeof data83 == "number") {
                                                    if (data83 < 0 || isNaN(data83)) {
                                                      validate21.errors = [{ instancePath: instancePath + "/eventsPersisted", schemaPath: "#/properties/eventsPersisted/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                      return false;
                                                    }
                                                  }
                                                }
                                                var valid0 = _errs169 === errors;
                                              } else {
                                                var valid0 = true;
                                              }
                                              if (valid0) {
                                                if (data.checkpoint !== void 0) {
                                                  let data84 = data.checkpoint;
                                                  const _errs171 = errors;
                                                  if (!(typeof data84 == "number" && (!(data84 % 1) && !isNaN(data84)))) {
                                                    validate21.errors = [{ instancePath: instancePath + "/checkpoint", schemaPath: "#/properties/checkpoint/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                    return false;
                                                  }
                                                  if (errors === _errs171) {
                                                    if (typeof data84 == "number") {
                                                      if (data84 < 0 || isNaN(data84)) {
                                                        validate21.errors = [{ instancePath: instancePath + "/checkpoint", schemaPath: "#/properties/checkpoint/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                        return false;
                                                      }
                                                    }
                                                  }
                                                  var valid0 = _errs171 === errors;
                                                } else {
                                                  var valid0 = true;
                                                }
                                                if (valid0) {
                                                  if (data.saveState !== void 0) {
                                                    let data85 = data.saveState;
                                                    const _errs173 = errors;
                                                    if (!(data85 === "saved" || data85 === "pending" || data85 === "error")) {
                                                      validate21.errors = [{ instancePath: instancePath + "/saveState", schemaPath: "#/properties/saveState/enum", keyword: "enum", params: { allowedValues: schema32.properties.saveState.enum }, message: "must be equal to one of the allowed values" }];
                                                      return false;
                                                    }
                                                    var valid0 = _errs173 === errors;
                                                  } else {
                                                    var valid0 = true;
                                                  }
                                                  if (valid0) {
                                                    if (data.saveError !== void 0) {
                                                      const _errs174 = errors;
                                                      if (typeof data.saveError !== "string") {
                                                        validate21.errors = [{ instancePath: instancePath + "/saveError", schemaPath: "#/properties/saveError/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                        return false;
                                                      }
                                                      var valid0 = _errs174 === errors;
                                                    } else {
                                                      var valid0 = true;
                                                    }
                                                    if (valid0) {
                                                      if (data.versions !== void 0) {
                                                        let data87 = data.versions;
                                                        const _errs176 = errors;
                                                        if (errors === _errs176) {
                                                          if (data87 && typeof data87 == "object" && !Array.isArray(data87)) {
                                                            let missing8;
                                                            if (data87.frontendBuildId === void 0 && (missing8 = "frontendBuildId") || data87.backendBuildId === void 0 && (missing8 = "backendBuildId") || data87.serviceInstance === void 0 && (missing8 = "serviceInstance") || data87.codeSnapshotMatch === void 0 && (missing8 = "codeSnapshotMatch") || data87.sources === void 0 && (missing8 = "sources")) {
                                                              validate21.errors = [{ instancePath: instancePath + "/versions", schemaPath: "#/properties/versions/required", keyword: "required", params: { missingProperty: missing8 }, message: "must have required property '" + missing8 + "'" }];
                                                              return false;
                                                            } else {
                                                              if (data87.frontendBuildId !== void 0) {
                                                                const _errs178 = errors;
                                                                if (typeof data87.frontendBuildId !== "string") {
                                                                  validate21.errors = [{ instancePath: instancePath + "/versions/frontendBuildId", schemaPath: "#/properties/versions/properties/frontendBuildId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                  return false;
                                                                }
                                                                var valid33 = _errs178 === errors;
                                                              } else {
                                                                var valid33 = true;
                                                              }
                                                              if (valid33) {
                                                                if (data87.backendBuildId !== void 0) {
                                                                  const _errs180 = errors;
                                                                  if (typeof data87.backendBuildId !== "string") {
                                                                    validate21.errors = [{ instancePath: instancePath + "/versions/backendBuildId", schemaPath: "#/properties/versions/properties/backendBuildId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                    return false;
                                                                  }
                                                                  var valid33 = _errs180 === errors;
                                                                } else {
                                                                  var valid33 = true;
                                                                }
                                                                if (valid33) {
                                                                  if (data87.serviceInstance !== void 0) {
                                                                    const _errs182 = errors;
                                                                    if (typeof data87.serviceInstance !== "string") {
                                                                      validate21.errors = [{ instancePath: instancePath + "/versions/serviceInstance", schemaPath: "#/properties/versions/properties/serviceInstance/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                      return false;
                                                                    }
                                                                    var valid33 = _errs182 === errors;
                                                                  } else {
                                                                    var valid33 = true;
                                                                  }
                                                                  if (valid33) {
                                                                    if (data87.codeSnapshotMatch !== void 0) {
                                                                      const _errs184 = errors;
                                                                      if (typeof data87.codeSnapshotMatch !== "string") {
                                                                        validate21.errors = [{ instancePath: instancePath + "/versions/codeSnapshotMatch", schemaPath: "#/properties/versions/properties/codeSnapshotMatch/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                        return false;
                                                                      }
                                                                      var valid33 = _errs184 === errors;
                                                                    } else {
                                                                      var valid33 = true;
                                                                    }
                                                                    if (valid33) {
                                                                      if (data87.sources !== void 0) {
                                                                        let data92 = data87.sources;
                                                                        const _errs186 = errors;
                                                                        if (errors === _errs186) {
                                                                          if (data92 && typeof data92 == "object" && !Array.isArray(data92)) {
                                                                            for (const key0 in data92) {
                                                                              const _errs189 = errors;
                                                                              if (typeof data92[key0] !== "string") {
                                                                                validate21.errors = [{ instancePath: instancePath + "/versions/sources/" + key0.replace(/~/g, "~0").replace(/\//g, "~1"), schemaPath: "#/properties/versions/properties/sources/additionalProperties/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                return false;
                                                                              }
                                                                              var valid34 = _errs189 === errors;
                                                                              if (!valid34) {
                                                                                break;
                                                                              }
                                                                            }
                                                                          } else {
                                                                            validate21.errors = [{ instancePath: instancePath + "/versions/sources", schemaPath: "#/properties/versions/properties/sources/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                            return false;
                                                                          }
                                                                        }
                                                                        var valid33 = _errs186 === errors;
                                                                      } else {
                                                                        var valid33 = true;
                                                                      }
                                                                    }
                                                                  }
                                                                }
                                                              }
                                                            }
                                                          } else {
                                                            validate21.errors = [{ instancePath: instancePath + "/versions", schemaPath: "#/properties/versions/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                            return false;
                                                          }
                                                        }
                                                        var valid0 = _errs176 === errors;
                                                      } else {
                                                        var valid0 = true;
                                                      }
                                                      if (valid0) {
                                                        if (data.capabilities !== void 0) {
                                                          let data94 = data.capabilities;
                                                          const _errs191 = errors;
                                                          if (!(data94 && typeof data94 == "object" && !Array.isArray(data94))) {
                                                            validate21.errors = [{ instancePath: instancePath + "/capabilities", schemaPath: "#/properties/capabilities/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                            return false;
                                                          }
                                                          var valid0 = _errs191 === errors;
                                                        } else {
                                                          var valid0 = true;
                                                        }
                                                        if (valid0) {
                                                          if (data.stopReason !== void 0) {
                                                            const _errs193 = errors;
                                                            if (typeof data.stopReason !== "string") {
                                                              validate21.errors = [{ instancePath: instancePath + "/stopReason", schemaPath: "#/properties/stopReason/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                              return false;
                                                            }
                                                            var valid0 = _errs193 === errors;
                                                          } else {
                                                            var valid0 = true;
                                                          }
                                                          if (valid0) {
                                                            if (data.stopProgress !== void 0) {
                                                              let data96 = data.stopProgress;
                                                              const _errs195 = errors;
                                                              if (errors === _errs195) {
                                                                if (data96 && typeof data96 == "object" && !Array.isArray(data96)) {
                                                                  let missing9;
                                                                  if (data96.startedAt === void 0 && (missing9 = "startedAt") || data96.cutoff === void 0 && (missing9 = "cutoff") || data96.marker === void 0 && (missing9 = "marker") || data96.cleanup === void 0 && (missing9 = "cleanup") || data96.drain === void 0 && (missing9 = "drain") || data96.terminal === void 0 && (missing9 = "terminal") || data96.deadlineExceeded === void 0 && (missing9 = "deadlineExceeded")) {
                                                                    validate21.errors = [{ instancePath: instancePath + "/stopProgress", schemaPath: "#/properties/stopProgress/required", keyword: "required", params: { missingProperty: missing9 }, message: "must have required property '" + missing9 + "'" }];
                                                                    return false;
                                                                  } else {
                                                                    if (data96.startedAt !== void 0) {
                                                                      const _errs197 = errors;
                                                                      if (typeof data96.startedAt !== "string") {
                                                                        validate21.errors = [{ instancePath: instancePath + "/stopProgress/startedAt", schemaPath: "#/properties/stopProgress/properties/startedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                        return false;
                                                                      }
                                                                      var valid35 = _errs197 === errors;
                                                                    } else {
                                                                      var valid35 = true;
                                                                    }
                                                                    if (valid35) {
                                                                      if (data96.cutoff !== void 0) {
                                                                        const _errs199 = errors;
                                                                        if ("complete" !== data96.cutoff) {
                                                                          validate21.errors = [{ instancePath: instancePath + "/stopProgress/cutoff", schemaPath: "#/properties/stopProgress/properties/cutoff/const", keyword: "const", params: { allowedValue: "complete" }, message: "must be equal to constant" }];
                                                                          return false;
                                                                        }
                                                                        var valid35 = _errs199 === errors;
                                                                      } else {
                                                                        var valid35 = true;
                                                                      }
                                                                      if (valid35) {
                                                                        if (data96.marker !== void 0) {
                                                                          let data99 = data96.marker;
                                                                          const _errs200 = errors;
                                                                          if (!(data99 === "pending" || data99 === "complete" || data99 === "error")) {
                                                                            validate21.errors = [{ instancePath: instancePath + "/stopProgress/marker", schemaPath: "#/properties/stopProgress/properties/marker/enum", keyword: "enum", params: { allowedValues: schema32.properties.stopProgress.properties.marker.enum }, message: "must be equal to one of the allowed values" }];
                                                                            return false;
                                                                          }
                                                                          var valid35 = _errs200 === errors;
                                                                        } else {
                                                                          var valid35 = true;
                                                                        }
                                                                        if (valid35) {
                                                                          if (data96.cleanup !== void 0) {
                                                                            let data100 = data96.cleanup;
                                                                            const _errs201 = errors;
                                                                            if (!(data100 === "pending" || data100 === "complete" || data100 === "error")) {
                                                                              validate21.errors = [{ instancePath: instancePath + "/stopProgress/cleanup", schemaPath: "#/properties/stopProgress/properties/cleanup/enum", keyword: "enum", params: { allowedValues: schema32.properties.stopProgress.properties.cleanup.enum }, message: "must be equal to one of the allowed values" }];
                                                                              return false;
                                                                            }
                                                                            var valid35 = _errs201 === errors;
                                                                          } else {
                                                                            var valid35 = true;
                                                                          }
                                                                          if (valid35) {
                                                                            if (data96.drain !== void 0) {
                                                                              let data101 = data96.drain;
                                                                              const _errs202 = errors;
                                                                              if (!(data101 === "pending" || data101 === "complete" || data101 === "error")) {
                                                                                validate21.errors = [{ instancePath: instancePath + "/stopProgress/drain", schemaPath: "#/properties/stopProgress/properties/drain/enum", keyword: "enum", params: { allowedValues: schema32.properties.stopProgress.properties.drain.enum }, message: "must be equal to one of the allowed values" }];
                                                                                return false;
                                                                              }
                                                                              var valid35 = _errs202 === errors;
                                                                            } else {
                                                                              var valid35 = true;
                                                                            }
                                                                            if (valid35) {
                                                                              if (data96.terminal !== void 0) {
                                                                                let data102 = data96.terminal;
                                                                                const _errs203 = errors;
                                                                                if (!(data102 === "pending" || data102 === "complete" || data102 === "error")) {
                                                                                  validate21.errors = [{ instancePath: instancePath + "/stopProgress/terminal", schemaPath: "#/properties/stopProgress/properties/terminal/enum", keyword: "enum", params: { allowedValues: schema32.properties.stopProgress.properties.terminal.enum }, message: "must be equal to one of the allowed values" }];
                                                                                  return false;
                                                                                }
                                                                                var valid35 = _errs203 === errors;
                                                                              } else {
                                                                                var valid35 = true;
                                                                              }
                                                                              if (valid35) {
                                                                                if (data96.deadlineExceeded !== void 0) {
                                                                                  const _errs204 = errors;
                                                                                  if (typeof data96.deadlineExceeded !== "boolean") {
                                                                                    validate21.errors = [{ instancePath: instancePath + "/stopProgress/deadlineExceeded", schemaPath: "#/properties/stopProgress/properties/deadlineExceeded/type", keyword: "type", params: { type: "boolean" }, message: "must be boolean" }];
                                                                                    return false;
                                                                                  }
                                                                                  var valid35 = _errs204 === errors;
                                                                                } else {
                                                                                  var valid35 = true;
                                                                                }
                                                                              }
                                                                            }
                                                                          }
                                                                        }
                                                                      }
                                                                    }
                                                                  }
                                                                } else {
                                                                  validate21.errors = [{ instancePath: instancePath + "/stopProgress", schemaPath: "#/properties/stopProgress/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                  return false;
                                                                }
                                                              }
                                                              var valid0 = _errs195 === errors;
                                                            } else {
                                                              var valid0 = true;
                                                            }
                                                            if (valid0) {
                                                              if (data.rootEnvironments !== void 0) {
                                                                let data104 = data.rootEnvironments;
                                                                const _errs206 = errors;
                                                                if (errors === _errs206) {
                                                                  if (data104 && typeof data104 == "object" && !Array.isArray(data104)) {
                                                                    for (const key1 in data104) {
                                                                      const _errs209 = errors;
                                                                      if (typeof data104[key1] !== "string") {
                                                                        validate21.errors = [{ instancePath: instancePath + "/rootEnvironments/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"), schemaPath: "#/properties/rootEnvironments/additionalProperties/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                        return false;
                                                                      }
                                                                      var valid36 = _errs209 === errors;
                                                                      if (!valid36) {
                                                                        break;
                                                                      }
                                                                    }
                                                                  } else {
                                                                    validate21.errors = [{ instancePath: instancePath + "/rootEnvironments", schemaPath: "#/properties/rootEnvironments/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                    return false;
                                                                  }
                                                                }
                                                                var valid0 = _errs206 === errors;
                                                              } else {
                                                                var valid0 = true;
                                                              }
                                                            }
                                                          }
                                                        }
                                                      }
                                                    }
                                                  }
                                                }
                                              }
                                            }
                                          }
                                        }
                                      }
                                    }
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        } else {
          validate21.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate21.errors = vErrors;
      return errors === 0;
    }
    validate21.evaluated = { "props": { "schemaVersion": true, "recordingId": true, "browserRunId": true, "state": true, "scopeVersion": true, "environmentId": true, "browserVersion": true, "extensionVersion": true, "rrwebVersion": true, "startedAt": true, "stoppedAt": true, "policy": true, "gaps": true, "rootTabInstanceIds": true, "commands": true, "bytesAccepted": true, "bytesPersisted": true, "eventsPersisted": true, "checkpoint": true, "saveState": true, "saveError": true, "versions": true, "capabilities": true, "stopReason": true, "stopProgress": true, "rootEnvironments": true }, "dynamicProps": false, "dynamicItems": false };
    var pattern9 = new RegExp("^[a-zA-Z0-9_./-]+$", "u");
    var pattern10 = new RegExp("^[0-9a-f]{64}$", "u");
    function validate20(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      ;
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate20.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.schemaVersion === void 0 && (missing0 = "schemaVersion") || data.recording === void 0 && (missing0 = "recording") || data.capabilities === void 0 && (missing0 = "capabilities") || data.gaps === void 0 && (missing0 = "gaps") || data.files === void 0 && (missing0 = "files") || data.integrity === void 0 && (missing0 = "integrity")) {
            validate20.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.schemaVersion !== void 0) {
              let data0 = data.schemaVersion;
              const _errs1 = errors;
              if (!(data0 === "3.0.0" || data0 === "4.0.0")) {
                validate20.errors = [{ instancePath: instancePath + "/schemaVersion", schemaPath: "#/properties/schemaVersion/enum", keyword: "enum", params: { allowedValues: schema31.properties.schemaVersion.enum }, message: "must be equal to one of the allowed values" }];
                return false;
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.recording !== void 0) {
                const _errs2 = errors;
                if (!validate21(data.recording, { instancePath: instancePath + "/recording", parentData: data, parentDataProperty: "recording", rootData, dynamicAnchors })) {
                  vErrors = vErrors === null ? validate21.errors : vErrors.concat(validate21.errors);
                  errors = vErrors.length;
                }
                var valid0 = _errs2 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.capabilities !== void 0) {
                  let data2 = data.capabilities;
                  const _errs3 = errors;
                  if (!(data2 && typeof data2 == "object" && !Array.isArray(data2))) {
                    validate20.errors = [{ instancePath: instancePath + "/capabilities", schemaPath: "#/properties/capabilities/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                    return false;
                  }
                  var valid0 = _errs3 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.gaps !== void 0) {
                    let data3 = data.gaps;
                    const _errs5 = errors;
                    if (errors === _errs5) {
                      if (Array.isArray(data3)) {
                        var valid1 = true;
                        const len0 = data3.length;
                        for (let i0 = 0; i0 < len0; i0++) {
                          let data4 = data3[i0];
                          const _errs7 = errors;
                          const _errs8 = errors;
                          if (errors === _errs8) {
                            if (data4 && typeof data4 == "object" && !Array.isArray(data4)) {
                              let missing1;
                              if (data4.id === void 0 && (missing1 = "id") || data4.code === void 0 && (missing1 = "code") || data4.observedAt === void 0 && (missing1 = "observedAt") || data4.detail === void 0 && (missing1 = "detail")) {
                                validate20.errors = [{ instancePath: instancePath + "/gaps/" + i0, schemaPath: "#/$defs/gap/required", keyword: "required", params: { missingProperty: missing1 }, message: "must have required property '" + missing1 + "'" }];
                                return false;
                              } else {
                                if (data4.id !== void 0) {
                                  let data5 = data4.id;
                                  const _errs10 = errors;
                                  if (errors === _errs10) {
                                    if (typeof data5 === "string") {
                                      if (func1(data5) > 256) {
                                        validate20.errors = [{ instancePath: instancePath + "/gaps/" + i0 + "/id", schemaPath: "#/$defs/gap/properties/id/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                        return false;
                                      } else {
                                        if (func1(data5) < 1) {
                                          validate20.errors = [{ instancePath: instancePath + "/gaps/" + i0 + "/id", schemaPath: "#/$defs/gap/properties/id/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                          return false;
                                        }
                                      }
                                    } else {
                                      validate20.errors = [{ instancePath: instancePath + "/gaps/" + i0 + "/id", schemaPath: "#/$defs/gap/properties/id/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                      return false;
                                    }
                                  }
                                  var valid3 = _errs10 === errors;
                                } else {
                                  var valid3 = true;
                                }
                                if (valid3) {
                                  if (data4.code !== void 0) {
                                    const _errs12 = errors;
                                    if (typeof data4.code !== "string") {
                                      validate20.errors = [{ instancePath: instancePath + "/gaps/" + i0 + "/code", schemaPath: "#/$defs/gap/properties/code/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                      return false;
                                    }
                                    var valid3 = _errs12 === errors;
                                  } else {
                                    var valid3 = true;
                                  }
                                  if (valid3) {
                                    if (data4.observedAt !== void 0) {
                                      const _errs14 = errors;
                                      if (typeof data4.observedAt !== "string") {
                                        validate20.errors = [{ instancePath: instancePath + "/gaps/" + i0 + "/observedAt", schemaPath: "#/$defs/gap/properties/observedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                        return false;
                                      }
                                      var valid3 = _errs14 === errors;
                                    } else {
                                      var valid3 = true;
                                    }
                                    if (valid3) {
                                      if (data4.detail !== void 0) {
                                        const _errs16 = errors;
                                        if (typeof data4.detail !== "string") {
                                          validate20.errors = [{ instancePath: instancePath + "/gaps/" + i0 + "/detail", schemaPath: "#/$defs/gap/properties/detail/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                          return false;
                                        }
                                        var valid3 = _errs16 === errors;
                                      } else {
                                        var valid3 = true;
                                      }
                                      if (valid3) {
                                        if (data4.tabInstanceId !== void 0) {
                                          const _errs18 = errors;
                                          if (typeof data4.tabInstanceId !== "string") {
                                            validate20.errors = [{ instancePath: instancePath + "/gaps/" + i0 + "/tabInstanceId", schemaPath: "#/$defs/gap/properties/tabInstanceId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                            return false;
                                          }
                                          var valid3 = _errs18 === errors;
                                        } else {
                                          var valid3 = true;
                                        }
                                        if (valid3) {
                                          if (data4.channel !== void 0) {
                                            let data10 = data4.channel;
                                            const _errs20 = errors;
                                            if (!(data10 === "page" || data10 === "semantic" || data10 === "network" || data10 === "runtime" || data10 === "screenshot")) {
                                              validate20.errors = [{ instancePath: instancePath + "/gaps/" + i0 + "/channel", schemaPath: "#/$defs/gap/properties/channel/enum", keyword: "enum", params: { allowedValues: schema34.properties.channel.enum }, message: "must be equal to one of the allowed values" }];
                                              return false;
                                            }
                                            var valid3 = _errs20 === errors;
                                          } else {
                                            var valid3 = true;
                                          }
                                        }
                                      }
                                    }
                                  }
                                }
                              }
                            } else {
                              validate20.errors = [{ instancePath: instancePath + "/gaps/" + i0, schemaPath: "#/$defs/gap/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                              return false;
                            }
                          }
                          var valid1 = _errs7 === errors;
                          if (!valid1) {
                            break;
                          }
                        }
                      } else {
                        validate20.errors = [{ instancePath: instancePath + "/gaps", schemaPath: "#/properties/gaps/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                        return false;
                      }
                    }
                    var valid0 = _errs5 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.files !== void 0) {
                      let data11 = data.files;
                      const _errs21 = errors;
                      if (errors === _errs21) {
                        if (Array.isArray(data11)) {
                          var valid4 = true;
                          const len1 = data11.length;
                          for (let i1 = 0; i1 < len1; i1++) {
                            let data12 = data11[i1];
                            const _errs23 = errors;
                            const _errs24 = errors;
                            if (errors === _errs24) {
                              if (data12 && typeof data12 == "object" && !Array.isArray(data12)) {
                                let missing2;
                                if (data12.path === void 0 && (missing2 = "path") || data12.mime === void 0 && (missing2 = "mime") || data12.bytes === void 0 && (missing2 = "bytes") || data12.sha256 === void 0 && (missing2 = "sha256") || data12.streamId === void 0 && (missing2 = "streamId") || data12.firstSeq === void 0 && (missing2 = "firstSeq") || data12.lastSeq === void 0 && (missing2 = "lastSeq") || data12.events === void 0 && (missing2 = "events")) {
                                  validate20.errors = [{ instancePath: instancePath + "/files/" + i1, schemaPath: "#/$defs/file/required", keyword: "required", params: { missingProperty: missing2 }, message: "must have required property '" + missing2 + "'" }];
                                  return false;
                                } else {
                                  if (data12.path !== void 0) {
                                    let data13 = data12.path;
                                    const _errs26 = errors;
                                    if (errors === _errs26) {
                                      if (typeof data13 === "string") {
                                        if (!pattern9.test(data13)) {
                                          validate20.errors = [{ instancePath: instancePath + "/files/" + i1 + "/path", schemaPath: "#/$defs/file/properties/path/pattern", keyword: "pattern", params: { pattern: "^[a-zA-Z0-9_./-]+$" }, message: 'must match pattern "^[a-zA-Z0-9_./-]+$"' }];
                                          return false;
                                        }
                                      } else {
                                        validate20.errors = [{ instancePath: instancePath + "/files/" + i1 + "/path", schemaPath: "#/$defs/file/properties/path/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                        return false;
                                      }
                                    }
                                    var valid6 = _errs26 === errors;
                                  } else {
                                    var valid6 = true;
                                  }
                                  if (valid6) {
                                    if (data12.mime !== void 0) {
                                      const _errs28 = errors;
                                      if (typeof data12.mime !== "string") {
                                        validate20.errors = [{ instancePath: instancePath + "/files/" + i1 + "/mime", schemaPath: "#/$defs/file/properties/mime/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                        return false;
                                      }
                                      var valid6 = _errs28 === errors;
                                    } else {
                                      var valid6 = true;
                                    }
                                    if (valid6) {
                                      if (data12.bytes !== void 0) {
                                        let data15 = data12.bytes;
                                        const _errs30 = errors;
                                        if (!(typeof data15 == "number" && (!(data15 % 1) && !isNaN(data15)))) {
                                          validate20.errors = [{ instancePath: instancePath + "/files/" + i1 + "/bytes", schemaPath: "#/$defs/file/properties/bytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                          return false;
                                        }
                                        if (errors === _errs30) {
                                          if (typeof data15 == "number") {
                                            if (data15 < 0 || isNaN(data15)) {
                                              validate20.errors = [{ instancePath: instancePath + "/files/" + i1 + "/bytes", schemaPath: "#/$defs/file/properties/bytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                              return false;
                                            }
                                          }
                                        }
                                        var valid6 = _errs30 === errors;
                                      } else {
                                        var valid6 = true;
                                      }
                                      if (valid6) {
                                        if (data12.sha256 !== void 0) {
                                          let data16 = data12.sha256;
                                          const _errs32 = errors;
                                          if (errors === _errs32) {
                                            if (typeof data16 === "string") {
                                              if (!pattern10.test(data16)) {
                                                validate20.errors = [{ instancePath: instancePath + "/files/" + i1 + "/sha256", schemaPath: "#/$defs/file/properties/sha256/pattern", keyword: "pattern", params: { pattern: "^[0-9a-f]{64}$" }, message: 'must match pattern "^[0-9a-f]{64}$"' }];
                                                return false;
                                              }
                                            } else {
                                              validate20.errors = [{ instancePath: instancePath + "/files/" + i1 + "/sha256", schemaPath: "#/$defs/file/properties/sha256/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                              return false;
                                            }
                                          }
                                          var valid6 = _errs32 === errors;
                                        } else {
                                          var valid6 = true;
                                        }
                                        if (valid6) {
                                          if (data12.streamId !== void 0) {
                                            let data17 = data12.streamId;
                                            const _errs34 = errors;
                                            if (typeof data17 !== "string" && data17 !== null) {
                                              validate20.errors = [{ instancePath: instancePath + "/files/" + i1 + "/streamId", schemaPath: "#/$defs/file/properties/streamId/type", keyword: "type", params: { type: schema36.properties.streamId.type }, message: "must be string,null" }];
                                              return false;
                                            }
                                            var valid6 = _errs34 === errors;
                                          } else {
                                            var valid6 = true;
                                          }
                                          if (valid6) {
                                            if (data12.firstSeq !== void 0) {
                                              let data18 = data12.firstSeq;
                                              const _errs36 = errors;
                                              if (!(typeof data18 == "number" && (!(data18 % 1) && !isNaN(data18))) && data18 !== null) {
                                                validate20.errors = [{ instancePath: instancePath + "/files/" + i1 + "/firstSeq", schemaPath: "#/$defs/file/properties/firstSeq/type", keyword: "type", params: { type: schema36.properties.firstSeq.type }, message: "must be integer,null" }];
                                                return false;
                                              }
                                              var valid6 = _errs36 === errors;
                                            } else {
                                              var valid6 = true;
                                            }
                                            if (valid6) {
                                              if (data12.lastSeq !== void 0) {
                                                let data19 = data12.lastSeq;
                                                const _errs38 = errors;
                                                if (!(typeof data19 == "number" && (!(data19 % 1) && !isNaN(data19))) && data19 !== null) {
                                                  validate20.errors = [{ instancePath: instancePath + "/files/" + i1 + "/lastSeq", schemaPath: "#/$defs/file/properties/lastSeq/type", keyword: "type", params: { type: schema36.properties.lastSeq.type }, message: "must be integer,null" }];
                                                  return false;
                                                }
                                                var valid6 = _errs38 === errors;
                                              } else {
                                                var valid6 = true;
                                              }
                                              if (valid6) {
                                                if (data12.events !== void 0) {
                                                  let data20 = data12.events;
                                                  const _errs40 = errors;
                                                  if (!(typeof data20 == "number" && (!(data20 % 1) && !isNaN(data20)))) {
                                                    validate20.errors = [{ instancePath: instancePath + "/files/" + i1 + "/events", schemaPath: "#/$defs/file/properties/events/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                    return false;
                                                  }
                                                  if (errors === _errs40) {
                                                    if (typeof data20 == "number") {
                                                      if (data20 < 0 || isNaN(data20)) {
                                                        validate20.errors = [{ instancePath: instancePath + "/files/" + i1 + "/events", schemaPath: "#/$defs/file/properties/events/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                        return false;
                                                      }
                                                    }
                                                  }
                                                  var valid6 = _errs40 === errors;
                                                } else {
                                                  var valid6 = true;
                                                }
                                              }
                                            }
                                          }
                                        }
                                      }
                                    }
                                  }
                                }
                              } else {
                                validate20.errors = [{ instancePath: instancePath + "/files/" + i1, schemaPath: "#/$defs/file/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                return false;
                              }
                            }
                            var valid4 = _errs23 === errors;
                            if (!valid4) {
                              break;
                            }
                          }
                        } else {
                          validate20.errors = [{ instancePath: instancePath + "/files", schemaPath: "#/properties/files/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                          return false;
                        }
                      }
                      var valid0 = _errs21 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.integrity !== void 0) {
                        let data21 = data.integrity;
                        const _errs42 = errors;
                        if (errors === _errs42) {
                          if (data21 && typeof data21 == "object" && !Array.isArray(data21)) {
                            let missing3;
                            if (data21.status === void 0 && (missing3 = "status") || data21.meaning === void 0 && (missing3 = "meaning")) {
                              validate20.errors = [{ instancePath: instancePath + "/integrity", schemaPath: "#/properties/integrity/required", keyword: "required", params: { missingProperty: missing3 }, message: "must have required property '" + missing3 + "'" }];
                              return false;
                            } else {
                              if (data21.status !== void 0) {
                                const _errs44 = errors;
                                if (typeof data21.status !== "string") {
                                  validate20.errors = [{ instancePath: instancePath + "/integrity/status", schemaPath: "#/properties/integrity/properties/status/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                  return false;
                                }
                                var valid7 = _errs44 === errors;
                              } else {
                                var valid7 = true;
                              }
                              if (valid7) {
                                if (data21.meaning !== void 0) {
                                  const _errs46 = errors;
                                  if (typeof data21.meaning !== "string") {
                                    validate20.errors = [{ instancePath: instancePath + "/integrity/meaning", schemaPath: "#/properties/integrity/properties/meaning/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                    return false;
                                  }
                                  var valid7 = _errs46 === errors;
                                } else {
                                  var valid7 = true;
                                }
                              }
                            }
                          } else {
                            validate20.errors = [{ instancePath: instancePath + "/integrity", schemaPath: "#/properties/integrity/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                            return false;
                          }
                        }
                        var valid0 = _errs42 === errors;
                      } else {
                        var valid0 = true;
                      }
                    }
                  }
                }
              }
            }
          }
        } else {
          validate20.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate20.errors = vErrors;
      return errors === 0;
    }
    validate20.evaluated = { "props": { "schemaVersion": true, "recording": true, "capabilities": true, "gaps": true, "files": true, "integrity": true }, "dynamicProps": false, "dynamicItems": false };
    exports.context = validate23;
    var schema37 = { "type": "object", "required": ["chromeFrameId", "documentId"], "properties": { "chromeFrameId": { "type": ["integer", "null"] }, "documentId": { "type": ["string", "null"] }, "verifiedBy": { "type": "string" }, "status": { "type": "string" }, "reason": { "type": "string" } } };
    function validate23(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate23.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.chromeFrameId === void 0 && (missing0 = "chromeFrameId") || data.documentId === void 0 && (missing0 = "documentId")) {
            validate23.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.chromeFrameId !== void 0) {
              let data0 = data.chromeFrameId;
              const _errs1 = errors;
              if (!(typeof data0 == "number" && (!(data0 % 1) && !isNaN(data0))) && data0 !== null) {
                validate23.errors = [{ instancePath: instancePath + "/chromeFrameId", schemaPath: "#/properties/chromeFrameId/type", keyword: "type", params: { type: schema37.properties.chromeFrameId.type }, message: "must be integer,null" }];
                return false;
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.documentId !== void 0) {
                let data1 = data.documentId;
                const _errs3 = errors;
                if (typeof data1 !== "string" && data1 !== null) {
                  validate23.errors = [{ instancePath: instancePath + "/documentId", schemaPath: "#/properties/documentId/type", keyword: "type", params: { type: schema37.properties.documentId.type }, message: "must be string,null" }];
                  return false;
                }
                var valid0 = _errs3 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.verifiedBy !== void 0) {
                  const _errs5 = errors;
                  if (typeof data.verifiedBy !== "string") {
                    validate23.errors = [{ instancePath: instancePath + "/verifiedBy", schemaPath: "#/properties/verifiedBy/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                    return false;
                  }
                  var valid0 = _errs5 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.status !== void 0) {
                    const _errs7 = errors;
                    if (typeof data.status !== "string") {
                      validate23.errors = [{ instancePath: instancePath + "/status", schemaPath: "#/properties/status/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                      return false;
                    }
                    var valid0 = _errs7 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.reason !== void 0) {
                      const _errs9 = errors;
                      if (typeof data.reason !== "string") {
                        validate23.errors = [{ instancePath: instancePath + "/reason", schemaPath: "#/properties/reason/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                        return false;
                      }
                      var valid0 = _errs9 === errors;
                    } else {
                      var valid0 = true;
                    }
                  }
                }
              }
            }
          }
        } else {
          validate23.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate23.errors = vErrors;
      return errors === 0;
    }
    validate23.evaluated = { "props": { "chromeFrameId": true, "documentId": true, "verifiedBy": true, "status": true, "reason": true }, "dynamicProps": false, "dynamicItems": false };
    exports.contextOrNull = validate24;
    function validate24(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate24.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      const _errs0 = errors;
      let valid0 = false;
      const _errs1 = errors;
      const _errs2 = errors;
      if (errors === _errs2) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.chromeFrameId === void 0 && (missing0 = "chromeFrameId") || data.documentId === void 0 && (missing0 = "documentId")) {
            const err0 = { instancePath, schemaPath: "#/$defs/context/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" };
            if (vErrors === null) {
              vErrors = [err0];
            } else {
              vErrors.push(err0);
            }
            errors++;
          } else {
            if (data.chromeFrameId !== void 0) {
              let data0 = data.chromeFrameId;
              const _errs4 = errors;
              if (!(typeof data0 == "number" && (!(data0 % 1) && !isNaN(data0))) && data0 !== null) {
                const err1 = { instancePath: instancePath + "/chromeFrameId", schemaPath: "#/$defs/context/properties/chromeFrameId/type", keyword: "type", params: { type: schema37.properties.chromeFrameId.type }, message: "must be integer,null" };
                if (vErrors === null) {
                  vErrors = [err1];
                } else {
                  vErrors.push(err1);
                }
                errors++;
              }
              var valid2 = _errs4 === errors;
            } else {
              var valid2 = true;
            }
            if (valid2) {
              if (data.documentId !== void 0) {
                let data1 = data.documentId;
                const _errs6 = errors;
                if (typeof data1 !== "string" && data1 !== null) {
                  const err2 = { instancePath: instancePath + "/documentId", schemaPath: "#/$defs/context/properties/documentId/type", keyword: "type", params: { type: schema37.properties.documentId.type }, message: "must be string,null" };
                  if (vErrors === null) {
                    vErrors = [err2];
                  } else {
                    vErrors.push(err2);
                  }
                  errors++;
                }
                var valid2 = _errs6 === errors;
              } else {
                var valid2 = true;
              }
              if (valid2) {
                if (data.verifiedBy !== void 0) {
                  const _errs8 = errors;
                  if (typeof data.verifiedBy !== "string") {
                    const err3 = { instancePath: instancePath + "/verifiedBy", schemaPath: "#/$defs/context/properties/verifiedBy/type", keyword: "type", params: { type: "string" }, message: "must be string" };
                    if (vErrors === null) {
                      vErrors = [err3];
                    } else {
                      vErrors.push(err3);
                    }
                    errors++;
                  }
                  var valid2 = _errs8 === errors;
                } else {
                  var valid2 = true;
                }
                if (valid2) {
                  if (data.status !== void 0) {
                    const _errs10 = errors;
                    if (typeof data.status !== "string") {
                      const err4 = { instancePath: instancePath + "/status", schemaPath: "#/$defs/context/properties/status/type", keyword: "type", params: { type: "string" }, message: "must be string" };
                      if (vErrors === null) {
                        vErrors = [err4];
                      } else {
                        vErrors.push(err4);
                      }
                      errors++;
                    }
                    var valid2 = _errs10 === errors;
                  } else {
                    var valid2 = true;
                  }
                  if (valid2) {
                    if (data.reason !== void 0) {
                      const _errs12 = errors;
                      if (typeof data.reason !== "string") {
                        const err5 = { instancePath: instancePath + "/reason", schemaPath: "#/$defs/context/properties/reason/type", keyword: "type", params: { type: "string" }, message: "must be string" };
                        if (vErrors === null) {
                          vErrors = [err5];
                        } else {
                          vErrors.push(err5);
                        }
                        errors++;
                      }
                      var valid2 = _errs12 === errors;
                    } else {
                      var valid2 = true;
                    }
                  }
                }
              }
            }
          }
        } else {
          const err6 = { instancePath, schemaPath: "#/$defs/context/type", keyword: "type", params: { type: "object" }, message: "must be object" };
          if (vErrors === null) {
            vErrors = [err6];
          } else {
            vErrors.push(err6);
          }
          errors++;
        }
      }
      var _valid0 = _errs1 === errors;
      valid0 = valid0 || _valid0;
      if (_valid0) {
        var props0 = {};
        props0.chromeFrameId = true;
        props0.documentId = true;
        props0.verifiedBy = true;
        props0.status = true;
        props0.reason = true;
      }
      const _errs14 = errors;
      if (data !== null) {
        const err7 = { instancePath, schemaPath: "#/anyOf/1/type", keyword: "type", params: { type: "null" }, message: "must be null" };
        if (vErrors === null) {
          vErrors = [err7];
        } else {
          vErrors.push(err7);
        }
        errors++;
      }
      var _valid0 = _errs14 === errors;
      valid0 = valid0 || _valid0;
      if (!valid0) {
        const err8 = { instancePath, schemaPath: "#/anyOf", keyword: "anyOf", params: {}, message: "must match a schema in anyOf" };
        if (vErrors === null) {
          vErrors = [err8];
        } else {
          vErrors.push(err8);
        }
        errors++;
        validate24.errors = vErrors;
        return false;
      } else {
        errors = _errs0;
        if (vErrors !== null) {
          if (_errs0) {
            vErrors.length = _errs0;
          } else {
            vErrors = null;
          }
        }
      }
      validate24.errors = vErrors;
      evaluated0.props = props0;
      return errors === 0;
    }
    validate24.evaluated = { "dynamicProps": true, "dynamicItems": false };
    exports.gap = validate25;
    function validate25(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate25.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.id === void 0 && (missing0 = "id") || data.code === void 0 && (missing0 = "code") || data.observedAt === void 0 && (missing0 = "observedAt") || data.detail === void 0 && (missing0 = "detail")) {
            validate25.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.id !== void 0) {
              let data0 = data.id;
              const _errs1 = errors;
              if (errors === _errs1) {
                if (typeof data0 === "string") {
                  if (func1(data0) > 256) {
                    validate25.errors = [{ instancePath: instancePath + "/id", schemaPath: "#/properties/id/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                    return false;
                  } else {
                    if (func1(data0) < 1) {
                      validate25.errors = [{ instancePath: instancePath + "/id", schemaPath: "#/properties/id/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                      return false;
                    }
                  }
                } else {
                  validate25.errors = [{ instancePath: instancePath + "/id", schemaPath: "#/properties/id/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                  return false;
                }
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.code !== void 0) {
                const _errs3 = errors;
                if (typeof data.code !== "string") {
                  validate25.errors = [{ instancePath: instancePath + "/code", schemaPath: "#/properties/code/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                  return false;
                }
                var valid0 = _errs3 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.observedAt !== void 0) {
                  const _errs5 = errors;
                  if (typeof data.observedAt !== "string") {
                    validate25.errors = [{ instancePath: instancePath + "/observedAt", schemaPath: "#/properties/observedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                    return false;
                  }
                  var valid0 = _errs5 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.detail !== void 0) {
                    const _errs7 = errors;
                    if (typeof data.detail !== "string") {
                      validate25.errors = [{ instancePath: instancePath + "/detail", schemaPath: "#/properties/detail/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                      return false;
                    }
                    var valid0 = _errs7 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.tabInstanceId !== void 0) {
                      const _errs9 = errors;
                      if (typeof data.tabInstanceId !== "string") {
                        validate25.errors = [{ instancePath: instancePath + "/tabInstanceId", schemaPath: "#/properties/tabInstanceId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                        return false;
                      }
                      var valid0 = _errs9 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.channel !== void 0) {
                        let data5 = data.channel;
                        const _errs11 = errors;
                        if (!(data5 === "page" || data5 === "semantic" || data5 === "network" || data5 === "runtime" || data5 === "screenshot")) {
                          validate25.errors = [{ instancePath: instancePath + "/channel", schemaPath: "#/properties/channel/enum", keyword: "enum", params: { allowedValues: schema34.properties.channel.enum }, message: "must be equal to one of the allowed values" }];
                          return false;
                        }
                        var valid0 = _errs11 === errors;
                      } else {
                        var valid0 = true;
                      }
                    }
                  }
                }
              }
            }
          }
        } else {
          validate25.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate25.errors = vErrors;
      return errors === 0;
    }
    validate25.evaluated = { "props": { "id": true, "code": true, "observedAt": true, "detail": true, "tabInstanceId": true, "channel": true }, "dynamicProps": false, "dynamicItems": false };
    exports.body = validate26;
    var schema41 = { "type": "object", "required": ["bodyCaptureStatus", "bodyRef", "bodyCaptureReason", "redactionStatus"], "properties": { "bodyCaptureStatus": { "enum": ["captured", "empty", "not_applicable", "truncated", "excluded_by_policy", "unavailable", "incomplete_target_closed", "incomplete_session_stopped"] }, "bodyRef": { "type": ["string", "null"] }, "bodyCaptureReason": { "type": ["string", "null"] }, "redactionStatus": { "enum": ["none", "applied", "fully_masked", "failed_excluded"] }, "originalBytes": { "type": "integer", "minimum": 0 }, "savedBytes": { "type": "integer", "minimum": 0 } } };
    function validate26(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate26.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.bodyCaptureStatus === void 0 && (missing0 = "bodyCaptureStatus") || data.bodyRef === void 0 && (missing0 = "bodyRef") || data.bodyCaptureReason === void 0 && (missing0 = "bodyCaptureReason") || data.redactionStatus === void 0 && (missing0 = "redactionStatus")) {
            validate26.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.bodyCaptureStatus !== void 0) {
              let data0 = data.bodyCaptureStatus;
              const _errs1 = errors;
              if (!(data0 === "captured" || data0 === "empty" || data0 === "not_applicable" || data0 === "truncated" || data0 === "excluded_by_policy" || data0 === "unavailable" || data0 === "incomplete_target_closed" || data0 === "incomplete_session_stopped")) {
                validate26.errors = [{ instancePath: instancePath + "/bodyCaptureStatus", schemaPath: "#/properties/bodyCaptureStatus/enum", keyword: "enum", params: { allowedValues: schema41.properties.bodyCaptureStatus.enum }, message: "must be equal to one of the allowed values" }];
                return false;
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.bodyRef !== void 0) {
                let data1 = data.bodyRef;
                const _errs2 = errors;
                if (typeof data1 !== "string" && data1 !== null) {
                  validate26.errors = [{ instancePath: instancePath + "/bodyRef", schemaPath: "#/properties/bodyRef/type", keyword: "type", params: { type: schema41.properties.bodyRef.type }, message: "must be string,null" }];
                  return false;
                }
                var valid0 = _errs2 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.bodyCaptureReason !== void 0) {
                  let data2 = data.bodyCaptureReason;
                  const _errs4 = errors;
                  if (typeof data2 !== "string" && data2 !== null) {
                    validate26.errors = [{ instancePath: instancePath + "/bodyCaptureReason", schemaPath: "#/properties/bodyCaptureReason/type", keyword: "type", params: { type: schema41.properties.bodyCaptureReason.type }, message: "must be string,null" }];
                    return false;
                  }
                  var valid0 = _errs4 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.redactionStatus !== void 0) {
                    let data3 = data.redactionStatus;
                    const _errs6 = errors;
                    if (!(data3 === "none" || data3 === "applied" || data3 === "fully_masked" || data3 === "failed_excluded")) {
                      validate26.errors = [{ instancePath: instancePath + "/redactionStatus", schemaPath: "#/properties/redactionStatus/enum", keyword: "enum", params: { allowedValues: schema41.properties.redactionStatus.enum }, message: "must be equal to one of the allowed values" }];
                      return false;
                    }
                    var valid0 = _errs6 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.originalBytes !== void 0) {
                      let data4 = data.originalBytes;
                      const _errs7 = errors;
                      if (!(typeof data4 == "number" && (!(data4 % 1) && !isNaN(data4)))) {
                        validate26.errors = [{ instancePath: instancePath + "/originalBytes", schemaPath: "#/properties/originalBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                        return false;
                      }
                      if (errors === _errs7) {
                        if (typeof data4 == "number") {
                          if (data4 < 0 || isNaN(data4)) {
                            validate26.errors = [{ instancePath: instancePath + "/originalBytes", schemaPath: "#/properties/originalBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                            return false;
                          }
                        }
                      }
                      var valid0 = _errs7 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.savedBytes !== void 0) {
                        let data5 = data.savedBytes;
                        const _errs9 = errors;
                        if (!(typeof data5 == "number" && (!(data5 % 1) && !isNaN(data5)))) {
                          validate26.errors = [{ instancePath: instancePath + "/savedBytes", schemaPath: "#/properties/savedBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                          return false;
                        }
                        if (errors === _errs9) {
                          if (typeof data5 == "number") {
                            if (data5 < 0 || isNaN(data5)) {
                              validate26.errors = [{ instancePath: instancePath + "/savedBytes", schemaPath: "#/properties/savedBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                              return false;
                            }
                          }
                        }
                        var valid0 = _errs9 === errors;
                      } else {
                        var valid0 = true;
                      }
                    }
                  }
                }
              }
            }
          }
        } else {
          validate26.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate26.errors = vErrors;
      return errors === 0;
    }
    validate26.evaluated = { "props": { "bodyCaptureStatus": true, "bodyRef": true, "bodyCaptureReason": true, "redactionStatus": true, "originalBytes": true, "savedBytes": true }, "dynamicProps": false, "dynamicItems": false };
    exports.policy = validate27;
    function validate27(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate27.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.policyVersion === void 0 && (missing0 = "policyVersion") || data.pageOrigins === void 0 && (missing0 = "pageOrigins") || data.apiRules === void 0 && (missing0 = "apiRules") || data.requestTypes === void 0 && (missing0 = "requestTypes") || data.allowedInputNames === void 0 && (missing0 = "allowedInputNames") || data.allowedQueryKeys === void 0 && (missing0 = "allowedQueryKeys") || data.sensitiveSelectors === void 0 && (missing0 = "sensitiveSelectors") || data.maskAllText === void 0 && (missing0 = "maskAllText") || data.screenshots === void 0 && (missing0 = "screenshots") || data.captureStreaming === void 0 && (missing0 = "captureStreaming") || data.businessRules === void 0 && (missing0 = "businessRules") || data.budgets === void 0 && (missing0 = "budgets") || data.logTimeMarginSeconds === void 0 && (missing0 = "logTimeMarginSeconds") || data.correlationSources === void 0 && (missing0 = "correlationSources") || data.sourceMappings === void 0 && (missing0 = "sourceMappings")) {
            validate27.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.policyVersion !== void 0) {
              const _errs1 = errors;
              if (typeof data.policyVersion !== "string") {
                validate27.errors = [{ instancePath: instancePath + "/policyVersion", schemaPath: "#/properties/policyVersion/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                return false;
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.pageOrigins !== void 0) {
                let data1 = data.pageOrigins;
                const _errs3 = errors;
                if (errors === _errs3) {
                  if (Array.isArray(data1)) {
                    var valid1 = true;
                    const len0 = data1.length;
                    for (let i0 = 0; i0 < len0; i0++) {
                      const _errs5 = errors;
                      if (typeof data1[i0] !== "string") {
                        validate27.errors = [{ instancePath: instancePath + "/pageOrigins/" + i0, schemaPath: "#/properties/pageOrigins/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                        return false;
                      }
                      var valid1 = _errs5 === errors;
                      if (!valid1) {
                        break;
                      }
                    }
                  } else {
                    validate27.errors = [{ instancePath: instancePath + "/pageOrigins", schemaPath: "#/properties/pageOrigins/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                    return false;
                  }
                }
                var valid0 = _errs3 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.apiRules !== void 0) {
                  let data3 = data.apiRules;
                  const _errs7 = errors;
                  if (errors === _errs7) {
                    if (Array.isArray(data3)) {
                      var valid2 = true;
                      const len1 = data3.length;
                      for (let i1 = 0; i1 < len1; i1++) {
                        let data4 = data3[i1];
                        const _errs9 = errors;
                        if (errors === _errs9) {
                          if (data4 && typeof data4 == "object" && !Array.isArray(data4)) {
                            let missing1;
                            if (data4.origin === void 0 && (missing1 = "origin") || data4.pathPrefix === void 0 && (missing1 = "pathPrefix")) {
                              validate27.errors = [{ instancePath: instancePath + "/apiRules/" + i1, schemaPath: "#/properties/apiRules/items/required", keyword: "required", params: { missingProperty: missing1 }, message: "must have required property '" + missing1 + "'" }];
                              return false;
                            } else {
                              if (data4.origin !== void 0) {
                                const _errs11 = errors;
                                if (typeof data4.origin !== "string") {
                                  validate27.errors = [{ instancePath: instancePath + "/apiRules/" + i1 + "/origin", schemaPath: "#/properties/apiRules/items/properties/origin/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                  return false;
                                }
                                var valid3 = _errs11 === errors;
                              } else {
                                var valid3 = true;
                              }
                              if (valid3) {
                                if (data4.pathPrefix !== void 0) {
                                  const _errs13 = errors;
                                  if (typeof data4.pathPrefix !== "string") {
                                    validate27.errors = [{ instancePath: instancePath + "/apiRules/" + i1 + "/pathPrefix", schemaPath: "#/properties/apiRules/items/properties/pathPrefix/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                    return false;
                                  }
                                  var valid3 = _errs13 === errors;
                                } else {
                                  var valid3 = true;
                                }
                              }
                            }
                          } else {
                            validate27.errors = [{ instancePath: instancePath + "/apiRules/" + i1, schemaPath: "#/properties/apiRules/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                            return false;
                          }
                        }
                        var valid2 = _errs9 === errors;
                        if (!valid2) {
                          break;
                        }
                      }
                    } else {
                      validate27.errors = [{ instancePath: instancePath + "/apiRules", schemaPath: "#/properties/apiRules/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                      return false;
                    }
                  }
                  var valid0 = _errs7 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.requestTypes !== void 0) {
                    let data7 = data.requestTypes;
                    const _errs15 = errors;
                    if (errors === _errs15) {
                      if (Array.isArray(data7)) {
                        var valid4 = true;
                        const len2 = data7.length;
                        for (let i2 = 0; i2 < len2; i2++) {
                          const _errs17 = errors;
                          if (typeof data7[i2] !== "string") {
                            validate27.errors = [{ instancePath: instancePath + "/requestTypes/" + i2, schemaPath: "#/properties/requestTypes/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                            return false;
                          }
                          var valid4 = _errs17 === errors;
                          if (!valid4) {
                            break;
                          }
                        }
                      } else {
                        validate27.errors = [{ instancePath: instancePath + "/requestTypes", schemaPath: "#/properties/requestTypes/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                        return false;
                      }
                    }
                    var valid0 = _errs15 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.allowedInputNames !== void 0) {
                      let data9 = data.allowedInputNames;
                      const _errs19 = errors;
                      if (errors === _errs19) {
                        if (Array.isArray(data9)) {
                          var valid5 = true;
                          const len3 = data9.length;
                          for (let i3 = 0; i3 < len3; i3++) {
                            const _errs21 = errors;
                            if (typeof data9[i3] !== "string") {
                              validate27.errors = [{ instancePath: instancePath + "/allowedInputNames/" + i3, schemaPath: "#/properties/allowedInputNames/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                              return false;
                            }
                            var valid5 = _errs21 === errors;
                            if (!valid5) {
                              break;
                            }
                          }
                        } else {
                          validate27.errors = [{ instancePath: instancePath + "/allowedInputNames", schemaPath: "#/properties/allowedInputNames/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                          return false;
                        }
                      }
                      var valid0 = _errs19 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.allowedQueryKeys !== void 0) {
                        let data11 = data.allowedQueryKeys;
                        const _errs23 = errors;
                        if (errors === _errs23) {
                          if (Array.isArray(data11)) {
                            var valid6 = true;
                            const len4 = data11.length;
                            for (let i4 = 0; i4 < len4; i4++) {
                              const _errs25 = errors;
                              if (typeof data11[i4] !== "string") {
                                validate27.errors = [{ instancePath: instancePath + "/allowedQueryKeys/" + i4, schemaPath: "#/properties/allowedQueryKeys/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                return false;
                              }
                              var valid6 = _errs25 === errors;
                              if (!valid6) {
                                break;
                              }
                            }
                          } else {
                            validate27.errors = [{ instancePath: instancePath + "/allowedQueryKeys", schemaPath: "#/properties/allowedQueryKeys/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                            return false;
                          }
                        }
                        var valid0 = _errs23 === errors;
                      } else {
                        var valid0 = true;
                      }
                      if (valid0) {
                        if (data.sensitiveSelectors !== void 0) {
                          let data13 = data.sensitiveSelectors;
                          const _errs27 = errors;
                          if (errors === _errs27) {
                            if (Array.isArray(data13)) {
                              var valid7 = true;
                              const len5 = data13.length;
                              for (let i5 = 0; i5 < len5; i5++) {
                                const _errs29 = errors;
                                if (typeof data13[i5] !== "string") {
                                  validate27.errors = [{ instancePath: instancePath + "/sensitiveSelectors/" + i5, schemaPath: "#/properties/sensitiveSelectors/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                  return false;
                                }
                                var valid7 = _errs29 === errors;
                                if (!valid7) {
                                  break;
                                }
                              }
                            } else {
                              validate27.errors = [{ instancePath: instancePath + "/sensitiveSelectors", schemaPath: "#/properties/sensitiveSelectors/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                              return false;
                            }
                          }
                          var valid0 = _errs27 === errors;
                        } else {
                          var valid0 = true;
                        }
                        if (valid0) {
                          if (data.maskAllText !== void 0) {
                            const _errs31 = errors;
                            if (typeof data.maskAllText !== "boolean") {
                              validate27.errors = [{ instancePath: instancePath + "/maskAllText", schemaPath: "#/properties/maskAllText/type", keyword: "type", params: { type: "boolean" }, message: "must be boolean" }];
                              return false;
                            }
                            var valid0 = _errs31 === errors;
                          } else {
                            var valid0 = true;
                          }
                          if (valid0) {
                            if (data.screenshots !== void 0) {
                              const _errs33 = errors;
                              if ("disabled" !== data.screenshots) {
                                validate27.errors = [{ instancePath: instancePath + "/screenshots", schemaPath: "#/properties/screenshots/const", keyword: "const", params: { allowedValue: "disabled" }, message: "must be equal to constant" }];
                                return false;
                              }
                              var valid0 = _errs33 === errors;
                            } else {
                              var valid0 = true;
                            }
                            if (valid0) {
                              if (data.captureStreaming !== void 0) {
                                const _errs34 = errors;
                                if (typeof data.captureStreaming !== "boolean") {
                                  validate27.errors = [{ instancePath: instancePath + "/captureStreaming", schemaPath: "#/properties/captureStreaming/type", keyword: "type", params: { type: "boolean" }, message: "must be boolean" }];
                                  return false;
                                }
                                var valid0 = _errs34 === errors;
                              } else {
                                var valid0 = true;
                              }
                              if (valid0) {
                                if (data.businessRules !== void 0) {
                                  let data18 = data.businessRules;
                                  const _errs36 = errors;
                                  if (errors === _errs36) {
                                    if (Array.isArray(data18)) {
                                      var valid8 = true;
                                      const len6 = data18.length;
                                      for (let i6 = 0; i6 < len6; i6++) {
                                        let data19 = data18[i6];
                                        const _errs38 = errors;
                                        if (errors === _errs38) {
                                          if (data19 && typeof data19 == "object" && !Array.isArray(data19)) {
                                            let missing2;
                                            if (data19.origin === void 0 && (missing2 = "origin") || data19.pathPrefix === void 0 && (missing2 = "pathPrefix") || data19.codePath === void 0 && (missing2 = "codePath") || data19.successValues === void 0 && (missing2 = "successValues")) {
                                              validate27.errors = [{ instancePath: instancePath + "/businessRules/" + i6, schemaPath: "#/properties/businessRules/items/required", keyword: "required", params: { missingProperty: missing2 }, message: "must have required property '" + missing2 + "'" }];
                                              return false;
                                            } else {
                                              if (data19.origin !== void 0) {
                                                const _errs40 = errors;
                                                if (typeof data19.origin !== "string") {
                                                  validate27.errors = [{ instancePath: instancePath + "/businessRules/" + i6 + "/origin", schemaPath: "#/properties/businessRules/items/properties/origin/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                  return false;
                                                }
                                                var valid9 = _errs40 === errors;
                                              } else {
                                                var valid9 = true;
                                              }
                                              if (valid9) {
                                                if (data19.pathPrefix !== void 0) {
                                                  const _errs42 = errors;
                                                  if (typeof data19.pathPrefix !== "string") {
                                                    validate27.errors = [{ instancePath: instancePath + "/businessRules/" + i6 + "/pathPrefix", schemaPath: "#/properties/businessRules/items/properties/pathPrefix/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                    return false;
                                                  }
                                                  var valid9 = _errs42 === errors;
                                                } else {
                                                  var valid9 = true;
                                                }
                                                if (valid9) {
                                                  if (data19.codePath !== void 0) {
                                                    const _errs44 = errors;
                                                    if (typeof data19.codePath !== "string") {
                                                      validate27.errors = [{ instancePath: instancePath + "/businessRules/" + i6 + "/codePath", schemaPath: "#/properties/businessRules/items/properties/codePath/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                      return false;
                                                    }
                                                    var valid9 = _errs44 === errors;
                                                  } else {
                                                    var valid9 = true;
                                                  }
                                                  if (valid9) {
                                                    if (data19.successValues !== void 0) {
                                                      let data23 = data19.successValues;
                                                      const _errs46 = errors;
                                                      if (errors === _errs46) {
                                                        if (Array.isArray(data23)) {
                                                          var valid10 = true;
                                                          const len7 = data23.length;
                                                          for (let i7 = 0; i7 < len7; i7++) {
                                                            let data24 = data23[i7];
                                                            const _errs48 = errors;
                                                            if (typeof data24 !== "string" && !(typeof data24 == "number")) {
                                                              validate27.errors = [{ instancePath: instancePath + "/businessRules/" + i6 + "/successValues/" + i7, schemaPath: "#/properties/businessRules/items/properties/successValues/items/type", keyword: "type", params: { type: schema33.properties.businessRules.items.properties.successValues.items.type }, message: "must be string,number" }];
                                                              return false;
                                                            }
                                                            var valid10 = _errs48 === errors;
                                                            if (!valid10) {
                                                              break;
                                                            }
                                                          }
                                                        } else {
                                                          validate27.errors = [{ instancePath: instancePath + "/businessRules/" + i6 + "/successValues", schemaPath: "#/properties/businessRules/items/properties/successValues/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                          return false;
                                                        }
                                                      }
                                                      var valid9 = _errs46 === errors;
                                                    } else {
                                                      var valid9 = true;
                                                    }
                                                  }
                                                }
                                              }
                                            }
                                          } else {
                                            validate27.errors = [{ instancePath: instancePath + "/businessRules/" + i6, schemaPath: "#/properties/businessRules/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                            return false;
                                          }
                                        }
                                        var valid8 = _errs38 === errors;
                                        if (!valid8) {
                                          break;
                                        }
                                      }
                                    } else {
                                      validate27.errors = [{ instancePath: instancePath + "/businessRules", schemaPath: "#/properties/businessRules/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                      return false;
                                    }
                                  }
                                  var valid0 = _errs36 === errors;
                                } else {
                                  var valid0 = true;
                                }
                                if (valid0) {
                                  if (data.budgets !== void 0) {
                                    let data25 = data.budgets;
                                    const _errs50 = errors;
                                    if (errors === _errs50) {
                                      if (data25 && typeof data25 == "object" && !Array.isArray(data25)) {
                                        let missing3;
                                        if (data25.softTabs === void 0 && (missing3 = "softTabs") || data25.hardTabs === void 0 && (missing3 = "hardTabs") || data25.reminderMinutes === void 0 && (missing3 = "reminderMinutes") || data25.ipcBytes === void 0 && (missing3 = "ipcBytes") || data25.baselineBytes === void 0 && (missing3 = "baselineBytes") || data25.bodyBytes === void 0 && (missing3 = "bodyBytes") || data25.softBytes === void 0 && (missing3 = "softBytes") || data25.hardBytes === void 0 && (missing3 = "hardBytes") || data25.queueBytes === void 0 && (missing3 = "queueBytes") || data25.bodyConcurrency === void 0 && (missing3 = "bodyConcurrency")) {
                                          validate27.errors = [{ instancePath: instancePath + "/budgets", schemaPath: "#/properties/budgets/required", keyword: "required", params: { missingProperty: missing3 }, message: "must have required property '" + missing3 + "'" }];
                                          return false;
                                        } else {
                                          if (data25.softTabs !== void 0) {
                                            let data26 = data25.softTabs;
                                            const _errs52 = errors;
                                            if (!(typeof data26 == "number" && (!(data26 % 1) && !isNaN(data26)))) {
                                              validate27.errors = [{ instancePath: instancePath + "/budgets/softTabs", schemaPath: "#/properties/budgets/properties/softTabs/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                              return false;
                                            }
                                            if (errors === _errs52) {
                                              if (typeof data26 == "number") {
                                                if (data26 < 1 || isNaN(data26)) {
                                                  validate27.errors = [{ instancePath: instancePath + "/budgets/softTabs", schemaPath: "#/properties/budgets/properties/softTabs/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                  return false;
                                                }
                                              }
                                            }
                                            var valid11 = _errs52 === errors;
                                          } else {
                                            var valid11 = true;
                                          }
                                          if (valid11) {
                                            if (data25.hardTabs !== void 0) {
                                              let data27 = data25.hardTabs;
                                              const _errs54 = errors;
                                              if (!(typeof data27 == "number" && (!(data27 % 1) && !isNaN(data27)))) {
                                                validate27.errors = [{ instancePath: instancePath + "/budgets/hardTabs", schemaPath: "#/properties/budgets/properties/hardTabs/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                return false;
                                              }
                                              if (errors === _errs54) {
                                                if (typeof data27 == "number") {
                                                  if (data27 < 1 || isNaN(data27)) {
                                                    validate27.errors = [{ instancePath: instancePath + "/budgets/hardTabs", schemaPath: "#/properties/budgets/properties/hardTabs/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                    return false;
                                                  }
                                                }
                                              }
                                              var valid11 = _errs54 === errors;
                                            } else {
                                              var valid11 = true;
                                            }
                                            if (valid11) {
                                              if (data25.reminderMinutes !== void 0) {
                                                let data28 = data25.reminderMinutes;
                                                const _errs56 = errors;
                                                if (!(typeof data28 == "number" && (!(data28 % 1) && !isNaN(data28)))) {
                                                  validate27.errors = [{ instancePath: instancePath + "/budgets/reminderMinutes", schemaPath: "#/properties/budgets/properties/reminderMinutes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                  return false;
                                                }
                                                if (errors === _errs56) {
                                                  if (typeof data28 == "number") {
                                                    if (data28 < 1 || isNaN(data28)) {
                                                      validate27.errors = [{ instancePath: instancePath + "/budgets/reminderMinutes", schemaPath: "#/properties/budgets/properties/reminderMinutes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                      return false;
                                                    }
                                                  }
                                                }
                                                var valid11 = _errs56 === errors;
                                              } else {
                                                var valid11 = true;
                                              }
                                              if (valid11) {
                                                if (data25.ipcBytes !== void 0) {
                                                  let data29 = data25.ipcBytes;
                                                  const _errs58 = errors;
                                                  if (!(typeof data29 == "number" && (!(data29 % 1) && !isNaN(data29)))) {
                                                    validate27.errors = [{ instancePath: instancePath + "/budgets/ipcBytes", schemaPath: "#/properties/budgets/properties/ipcBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                    return false;
                                                  }
                                                  if (errors === _errs58) {
                                                    if (typeof data29 == "number") {
                                                      if (data29 < 1 || isNaN(data29)) {
                                                        validate27.errors = [{ instancePath: instancePath + "/budgets/ipcBytes", schemaPath: "#/properties/budgets/properties/ipcBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                        return false;
                                                      }
                                                    }
                                                  }
                                                  var valid11 = _errs58 === errors;
                                                } else {
                                                  var valid11 = true;
                                                }
                                                if (valid11) {
                                                  if (data25.baselineBytes !== void 0) {
                                                    let data30 = data25.baselineBytes;
                                                    const _errs60 = errors;
                                                    if (!(typeof data30 == "number" && (!(data30 % 1) && !isNaN(data30)))) {
                                                      validate27.errors = [{ instancePath: instancePath + "/budgets/baselineBytes", schemaPath: "#/properties/budgets/properties/baselineBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                      return false;
                                                    }
                                                    if (errors === _errs60) {
                                                      if (typeof data30 == "number") {
                                                        if (data30 < 1 || isNaN(data30)) {
                                                          validate27.errors = [{ instancePath: instancePath + "/budgets/baselineBytes", schemaPath: "#/properties/budgets/properties/baselineBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                          return false;
                                                        }
                                                      }
                                                    }
                                                    var valid11 = _errs60 === errors;
                                                  } else {
                                                    var valid11 = true;
                                                  }
                                                  if (valid11) {
                                                    if (data25.bodyBytes !== void 0) {
                                                      let data31 = data25.bodyBytes;
                                                      const _errs62 = errors;
                                                      if (!(typeof data31 == "number" && (!(data31 % 1) && !isNaN(data31)))) {
                                                        validate27.errors = [{ instancePath: instancePath + "/budgets/bodyBytes", schemaPath: "#/properties/budgets/properties/bodyBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                        return false;
                                                      }
                                                      if (errors === _errs62) {
                                                        if (typeof data31 == "number") {
                                                          if (data31 < 1 || isNaN(data31)) {
                                                            validate27.errors = [{ instancePath: instancePath + "/budgets/bodyBytes", schemaPath: "#/properties/budgets/properties/bodyBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                            return false;
                                                          }
                                                        }
                                                      }
                                                      var valid11 = _errs62 === errors;
                                                    } else {
                                                      var valid11 = true;
                                                    }
                                                    if (valid11) {
                                                      if (data25.softBytes !== void 0) {
                                                        let data32 = data25.softBytes;
                                                        const _errs64 = errors;
                                                        if (!(typeof data32 == "number" && (!(data32 % 1) && !isNaN(data32)))) {
                                                          validate27.errors = [{ instancePath: instancePath + "/budgets/softBytes", schemaPath: "#/properties/budgets/properties/softBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                          return false;
                                                        }
                                                        if (errors === _errs64) {
                                                          if (typeof data32 == "number") {
                                                            if (data32 < 1 || isNaN(data32)) {
                                                              validate27.errors = [{ instancePath: instancePath + "/budgets/softBytes", schemaPath: "#/properties/budgets/properties/softBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                              return false;
                                                            }
                                                          }
                                                        }
                                                        var valid11 = _errs64 === errors;
                                                      } else {
                                                        var valid11 = true;
                                                      }
                                                      if (valid11) {
                                                        if (data25.hardBytes !== void 0) {
                                                          let data33 = data25.hardBytes;
                                                          const _errs66 = errors;
                                                          if (!(typeof data33 == "number" && (!(data33 % 1) && !isNaN(data33)))) {
                                                            validate27.errors = [{ instancePath: instancePath + "/budgets/hardBytes", schemaPath: "#/properties/budgets/properties/hardBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                            return false;
                                                          }
                                                          if (errors === _errs66) {
                                                            if (typeof data33 == "number") {
                                                              if (data33 < 1 || isNaN(data33)) {
                                                                validate27.errors = [{ instancePath: instancePath + "/budgets/hardBytes", schemaPath: "#/properties/budgets/properties/hardBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                return false;
                                                              }
                                                            }
                                                          }
                                                          var valid11 = _errs66 === errors;
                                                        } else {
                                                          var valid11 = true;
                                                        }
                                                        if (valid11) {
                                                          if (data25.queueBytes !== void 0) {
                                                            let data34 = data25.queueBytes;
                                                            const _errs68 = errors;
                                                            if (!(typeof data34 == "number" && (!(data34 % 1) && !isNaN(data34)))) {
                                                              validate27.errors = [{ instancePath: instancePath + "/budgets/queueBytes", schemaPath: "#/properties/budgets/properties/queueBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                              return false;
                                                            }
                                                            if (errors === _errs68) {
                                                              if (typeof data34 == "number") {
                                                                if (data34 < 1 || isNaN(data34)) {
                                                                  validate27.errors = [{ instancePath: instancePath + "/budgets/queueBytes", schemaPath: "#/properties/budgets/properties/queueBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                  return false;
                                                                }
                                                              }
                                                            }
                                                            var valid11 = _errs68 === errors;
                                                          } else {
                                                            var valid11 = true;
                                                          }
                                                          if (valid11) {
                                                            if (data25.bodyConcurrency !== void 0) {
                                                              let data35 = data25.bodyConcurrency;
                                                              const _errs70 = errors;
                                                              if (!(typeof data35 == "number" && (!(data35 % 1) && !isNaN(data35)))) {
                                                                validate27.errors = [{ instancePath: instancePath + "/budgets/bodyConcurrency", schemaPath: "#/properties/budgets/properties/bodyConcurrency/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                return false;
                                                              }
                                                              if (errors === _errs70) {
                                                                if (typeof data35 == "number") {
                                                                  if (data35 < 1 || isNaN(data35)) {
                                                                    validate27.errors = [{ instancePath: instancePath + "/budgets/bodyConcurrency", schemaPath: "#/properties/budgets/properties/bodyConcurrency/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                    return false;
                                                                  }
                                                                }
                                                              }
                                                              var valid11 = _errs70 === errors;
                                                            } else {
                                                              var valid11 = true;
                                                            }
                                                          }
                                                        }
                                                      }
                                                    }
                                                  }
                                                }
                                              }
                                            }
                                          }
                                        }
                                      } else {
                                        validate27.errors = [{ instancePath: instancePath + "/budgets", schemaPath: "#/properties/budgets/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                        return false;
                                      }
                                    }
                                    var valid0 = _errs50 === errors;
                                  } else {
                                    var valid0 = true;
                                  }
                                  if (valid0) {
                                    if (data.logTimeMarginSeconds !== void 0) {
                                      let data36 = data.logTimeMarginSeconds;
                                      const _errs72 = errors;
                                      if (!(typeof data36 == "number" && (!(data36 % 1) && !isNaN(data36)))) {
                                        validate27.errors = [{ instancePath: instancePath + "/logTimeMarginSeconds", schemaPath: "#/properties/logTimeMarginSeconds/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                        return false;
                                      }
                                      if (errors === _errs72) {
                                        if (typeof data36 == "number") {
                                          if (data36 < 0 || isNaN(data36)) {
                                            validate27.errors = [{ instancePath: instancePath + "/logTimeMarginSeconds", schemaPath: "#/properties/logTimeMarginSeconds/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                            return false;
                                          }
                                        }
                                      }
                                      var valid0 = _errs72 === errors;
                                    } else {
                                      var valid0 = true;
                                    }
                                    if (valid0) {
                                      if (data.correlationSources !== void 0) {
                                        let data37 = data.correlationSources;
                                        const _errs74 = errors;
                                        if (errors === _errs74) {
                                          if (Array.isArray(data37)) {
                                            if (data37.length > 32) {
                                              validate27.errors = [{ instancePath: instancePath + "/correlationSources", schemaPath: "#/properties/correlationSources/maxItems", keyword: "maxItems", params: { limit: 32 }, message: "must NOT have more than 32 items" }];
                                              return false;
                                            } else {
                                              var valid12 = true;
                                              const len8 = data37.length;
                                              for (let i8 = 0; i8 < len8; i8++) {
                                                let data38 = data37[i8];
                                                const _errs76 = errors;
                                                const _errs78 = errors;
                                                const _errs79 = errors;
                                                let valid14 = true;
                                                const _errs80 = errors;
                                                if (data38 && typeof data38 == "object" && !Array.isArray(data38)) {
                                                  if (data38.source !== void 0) {
                                                    if ("response_header" !== data38.source) {
                                                      const err0 = {};
                                                      if (vErrors === null) {
                                                        vErrors = [err0];
                                                      } else {
                                                        vErrors.push(err0);
                                                      }
                                                      errors++;
                                                    }
                                                  }
                                                }
                                                var _valid0 = _errs80 === errors;
                                                errors = _errs79;
                                                if (vErrors !== null) {
                                                  if (_errs79) {
                                                    vErrors.length = _errs79;
                                                  } else {
                                                    vErrors = null;
                                                  }
                                                }
                                                if (_valid0) {
                                                  const _errs82 = errors;
                                                  if (data38 && typeof data38 == "object" && !Array.isArray(data38)) {
                                                    if (data38.key !== void 0) {
                                                      let data40 = data38.key;
                                                      if (typeof data40 === "string") {
                                                        if (!pattern4.test(data40)) {
                                                          validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/key", schemaPath: "#/properties/correlationSources/items/allOf/0/then/properties/key/pattern", keyword: "pattern", params: { pattern: "^[a-zA-Z0-9-]{1,80}$" }, message: 'must match pattern "^[a-zA-Z0-9-]{1,80}$"' }];
                                                          return false;
                                                        }
                                                      }
                                                    }
                                                  }
                                                  var _valid0 = _errs82 === errors;
                                                  valid14 = _valid0;
                                                  if (valid14) {
                                                    var props0 = {};
                                                    props0.key = true;
                                                    props0.source = true;
                                                  }
                                                }
                                                if (!valid14) {
                                                  const err1 = { instancePath: instancePath + "/correlationSources/" + i8, schemaPath: "#/properties/correlationSources/items/allOf/0/if", keyword: "if", params: { failingKeyword: "then" }, message: 'must match "then" schema' };
                                                  if (vErrors === null) {
                                                    vErrors = [err1];
                                                  } else {
                                                    vErrors.push(err1);
                                                  }
                                                  errors++;
                                                  validate27.errors = vErrors;
                                                  return false;
                                                }
                                                var valid13 = _errs78 === errors;
                                                if (valid13) {
                                                  const _errs84 = errors;
                                                  const _errs85 = errors;
                                                  let valid17 = true;
                                                  const _errs86 = errors;
                                                  if (data38 && typeof data38 == "object" && !Array.isArray(data38)) {
                                                    if (data38.source !== void 0) {
                                                      if ("response_json" !== data38.source) {
                                                        const err2 = {};
                                                        if (vErrors === null) {
                                                          vErrors = [err2];
                                                        } else {
                                                          vErrors.push(err2);
                                                        }
                                                        errors++;
                                                      }
                                                    }
                                                  }
                                                  var _valid1 = _errs86 === errors;
                                                  errors = _errs85;
                                                  if (vErrors !== null) {
                                                    if (_errs85) {
                                                      vErrors.length = _errs85;
                                                    } else {
                                                      vErrors = null;
                                                    }
                                                  }
                                                  if (_valid1) {
                                                    const _errs88 = errors;
                                                    if (data38 && typeof data38 == "object" && !Array.isArray(data38)) {
                                                      if (data38.key !== void 0) {
                                                        let data42 = data38.key;
                                                        if (typeof data42 === "string") {
                                                          if (!pattern5.test(data42)) {
                                                            validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/key", schemaPath: "#/properties/correlationSources/items/allOf/1/then/properties/key/pattern", keyword: "pattern", params: { pattern: "^(\\/([^~]|~[01])*)+$" }, message: 'must match pattern "^(\\/([^~]|~[01])*)+$"' }];
                                                            return false;
                                                          }
                                                        }
                                                      }
                                                    }
                                                    var _valid1 = _errs88 === errors;
                                                    valid17 = _valid1;
                                                    if (valid17) {
                                                      var props1 = {};
                                                      props1.key = true;
                                                      props1.source = true;
                                                    }
                                                  }
                                                  if (!valid17) {
                                                    const err3 = { instancePath: instancePath + "/correlationSources/" + i8, schemaPath: "#/properties/correlationSources/items/allOf/1/if", keyword: "if", params: { failingKeyword: "then" }, message: 'must match "then" schema' };
                                                    if (vErrors === null) {
                                                      vErrors = [err3];
                                                    } else {
                                                      vErrors.push(err3);
                                                    }
                                                    errors++;
                                                    validate27.errors = vErrors;
                                                    return false;
                                                  }
                                                  var valid13 = _errs84 === errors;
                                                  if (valid13) {
                                                    if (props0 !== true && props1 !== void 0) {
                                                      if (props1 === true) {
                                                        props0 = true;
                                                      } else {
                                                        props0 = props0 || {};
                                                        Object.assign(props0, props1);
                                                      }
                                                    }
                                                    const _errs90 = errors;
                                                    const _errs91 = errors;
                                                    let valid20 = true;
                                                    const _errs92 = errors;
                                                    if (data38 && typeof data38 == "object" && !Array.isArray(data38)) {
                                                      if (data38.source !== void 0) {
                                                        if ("page_meta" !== data38.source) {
                                                          const err4 = {};
                                                          if (vErrors === null) {
                                                            vErrors = [err4];
                                                          } else {
                                                            vErrors.push(err4);
                                                          }
                                                          errors++;
                                                        }
                                                      }
                                                    }
                                                    var _valid2 = _errs92 === errors;
                                                    errors = _errs91;
                                                    if (vErrors !== null) {
                                                      if (_errs91) {
                                                        vErrors.length = _errs91;
                                                      } else {
                                                        vErrors = null;
                                                      }
                                                    }
                                                    if (_valid2) {
                                                      const _errs94 = errors;
                                                      if (data38 && typeof data38 == "object" && !Array.isArray(data38)) {
                                                        if (data38.key !== void 0) {
                                                          let data44 = data38.key;
                                                          if (typeof data44 === "string") {
                                                            if (!pattern6.test(data44)) {
                                                              validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/key", schemaPath: "#/properties/correlationSources/items/allOf/2/then/properties/key/pattern", keyword: "pattern", params: { pattern: `^meta\\[name=(?:"[a-zA-Z0-9_.-]+"|'[a-zA-Z0-9_.-]+')\\]$` }, message: `must match pattern "^meta\\[name=(?:"[a-zA-Z0-9_.-]+"|'[a-zA-Z0-9_.-]+')\\]$"` }];
                                                              return false;
                                                            }
                                                          }
                                                        }
                                                      }
                                                      var _valid2 = _errs94 === errors;
                                                      valid20 = _valid2;
                                                      if (valid20) {
                                                        var props2 = {};
                                                        props2.key = true;
                                                        props2.source = true;
                                                      }
                                                    }
                                                    if (!valid20) {
                                                      const err5 = { instancePath: instancePath + "/correlationSources/" + i8, schemaPath: "#/properties/correlationSources/items/allOf/2/if", keyword: "if", params: { failingKeyword: "then" }, message: 'must match "then" schema' };
                                                      if (vErrors === null) {
                                                        vErrors = [err5];
                                                      } else {
                                                        vErrors.push(err5);
                                                      }
                                                      errors++;
                                                      validate27.errors = vErrors;
                                                      return false;
                                                    }
                                                    var valid13 = _errs90 === errors;
                                                    if (valid13) {
                                                      if (props0 !== true && props2 !== void 0) {
                                                        if (props2 === true) {
                                                          props0 = true;
                                                        } else {
                                                          props0 = props0 || {};
                                                          Object.assign(props0, props2);
                                                        }
                                                      }
                                                    }
                                                  }
                                                }
                                                if (errors === _errs76) {
                                                  if (data38 && typeof data38 == "object" && !Array.isArray(data38)) {
                                                    let missing4;
                                                    if (data38.field === void 0 && (missing4 = "field") || data38.source === void 0 && (missing4 = "source") || data38.key === void 0 && (missing4 = "key") || data38.component === void 0 && (missing4 = "component")) {
                                                      validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8, schemaPath: "#/properties/correlationSources/items/required", keyword: "required", params: { missingProperty: missing4 }, message: "must have required property '" + missing4 + "'" }];
                                                      return false;
                                                    } else {
                                                      if (props0 !== true) {
                                                        props0 = props0 || {};
                                                        props0.field = true;
                                                        props0.source = true;
                                                        props0.key = true;
                                                        props0.component = true;
                                                        props0.origin = true;
                                                        props0.pathPrefix = true;
                                                      }
                                                      if (data38.field !== void 0) {
                                                        let data45 = data38.field;
                                                        const _errs96 = errors;
                                                        if (!(data45 === "frontendBuildId" || data45 === "backendBuildId" || data45 === "serviceInstance" || data45 === "requestId" || data45 === "traceId" || data45 === "spanId")) {
                                                          validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/field", schemaPath: "#/properties/correlationSources/items/properties/field/enum", keyword: "enum", params: { allowedValues: schema33.properties.correlationSources.items.properties.field.enum }, message: "must be equal to one of the allowed values" }];
                                                          return false;
                                                        }
                                                        var valid23 = _errs96 === errors;
                                                      } else {
                                                        var valid23 = true;
                                                      }
                                                      if (valid23) {
                                                        if (data38.source !== void 0) {
                                                          let data46 = data38.source;
                                                          const _errs97 = errors;
                                                          if (!(data46 === "response_header" || data46 === "response_json" || data46 === "page_meta")) {
                                                            validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/source", schemaPath: "#/properties/correlationSources/items/properties/source/enum", keyword: "enum", params: { allowedValues: schema33.properties.correlationSources.items.properties.source.enum }, message: "must be equal to one of the allowed values" }];
                                                            return false;
                                                          }
                                                          var valid23 = _errs97 === errors;
                                                        } else {
                                                          var valid23 = true;
                                                        }
                                                        if (valid23) {
                                                          if (data38.key !== void 0) {
                                                            let data47 = data38.key;
                                                            const _errs98 = errors;
                                                            if (errors === _errs98) {
                                                              if (typeof data47 === "string") {
                                                                if (func1(data47) > 200) {
                                                                  validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/key", schemaPath: "#/properties/correlationSources/items/properties/key/maxLength", keyword: "maxLength", params: { limit: 200 }, message: "must NOT have more than 200 characters" }];
                                                                  return false;
                                                                } else {
                                                                  if (func1(data47) < 1) {
                                                                    validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/key", schemaPath: "#/properties/correlationSources/items/properties/key/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                    return false;
                                                                  }
                                                                }
                                                              } else {
                                                                validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/key", schemaPath: "#/properties/correlationSources/items/properties/key/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                return false;
                                                              }
                                                            }
                                                            var valid23 = _errs98 === errors;
                                                          } else {
                                                            var valid23 = true;
                                                          }
                                                          if (valid23) {
                                                            if (data38.component !== void 0) {
                                                              let data48 = data38.component;
                                                              const _errs100 = errors;
                                                              if (errors === _errs100) {
                                                                if (typeof data48 === "string") {
                                                                  if (func1(data48) > 80) {
                                                                    validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/component", schemaPath: "#/properties/correlationSources/items/properties/component/maxLength", keyword: "maxLength", params: { limit: 80 }, message: "must NOT have more than 80 characters" }];
                                                                    return false;
                                                                  } else {
                                                                    if (func1(data48) < 1) {
                                                                      validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/component", schemaPath: "#/properties/correlationSources/items/properties/component/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                      return false;
                                                                    }
                                                                  }
                                                                } else {
                                                                  validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/component", schemaPath: "#/properties/correlationSources/items/properties/component/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                  return false;
                                                                }
                                                              }
                                                              var valid23 = _errs100 === errors;
                                                            } else {
                                                              var valid23 = true;
                                                            }
                                                            if (valid23) {
                                                              if (data38.origin !== void 0) {
                                                                let data49 = data38.origin;
                                                                const _errs102 = errors;
                                                                if (errors === _errs102) {
                                                                  if (typeof data49 === "string") {
                                                                    if (func1(data49) < 1) {
                                                                      validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/origin", schemaPath: "#/properties/correlationSources/items/properties/origin/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                      return false;
                                                                    } else {
                                                                      if (!pattern7.test(data49)) {
                                                                        validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/origin", schemaPath: "#/properties/correlationSources/items/properties/origin/pattern", keyword: "pattern", params: { pattern: "^https?://[^/?#]+$" }, message: 'must match pattern "^https?://[^/?#]+$"' }];
                                                                        return false;
                                                                      }
                                                                    }
                                                                  } else {
                                                                    validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/origin", schemaPath: "#/properties/correlationSources/items/properties/origin/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                    return false;
                                                                  }
                                                                }
                                                                var valid23 = _errs102 === errors;
                                                              } else {
                                                                var valid23 = true;
                                                              }
                                                              if (valid23) {
                                                                if (data38.pathPrefix !== void 0) {
                                                                  let data50 = data38.pathPrefix;
                                                                  const _errs104 = errors;
                                                                  if (errors === _errs104) {
                                                                    if (typeof data50 === "string") {
                                                                      if (func1(data50) > 499) {
                                                                        validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/pathPrefix", schemaPath: "#/properties/correlationSources/items/properties/pathPrefix/maxLength", keyword: "maxLength", params: { limit: 499 }, message: "must NOT have more than 499 characters" }];
                                                                        return false;
                                                                      } else {
                                                                        if (func1(data50) < 1) {
                                                                          validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/pathPrefix", schemaPath: "#/properties/correlationSources/items/properties/pathPrefix/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                          return false;
                                                                        } else {
                                                                          if (!pattern8.test(data50)) {
                                                                            validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/pathPrefix", schemaPath: "#/properties/correlationSources/items/properties/pathPrefix/pattern", keyword: "pattern", params: { pattern: "^/" }, message: 'must match pattern "^/"' }];
                                                                            return false;
                                                                          }
                                                                        }
                                                                      }
                                                                    } else {
                                                                      validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8 + "/pathPrefix", schemaPath: "#/properties/correlationSources/items/properties/pathPrefix/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                      return false;
                                                                    }
                                                                  }
                                                                  var valid23 = _errs104 === errors;
                                                                } else {
                                                                  var valid23 = true;
                                                                }
                                                              }
                                                            }
                                                          }
                                                        }
                                                      }
                                                    }
                                                  } else {
                                                    validate27.errors = [{ instancePath: instancePath + "/correlationSources/" + i8, schemaPath: "#/properties/correlationSources/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                    return false;
                                                  }
                                                }
                                                var valid12 = _errs76 === errors;
                                                if (!valid12) {
                                                  break;
                                                }
                                              }
                                            }
                                          } else {
                                            validate27.errors = [{ instancePath: instancePath + "/correlationSources", schemaPath: "#/properties/correlationSources/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                            return false;
                                          }
                                        }
                                        var valid0 = _errs74 === errors;
                                      } else {
                                        var valid0 = true;
                                      }
                                      if (valid0) {
                                        if (data.sourceMappings !== void 0) {
                                          let data51 = data.sourceMappings;
                                          const _errs106 = errors;
                                          if (errors === _errs106) {
                                            if (Array.isArray(data51)) {
                                              if (data51.length > 100) {
                                                validate27.errors = [{ instancePath: instancePath + "/sourceMappings", schemaPath: "#/properties/sourceMappings/maxItems", keyword: "maxItems", params: { limit: 100 }, message: "must NOT have more than 100 items" }];
                                                return false;
                                              } else {
                                                var valid24 = true;
                                                const len9 = data51.length;
                                                for (let i9 = 0; i9 < len9; i9++) {
                                                  let data52 = data51[i9];
                                                  const _errs108 = errors;
                                                  if (errors === _errs108) {
                                                    if (data52 && typeof data52 == "object" && !Array.isArray(data52)) {
                                                      let missing5;
                                                      if (data52.environmentId === void 0 && (missing5 = "environmentId") || data52.component === void 0 && (missing5 = "component") || data52.buildId === void 0 && (missing5 = "buildId") || data52.codeSnapshot === void 0 && (missing5 = "codeSnapshot")) {
                                                        validate27.errors = [{ instancePath: instancePath + "/sourceMappings/" + i9, schemaPath: "#/properties/sourceMappings/items/required", keyword: "required", params: { missingProperty: missing5 }, message: "must have required property '" + missing5 + "'" }];
                                                        return false;
                                                      } else {
                                                        if (data52.environmentId !== void 0) {
                                                          let data53 = data52.environmentId;
                                                          const _errs110 = errors;
                                                          if (errors === _errs110) {
                                                            if (typeof data53 === "string") {
                                                              if (func1(data53) > 500) {
                                                                validate27.errors = [{ instancePath: instancePath + "/sourceMappings/" + i9 + "/environmentId", schemaPath: "#/properties/sourceMappings/items/properties/environmentId/maxLength", keyword: "maxLength", params: { limit: 500 }, message: "must NOT have more than 500 characters" }];
                                                                return false;
                                                              } else {
                                                                if (func1(data53) < 1) {
                                                                  validate27.errors = [{ instancePath: instancePath + "/sourceMappings/" + i9 + "/environmentId", schemaPath: "#/properties/sourceMappings/items/properties/environmentId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                  return false;
                                                                }
                                                              }
                                                            } else {
                                                              validate27.errors = [{ instancePath: instancePath + "/sourceMappings/" + i9 + "/environmentId", schemaPath: "#/properties/sourceMappings/items/properties/environmentId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                              return false;
                                                            }
                                                          }
                                                          var valid25 = _errs110 === errors;
                                                        } else {
                                                          var valid25 = true;
                                                        }
                                                        if (valid25) {
                                                          if (data52.component !== void 0) {
                                                            let data54 = data52.component;
                                                            const _errs112 = errors;
                                                            if (errors === _errs112) {
                                                              if (typeof data54 === "string") {
                                                                if (func1(data54) > 500) {
                                                                  validate27.errors = [{ instancePath: instancePath + "/sourceMappings/" + i9 + "/component", schemaPath: "#/properties/sourceMappings/items/properties/component/maxLength", keyword: "maxLength", params: { limit: 500 }, message: "must NOT have more than 500 characters" }];
                                                                  return false;
                                                                } else {
                                                                  if (func1(data54) < 1) {
                                                                    validate27.errors = [{ instancePath: instancePath + "/sourceMappings/" + i9 + "/component", schemaPath: "#/properties/sourceMappings/items/properties/component/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                    return false;
                                                                  }
                                                                }
                                                              } else {
                                                                validate27.errors = [{ instancePath: instancePath + "/sourceMappings/" + i9 + "/component", schemaPath: "#/properties/sourceMappings/items/properties/component/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                return false;
                                                              }
                                                            }
                                                            var valid25 = _errs112 === errors;
                                                          } else {
                                                            var valid25 = true;
                                                          }
                                                          if (valid25) {
                                                            if (data52.buildId !== void 0) {
                                                              let data55 = data52.buildId;
                                                              const _errs114 = errors;
                                                              if (errors === _errs114) {
                                                                if (typeof data55 === "string") {
                                                                  if (func1(data55) > 500) {
                                                                    validate27.errors = [{ instancePath: instancePath + "/sourceMappings/" + i9 + "/buildId", schemaPath: "#/properties/sourceMappings/items/properties/buildId/maxLength", keyword: "maxLength", params: { limit: 500 }, message: "must NOT have more than 500 characters" }];
                                                                    return false;
                                                                  } else {
                                                                    if (func1(data55) < 1) {
                                                                      validate27.errors = [{ instancePath: instancePath + "/sourceMappings/" + i9 + "/buildId", schemaPath: "#/properties/sourceMappings/items/properties/buildId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                      return false;
                                                                    }
                                                                  }
                                                                } else {
                                                                  validate27.errors = [{ instancePath: instancePath + "/sourceMappings/" + i9 + "/buildId", schemaPath: "#/properties/sourceMappings/items/properties/buildId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                  return false;
                                                                }
                                                              }
                                                              var valid25 = _errs114 === errors;
                                                            } else {
                                                              var valid25 = true;
                                                            }
                                                            if (valid25) {
                                                              if (data52.codeSnapshot !== void 0) {
                                                                let data56 = data52.codeSnapshot;
                                                                const _errs116 = errors;
                                                                if (errors === _errs116) {
                                                                  if (typeof data56 === "string") {
                                                                    if (func1(data56) > 500) {
                                                                      validate27.errors = [{ instancePath: instancePath + "/sourceMappings/" + i9 + "/codeSnapshot", schemaPath: "#/properties/sourceMappings/items/properties/codeSnapshot/maxLength", keyword: "maxLength", params: { limit: 500 }, message: "must NOT have more than 500 characters" }];
                                                                      return false;
                                                                    } else {
                                                                      if (func1(data56) < 1) {
                                                                        validate27.errors = [{ instancePath: instancePath + "/sourceMappings/" + i9 + "/codeSnapshot", schemaPath: "#/properties/sourceMappings/items/properties/codeSnapshot/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                        return false;
                                                                      }
                                                                    }
                                                                  } else {
                                                                    validate27.errors = [{ instancePath: instancePath + "/sourceMappings/" + i9 + "/codeSnapshot", schemaPath: "#/properties/sourceMappings/items/properties/codeSnapshot/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                    return false;
                                                                  }
                                                                }
                                                                var valid25 = _errs116 === errors;
                                                              } else {
                                                                var valid25 = true;
                                                              }
                                                            }
                                                          }
                                                        }
                                                      }
                                                    } else {
                                                      validate27.errors = [{ instancePath: instancePath + "/sourceMappings/" + i9, schemaPath: "#/properties/sourceMappings/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                      return false;
                                                    }
                                                  }
                                                  var valid24 = _errs108 === errors;
                                                  if (!valid24) {
                                                    break;
                                                  }
                                                }
                                              }
                                            } else {
                                              validate27.errors = [{ instancePath: instancePath + "/sourceMappings", schemaPath: "#/properties/sourceMappings/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                              return false;
                                            }
                                          }
                                          var valid0 = _errs106 === errors;
                                        } else {
                                          var valid0 = true;
                                        }
                                      }
                                    }
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        } else {
          validate27.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate27.errors = vErrors;
      return errors === 0;
    }
    validate27.evaluated = { "props": { "policyVersion": true, "pageOrigins": true, "apiRules": true, "requestTypes": true, "allowedInputNames": true, "allowedQueryKeys": true, "sensitiveSelectors": true, "maskAllText": true, "screenshots": true, "captureStreaming": true, "businessRules": true, "budgets": true, "logTimeMarginSeconds": true, "correlationSources": true, "sourceMappings": true }, "dynamicProps": false, "dynamicItems": false };
    exports.recording = validate28;
    function validate28(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate28.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.schemaVersion === void 0 && (missing0 = "schemaVersion") || data.recordingId === void 0 && (missing0 = "recordingId") || data.browserRunId === void 0 && (missing0 = "browserRunId") || data.state === void 0 && (missing0 = "state") || data.scopeVersion === void 0 && (missing0 = "scopeVersion") || data.environmentId === void 0 && (missing0 = "environmentId") || data.browserVersion === void 0 && (missing0 = "browserVersion") || data.extensionVersion === void 0 && (missing0 = "extensionVersion") || data.rrwebVersion === void 0 && (missing0 = "rrwebVersion") || data.startedAt === void 0 && (missing0 = "startedAt") || data.policy === void 0 && (missing0 = "policy") || data.gaps === void 0 && (missing0 = "gaps") || data.rootTabInstanceIds === void 0 && (missing0 = "rootTabInstanceIds") || data.commands === void 0 && (missing0 = "commands") || data.bytesAccepted === void 0 && (missing0 = "bytesAccepted") || data.bytesPersisted === void 0 && (missing0 = "bytesPersisted") || data.eventsPersisted === void 0 && (missing0 = "eventsPersisted") || data.checkpoint === void 0 && (missing0 = "checkpoint") || data.saveState === void 0 && (missing0 = "saveState") || data.versions === void 0 && (missing0 = "versions") || data.capabilities === void 0 && (missing0 = "capabilities")) {
            validate28.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.schemaVersion !== void 0) {
              const _errs1 = errors;
              if ("3.0.0" !== data.schemaVersion) {
                validate28.errors = [{ instancePath: instancePath + "/schemaVersion", schemaPath: "#/properties/schemaVersion/const", keyword: "const", params: { allowedValue: "3.0.0" }, message: "must be equal to constant" }];
                return false;
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.recordingId !== void 0) {
                let data1 = data.recordingId;
                const _errs2 = errors;
                if (errors === _errs2) {
                  if (typeof data1 === "string") {
                    if (func1(data1) > 256) {
                      validate28.errors = [{ instancePath: instancePath + "/recordingId", schemaPath: "#/properties/recordingId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                      return false;
                    } else {
                      if (func1(data1) < 1) {
                        validate28.errors = [{ instancePath: instancePath + "/recordingId", schemaPath: "#/properties/recordingId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                        return false;
                      }
                    }
                  } else {
                    validate28.errors = [{ instancePath: instancePath + "/recordingId", schemaPath: "#/properties/recordingId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                    return false;
                  }
                }
                var valid0 = _errs2 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.browserRunId !== void 0) {
                  let data2 = data.browserRunId;
                  const _errs4 = errors;
                  if (errors === _errs4) {
                    if (typeof data2 === "string") {
                      if (func1(data2) > 256) {
                        validate28.errors = [{ instancePath: instancePath + "/browserRunId", schemaPath: "#/properties/browserRunId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                        return false;
                      } else {
                        if (func1(data2) < 1) {
                          validate28.errors = [{ instancePath: instancePath + "/browserRunId", schemaPath: "#/properties/browserRunId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                          return false;
                        }
                      }
                    } else {
                      validate28.errors = [{ instancePath: instancePath + "/browserRunId", schemaPath: "#/properties/browserRunId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                      return false;
                    }
                  }
                  var valid0 = _errs4 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.state !== void 0) {
                    let data3 = data.state;
                    const _errs6 = errors;
                    if (!(data3 === "STARTING" || data3 === "RECORDING" || data3 === "STOPPING" || data3 === "FINALIZING" || data3 === "READY" || data3 === "INTERRUPTED" || data3 === "FAILED")) {
                      validate28.errors = [{ instancePath: instancePath + "/state", schemaPath: "#/properties/state/enum", keyword: "enum", params: { allowedValues: schema32.properties.state.enum }, message: "must be equal to one of the allowed values" }];
                      return false;
                    }
                    var valid0 = _errs6 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.scopeVersion !== void 0) {
                      let data4 = data.scopeVersion;
                      const _errs7 = errors;
                      if (!(typeof data4 == "number" && (!(data4 % 1) && !isNaN(data4)))) {
                        validate28.errors = [{ instancePath: instancePath + "/scopeVersion", schemaPath: "#/properties/scopeVersion/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                        return false;
                      }
                      if (errors === _errs7) {
                        if (typeof data4 == "number") {
                          if (data4 < 0 || isNaN(data4)) {
                            validate28.errors = [{ instancePath: instancePath + "/scopeVersion", schemaPath: "#/properties/scopeVersion/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                            return false;
                          }
                        }
                      }
                      var valid0 = _errs7 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.environmentId !== void 0) {
                        const _errs9 = errors;
                        if (typeof data.environmentId !== "string") {
                          validate28.errors = [{ instancePath: instancePath + "/environmentId", schemaPath: "#/properties/environmentId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                          return false;
                        }
                        var valid0 = _errs9 === errors;
                      } else {
                        var valid0 = true;
                      }
                      if (valid0) {
                        if (data.browserVersion !== void 0) {
                          const _errs11 = errors;
                          if (typeof data.browserVersion !== "string") {
                            validate28.errors = [{ instancePath: instancePath + "/browserVersion", schemaPath: "#/properties/browserVersion/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                            return false;
                          }
                          var valid0 = _errs11 === errors;
                        } else {
                          var valid0 = true;
                        }
                        if (valid0) {
                          if (data.extensionVersion !== void 0) {
                            const _errs13 = errors;
                            if (typeof data.extensionVersion !== "string") {
                              validate28.errors = [{ instancePath: instancePath + "/extensionVersion", schemaPath: "#/properties/extensionVersion/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                              return false;
                            }
                            var valid0 = _errs13 === errors;
                          } else {
                            var valid0 = true;
                          }
                          if (valid0) {
                            if (data.rrwebVersion !== void 0) {
                              const _errs15 = errors;
                              if (typeof data.rrwebVersion !== "string") {
                                validate28.errors = [{ instancePath: instancePath + "/rrwebVersion", schemaPath: "#/properties/rrwebVersion/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                return false;
                              }
                              var valid0 = _errs15 === errors;
                            } else {
                              var valid0 = true;
                            }
                            if (valid0) {
                              if (data.startedAt !== void 0) {
                                const _errs17 = errors;
                                if (typeof data.startedAt !== "string") {
                                  validate28.errors = [{ instancePath: instancePath + "/startedAt", schemaPath: "#/properties/startedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                  return false;
                                }
                                var valid0 = _errs17 === errors;
                              } else {
                                var valid0 = true;
                              }
                              if (valid0) {
                                if (data.stoppedAt !== void 0) {
                                  const _errs19 = errors;
                                  if (typeof data.stoppedAt !== "string") {
                                    validate28.errors = [{ instancePath: instancePath + "/stoppedAt", schemaPath: "#/properties/stoppedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                    return false;
                                  }
                                  var valid0 = _errs19 === errors;
                                } else {
                                  var valid0 = true;
                                }
                                if (valid0) {
                                  if (data.policy !== void 0) {
                                    let data11 = data.policy;
                                    const _errs21 = errors;
                                    const _errs22 = errors;
                                    if (errors === _errs22) {
                                      if (data11 && typeof data11 == "object" && !Array.isArray(data11)) {
                                        let missing1;
                                        if (data11.policyVersion === void 0 && (missing1 = "policyVersion") || data11.pageOrigins === void 0 && (missing1 = "pageOrigins") || data11.apiRules === void 0 && (missing1 = "apiRules") || data11.requestTypes === void 0 && (missing1 = "requestTypes") || data11.allowedInputNames === void 0 && (missing1 = "allowedInputNames") || data11.allowedQueryKeys === void 0 && (missing1 = "allowedQueryKeys") || data11.sensitiveSelectors === void 0 && (missing1 = "sensitiveSelectors") || data11.maskAllText === void 0 && (missing1 = "maskAllText") || data11.screenshots === void 0 && (missing1 = "screenshots") || data11.captureStreaming === void 0 && (missing1 = "captureStreaming") || data11.businessRules === void 0 && (missing1 = "businessRules") || data11.budgets === void 0 && (missing1 = "budgets") || data11.logTimeMarginSeconds === void 0 && (missing1 = "logTimeMarginSeconds") || data11.correlationSources === void 0 && (missing1 = "correlationSources") || data11.sourceMappings === void 0 && (missing1 = "sourceMappings")) {
                                          validate28.errors = [{ instancePath: instancePath + "/policy", schemaPath: "#/$defs/policy/required", keyword: "required", params: { missingProperty: missing1 }, message: "must have required property '" + missing1 + "'" }];
                                          return false;
                                        } else {
                                          if (data11.policyVersion !== void 0) {
                                            const _errs24 = errors;
                                            if (typeof data11.policyVersion !== "string") {
                                              validate28.errors = [{ instancePath: instancePath + "/policy/policyVersion", schemaPath: "#/$defs/policy/properties/policyVersion/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                              return false;
                                            }
                                            var valid2 = _errs24 === errors;
                                          } else {
                                            var valid2 = true;
                                          }
                                          if (valid2) {
                                            if (data11.pageOrigins !== void 0) {
                                              let data13 = data11.pageOrigins;
                                              const _errs26 = errors;
                                              if (errors === _errs26) {
                                                if (Array.isArray(data13)) {
                                                  var valid3 = true;
                                                  const len0 = data13.length;
                                                  for (let i0 = 0; i0 < len0; i0++) {
                                                    const _errs28 = errors;
                                                    if (typeof data13[i0] !== "string") {
                                                      validate28.errors = [{ instancePath: instancePath + "/policy/pageOrigins/" + i0, schemaPath: "#/$defs/policy/properties/pageOrigins/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                      return false;
                                                    }
                                                    var valid3 = _errs28 === errors;
                                                    if (!valid3) {
                                                      break;
                                                    }
                                                  }
                                                } else {
                                                  validate28.errors = [{ instancePath: instancePath + "/policy/pageOrigins", schemaPath: "#/$defs/policy/properties/pageOrigins/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                  return false;
                                                }
                                              }
                                              var valid2 = _errs26 === errors;
                                            } else {
                                              var valid2 = true;
                                            }
                                            if (valid2) {
                                              if (data11.apiRules !== void 0) {
                                                let data15 = data11.apiRules;
                                                const _errs30 = errors;
                                                if (errors === _errs30) {
                                                  if (Array.isArray(data15)) {
                                                    var valid4 = true;
                                                    const len1 = data15.length;
                                                    for (let i1 = 0; i1 < len1; i1++) {
                                                      let data16 = data15[i1];
                                                      const _errs32 = errors;
                                                      if (errors === _errs32) {
                                                        if (data16 && typeof data16 == "object" && !Array.isArray(data16)) {
                                                          let missing2;
                                                          if (data16.origin === void 0 && (missing2 = "origin") || data16.pathPrefix === void 0 && (missing2 = "pathPrefix")) {
                                                            validate28.errors = [{ instancePath: instancePath + "/policy/apiRules/" + i1, schemaPath: "#/$defs/policy/properties/apiRules/items/required", keyword: "required", params: { missingProperty: missing2 }, message: "must have required property '" + missing2 + "'" }];
                                                            return false;
                                                          } else {
                                                            if (data16.origin !== void 0) {
                                                              const _errs34 = errors;
                                                              if (typeof data16.origin !== "string") {
                                                                validate28.errors = [{ instancePath: instancePath + "/policy/apiRules/" + i1 + "/origin", schemaPath: "#/$defs/policy/properties/apiRules/items/properties/origin/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                return false;
                                                              }
                                                              var valid5 = _errs34 === errors;
                                                            } else {
                                                              var valid5 = true;
                                                            }
                                                            if (valid5) {
                                                              if (data16.pathPrefix !== void 0) {
                                                                const _errs36 = errors;
                                                                if (typeof data16.pathPrefix !== "string") {
                                                                  validate28.errors = [{ instancePath: instancePath + "/policy/apiRules/" + i1 + "/pathPrefix", schemaPath: "#/$defs/policy/properties/apiRules/items/properties/pathPrefix/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                  return false;
                                                                }
                                                                var valid5 = _errs36 === errors;
                                                              } else {
                                                                var valid5 = true;
                                                              }
                                                            }
                                                          }
                                                        } else {
                                                          validate28.errors = [{ instancePath: instancePath + "/policy/apiRules/" + i1, schemaPath: "#/$defs/policy/properties/apiRules/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                          return false;
                                                        }
                                                      }
                                                      var valid4 = _errs32 === errors;
                                                      if (!valid4) {
                                                        break;
                                                      }
                                                    }
                                                  } else {
                                                    validate28.errors = [{ instancePath: instancePath + "/policy/apiRules", schemaPath: "#/$defs/policy/properties/apiRules/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                    return false;
                                                  }
                                                }
                                                var valid2 = _errs30 === errors;
                                              } else {
                                                var valid2 = true;
                                              }
                                              if (valid2) {
                                                if (data11.requestTypes !== void 0) {
                                                  let data19 = data11.requestTypes;
                                                  const _errs38 = errors;
                                                  if (errors === _errs38) {
                                                    if (Array.isArray(data19)) {
                                                      var valid6 = true;
                                                      const len2 = data19.length;
                                                      for (let i2 = 0; i2 < len2; i2++) {
                                                        const _errs40 = errors;
                                                        if (typeof data19[i2] !== "string") {
                                                          validate28.errors = [{ instancePath: instancePath + "/policy/requestTypes/" + i2, schemaPath: "#/$defs/policy/properties/requestTypes/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                          return false;
                                                        }
                                                        var valid6 = _errs40 === errors;
                                                        if (!valid6) {
                                                          break;
                                                        }
                                                      }
                                                    } else {
                                                      validate28.errors = [{ instancePath: instancePath + "/policy/requestTypes", schemaPath: "#/$defs/policy/properties/requestTypes/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                      return false;
                                                    }
                                                  }
                                                  var valid2 = _errs38 === errors;
                                                } else {
                                                  var valid2 = true;
                                                }
                                                if (valid2) {
                                                  if (data11.allowedInputNames !== void 0) {
                                                    let data21 = data11.allowedInputNames;
                                                    const _errs42 = errors;
                                                    if (errors === _errs42) {
                                                      if (Array.isArray(data21)) {
                                                        var valid7 = true;
                                                        const len3 = data21.length;
                                                        for (let i3 = 0; i3 < len3; i3++) {
                                                          const _errs44 = errors;
                                                          if (typeof data21[i3] !== "string") {
                                                            validate28.errors = [{ instancePath: instancePath + "/policy/allowedInputNames/" + i3, schemaPath: "#/$defs/policy/properties/allowedInputNames/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                            return false;
                                                          }
                                                          var valid7 = _errs44 === errors;
                                                          if (!valid7) {
                                                            break;
                                                          }
                                                        }
                                                      } else {
                                                        validate28.errors = [{ instancePath: instancePath + "/policy/allowedInputNames", schemaPath: "#/$defs/policy/properties/allowedInputNames/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                        return false;
                                                      }
                                                    }
                                                    var valid2 = _errs42 === errors;
                                                  } else {
                                                    var valid2 = true;
                                                  }
                                                  if (valid2) {
                                                    if (data11.allowedQueryKeys !== void 0) {
                                                      let data23 = data11.allowedQueryKeys;
                                                      const _errs46 = errors;
                                                      if (errors === _errs46) {
                                                        if (Array.isArray(data23)) {
                                                          var valid8 = true;
                                                          const len4 = data23.length;
                                                          for (let i4 = 0; i4 < len4; i4++) {
                                                            const _errs48 = errors;
                                                            if (typeof data23[i4] !== "string") {
                                                              validate28.errors = [{ instancePath: instancePath + "/policy/allowedQueryKeys/" + i4, schemaPath: "#/$defs/policy/properties/allowedQueryKeys/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                              return false;
                                                            }
                                                            var valid8 = _errs48 === errors;
                                                            if (!valid8) {
                                                              break;
                                                            }
                                                          }
                                                        } else {
                                                          validate28.errors = [{ instancePath: instancePath + "/policy/allowedQueryKeys", schemaPath: "#/$defs/policy/properties/allowedQueryKeys/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                          return false;
                                                        }
                                                      }
                                                      var valid2 = _errs46 === errors;
                                                    } else {
                                                      var valid2 = true;
                                                    }
                                                    if (valid2) {
                                                      if (data11.sensitiveSelectors !== void 0) {
                                                        let data25 = data11.sensitiveSelectors;
                                                        const _errs50 = errors;
                                                        if (errors === _errs50) {
                                                          if (Array.isArray(data25)) {
                                                            var valid9 = true;
                                                            const len5 = data25.length;
                                                            for (let i5 = 0; i5 < len5; i5++) {
                                                              const _errs52 = errors;
                                                              if (typeof data25[i5] !== "string") {
                                                                validate28.errors = [{ instancePath: instancePath + "/policy/sensitiveSelectors/" + i5, schemaPath: "#/$defs/policy/properties/sensitiveSelectors/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                return false;
                                                              }
                                                              var valid9 = _errs52 === errors;
                                                              if (!valid9) {
                                                                break;
                                                              }
                                                            }
                                                          } else {
                                                            validate28.errors = [{ instancePath: instancePath + "/policy/sensitiveSelectors", schemaPath: "#/$defs/policy/properties/sensitiveSelectors/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                            return false;
                                                          }
                                                        }
                                                        var valid2 = _errs50 === errors;
                                                      } else {
                                                        var valid2 = true;
                                                      }
                                                      if (valid2) {
                                                        if (data11.maskAllText !== void 0) {
                                                          const _errs54 = errors;
                                                          if (typeof data11.maskAllText !== "boolean") {
                                                            validate28.errors = [{ instancePath: instancePath + "/policy/maskAllText", schemaPath: "#/$defs/policy/properties/maskAllText/type", keyword: "type", params: { type: "boolean" }, message: "must be boolean" }];
                                                            return false;
                                                          }
                                                          var valid2 = _errs54 === errors;
                                                        } else {
                                                          var valid2 = true;
                                                        }
                                                        if (valid2) {
                                                          if (data11.screenshots !== void 0) {
                                                            const _errs56 = errors;
                                                            if ("disabled" !== data11.screenshots) {
                                                              validate28.errors = [{ instancePath: instancePath + "/policy/screenshots", schemaPath: "#/$defs/policy/properties/screenshots/const", keyword: "const", params: { allowedValue: "disabled" }, message: "must be equal to constant" }];
                                                              return false;
                                                            }
                                                            var valid2 = _errs56 === errors;
                                                          } else {
                                                            var valid2 = true;
                                                          }
                                                          if (valid2) {
                                                            if (data11.captureStreaming !== void 0) {
                                                              const _errs57 = errors;
                                                              if (typeof data11.captureStreaming !== "boolean") {
                                                                validate28.errors = [{ instancePath: instancePath + "/policy/captureStreaming", schemaPath: "#/$defs/policy/properties/captureStreaming/type", keyword: "type", params: { type: "boolean" }, message: "must be boolean" }];
                                                                return false;
                                                              }
                                                              var valid2 = _errs57 === errors;
                                                            } else {
                                                              var valid2 = true;
                                                            }
                                                            if (valid2) {
                                                              if (data11.businessRules !== void 0) {
                                                                let data30 = data11.businessRules;
                                                                const _errs59 = errors;
                                                                if (errors === _errs59) {
                                                                  if (Array.isArray(data30)) {
                                                                    var valid10 = true;
                                                                    const len6 = data30.length;
                                                                    for (let i6 = 0; i6 < len6; i6++) {
                                                                      let data31 = data30[i6];
                                                                      const _errs61 = errors;
                                                                      if (errors === _errs61) {
                                                                        if (data31 && typeof data31 == "object" && !Array.isArray(data31)) {
                                                                          let missing3;
                                                                          if (data31.origin === void 0 && (missing3 = "origin") || data31.pathPrefix === void 0 && (missing3 = "pathPrefix") || data31.codePath === void 0 && (missing3 = "codePath") || data31.successValues === void 0 && (missing3 = "successValues")) {
                                                                            validate28.errors = [{ instancePath: instancePath + "/policy/businessRules/" + i6, schemaPath: "#/$defs/policy/properties/businessRules/items/required", keyword: "required", params: { missingProperty: missing3 }, message: "must have required property '" + missing3 + "'" }];
                                                                            return false;
                                                                          } else {
                                                                            if (data31.origin !== void 0) {
                                                                              const _errs63 = errors;
                                                                              if (typeof data31.origin !== "string") {
                                                                                validate28.errors = [{ instancePath: instancePath + "/policy/businessRules/" + i6 + "/origin", schemaPath: "#/$defs/policy/properties/businessRules/items/properties/origin/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                return false;
                                                                              }
                                                                              var valid11 = _errs63 === errors;
                                                                            } else {
                                                                              var valid11 = true;
                                                                            }
                                                                            if (valid11) {
                                                                              if (data31.pathPrefix !== void 0) {
                                                                                const _errs65 = errors;
                                                                                if (typeof data31.pathPrefix !== "string") {
                                                                                  validate28.errors = [{ instancePath: instancePath + "/policy/businessRules/" + i6 + "/pathPrefix", schemaPath: "#/$defs/policy/properties/businessRules/items/properties/pathPrefix/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                  return false;
                                                                                }
                                                                                var valid11 = _errs65 === errors;
                                                                              } else {
                                                                                var valid11 = true;
                                                                              }
                                                                              if (valid11) {
                                                                                if (data31.codePath !== void 0) {
                                                                                  const _errs67 = errors;
                                                                                  if (typeof data31.codePath !== "string") {
                                                                                    validate28.errors = [{ instancePath: instancePath + "/policy/businessRules/" + i6 + "/codePath", schemaPath: "#/$defs/policy/properties/businessRules/items/properties/codePath/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                    return false;
                                                                                  }
                                                                                  var valid11 = _errs67 === errors;
                                                                                } else {
                                                                                  var valid11 = true;
                                                                                }
                                                                                if (valid11) {
                                                                                  if (data31.successValues !== void 0) {
                                                                                    let data35 = data31.successValues;
                                                                                    const _errs69 = errors;
                                                                                    if (errors === _errs69) {
                                                                                      if (Array.isArray(data35)) {
                                                                                        var valid12 = true;
                                                                                        const len7 = data35.length;
                                                                                        for (let i7 = 0; i7 < len7; i7++) {
                                                                                          let data36 = data35[i7];
                                                                                          const _errs71 = errors;
                                                                                          if (typeof data36 !== "string" && !(typeof data36 == "number")) {
                                                                                            validate28.errors = [{ instancePath: instancePath + "/policy/businessRules/" + i6 + "/successValues/" + i7, schemaPath: "#/$defs/policy/properties/businessRules/items/properties/successValues/items/type", keyword: "type", params: { type: schema33.properties.businessRules.items.properties.successValues.items.type }, message: "must be string,number" }];
                                                                                            return false;
                                                                                          }
                                                                                          var valid12 = _errs71 === errors;
                                                                                          if (!valid12) {
                                                                                            break;
                                                                                          }
                                                                                        }
                                                                                      } else {
                                                                                        validate28.errors = [{ instancePath: instancePath + "/policy/businessRules/" + i6 + "/successValues", schemaPath: "#/$defs/policy/properties/businessRules/items/properties/successValues/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                                                        return false;
                                                                                      }
                                                                                    }
                                                                                    var valid11 = _errs69 === errors;
                                                                                  } else {
                                                                                    var valid11 = true;
                                                                                  }
                                                                                }
                                                                              }
                                                                            }
                                                                          }
                                                                        } else {
                                                                          validate28.errors = [{ instancePath: instancePath + "/policy/businessRules/" + i6, schemaPath: "#/$defs/policy/properties/businessRules/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                          return false;
                                                                        }
                                                                      }
                                                                      var valid10 = _errs61 === errors;
                                                                      if (!valid10) {
                                                                        break;
                                                                      }
                                                                    }
                                                                  } else {
                                                                    validate28.errors = [{ instancePath: instancePath + "/policy/businessRules", schemaPath: "#/$defs/policy/properties/businessRules/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                                    return false;
                                                                  }
                                                                }
                                                                var valid2 = _errs59 === errors;
                                                              } else {
                                                                var valid2 = true;
                                                              }
                                                              if (valid2) {
                                                                if (data11.budgets !== void 0) {
                                                                  let data37 = data11.budgets;
                                                                  const _errs73 = errors;
                                                                  if (errors === _errs73) {
                                                                    if (data37 && typeof data37 == "object" && !Array.isArray(data37)) {
                                                                      let missing4;
                                                                      if (data37.softTabs === void 0 && (missing4 = "softTabs") || data37.hardTabs === void 0 && (missing4 = "hardTabs") || data37.reminderMinutes === void 0 && (missing4 = "reminderMinutes") || data37.ipcBytes === void 0 && (missing4 = "ipcBytes") || data37.baselineBytes === void 0 && (missing4 = "baselineBytes") || data37.bodyBytes === void 0 && (missing4 = "bodyBytes") || data37.softBytes === void 0 && (missing4 = "softBytes") || data37.hardBytes === void 0 && (missing4 = "hardBytes") || data37.queueBytes === void 0 && (missing4 = "queueBytes") || data37.bodyConcurrency === void 0 && (missing4 = "bodyConcurrency")) {
                                                                        validate28.errors = [{ instancePath: instancePath + "/policy/budgets", schemaPath: "#/$defs/policy/properties/budgets/required", keyword: "required", params: { missingProperty: missing4 }, message: "must have required property '" + missing4 + "'" }];
                                                                        return false;
                                                                      } else {
                                                                        if (data37.softTabs !== void 0) {
                                                                          let data38 = data37.softTabs;
                                                                          const _errs75 = errors;
                                                                          if (!(typeof data38 == "number" && (!(data38 % 1) && !isNaN(data38)))) {
                                                                            validate28.errors = [{ instancePath: instancePath + "/policy/budgets/softTabs", schemaPath: "#/$defs/policy/properties/budgets/properties/softTabs/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                            return false;
                                                                          }
                                                                          if (errors === _errs75) {
                                                                            if (typeof data38 == "number") {
                                                                              if (data38 < 1 || isNaN(data38)) {
                                                                                validate28.errors = [{ instancePath: instancePath + "/policy/budgets/softTabs", schemaPath: "#/$defs/policy/properties/budgets/properties/softTabs/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                return false;
                                                                              }
                                                                            }
                                                                          }
                                                                          var valid13 = _errs75 === errors;
                                                                        } else {
                                                                          var valid13 = true;
                                                                        }
                                                                        if (valid13) {
                                                                          if (data37.hardTabs !== void 0) {
                                                                            let data39 = data37.hardTabs;
                                                                            const _errs77 = errors;
                                                                            if (!(typeof data39 == "number" && (!(data39 % 1) && !isNaN(data39)))) {
                                                                              validate28.errors = [{ instancePath: instancePath + "/policy/budgets/hardTabs", schemaPath: "#/$defs/policy/properties/budgets/properties/hardTabs/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                              return false;
                                                                            }
                                                                            if (errors === _errs77) {
                                                                              if (typeof data39 == "number") {
                                                                                if (data39 < 1 || isNaN(data39)) {
                                                                                  validate28.errors = [{ instancePath: instancePath + "/policy/budgets/hardTabs", schemaPath: "#/$defs/policy/properties/budgets/properties/hardTabs/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                  return false;
                                                                                }
                                                                              }
                                                                            }
                                                                            var valid13 = _errs77 === errors;
                                                                          } else {
                                                                            var valid13 = true;
                                                                          }
                                                                          if (valid13) {
                                                                            if (data37.reminderMinutes !== void 0) {
                                                                              let data40 = data37.reminderMinutes;
                                                                              const _errs79 = errors;
                                                                              if (!(typeof data40 == "number" && (!(data40 % 1) && !isNaN(data40)))) {
                                                                                validate28.errors = [{ instancePath: instancePath + "/policy/budgets/reminderMinutes", schemaPath: "#/$defs/policy/properties/budgets/properties/reminderMinutes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                return false;
                                                                              }
                                                                              if (errors === _errs79) {
                                                                                if (typeof data40 == "number") {
                                                                                  if (data40 < 1 || isNaN(data40)) {
                                                                                    validate28.errors = [{ instancePath: instancePath + "/policy/budgets/reminderMinutes", schemaPath: "#/$defs/policy/properties/budgets/properties/reminderMinutes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                    return false;
                                                                                  }
                                                                                }
                                                                              }
                                                                              var valid13 = _errs79 === errors;
                                                                            } else {
                                                                              var valid13 = true;
                                                                            }
                                                                            if (valid13) {
                                                                              if (data37.ipcBytes !== void 0) {
                                                                                let data41 = data37.ipcBytes;
                                                                                const _errs81 = errors;
                                                                                if (!(typeof data41 == "number" && (!(data41 % 1) && !isNaN(data41)))) {
                                                                                  validate28.errors = [{ instancePath: instancePath + "/policy/budgets/ipcBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/ipcBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                  return false;
                                                                                }
                                                                                if (errors === _errs81) {
                                                                                  if (typeof data41 == "number") {
                                                                                    if (data41 < 1 || isNaN(data41)) {
                                                                                      validate28.errors = [{ instancePath: instancePath + "/policy/budgets/ipcBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/ipcBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                      return false;
                                                                                    }
                                                                                  }
                                                                                }
                                                                                var valid13 = _errs81 === errors;
                                                                              } else {
                                                                                var valid13 = true;
                                                                              }
                                                                              if (valid13) {
                                                                                if (data37.baselineBytes !== void 0) {
                                                                                  let data42 = data37.baselineBytes;
                                                                                  const _errs83 = errors;
                                                                                  if (!(typeof data42 == "number" && (!(data42 % 1) && !isNaN(data42)))) {
                                                                                    validate28.errors = [{ instancePath: instancePath + "/policy/budgets/baselineBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/baselineBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                    return false;
                                                                                  }
                                                                                  if (errors === _errs83) {
                                                                                    if (typeof data42 == "number") {
                                                                                      if (data42 < 1 || isNaN(data42)) {
                                                                                        validate28.errors = [{ instancePath: instancePath + "/policy/budgets/baselineBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/baselineBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                        return false;
                                                                                      }
                                                                                    }
                                                                                  }
                                                                                  var valid13 = _errs83 === errors;
                                                                                } else {
                                                                                  var valid13 = true;
                                                                                }
                                                                                if (valid13) {
                                                                                  if (data37.bodyBytes !== void 0) {
                                                                                    let data43 = data37.bodyBytes;
                                                                                    const _errs85 = errors;
                                                                                    if (!(typeof data43 == "number" && (!(data43 % 1) && !isNaN(data43)))) {
                                                                                      validate28.errors = [{ instancePath: instancePath + "/policy/budgets/bodyBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/bodyBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                      return false;
                                                                                    }
                                                                                    if (errors === _errs85) {
                                                                                      if (typeof data43 == "number") {
                                                                                        if (data43 < 1 || isNaN(data43)) {
                                                                                          validate28.errors = [{ instancePath: instancePath + "/policy/budgets/bodyBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/bodyBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                          return false;
                                                                                        }
                                                                                      }
                                                                                    }
                                                                                    var valid13 = _errs85 === errors;
                                                                                  } else {
                                                                                    var valid13 = true;
                                                                                  }
                                                                                  if (valid13) {
                                                                                    if (data37.softBytes !== void 0) {
                                                                                      let data44 = data37.softBytes;
                                                                                      const _errs87 = errors;
                                                                                      if (!(typeof data44 == "number" && (!(data44 % 1) && !isNaN(data44)))) {
                                                                                        validate28.errors = [{ instancePath: instancePath + "/policy/budgets/softBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/softBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                        return false;
                                                                                      }
                                                                                      if (errors === _errs87) {
                                                                                        if (typeof data44 == "number") {
                                                                                          if (data44 < 1 || isNaN(data44)) {
                                                                                            validate28.errors = [{ instancePath: instancePath + "/policy/budgets/softBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/softBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                            return false;
                                                                                          }
                                                                                        }
                                                                                      }
                                                                                      var valid13 = _errs87 === errors;
                                                                                    } else {
                                                                                      var valid13 = true;
                                                                                    }
                                                                                    if (valid13) {
                                                                                      if (data37.hardBytes !== void 0) {
                                                                                        let data45 = data37.hardBytes;
                                                                                        const _errs89 = errors;
                                                                                        if (!(typeof data45 == "number" && (!(data45 % 1) && !isNaN(data45)))) {
                                                                                          validate28.errors = [{ instancePath: instancePath + "/policy/budgets/hardBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/hardBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                          return false;
                                                                                        }
                                                                                        if (errors === _errs89) {
                                                                                          if (typeof data45 == "number") {
                                                                                            if (data45 < 1 || isNaN(data45)) {
                                                                                              validate28.errors = [{ instancePath: instancePath + "/policy/budgets/hardBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/hardBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                              return false;
                                                                                            }
                                                                                          }
                                                                                        }
                                                                                        var valid13 = _errs89 === errors;
                                                                                      } else {
                                                                                        var valid13 = true;
                                                                                      }
                                                                                      if (valid13) {
                                                                                        if (data37.queueBytes !== void 0) {
                                                                                          let data46 = data37.queueBytes;
                                                                                          const _errs91 = errors;
                                                                                          if (!(typeof data46 == "number" && (!(data46 % 1) && !isNaN(data46)))) {
                                                                                            validate28.errors = [{ instancePath: instancePath + "/policy/budgets/queueBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/queueBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                            return false;
                                                                                          }
                                                                                          if (errors === _errs91) {
                                                                                            if (typeof data46 == "number") {
                                                                                              if (data46 < 1 || isNaN(data46)) {
                                                                                                validate28.errors = [{ instancePath: instancePath + "/policy/budgets/queueBytes", schemaPath: "#/$defs/policy/properties/budgets/properties/queueBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                                return false;
                                                                                              }
                                                                                            }
                                                                                          }
                                                                                          var valid13 = _errs91 === errors;
                                                                                        } else {
                                                                                          var valid13 = true;
                                                                                        }
                                                                                        if (valid13) {
                                                                                          if (data37.bodyConcurrency !== void 0) {
                                                                                            let data47 = data37.bodyConcurrency;
                                                                                            const _errs93 = errors;
                                                                                            if (!(typeof data47 == "number" && (!(data47 % 1) && !isNaN(data47)))) {
                                                                                              validate28.errors = [{ instancePath: instancePath + "/policy/budgets/bodyConcurrency", schemaPath: "#/$defs/policy/properties/budgets/properties/bodyConcurrency/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                              return false;
                                                                                            }
                                                                                            if (errors === _errs93) {
                                                                                              if (typeof data47 == "number") {
                                                                                                if (data47 < 1 || isNaN(data47)) {
                                                                                                  validate28.errors = [{ instancePath: instancePath + "/policy/budgets/bodyConcurrency", schemaPath: "#/$defs/policy/properties/budgets/properties/bodyConcurrency/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                                                                  return false;
                                                                                                }
                                                                                              }
                                                                                            }
                                                                                            var valid13 = _errs93 === errors;
                                                                                          } else {
                                                                                            var valid13 = true;
                                                                                          }
                                                                                        }
                                                                                      }
                                                                                    }
                                                                                  }
                                                                                }
                                                                              }
                                                                            }
                                                                          }
                                                                        }
                                                                      }
                                                                    } else {
                                                                      validate28.errors = [{ instancePath: instancePath + "/policy/budgets", schemaPath: "#/$defs/policy/properties/budgets/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                      return false;
                                                                    }
                                                                  }
                                                                  var valid2 = _errs73 === errors;
                                                                } else {
                                                                  var valid2 = true;
                                                                }
                                                                if (valid2) {
                                                                  if (data11.logTimeMarginSeconds !== void 0) {
                                                                    let data48 = data11.logTimeMarginSeconds;
                                                                    const _errs95 = errors;
                                                                    if (!(typeof data48 == "number" && (!(data48 % 1) && !isNaN(data48)))) {
                                                                      validate28.errors = [{ instancePath: instancePath + "/policy/logTimeMarginSeconds", schemaPath: "#/$defs/policy/properties/logTimeMarginSeconds/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                      return false;
                                                                    }
                                                                    if (errors === _errs95) {
                                                                      if (typeof data48 == "number") {
                                                                        if (data48 < 0 || isNaN(data48)) {
                                                                          validate28.errors = [{ instancePath: instancePath + "/policy/logTimeMarginSeconds", schemaPath: "#/$defs/policy/properties/logTimeMarginSeconds/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                                          return false;
                                                                        }
                                                                      }
                                                                    }
                                                                    var valid2 = _errs95 === errors;
                                                                  } else {
                                                                    var valid2 = true;
                                                                  }
                                                                  if (valid2) {
                                                                    if (data11.correlationSources !== void 0) {
                                                                      let data49 = data11.correlationSources;
                                                                      const _errs97 = errors;
                                                                      if (errors === _errs97) {
                                                                        if (Array.isArray(data49)) {
                                                                          if (data49.length > 32) {
                                                                            validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources", schemaPath: "#/$defs/policy/properties/correlationSources/maxItems", keyword: "maxItems", params: { limit: 32 }, message: "must NOT have more than 32 items" }];
                                                                            return false;
                                                                          } else {
                                                                            var valid14 = true;
                                                                            const len8 = data49.length;
                                                                            for (let i8 = 0; i8 < len8; i8++) {
                                                                              let data50 = data49[i8];
                                                                              const _errs99 = errors;
                                                                              const _errs101 = errors;
                                                                              const _errs102 = errors;
                                                                              let valid16 = true;
                                                                              const _errs103 = errors;
                                                                              if (data50 && typeof data50 == "object" && !Array.isArray(data50)) {
                                                                                if (data50.source !== void 0) {
                                                                                  if ("response_header" !== data50.source) {
                                                                                    const err0 = {};
                                                                                    if (vErrors === null) {
                                                                                      vErrors = [err0];
                                                                                    } else {
                                                                                      vErrors.push(err0);
                                                                                    }
                                                                                    errors++;
                                                                                  }
                                                                                }
                                                                              }
                                                                              var _valid0 = _errs103 === errors;
                                                                              errors = _errs102;
                                                                              if (vErrors !== null) {
                                                                                if (_errs102) {
                                                                                  vErrors.length = _errs102;
                                                                                } else {
                                                                                  vErrors = null;
                                                                                }
                                                                              }
                                                                              if (_valid0) {
                                                                                const _errs105 = errors;
                                                                                if (data50 && typeof data50 == "object" && !Array.isArray(data50)) {
                                                                                  if (data50.key !== void 0) {
                                                                                    let data52 = data50.key;
                                                                                    if (typeof data52 === "string") {
                                                                                      if (!pattern4.test(data52)) {
                                                                                        validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/key", schemaPath: "#/$defs/policy/properties/correlationSources/items/allOf/0/then/properties/key/pattern", keyword: "pattern", params: { pattern: "^[a-zA-Z0-9-]{1,80}$" }, message: 'must match pattern "^[a-zA-Z0-9-]{1,80}$"' }];
                                                                                        return false;
                                                                                      }
                                                                                    }
                                                                                  }
                                                                                }
                                                                                var _valid0 = _errs105 === errors;
                                                                                valid16 = _valid0;
                                                                                if (valid16) {
                                                                                  var props0 = {};
                                                                                  props0.key = true;
                                                                                  props0.source = true;
                                                                                }
                                                                              }
                                                                              if (!valid16) {
                                                                                const err1 = { instancePath: instancePath + "/policy/correlationSources/" + i8, schemaPath: "#/$defs/policy/properties/correlationSources/items/allOf/0/if", keyword: "if", params: { failingKeyword: "then" }, message: 'must match "then" schema' };
                                                                                if (vErrors === null) {
                                                                                  vErrors = [err1];
                                                                                } else {
                                                                                  vErrors.push(err1);
                                                                                }
                                                                                errors++;
                                                                                validate28.errors = vErrors;
                                                                                return false;
                                                                              }
                                                                              var valid15 = _errs101 === errors;
                                                                              if (valid15) {
                                                                                const _errs107 = errors;
                                                                                const _errs108 = errors;
                                                                                let valid19 = true;
                                                                                const _errs109 = errors;
                                                                                if (data50 && typeof data50 == "object" && !Array.isArray(data50)) {
                                                                                  if (data50.source !== void 0) {
                                                                                    if ("response_json" !== data50.source) {
                                                                                      const err2 = {};
                                                                                      if (vErrors === null) {
                                                                                        vErrors = [err2];
                                                                                      } else {
                                                                                        vErrors.push(err2);
                                                                                      }
                                                                                      errors++;
                                                                                    }
                                                                                  }
                                                                                }
                                                                                var _valid1 = _errs109 === errors;
                                                                                errors = _errs108;
                                                                                if (vErrors !== null) {
                                                                                  if (_errs108) {
                                                                                    vErrors.length = _errs108;
                                                                                  } else {
                                                                                    vErrors = null;
                                                                                  }
                                                                                }
                                                                                if (_valid1) {
                                                                                  const _errs111 = errors;
                                                                                  if (data50 && typeof data50 == "object" && !Array.isArray(data50)) {
                                                                                    if (data50.key !== void 0) {
                                                                                      let data54 = data50.key;
                                                                                      if (typeof data54 === "string") {
                                                                                        if (!pattern5.test(data54)) {
                                                                                          validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/key", schemaPath: "#/$defs/policy/properties/correlationSources/items/allOf/1/then/properties/key/pattern", keyword: "pattern", params: { pattern: "^(\\/([^~]|~[01])*)+$" }, message: 'must match pattern "^(\\/([^~]|~[01])*)+$"' }];
                                                                                          return false;
                                                                                        }
                                                                                      }
                                                                                    }
                                                                                  }
                                                                                  var _valid1 = _errs111 === errors;
                                                                                  valid19 = _valid1;
                                                                                  if (valid19) {
                                                                                    var props1 = {};
                                                                                    props1.key = true;
                                                                                    props1.source = true;
                                                                                  }
                                                                                }
                                                                                if (!valid19) {
                                                                                  const err3 = { instancePath: instancePath + "/policy/correlationSources/" + i8, schemaPath: "#/$defs/policy/properties/correlationSources/items/allOf/1/if", keyword: "if", params: { failingKeyword: "then" }, message: 'must match "then" schema' };
                                                                                  if (vErrors === null) {
                                                                                    vErrors = [err3];
                                                                                  } else {
                                                                                    vErrors.push(err3);
                                                                                  }
                                                                                  errors++;
                                                                                  validate28.errors = vErrors;
                                                                                  return false;
                                                                                }
                                                                                var valid15 = _errs107 === errors;
                                                                                if (valid15) {
                                                                                  if (props0 !== true && props1 !== void 0) {
                                                                                    if (props1 === true) {
                                                                                      props0 = true;
                                                                                    } else {
                                                                                      props0 = props0 || {};
                                                                                      Object.assign(props0, props1);
                                                                                    }
                                                                                  }
                                                                                  const _errs113 = errors;
                                                                                  const _errs114 = errors;
                                                                                  let valid22 = true;
                                                                                  const _errs115 = errors;
                                                                                  if (data50 && typeof data50 == "object" && !Array.isArray(data50)) {
                                                                                    if (data50.source !== void 0) {
                                                                                      if ("page_meta" !== data50.source) {
                                                                                        const err4 = {};
                                                                                        if (vErrors === null) {
                                                                                          vErrors = [err4];
                                                                                        } else {
                                                                                          vErrors.push(err4);
                                                                                        }
                                                                                        errors++;
                                                                                      }
                                                                                    }
                                                                                  }
                                                                                  var _valid2 = _errs115 === errors;
                                                                                  errors = _errs114;
                                                                                  if (vErrors !== null) {
                                                                                    if (_errs114) {
                                                                                      vErrors.length = _errs114;
                                                                                    } else {
                                                                                      vErrors = null;
                                                                                    }
                                                                                  }
                                                                                  if (_valid2) {
                                                                                    const _errs117 = errors;
                                                                                    if (data50 && typeof data50 == "object" && !Array.isArray(data50)) {
                                                                                      if (data50.key !== void 0) {
                                                                                        let data56 = data50.key;
                                                                                        if (typeof data56 === "string") {
                                                                                          if (!pattern6.test(data56)) {
                                                                                            validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/key", schemaPath: "#/$defs/policy/properties/correlationSources/items/allOf/2/then/properties/key/pattern", keyword: "pattern", params: { pattern: `^meta\\[name=(?:"[a-zA-Z0-9_.-]+"|'[a-zA-Z0-9_.-]+')\\]$` }, message: `must match pattern "^meta\\[name=(?:"[a-zA-Z0-9_.-]+"|'[a-zA-Z0-9_.-]+')\\]$"` }];
                                                                                            return false;
                                                                                          }
                                                                                        }
                                                                                      }
                                                                                    }
                                                                                    var _valid2 = _errs117 === errors;
                                                                                    valid22 = _valid2;
                                                                                    if (valid22) {
                                                                                      var props2 = {};
                                                                                      props2.key = true;
                                                                                      props2.source = true;
                                                                                    }
                                                                                  }
                                                                                  if (!valid22) {
                                                                                    const err5 = { instancePath: instancePath + "/policy/correlationSources/" + i8, schemaPath: "#/$defs/policy/properties/correlationSources/items/allOf/2/if", keyword: "if", params: { failingKeyword: "then" }, message: 'must match "then" schema' };
                                                                                    if (vErrors === null) {
                                                                                      vErrors = [err5];
                                                                                    } else {
                                                                                      vErrors.push(err5);
                                                                                    }
                                                                                    errors++;
                                                                                    validate28.errors = vErrors;
                                                                                    return false;
                                                                                  }
                                                                                  var valid15 = _errs113 === errors;
                                                                                  if (valid15) {
                                                                                    if (props0 !== true && props2 !== void 0) {
                                                                                      if (props2 === true) {
                                                                                        props0 = true;
                                                                                      } else {
                                                                                        props0 = props0 || {};
                                                                                        Object.assign(props0, props2);
                                                                                      }
                                                                                    }
                                                                                  }
                                                                                }
                                                                              }
                                                                              if (errors === _errs99) {
                                                                                if (data50 && typeof data50 == "object" && !Array.isArray(data50)) {
                                                                                  let missing5;
                                                                                  if (data50.field === void 0 && (missing5 = "field") || data50.source === void 0 && (missing5 = "source") || data50.key === void 0 && (missing5 = "key") || data50.component === void 0 && (missing5 = "component")) {
                                                                                    validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8, schemaPath: "#/$defs/policy/properties/correlationSources/items/required", keyword: "required", params: { missingProperty: missing5 }, message: "must have required property '" + missing5 + "'" }];
                                                                                    return false;
                                                                                  } else {
                                                                                    if (props0 !== true) {
                                                                                      props0 = props0 || {};
                                                                                      props0.field = true;
                                                                                      props0.source = true;
                                                                                      props0.key = true;
                                                                                      props0.component = true;
                                                                                      props0.origin = true;
                                                                                      props0.pathPrefix = true;
                                                                                    }
                                                                                    if (data50.field !== void 0) {
                                                                                      let data57 = data50.field;
                                                                                      const _errs119 = errors;
                                                                                      if (!(data57 === "frontendBuildId" || data57 === "backendBuildId" || data57 === "serviceInstance" || data57 === "requestId" || data57 === "traceId" || data57 === "spanId")) {
                                                                                        validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/field", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/field/enum", keyword: "enum", params: { allowedValues: schema33.properties.correlationSources.items.properties.field.enum }, message: "must be equal to one of the allowed values" }];
                                                                                        return false;
                                                                                      }
                                                                                      var valid25 = _errs119 === errors;
                                                                                    } else {
                                                                                      var valid25 = true;
                                                                                    }
                                                                                    if (valid25) {
                                                                                      if (data50.source !== void 0) {
                                                                                        let data58 = data50.source;
                                                                                        const _errs120 = errors;
                                                                                        if (!(data58 === "response_header" || data58 === "response_json" || data58 === "page_meta")) {
                                                                                          validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/source", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/source/enum", keyword: "enum", params: { allowedValues: schema33.properties.correlationSources.items.properties.source.enum }, message: "must be equal to one of the allowed values" }];
                                                                                          return false;
                                                                                        }
                                                                                        var valid25 = _errs120 === errors;
                                                                                      } else {
                                                                                        var valid25 = true;
                                                                                      }
                                                                                      if (valid25) {
                                                                                        if (data50.key !== void 0) {
                                                                                          let data59 = data50.key;
                                                                                          const _errs121 = errors;
                                                                                          if (errors === _errs121) {
                                                                                            if (typeof data59 === "string") {
                                                                                              if (func1(data59) > 200) {
                                                                                                validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/key", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/key/maxLength", keyword: "maxLength", params: { limit: 200 }, message: "must NOT have more than 200 characters" }];
                                                                                                return false;
                                                                                              } else {
                                                                                                if (func1(data59) < 1) {
                                                                                                  validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/key", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/key/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                  return false;
                                                                                                }
                                                                                              }
                                                                                            } else {
                                                                                              validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/key", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/key/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                              return false;
                                                                                            }
                                                                                          }
                                                                                          var valid25 = _errs121 === errors;
                                                                                        } else {
                                                                                          var valid25 = true;
                                                                                        }
                                                                                        if (valid25) {
                                                                                          if (data50.component !== void 0) {
                                                                                            let data60 = data50.component;
                                                                                            const _errs123 = errors;
                                                                                            if (errors === _errs123) {
                                                                                              if (typeof data60 === "string") {
                                                                                                if (func1(data60) > 80) {
                                                                                                  validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/component", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/component/maxLength", keyword: "maxLength", params: { limit: 80 }, message: "must NOT have more than 80 characters" }];
                                                                                                  return false;
                                                                                                } else {
                                                                                                  if (func1(data60) < 1) {
                                                                                                    validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/component", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/component/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                    return false;
                                                                                                  }
                                                                                                }
                                                                                              } else {
                                                                                                validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/component", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/component/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                                return false;
                                                                                              }
                                                                                            }
                                                                                            var valid25 = _errs123 === errors;
                                                                                          } else {
                                                                                            var valid25 = true;
                                                                                          }
                                                                                          if (valid25) {
                                                                                            if (data50.origin !== void 0) {
                                                                                              let data61 = data50.origin;
                                                                                              const _errs125 = errors;
                                                                                              if (errors === _errs125) {
                                                                                                if (typeof data61 === "string") {
                                                                                                  if (func1(data61) < 1) {
                                                                                                    validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/origin", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/origin/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                    return false;
                                                                                                  } else {
                                                                                                    if (!pattern7.test(data61)) {
                                                                                                      validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/origin", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/origin/pattern", keyword: "pattern", params: { pattern: "^https?://[^/?#]+$" }, message: 'must match pattern "^https?://[^/?#]+$"' }];
                                                                                                      return false;
                                                                                                    }
                                                                                                  }
                                                                                                } else {
                                                                                                  validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/origin", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/origin/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                                  return false;
                                                                                                }
                                                                                              }
                                                                                              var valid25 = _errs125 === errors;
                                                                                            } else {
                                                                                              var valid25 = true;
                                                                                            }
                                                                                            if (valid25) {
                                                                                              if (data50.pathPrefix !== void 0) {
                                                                                                let data62 = data50.pathPrefix;
                                                                                                const _errs127 = errors;
                                                                                                if (errors === _errs127) {
                                                                                                  if (typeof data62 === "string") {
                                                                                                    if (func1(data62) > 499) {
                                                                                                      validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/pathPrefix", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/pathPrefix/maxLength", keyword: "maxLength", params: { limit: 499 }, message: "must NOT have more than 499 characters" }];
                                                                                                      return false;
                                                                                                    } else {
                                                                                                      if (func1(data62) < 1) {
                                                                                                        validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/pathPrefix", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/pathPrefix/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                        return false;
                                                                                                      } else {
                                                                                                        if (!pattern8.test(data62)) {
                                                                                                          validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/pathPrefix", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/pathPrefix/pattern", keyword: "pattern", params: { pattern: "^/" }, message: 'must match pattern "^/"' }];
                                                                                                          return false;
                                                                                                        }
                                                                                                      }
                                                                                                    }
                                                                                                  } else {
                                                                                                    validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8 + "/pathPrefix", schemaPath: "#/$defs/policy/properties/correlationSources/items/properties/pathPrefix/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                                    return false;
                                                                                                  }
                                                                                                }
                                                                                                var valid25 = _errs127 === errors;
                                                                                              } else {
                                                                                                var valid25 = true;
                                                                                              }
                                                                                            }
                                                                                          }
                                                                                        }
                                                                                      }
                                                                                    }
                                                                                  }
                                                                                } else {
                                                                                  validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources/" + i8, schemaPath: "#/$defs/policy/properties/correlationSources/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                                  return false;
                                                                                }
                                                                              }
                                                                              var valid14 = _errs99 === errors;
                                                                              if (!valid14) {
                                                                                break;
                                                                              }
                                                                            }
                                                                          }
                                                                        } else {
                                                                          validate28.errors = [{ instancePath: instancePath + "/policy/correlationSources", schemaPath: "#/$defs/policy/properties/correlationSources/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                                          return false;
                                                                        }
                                                                      }
                                                                      var valid2 = _errs97 === errors;
                                                                    } else {
                                                                      var valid2 = true;
                                                                    }
                                                                    if (valid2) {
                                                                      if (data11.sourceMappings !== void 0) {
                                                                        let data63 = data11.sourceMappings;
                                                                        const _errs129 = errors;
                                                                        if (errors === _errs129) {
                                                                          if (Array.isArray(data63)) {
                                                                            if (data63.length > 100) {
                                                                              validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings", schemaPath: "#/$defs/policy/properties/sourceMappings/maxItems", keyword: "maxItems", params: { limit: 100 }, message: "must NOT have more than 100 items" }];
                                                                              return false;
                                                                            } else {
                                                                              var valid26 = true;
                                                                              const len9 = data63.length;
                                                                              for (let i9 = 0; i9 < len9; i9++) {
                                                                                let data64 = data63[i9];
                                                                                const _errs131 = errors;
                                                                                if (errors === _errs131) {
                                                                                  if (data64 && typeof data64 == "object" && !Array.isArray(data64)) {
                                                                                    let missing6;
                                                                                    if (data64.environmentId === void 0 && (missing6 = "environmentId") || data64.component === void 0 && (missing6 = "component") || data64.buildId === void 0 && (missing6 = "buildId") || data64.codeSnapshot === void 0 && (missing6 = "codeSnapshot")) {
                                                                                      validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9, schemaPath: "#/$defs/policy/properties/sourceMappings/items/required", keyword: "required", params: { missingProperty: missing6 }, message: "must have required property '" + missing6 + "'" }];
                                                                                      return false;
                                                                                    } else {
                                                                                      if (data64.environmentId !== void 0) {
                                                                                        let data65 = data64.environmentId;
                                                                                        const _errs133 = errors;
                                                                                        if (errors === _errs133) {
                                                                                          if (typeof data65 === "string") {
                                                                                            if (func1(data65) > 500) {
                                                                                              validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/environmentId", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/environmentId/maxLength", keyword: "maxLength", params: { limit: 500 }, message: "must NOT have more than 500 characters" }];
                                                                                              return false;
                                                                                            } else {
                                                                                              if (func1(data65) < 1) {
                                                                                                validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/environmentId", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/environmentId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                return false;
                                                                                              }
                                                                                            }
                                                                                          } else {
                                                                                            validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/environmentId", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/environmentId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                            return false;
                                                                                          }
                                                                                        }
                                                                                        var valid27 = _errs133 === errors;
                                                                                      } else {
                                                                                        var valid27 = true;
                                                                                      }
                                                                                      if (valid27) {
                                                                                        if (data64.component !== void 0) {
                                                                                          let data66 = data64.component;
                                                                                          const _errs135 = errors;
                                                                                          if (errors === _errs135) {
                                                                                            if (typeof data66 === "string") {
                                                                                              if (func1(data66) > 500) {
                                                                                                validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/component", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/component/maxLength", keyword: "maxLength", params: { limit: 500 }, message: "must NOT have more than 500 characters" }];
                                                                                                return false;
                                                                                              } else {
                                                                                                if (func1(data66) < 1) {
                                                                                                  validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/component", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/component/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                  return false;
                                                                                                }
                                                                                              }
                                                                                            } else {
                                                                                              validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/component", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/component/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                              return false;
                                                                                            }
                                                                                          }
                                                                                          var valid27 = _errs135 === errors;
                                                                                        } else {
                                                                                          var valid27 = true;
                                                                                        }
                                                                                        if (valid27) {
                                                                                          if (data64.buildId !== void 0) {
                                                                                            let data67 = data64.buildId;
                                                                                            const _errs137 = errors;
                                                                                            if (errors === _errs137) {
                                                                                              if (typeof data67 === "string") {
                                                                                                if (func1(data67) > 500) {
                                                                                                  validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/buildId", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/buildId/maxLength", keyword: "maxLength", params: { limit: 500 }, message: "must NOT have more than 500 characters" }];
                                                                                                  return false;
                                                                                                } else {
                                                                                                  if (func1(data67) < 1) {
                                                                                                    validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/buildId", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/buildId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                    return false;
                                                                                                  }
                                                                                                }
                                                                                              } else {
                                                                                                validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/buildId", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/buildId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                                return false;
                                                                                              }
                                                                                            }
                                                                                            var valid27 = _errs137 === errors;
                                                                                          } else {
                                                                                            var valid27 = true;
                                                                                          }
                                                                                          if (valid27) {
                                                                                            if (data64.codeSnapshot !== void 0) {
                                                                                              let data68 = data64.codeSnapshot;
                                                                                              const _errs139 = errors;
                                                                                              if (errors === _errs139) {
                                                                                                if (typeof data68 === "string") {
                                                                                                  if (func1(data68) > 500) {
                                                                                                    validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/codeSnapshot", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/codeSnapshot/maxLength", keyword: "maxLength", params: { limit: 500 }, message: "must NOT have more than 500 characters" }];
                                                                                                    return false;
                                                                                                  } else {
                                                                                                    if (func1(data68) < 1) {
                                                                                                      validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/codeSnapshot", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/codeSnapshot/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                                      return false;
                                                                                                    }
                                                                                                  }
                                                                                                } else {
                                                                                                  validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9 + "/codeSnapshot", schemaPath: "#/$defs/policy/properties/sourceMappings/items/properties/codeSnapshot/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                                  return false;
                                                                                                }
                                                                                              }
                                                                                              var valid27 = _errs139 === errors;
                                                                                            } else {
                                                                                              var valid27 = true;
                                                                                            }
                                                                                          }
                                                                                        }
                                                                                      }
                                                                                    }
                                                                                  } else {
                                                                                    validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings/" + i9, schemaPath: "#/$defs/policy/properties/sourceMappings/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                                    return false;
                                                                                  }
                                                                                }
                                                                                var valid26 = _errs131 === errors;
                                                                                if (!valid26) {
                                                                                  break;
                                                                                }
                                                                              }
                                                                            }
                                                                          } else {
                                                                            validate28.errors = [{ instancePath: instancePath + "/policy/sourceMappings", schemaPath: "#/$defs/policy/properties/sourceMappings/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                                            return false;
                                                                          }
                                                                        }
                                                                        var valid2 = _errs129 === errors;
                                                                      } else {
                                                                        var valid2 = true;
                                                                      }
                                                                    }
                                                                  }
                                                                }
                                                              }
                                                            }
                                                          }
                                                        }
                                                      }
                                                    }
                                                  }
                                                }
                                              }
                                            }
                                          }
                                        }
                                      } else {
                                        validate28.errors = [{ instancePath: instancePath + "/policy", schemaPath: "#/$defs/policy/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                        return false;
                                      }
                                    }
                                    var valid0 = _errs21 === errors;
                                  } else {
                                    var valid0 = true;
                                  }
                                  if (valid0) {
                                    if (data.gaps !== void 0) {
                                      let data69 = data.gaps;
                                      const _errs141 = errors;
                                      if (errors === _errs141) {
                                        if (Array.isArray(data69)) {
                                          var valid28 = true;
                                          const len10 = data69.length;
                                          for (let i10 = 0; i10 < len10; i10++) {
                                            let data70 = data69[i10];
                                            const _errs143 = errors;
                                            const _errs144 = errors;
                                            if (errors === _errs144) {
                                              if (data70 && typeof data70 == "object" && !Array.isArray(data70)) {
                                                let missing7;
                                                if (data70.id === void 0 && (missing7 = "id") || data70.code === void 0 && (missing7 = "code") || data70.observedAt === void 0 && (missing7 = "observedAt") || data70.detail === void 0 && (missing7 = "detail")) {
                                                  validate28.errors = [{ instancePath: instancePath + "/gaps/" + i10, schemaPath: "#/$defs/gap/required", keyword: "required", params: { missingProperty: missing7 }, message: "must have required property '" + missing7 + "'" }];
                                                  return false;
                                                } else {
                                                  if (data70.id !== void 0) {
                                                    let data71 = data70.id;
                                                    const _errs146 = errors;
                                                    if (errors === _errs146) {
                                                      if (typeof data71 === "string") {
                                                        if (func1(data71) > 256) {
                                                          validate28.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/id", schemaPath: "#/$defs/gap/properties/id/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                                          return false;
                                                        } else {
                                                          if (func1(data71) < 1) {
                                                            validate28.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/id", schemaPath: "#/$defs/gap/properties/id/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                            return false;
                                                          }
                                                        }
                                                      } else {
                                                        validate28.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/id", schemaPath: "#/$defs/gap/properties/id/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                        return false;
                                                      }
                                                    }
                                                    var valid30 = _errs146 === errors;
                                                  } else {
                                                    var valid30 = true;
                                                  }
                                                  if (valid30) {
                                                    if (data70.code !== void 0) {
                                                      const _errs148 = errors;
                                                      if (typeof data70.code !== "string") {
                                                        validate28.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/code", schemaPath: "#/$defs/gap/properties/code/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                        return false;
                                                      }
                                                      var valid30 = _errs148 === errors;
                                                    } else {
                                                      var valid30 = true;
                                                    }
                                                    if (valid30) {
                                                      if (data70.observedAt !== void 0) {
                                                        const _errs150 = errors;
                                                        if (typeof data70.observedAt !== "string") {
                                                          validate28.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/observedAt", schemaPath: "#/$defs/gap/properties/observedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                          return false;
                                                        }
                                                        var valid30 = _errs150 === errors;
                                                      } else {
                                                        var valid30 = true;
                                                      }
                                                      if (valid30) {
                                                        if (data70.detail !== void 0) {
                                                          const _errs152 = errors;
                                                          if (typeof data70.detail !== "string") {
                                                            validate28.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/detail", schemaPath: "#/$defs/gap/properties/detail/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                            return false;
                                                          }
                                                          var valid30 = _errs152 === errors;
                                                        } else {
                                                          var valid30 = true;
                                                        }
                                                        if (valid30) {
                                                          if (data70.tabInstanceId !== void 0) {
                                                            const _errs154 = errors;
                                                            if (typeof data70.tabInstanceId !== "string") {
                                                              validate28.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/tabInstanceId", schemaPath: "#/$defs/gap/properties/tabInstanceId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                              return false;
                                                            }
                                                            var valid30 = _errs154 === errors;
                                                          } else {
                                                            var valid30 = true;
                                                          }
                                                          if (valid30) {
                                                            if (data70.channel !== void 0) {
                                                              let data76 = data70.channel;
                                                              const _errs156 = errors;
                                                              if (!(data76 === "page" || data76 === "semantic" || data76 === "network" || data76 === "runtime" || data76 === "screenshot")) {
                                                                validate28.errors = [{ instancePath: instancePath + "/gaps/" + i10 + "/channel", schemaPath: "#/$defs/gap/properties/channel/enum", keyword: "enum", params: { allowedValues: schema34.properties.channel.enum }, message: "must be equal to one of the allowed values" }];
                                                                return false;
                                                              }
                                                              var valid30 = _errs156 === errors;
                                                            } else {
                                                              var valid30 = true;
                                                            }
                                                          }
                                                        }
                                                      }
                                                    }
                                                  }
                                                }
                                              } else {
                                                validate28.errors = [{ instancePath: instancePath + "/gaps/" + i10, schemaPath: "#/$defs/gap/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                return false;
                                              }
                                            }
                                            var valid28 = _errs143 === errors;
                                            if (!valid28) {
                                              break;
                                            }
                                          }
                                        } else {
                                          validate28.errors = [{ instancePath: instancePath + "/gaps", schemaPath: "#/properties/gaps/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                          return false;
                                        }
                                      }
                                      var valid0 = _errs141 === errors;
                                    } else {
                                      var valid0 = true;
                                    }
                                    if (valid0) {
                                      if (data.rootTabInstanceIds !== void 0) {
                                        let data77 = data.rootTabInstanceIds;
                                        const _errs157 = errors;
                                        if (errors === _errs157) {
                                          if (Array.isArray(data77)) {
                                            var valid31 = true;
                                            const len11 = data77.length;
                                            for (let i11 = 0; i11 < len11; i11++) {
                                              let data78 = data77[i11];
                                              const _errs159 = errors;
                                              if (errors === _errs159) {
                                                if (typeof data78 === "string") {
                                                  if (func1(data78) > 256) {
                                                    validate28.errors = [{ instancePath: instancePath + "/rootTabInstanceIds/" + i11, schemaPath: "#/properties/rootTabInstanceIds/items/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                                    return false;
                                                  } else {
                                                    if (func1(data78) < 1) {
                                                      validate28.errors = [{ instancePath: instancePath + "/rootTabInstanceIds/" + i11, schemaPath: "#/properties/rootTabInstanceIds/items/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                      return false;
                                                    }
                                                  }
                                                } else {
                                                  validate28.errors = [{ instancePath: instancePath + "/rootTabInstanceIds/" + i11, schemaPath: "#/properties/rootTabInstanceIds/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                  return false;
                                                }
                                              }
                                              var valid31 = _errs159 === errors;
                                              if (!valid31) {
                                                break;
                                              }
                                            }
                                          } else {
                                            validate28.errors = [{ instancePath: instancePath + "/rootTabInstanceIds", schemaPath: "#/properties/rootTabInstanceIds/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                            return false;
                                          }
                                        }
                                        var valid0 = _errs157 === errors;
                                      } else {
                                        var valid0 = true;
                                      }
                                      if (valid0) {
                                        if (data.commands !== void 0) {
                                          let data79 = data.commands;
                                          const _errs161 = errors;
                                          if (errors === _errs161) {
                                            if (Array.isArray(data79)) {
                                              var valid32 = true;
                                              const len12 = data79.length;
                                              for (let i12 = 0; i12 < len12; i12++) {
                                                let data80 = data79[i12];
                                                const _errs163 = errors;
                                                if (errors === _errs163) {
                                                  if (typeof data80 === "string") {
                                                    if (func1(data80) > 256) {
                                                      validate28.errors = [{ instancePath: instancePath + "/commands/" + i12, schemaPath: "#/properties/commands/items/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                                      return false;
                                                    } else {
                                                      if (func1(data80) < 1) {
                                                        validate28.errors = [{ instancePath: instancePath + "/commands/" + i12, schemaPath: "#/properties/commands/items/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                        return false;
                                                      }
                                                    }
                                                  } else {
                                                    validate28.errors = [{ instancePath: instancePath + "/commands/" + i12, schemaPath: "#/properties/commands/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                    return false;
                                                  }
                                                }
                                                var valid32 = _errs163 === errors;
                                                if (!valid32) {
                                                  break;
                                                }
                                              }
                                            } else {
                                              validate28.errors = [{ instancePath: instancePath + "/commands", schemaPath: "#/properties/commands/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                              return false;
                                            }
                                          }
                                          var valid0 = _errs161 === errors;
                                        } else {
                                          var valid0 = true;
                                        }
                                        if (valid0) {
                                          if (data.bytesAccepted !== void 0) {
                                            let data81 = data.bytesAccepted;
                                            const _errs165 = errors;
                                            if (!(typeof data81 == "number" && (!(data81 % 1) && !isNaN(data81)))) {
                                              validate28.errors = [{ instancePath: instancePath + "/bytesAccepted", schemaPath: "#/properties/bytesAccepted/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                              return false;
                                            }
                                            if (errors === _errs165) {
                                              if (typeof data81 == "number") {
                                                if (data81 < 0 || isNaN(data81)) {
                                                  validate28.errors = [{ instancePath: instancePath + "/bytesAccepted", schemaPath: "#/properties/bytesAccepted/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                  return false;
                                                }
                                              }
                                            }
                                            var valid0 = _errs165 === errors;
                                          } else {
                                            var valid0 = true;
                                          }
                                          if (valid0) {
                                            if (data.bytesPersisted !== void 0) {
                                              let data82 = data.bytesPersisted;
                                              const _errs167 = errors;
                                              if (!(typeof data82 == "number" && (!(data82 % 1) && !isNaN(data82)))) {
                                                validate28.errors = [{ instancePath: instancePath + "/bytesPersisted", schemaPath: "#/properties/bytesPersisted/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                return false;
                                              }
                                              if (errors === _errs167) {
                                                if (typeof data82 == "number") {
                                                  if (data82 < 0 || isNaN(data82)) {
                                                    validate28.errors = [{ instancePath: instancePath + "/bytesPersisted", schemaPath: "#/properties/bytesPersisted/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                    return false;
                                                  }
                                                }
                                              }
                                              var valid0 = _errs167 === errors;
                                            } else {
                                              var valid0 = true;
                                            }
                                            if (valid0) {
                                              if (data.eventsPersisted !== void 0) {
                                                let data83 = data.eventsPersisted;
                                                const _errs169 = errors;
                                                if (!(typeof data83 == "number" && (!(data83 % 1) && !isNaN(data83)))) {
                                                  validate28.errors = [{ instancePath: instancePath + "/eventsPersisted", schemaPath: "#/properties/eventsPersisted/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                  return false;
                                                }
                                                if (errors === _errs169) {
                                                  if (typeof data83 == "number") {
                                                    if (data83 < 0 || isNaN(data83)) {
                                                      validate28.errors = [{ instancePath: instancePath + "/eventsPersisted", schemaPath: "#/properties/eventsPersisted/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                      return false;
                                                    }
                                                  }
                                                }
                                                var valid0 = _errs169 === errors;
                                              } else {
                                                var valid0 = true;
                                              }
                                              if (valid0) {
                                                if (data.checkpoint !== void 0) {
                                                  let data84 = data.checkpoint;
                                                  const _errs171 = errors;
                                                  if (!(typeof data84 == "number" && (!(data84 % 1) && !isNaN(data84)))) {
                                                    validate28.errors = [{ instancePath: instancePath + "/checkpoint", schemaPath: "#/properties/checkpoint/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                    return false;
                                                  }
                                                  if (errors === _errs171) {
                                                    if (typeof data84 == "number") {
                                                      if (data84 < 0 || isNaN(data84)) {
                                                        validate28.errors = [{ instancePath: instancePath + "/checkpoint", schemaPath: "#/properties/checkpoint/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                        return false;
                                                      }
                                                    }
                                                  }
                                                  var valid0 = _errs171 === errors;
                                                } else {
                                                  var valid0 = true;
                                                }
                                                if (valid0) {
                                                  if (data.saveState !== void 0) {
                                                    let data85 = data.saveState;
                                                    const _errs173 = errors;
                                                    if (!(data85 === "saved" || data85 === "pending" || data85 === "error")) {
                                                      validate28.errors = [{ instancePath: instancePath + "/saveState", schemaPath: "#/properties/saveState/enum", keyword: "enum", params: { allowedValues: schema32.properties.saveState.enum }, message: "must be equal to one of the allowed values" }];
                                                      return false;
                                                    }
                                                    var valid0 = _errs173 === errors;
                                                  } else {
                                                    var valid0 = true;
                                                  }
                                                  if (valid0) {
                                                    if (data.saveError !== void 0) {
                                                      const _errs174 = errors;
                                                      if (typeof data.saveError !== "string") {
                                                        validate28.errors = [{ instancePath: instancePath + "/saveError", schemaPath: "#/properties/saveError/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                        return false;
                                                      }
                                                      var valid0 = _errs174 === errors;
                                                    } else {
                                                      var valid0 = true;
                                                    }
                                                    if (valid0) {
                                                      if (data.versions !== void 0) {
                                                        let data87 = data.versions;
                                                        const _errs176 = errors;
                                                        if (errors === _errs176) {
                                                          if (data87 && typeof data87 == "object" && !Array.isArray(data87)) {
                                                            let missing8;
                                                            if (data87.frontendBuildId === void 0 && (missing8 = "frontendBuildId") || data87.backendBuildId === void 0 && (missing8 = "backendBuildId") || data87.serviceInstance === void 0 && (missing8 = "serviceInstance") || data87.codeSnapshotMatch === void 0 && (missing8 = "codeSnapshotMatch") || data87.sources === void 0 && (missing8 = "sources")) {
                                                              validate28.errors = [{ instancePath: instancePath + "/versions", schemaPath: "#/properties/versions/required", keyword: "required", params: { missingProperty: missing8 }, message: "must have required property '" + missing8 + "'" }];
                                                              return false;
                                                            } else {
                                                              if (data87.frontendBuildId !== void 0) {
                                                                const _errs178 = errors;
                                                                if (typeof data87.frontendBuildId !== "string") {
                                                                  validate28.errors = [{ instancePath: instancePath + "/versions/frontendBuildId", schemaPath: "#/properties/versions/properties/frontendBuildId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                  return false;
                                                                }
                                                                var valid33 = _errs178 === errors;
                                                              } else {
                                                                var valid33 = true;
                                                              }
                                                              if (valid33) {
                                                                if (data87.backendBuildId !== void 0) {
                                                                  const _errs180 = errors;
                                                                  if (typeof data87.backendBuildId !== "string") {
                                                                    validate28.errors = [{ instancePath: instancePath + "/versions/backendBuildId", schemaPath: "#/properties/versions/properties/backendBuildId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                    return false;
                                                                  }
                                                                  var valid33 = _errs180 === errors;
                                                                } else {
                                                                  var valid33 = true;
                                                                }
                                                                if (valid33) {
                                                                  if (data87.serviceInstance !== void 0) {
                                                                    const _errs182 = errors;
                                                                    if (typeof data87.serviceInstance !== "string") {
                                                                      validate28.errors = [{ instancePath: instancePath + "/versions/serviceInstance", schemaPath: "#/properties/versions/properties/serviceInstance/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                      return false;
                                                                    }
                                                                    var valid33 = _errs182 === errors;
                                                                  } else {
                                                                    var valid33 = true;
                                                                  }
                                                                  if (valid33) {
                                                                    if (data87.codeSnapshotMatch !== void 0) {
                                                                      const _errs184 = errors;
                                                                      if (typeof data87.codeSnapshotMatch !== "string") {
                                                                        validate28.errors = [{ instancePath: instancePath + "/versions/codeSnapshotMatch", schemaPath: "#/properties/versions/properties/codeSnapshotMatch/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                        return false;
                                                                      }
                                                                      var valid33 = _errs184 === errors;
                                                                    } else {
                                                                      var valid33 = true;
                                                                    }
                                                                    if (valid33) {
                                                                      if (data87.sources !== void 0) {
                                                                        let data92 = data87.sources;
                                                                        const _errs186 = errors;
                                                                        if (errors === _errs186) {
                                                                          if (data92 && typeof data92 == "object" && !Array.isArray(data92)) {
                                                                            for (const key0 in data92) {
                                                                              const _errs189 = errors;
                                                                              if (typeof data92[key0] !== "string") {
                                                                                validate28.errors = [{ instancePath: instancePath + "/versions/sources/" + key0.replace(/~/g, "~0").replace(/\//g, "~1"), schemaPath: "#/properties/versions/properties/sources/additionalProperties/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                return false;
                                                                              }
                                                                              var valid34 = _errs189 === errors;
                                                                              if (!valid34) {
                                                                                break;
                                                                              }
                                                                            }
                                                                          } else {
                                                                            validate28.errors = [{ instancePath: instancePath + "/versions/sources", schemaPath: "#/properties/versions/properties/sources/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                            return false;
                                                                          }
                                                                        }
                                                                        var valid33 = _errs186 === errors;
                                                                      } else {
                                                                        var valid33 = true;
                                                                      }
                                                                    }
                                                                  }
                                                                }
                                                              }
                                                            }
                                                          } else {
                                                            validate28.errors = [{ instancePath: instancePath + "/versions", schemaPath: "#/properties/versions/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                            return false;
                                                          }
                                                        }
                                                        var valid0 = _errs176 === errors;
                                                      } else {
                                                        var valid0 = true;
                                                      }
                                                      if (valid0) {
                                                        if (data.capabilities !== void 0) {
                                                          let data94 = data.capabilities;
                                                          const _errs191 = errors;
                                                          if (!(data94 && typeof data94 == "object" && !Array.isArray(data94))) {
                                                            validate28.errors = [{ instancePath: instancePath + "/capabilities", schemaPath: "#/properties/capabilities/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                            return false;
                                                          }
                                                          var valid0 = _errs191 === errors;
                                                        } else {
                                                          var valid0 = true;
                                                        }
                                                        if (valid0) {
                                                          if (data.stopReason !== void 0) {
                                                            const _errs193 = errors;
                                                            if (typeof data.stopReason !== "string") {
                                                              validate28.errors = [{ instancePath: instancePath + "/stopReason", schemaPath: "#/properties/stopReason/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                              return false;
                                                            }
                                                            var valid0 = _errs193 === errors;
                                                          } else {
                                                            var valid0 = true;
                                                          }
                                                          if (valid0) {
                                                            if (data.stopProgress !== void 0) {
                                                              let data96 = data.stopProgress;
                                                              const _errs195 = errors;
                                                              if (errors === _errs195) {
                                                                if (data96 && typeof data96 == "object" && !Array.isArray(data96)) {
                                                                  let missing9;
                                                                  if (data96.startedAt === void 0 && (missing9 = "startedAt") || data96.cutoff === void 0 && (missing9 = "cutoff") || data96.marker === void 0 && (missing9 = "marker") || data96.cleanup === void 0 && (missing9 = "cleanup") || data96.drain === void 0 && (missing9 = "drain") || data96.terminal === void 0 && (missing9 = "terminal") || data96.deadlineExceeded === void 0 && (missing9 = "deadlineExceeded")) {
                                                                    validate28.errors = [{ instancePath: instancePath + "/stopProgress", schemaPath: "#/properties/stopProgress/required", keyword: "required", params: { missingProperty: missing9 }, message: "must have required property '" + missing9 + "'" }];
                                                                    return false;
                                                                  } else {
                                                                    if (data96.startedAt !== void 0) {
                                                                      const _errs197 = errors;
                                                                      if (typeof data96.startedAt !== "string") {
                                                                        validate28.errors = [{ instancePath: instancePath + "/stopProgress/startedAt", schemaPath: "#/properties/stopProgress/properties/startedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                        return false;
                                                                      }
                                                                      var valid35 = _errs197 === errors;
                                                                    } else {
                                                                      var valid35 = true;
                                                                    }
                                                                    if (valid35) {
                                                                      if (data96.cutoff !== void 0) {
                                                                        const _errs199 = errors;
                                                                        if ("complete" !== data96.cutoff) {
                                                                          validate28.errors = [{ instancePath: instancePath + "/stopProgress/cutoff", schemaPath: "#/properties/stopProgress/properties/cutoff/const", keyword: "const", params: { allowedValue: "complete" }, message: "must be equal to constant" }];
                                                                          return false;
                                                                        }
                                                                        var valid35 = _errs199 === errors;
                                                                      } else {
                                                                        var valid35 = true;
                                                                      }
                                                                      if (valid35) {
                                                                        if (data96.marker !== void 0) {
                                                                          let data99 = data96.marker;
                                                                          const _errs200 = errors;
                                                                          if (!(data99 === "pending" || data99 === "complete" || data99 === "error")) {
                                                                            validate28.errors = [{ instancePath: instancePath + "/stopProgress/marker", schemaPath: "#/properties/stopProgress/properties/marker/enum", keyword: "enum", params: { allowedValues: schema32.properties.stopProgress.properties.marker.enum }, message: "must be equal to one of the allowed values" }];
                                                                            return false;
                                                                          }
                                                                          var valid35 = _errs200 === errors;
                                                                        } else {
                                                                          var valid35 = true;
                                                                        }
                                                                        if (valid35) {
                                                                          if (data96.cleanup !== void 0) {
                                                                            let data100 = data96.cleanup;
                                                                            const _errs201 = errors;
                                                                            if (!(data100 === "pending" || data100 === "complete" || data100 === "error")) {
                                                                              validate28.errors = [{ instancePath: instancePath + "/stopProgress/cleanup", schemaPath: "#/properties/stopProgress/properties/cleanup/enum", keyword: "enum", params: { allowedValues: schema32.properties.stopProgress.properties.cleanup.enum }, message: "must be equal to one of the allowed values" }];
                                                                              return false;
                                                                            }
                                                                            var valid35 = _errs201 === errors;
                                                                          } else {
                                                                            var valid35 = true;
                                                                          }
                                                                          if (valid35) {
                                                                            if (data96.drain !== void 0) {
                                                                              let data101 = data96.drain;
                                                                              const _errs202 = errors;
                                                                              if (!(data101 === "pending" || data101 === "complete" || data101 === "error")) {
                                                                                validate28.errors = [{ instancePath: instancePath + "/stopProgress/drain", schemaPath: "#/properties/stopProgress/properties/drain/enum", keyword: "enum", params: { allowedValues: schema32.properties.stopProgress.properties.drain.enum }, message: "must be equal to one of the allowed values" }];
                                                                                return false;
                                                                              }
                                                                              var valid35 = _errs202 === errors;
                                                                            } else {
                                                                              var valid35 = true;
                                                                            }
                                                                            if (valid35) {
                                                                              if (data96.terminal !== void 0) {
                                                                                let data102 = data96.terminal;
                                                                                const _errs203 = errors;
                                                                                if (!(data102 === "pending" || data102 === "complete" || data102 === "error")) {
                                                                                  validate28.errors = [{ instancePath: instancePath + "/stopProgress/terminal", schemaPath: "#/properties/stopProgress/properties/terminal/enum", keyword: "enum", params: { allowedValues: schema32.properties.stopProgress.properties.terminal.enum }, message: "must be equal to one of the allowed values" }];
                                                                                  return false;
                                                                                }
                                                                                var valid35 = _errs203 === errors;
                                                                              } else {
                                                                                var valid35 = true;
                                                                              }
                                                                              if (valid35) {
                                                                                if (data96.deadlineExceeded !== void 0) {
                                                                                  const _errs204 = errors;
                                                                                  if (typeof data96.deadlineExceeded !== "boolean") {
                                                                                    validate28.errors = [{ instancePath: instancePath + "/stopProgress/deadlineExceeded", schemaPath: "#/properties/stopProgress/properties/deadlineExceeded/type", keyword: "type", params: { type: "boolean" }, message: "must be boolean" }];
                                                                                    return false;
                                                                                  }
                                                                                  var valid35 = _errs204 === errors;
                                                                                } else {
                                                                                  var valid35 = true;
                                                                                }
                                                                              }
                                                                            }
                                                                          }
                                                                        }
                                                                      }
                                                                    }
                                                                  }
                                                                } else {
                                                                  validate28.errors = [{ instancePath: instancePath + "/stopProgress", schemaPath: "#/properties/stopProgress/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                  return false;
                                                                }
                                                              }
                                                              var valid0 = _errs195 === errors;
                                                            } else {
                                                              var valid0 = true;
                                                            }
                                                            if (valid0) {
                                                              if (data.rootEnvironments !== void 0) {
                                                                let data104 = data.rootEnvironments;
                                                                const _errs206 = errors;
                                                                if (errors === _errs206) {
                                                                  if (data104 && typeof data104 == "object" && !Array.isArray(data104)) {
                                                                    for (const key1 in data104) {
                                                                      const _errs209 = errors;
                                                                      if (typeof data104[key1] !== "string") {
                                                                        validate28.errors = [{ instancePath: instancePath + "/rootEnvironments/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"), schemaPath: "#/properties/rootEnvironments/additionalProperties/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                        return false;
                                                                      }
                                                                      var valid36 = _errs209 === errors;
                                                                      if (!valid36) {
                                                                        break;
                                                                      }
                                                                    }
                                                                  } else {
                                                                    validate28.errors = [{ instancePath: instancePath + "/rootEnvironments", schemaPath: "#/properties/rootEnvironments/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                    return false;
                                                                  }
                                                                }
                                                                var valid0 = _errs206 === errors;
                                                              } else {
                                                                var valid0 = true;
                                                              }
                                                            }
                                                          }
                                                        }
                                                      }
                                                    }
                                                  }
                                                }
                                              }
                                            }
                                          }
                                        }
                                      }
                                    }
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        } else {
          validate28.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate28.errors = vErrors;
      return errors === 0;
    }
    validate28.evaluated = { "props": { "schemaVersion": true, "recordingId": true, "browserRunId": true, "state": true, "scopeVersion": true, "environmentId": true, "browserVersion": true, "extensionVersion": true, "rrwebVersion": true, "startedAt": true, "stoppedAt": true, "policy": true, "gaps": true, "rootTabInstanceIds": true, "commands": true, "bytesAccepted": true, "bytesPersisted": true, "eventsPersisted": true, "checkpoint": true, "saveState": true, "saveError": true, "versions": true, "capabilities": true, "stopReason": true, "stopProgress": true, "rootEnvironments": true }, "dynamicProps": false, "dynamicItems": false };
    exports.channel = validate29;
    var schema46 = { "type": "object", "required": ["state", "generation"], "properties": { "state": { "enum": ["PENDING", "ACTIVE", "BLOCKED", "LOST", "STOPPED"] }, "generation": { "type": "integer", "minimum": 0 }, "readyAt": { "type": "string" }, "stoppedAt": { "type": "string" }, "reason": { "type": "string" } } };
    function validate29(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate29.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.state === void 0 && (missing0 = "state") || data.generation === void 0 && (missing0 = "generation")) {
            validate29.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.state !== void 0) {
              let data0 = data.state;
              const _errs1 = errors;
              if (!(data0 === "PENDING" || data0 === "ACTIVE" || data0 === "BLOCKED" || data0 === "LOST" || data0 === "STOPPED")) {
                validate29.errors = [{ instancePath: instancePath + "/state", schemaPath: "#/properties/state/enum", keyword: "enum", params: { allowedValues: schema46.properties.state.enum }, message: "must be equal to one of the allowed values" }];
                return false;
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.generation !== void 0) {
                let data1 = data.generation;
                const _errs2 = errors;
                if (!(typeof data1 == "number" && (!(data1 % 1) && !isNaN(data1)))) {
                  validate29.errors = [{ instancePath: instancePath + "/generation", schemaPath: "#/properties/generation/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                  return false;
                }
                if (errors === _errs2) {
                  if (typeof data1 == "number") {
                    if (data1 < 0 || isNaN(data1)) {
                      validate29.errors = [{ instancePath: instancePath + "/generation", schemaPath: "#/properties/generation/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                      return false;
                    }
                  }
                }
                var valid0 = _errs2 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.readyAt !== void 0) {
                  const _errs4 = errors;
                  if (typeof data.readyAt !== "string") {
                    validate29.errors = [{ instancePath: instancePath + "/readyAt", schemaPath: "#/properties/readyAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                    return false;
                  }
                  var valid0 = _errs4 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.stoppedAt !== void 0) {
                    const _errs6 = errors;
                    if (typeof data.stoppedAt !== "string") {
                      validate29.errors = [{ instancePath: instancePath + "/stoppedAt", schemaPath: "#/properties/stoppedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                      return false;
                    }
                    var valid0 = _errs6 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.reason !== void 0) {
                      const _errs8 = errors;
                      if (typeof data.reason !== "string") {
                        validate29.errors = [{ instancePath: instancePath + "/reason", schemaPath: "#/properties/reason/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                        return false;
                      }
                      var valid0 = _errs8 === errors;
                    } else {
                      var valid0 = true;
                    }
                  }
                }
              }
            }
          }
        } else {
          validate29.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate29.errors = vErrors;
      return errors === 0;
    }
    validate29.evaluated = { "props": { "state": true, "generation": true, "readyAt": true, "stoppedAt": true, "reason": true }, "dynamicProps": false, "dynamicItems": false };
    exports.baseline = validate30;
    function validate30(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate30.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.eventId === void 0 && (missing0 = "eventId") || data.recorderStreamId === void 0 && (missing0 = "recorderStreamId") || data.nodeId === void 0 && (missing0 = "nodeId")) {
            validate30.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.eventId !== void 0) {
              let data0 = data.eventId;
              const _errs1 = errors;
              if (errors === _errs1) {
                if (typeof data0 === "string") {
                  if (func1(data0) > 256) {
                    validate30.errors = [{ instancePath: instancePath + "/eventId", schemaPath: "#/properties/eventId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                    return false;
                  } else {
                    if (func1(data0) < 1) {
                      validate30.errors = [{ instancePath: instancePath + "/eventId", schemaPath: "#/properties/eventId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                      return false;
                    }
                  }
                } else {
                  validate30.errors = [{ instancePath: instancePath + "/eventId", schemaPath: "#/properties/eventId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                  return false;
                }
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.recorderStreamId !== void 0) {
                let data1 = data.recorderStreamId;
                const _errs3 = errors;
                if (errors === _errs3) {
                  if (typeof data1 === "string") {
                    if (func1(data1) > 256) {
                      validate30.errors = [{ instancePath: instancePath + "/recorderStreamId", schemaPath: "#/properties/recorderStreamId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                      return false;
                    } else {
                      if (func1(data1) < 1) {
                        validate30.errors = [{ instancePath: instancePath + "/recorderStreamId", schemaPath: "#/properties/recorderStreamId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                        return false;
                      }
                    }
                  } else {
                    validate30.errors = [{ instancePath: instancePath + "/recorderStreamId", schemaPath: "#/properties/recorderStreamId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                    return false;
                  }
                }
                var valid0 = _errs3 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.nodeId !== void 0) {
                  let data2 = data.nodeId;
                  const _errs5 = errors;
                  if (!(typeof data2 == "number" && (!(data2 % 1) && !isNaN(data2)))) {
                    validate30.errors = [{ instancePath: instancePath + "/nodeId", schemaPath: "#/properties/nodeId/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                    return false;
                  }
                  if (errors === _errs5) {
                    if (typeof data2 == "number") {
                      if (data2 < 0 || isNaN(data2)) {
                        validate30.errors = [{ instancePath: instancePath + "/nodeId", schemaPath: "#/properties/nodeId/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                        return false;
                      }
                    }
                  }
                  var valid0 = _errs5 === errors;
                } else {
                  var valid0 = true;
                }
              }
            }
          }
        } else {
          validate30.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate30.errors = vErrors;
      return errors === 0;
    }
    validate30.evaluated = { "props": { "eventId": true, "recorderStreamId": true, "nodeId": true }, "dynamicProps": false, "dynamicItems": false };
    exports.document = validate31;
    function validate31(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate31.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.documentId === void 0 && (missing0 = "documentId") || data.chromeFrameId === void 0 && (missing0 = "chromeFrameId") || data.parentFrameId === void 0 && (missing0 = "parentFrameId") || data.url === void 0 && (missing0 = "url") || data.observedAt === void 0 && (missing0 = "observedAt") || data.status === void 0 && (missing0 = "status") || data.subjectMapping === void 0 && (missing0 = "subjectMapping")) {
            validate31.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.documentId !== void 0) {
              let data0 = data.documentId;
              const _errs1 = errors;
              if (errors === _errs1) {
                if (typeof data0 === "string") {
                  if (func1(data0) > 256) {
                    validate31.errors = [{ instancePath: instancePath + "/documentId", schemaPath: "#/properties/documentId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                    return false;
                  } else {
                    if (func1(data0) < 1) {
                      validate31.errors = [{ instancePath: instancePath + "/documentId", schemaPath: "#/properties/documentId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                      return false;
                    }
                  }
                } else {
                  validate31.errors = [{ instancePath: instancePath + "/documentId", schemaPath: "#/properties/documentId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                  return false;
                }
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.chromeFrameId !== void 0) {
                let data1 = data.chromeFrameId;
                const _errs3 = errors;
                if (!(typeof data1 == "number" && (!(data1 % 1) && !isNaN(data1)))) {
                  validate31.errors = [{ instancePath: instancePath + "/chromeFrameId", schemaPath: "#/properties/chromeFrameId/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                  return false;
                }
                if (errors === _errs3) {
                  if (typeof data1 == "number") {
                    if (data1 < 0 || isNaN(data1)) {
                      validate31.errors = [{ instancePath: instancePath + "/chromeFrameId", schemaPath: "#/properties/chromeFrameId/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                      return false;
                    }
                  }
                }
                var valid0 = _errs3 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.parentFrameId !== void 0) {
                  let data2 = data.parentFrameId;
                  const _errs5 = errors;
                  if (!(typeof data2 == "number" && (!(data2 % 1) && !isNaN(data2)))) {
                    validate31.errors = [{ instancePath: instancePath + "/parentFrameId", schemaPath: "#/properties/parentFrameId/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                    return false;
                  }
                  var valid0 = _errs5 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.url !== void 0) {
                    const _errs7 = errors;
                    if (typeof data.url !== "string") {
                      validate31.errors = [{ instancePath: instancePath + "/url", schemaPath: "#/properties/url/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                      return false;
                    }
                    var valid0 = _errs7 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.observedAt !== void 0) {
                      const _errs9 = errors;
                      if (typeof data.observedAt !== "string") {
                        validate31.errors = [{ instancePath: instancePath + "/observedAt", schemaPath: "#/properties/observedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                        return false;
                      }
                      var valid0 = _errs9 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.recorderStreamId !== void 0) {
                        let data5 = data.recorderStreamId;
                        const _errs11 = errors;
                        if (errors === _errs11) {
                          if (typeof data5 === "string") {
                            if (func1(data5) > 256) {
                              validate31.errors = [{ instancePath: instancePath + "/recorderStreamId", schemaPath: "#/properties/recorderStreamId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                              return false;
                            } else {
                              if (func1(data5) < 1) {
                                validate31.errors = [{ instancePath: instancePath + "/recorderStreamId", schemaPath: "#/properties/recorderStreamId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                return false;
                              }
                            }
                          } else {
                            validate31.errors = [{ instancePath: instancePath + "/recorderStreamId", schemaPath: "#/properties/recorderStreamId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                            return false;
                          }
                        }
                        var valid0 = _errs11 === errors;
                      } else {
                        var valid0 = true;
                      }
                      if (valid0) {
                        if (data.recorderStartedAt !== void 0) {
                          const _errs13 = errors;
                          if (typeof data.recorderStartedAt !== "string") {
                            validate31.errors = [{ instancePath: instancePath + "/recorderStartedAt", schemaPath: "#/properties/recorderStartedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                            return false;
                          }
                          var valid0 = _errs13 === errors;
                        } else {
                          var valid0 = true;
                        }
                        if (valid0) {
                          if (data.firstBaselineAt !== void 0) {
                            const _errs15 = errors;
                            if (typeof data.firstBaselineAt !== "string") {
                              validate31.errors = [{ instancePath: instancePath + "/firstBaselineAt", schemaPath: "#/properties/firstBaselineAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                              return false;
                            }
                            var valid0 = _errs15 === errors;
                          } else {
                            var valid0 = true;
                          }
                          if (valid0) {
                            if (data.status !== void 0) {
                              const _errs17 = errors;
                              if (typeof data.status !== "string") {
                                validate31.errors = [{ instancePath: instancePath + "/status", schemaPath: "#/properties/status/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                return false;
                              }
                              var valid0 = _errs17 === errors;
                            } else {
                              var valid0 = true;
                            }
                            if (valid0) {
                              if (data.subjectMapping !== void 0) {
                                const _errs19 = errors;
                                if (typeof data.subjectMapping !== "string") {
                                  validate31.errors = [{ instancePath: instancePath + "/subjectMapping", schemaPath: "#/properties/subjectMapping/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                  return false;
                                }
                                var valid0 = _errs19 === errors;
                              } else {
                                var valid0 = true;
                              }
                              if (valid0) {
                                if (data.endedAt !== void 0) {
                                  const _errs21 = errors;
                                  if (typeof data.endedAt !== "string") {
                                    validate31.errors = [{ instancePath: instancePath + "/endedAt", schemaPath: "#/properties/endedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                    return false;
                                  }
                                  var valid0 = _errs21 === errors;
                                } else {
                                  var valid0 = true;
                                }
                                if (valid0) {
                                  if (data.baselineRef !== void 0) {
                                    let data11 = data.baselineRef;
                                    const _errs23 = errors;
                                    const _errs24 = errors;
                                    if (errors === _errs24) {
                                      if (data11 && typeof data11 == "object" && !Array.isArray(data11)) {
                                        let missing1;
                                        if (data11.eventId === void 0 && (missing1 = "eventId") || data11.recorderStreamId === void 0 && (missing1 = "recorderStreamId") || data11.nodeId === void 0 && (missing1 = "nodeId")) {
                                          validate31.errors = [{ instancePath: instancePath + "/baselineRef", schemaPath: "#/$defs/baseline/required", keyword: "required", params: { missingProperty: missing1 }, message: "must have required property '" + missing1 + "'" }];
                                          return false;
                                        } else {
                                          if (data11.eventId !== void 0) {
                                            let data12 = data11.eventId;
                                            const _errs26 = errors;
                                            if (errors === _errs26) {
                                              if (typeof data12 === "string") {
                                                if (func1(data12) > 256) {
                                                  validate31.errors = [{ instancePath: instancePath + "/baselineRef/eventId", schemaPath: "#/$defs/baseline/properties/eventId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                                  return false;
                                                } else {
                                                  if (func1(data12) < 1) {
                                                    validate31.errors = [{ instancePath: instancePath + "/baselineRef/eventId", schemaPath: "#/$defs/baseline/properties/eventId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                    return false;
                                                  }
                                                }
                                              } else {
                                                validate31.errors = [{ instancePath: instancePath + "/baselineRef/eventId", schemaPath: "#/$defs/baseline/properties/eventId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                return false;
                                              }
                                            }
                                            var valid2 = _errs26 === errors;
                                          } else {
                                            var valid2 = true;
                                          }
                                          if (valid2) {
                                            if (data11.recorderStreamId !== void 0) {
                                              let data13 = data11.recorderStreamId;
                                              const _errs28 = errors;
                                              if (errors === _errs28) {
                                                if (typeof data13 === "string") {
                                                  if (func1(data13) > 256) {
                                                    validate31.errors = [{ instancePath: instancePath + "/baselineRef/recorderStreamId", schemaPath: "#/$defs/baseline/properties/recorderStreamId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                                    return false;
                                                  } else {
                                                    if (func1(data13) < 1) {
                                                      validate31.errors = [{ instancePath: instancePath + "/baselineRef/recorderStreamId", schemaPath: "#/$defs/baseline/properties/recorderStreamId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                      return false;
                                                    }
                                                  }
                                                } else {
                                                  validate31.errors = [{ instancePath: instancePath + "/baselineRef/recorderStreamId", schemaPath: "#/$defs/baseline/properties/recorderStreamId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                  return false;
                                                }
                                              }
                                              var valid2 = _errs28 === errors;
                                            } else {
                                              var valid2 = true;
                                            }
                                            if (valid2) {
                                              if (data11.nodeId !== void 0) {
                                                let data14 = data11.nodeId;
                                                const _errs30 = errors;
                                                if (!(typeof data14 == "number" && (!(data14 % 1) && !isNaN(data14)))) {
                                                  validate31.errors = [{ instancePath: instancePath + "/baselineRef/nodeId", schemaPath: "#/$defs/baseline/properties/nodeId/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                  return false;
                                                }
                                                if (errors === _errs30) {
                                                  if (typeof data14 == "number") {
                                                    if (data14 < 0 || isNaN(data14)) {
                                                      validate31.errors = [{ instancePath: instancePath + "/baselineRef/nodeId", schemaPath: "#/$defs/baseline/properties/nodeId/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                      return false;
                                                    }
                                                  }
                                                }
                                                var valid2 = _errs30 === errors;
                                              } else {
                                                var valid2 = true;
                                              }
                                            }
                                          }
                                        }
                                      } else {
                                        validate31.errors = [{ instancePath: instancePath + "/baselineRef", schemaPath: "#/$defs/baseline/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                        return false;
                                      }
                                    }
                                    var valid0 = _errs23 === errors;
                                  } else {
                                    var valid0 = true;
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        } else {
          validate31.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate31.errors = vErrors;
      return errors === 0;
    }
    validate31.evaluated = { "props": { "documentId": true, "chromeFrameId": true, "parentFrameId": true, "url": true, "observedAt": true, "recorderStreamId": true, "recorderStartedAt": true, "firstBaselineAt": true, "status": true, "subjectMapping": true, "endedAt": true, "baselineRef": true }, "dynamicProps": false, "dynamicItems": false };
    exports.target = validate32;
    var schema50 = { "type": "object", "required": ["recordingId", "browserRunId", "tabInstanceId", "browserTabId", "windowId", "title", "url", "parentTabInstanceId", "rootTabInstanceIds", "membershipReason", "lineageEvidence", "scopeGrantedAt", "scopeGrantedSeq", "grantCommandId", "lineageConfirmedAt", "lifecycle", "captureState", "captureGeneration", "accepting", "channels", "quality", "possibleInitialGap", "finalFlushConfirmed", "lateResults", "documents"], "properties": { "recordingId": { "type": "string", "minLength": 1, "maxLength": 256 }, "browserRunId": { "type": "string", "minLength": 1, "maxLength": 256 }, "tabInstanceId": { "type": "string", "minLength": 1, "maxLength": 256 }, "browserTabId": { "type": "integer" }, "windowId": { "type": "integer" }, "title": { "type": "string" }, "url": { "type": "string" }, "parentTabInstanceId": { "type": ["string", "null"] }, "rootTabInstanceIds": { "type": "array", "items": { "type": "string", "minLength": 1, "maxLength": 256 } }, "replacesTabInstanceId": { "type": "string", "minLength": 1, "maxLength": 256 }, "membershipReason": { "enum": ["root", "manual_add", "derived", "replacement"] }, "lineageEvidence": { "type": "array", "items": { "type": "object", "required": ["source", "sourceBrowserTabId", "targetBrowserTabId", "observedAt", "observedSeq"], "properties": { "source": { "type": "string" }, "sourceBrowserTabId": { "type": "integer" }, "targetBrowserTabId": { "type": "integer" }, "observedAt": { "type": "string" }, "observedSeq": { "type": "integer", "minimum": 0 } } } }, "scopeGrantedAt": { "type": "string" }, "scopeGrantedSeq": { "type": "integer", "minimum": 0 }, "grantCommandId": { "type": "string", "minLength": 1, "maxLength": 256 }, "lineageConfirmedAt": { "type": "string" }, "lifecycle": { "enum": ["OPEN", "CLOSED", "REPLACED"] }, "captureState": { "enum": ["PENDING", "ATTACHING", "ACTIVE", "DEGRADED", "BLOCKED", "STOPPED"] }, "captureGeneration": { "type": "integer", "minimum": 0 }, "accepting": { "type": "boolean" }, "channels": { "type": "object", "required": ["page", "semantic", "network", "runtime", "screenshot"], "properties": { "page": { "$ref": "#/$defs/channel" }, "semantic": { "$ref": "#/$defs/channel" }, "network": { "$ref": "#/$defs/channel" }, "runtime": { "$ref": "#/$defs/channel" }, "screenshot": { "$ref": "#/$defs/channel" } } }, "quality": { "enum": ["complete_within_declared_scope", "partial", "unavailable"] }, "possibleInitialGap": { "type": "boolean" }, "finalFlushConfirmed": { "type": "boolean" }, "lateResults": { "type": "integer", "minimum": 0 }, "documents": { "type": "array", "items": { "$ref": "#/$defs/document" } } } };
    function validate32(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate32.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.recordingId === void 0 && (missing0 = "recordingId") || data.browserRunId === void 0 && (missing0 = "browserRunId") || data.tabInstanceId === void 0 && (missing0 = "tabInstanceId") || data.browserTabId === void 0 && (missing0 = "browserTabId") || data.windowId === void 0 && (missing0 = "windowId") || data.title === void 0 && (missing0 = "title") || data.url === void 0 && (missing0 = "url") || data.parentTabInstanceId === void 0 && (missing0 = "parentTabInstanceId") || data.rootTabInstanceIds === void 0 && (missing0 = "rootTabInstanceIds") || data.membershipReason === void 0 && (missing0 = "membershipReason") || data.lineageEvidence === void 0 && (missing0 = "lineageEvidence") || data.scopeGrantedAt === void 0 && (missing0 = "scopeGrantedAt") || data.scopeGrantedSeq === void 0 && (missing0 = "scopeGrantedSeq") || data.grantCommandId === void 0 && (missing0 = "grantCommandId") || data.lineageConfirmedAt === void 0 && (missing0 = "lineageConfirmedAt") || data.lifecycle === void 0 && (missing0 = "lifecycle") || data.captureState === void 0 && (missing0 = "captureState") || data.captureGeneration === void 0 && (missing0 = "captureGeneration") || data.accepting === void 0 && (missing0 = "accepting") || data.channels === void 0 && (missing0 = "channels") || data.quality === void 0 && (missing0 = "quality") || data.possibleInitialGap === void 0 && (missing0 = "possibleInitialGap") || data.finalFlushConfirmed === void 0 && (missing0 = "finalFlushConfirmed") || data.lateResults === void 0 && (missing0 = "lateResults") || data.documents === void 0 && (missing0 = "documents")) {
            validate32.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.recordingId !== void 0) {
              let data0 = data.recordingId;
              const _errs1 = errors;
              if (errors === _errs1) {
                if (typeof data0 === "string") {
                  if (func1(data0) > 256) {
                    validate32.errors = [{ instancePath: instancePath + "/recordingId", schemaPath: "#/properties/recordingId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                    return false;
                  } else {
                    if (func1(data0) < 1) {
                      validate32.errors = [{ instancePath: instancePath + "/recordingId", schemaPath: "#/properties/recordingId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                      return false;
                    }
                  }
                } else {
                  validate32.errors = [{ instancePath: instancePath + "/recordingId", schemaPath: "#/properties/recordingId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                  return false;
                }
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.browserRunId !== void 0) {
                let data1 = data.browserRunId;
                const _errs3 = errors;
                if (errors === _errs3) {
                  if (typeof data1 === "string") {
                    if (func1(data1) > 256) {
                      validate32.errors = [{ instancePath: instancePath + "/browserRunId", schemaPath: "#/properties/browserRunId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                      return false;
                    } else {
                      if (func1(data1) < 1) {
                        validate32.errors = [{ instancePath: instancePath + "/browserRunId", schemaPath: "#/properties/browserRunId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                        return false;
                      }
                    }
                  } else {
                    validate32.errors = [{ instancePath: instancePath + "/browserRunId", schemaPath: "#/properties/browserRunId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                    return false;
                  }
                }
                var valid0 = _errs3 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.tabInstanceId !== void 0) {
                  let data2 = data.tabInstanceId;
                  const _errs5 = errors;
                  if (errors === _errs5) {
                    if (typeof data2 === "string") {
                      if (func1(data2) > 256) {
                        validate32.errors = [{ instancePath: instancePath + "/tabInstanceId", schemaPath: "#/properties/tabInstanceId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                        return false;
                      } else {
                        if (func1(data2) < 1) {
                          validate32.errors = [{ instancePath: instancePath + "/tabInstanceId", schemaPath: "#/properties/tabInstanceId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                          return false;
                        }
                      }
                    } else {
                      validate32.errors = [{ instancePath: instancePath + "/tabInstanceId", schemaPath: "#/properties/tabInstanceId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                      return false;
                    }
                  }
                  var valid0 = _errs5 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.browserTabId !== void 0) {
                    let data3 = data.browserTabId;
                    const _errs7 = errors;
                    if (!(typeof data3 == "number" && (!(data3 % 1) && !isNaN(data3)))) {
                      validate32.errors = [{ instancePath: instancePath + "/browserTabId", schemaPath: "#/properties/browserTabId/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                      return false;
                    }
                    var valid0 = _errs7 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.windowId !== void 0) {
                      let data4 = data.windowId;
                      const _errs9 = errors;
                      if (!(typeof data4 == "number" && (!(data4 % 1) && !isNaN(data4)))) {
                        validate32.errors = [{ instancePath: instancePath + "/windowId", schemaPath: "#/properties/windowId/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                        return false;
                      }
                      var valid0 = _errs9 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.title !== void 0) {
                        const _errs11 = errors;
                        if (typeof data.title !== "string") {
                          validate32.errors = [{ instancePath: instancePath + "/title", schemaPath: "#/properties/title/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                          return false;
                        }
                        var valid0 = _errs11 === errors;
                      } else {
                        var valid0 = true;
                      }
                      if (valid0) {
                        if (data.url !== void 0) {
                          const _errs13 = errors;
                          if (typeof data.url !== "string") {
                            validate32.errors = [{ instancePath: instancePath + "/url", schemaPath: "#/properties/url/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                            return false;
                          }
                          var valid0 = _errs13 === errors;
                        } else {
                          var valid0 = true;
                        }
                        if (valid0) {
                          if (data.parentTabInstanceId !== void 0) {
                            let data7 = data.parentTabInstanceId;
                            const _errs15 = errors;
                            if (typeof data7 !== "string" && data7 !== null) {
                              validate32.errors = [{ instancePath: instancePath + "/parentTabInstanceId", schemaPath: "#/properties/parentTabInstanceId/type", keyword: "type", params: { type: schema50.properties.parentTabInstanceId.type }, message: "must be string,null" }];
                              return false;
                            }
                            var valid0 = _errs15 === errors;
                          } else {
                            var valid0 = true;
                          }
                          if (valid0) {
                            if (data.rootTabInstanceIds !== void 0) {
                              let data8 = data.rootTabInstanceIds;
                              const _errs17 = errors;
                              if (errors === _errs17) {
                                if (Array.isArray(data8)) {
                                  var valid1 = true;
                                  const len0 = data8.length;
                                  for (let i0 = 0; i0 < len0; i0++) {
                                    let data9 = data8[i0];
                                    const _errs19 = errors;
                                    if (errors === _errs19) {
                                      if (typeof data9 === "string") {
                                        if (func1(data9) > 256) {
                                          validate32.errors = [{ instancePath: instancePath + "/rootTabInstanceIds/" + i0, schemaPath: "#/properties/rootTabInstanceIds/items/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                          return false;
                                        } else {
                                          if (func1(data9) < 1) {
                                            validate32.errors = [{ instancePath: instancePath + "/rootTabInstanceIds/" + i0, schemaPath: "#/properties/rootTabInstanceIds/items/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                            return false;
                                          }
                                        }
                                      } else {
                                        validate32.errors = [{ instancePath: instancePath + "/rootTabInstanceIds/" + i0, schemaPath: "#/properties/rootTabInstanceIds/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                        return false;
                                      }
                                    }
                                    var valid1 = _errs19 === errors;
                                    if (!valid1) {
                                      break;
                                    }
                                  }
                                } else {
                                  validate32.errors = [{ instancePath: instancePath + "/rootTabInstanceIds", schemaPath: "#/properties/rootTabInstanceIds/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                  return false;
                                }
                              }
                              var valid0 = _errs17 === errors;
                            } else {
                              var valid0 = true;
                            }
                            if (valid0) {
                              if (data.replacesTabInstanceId !== void 0) {
                                let data10 = data.replacesTabInstanceId;
                                const _errs21 = errors;
                                if (errors === _errs21) {
                                  if (typeof data10 === "string") {
                                    if (func1(data10) > 256) {
                                      validate32.errors = [{ instancePath: instancePath + "/replacesTabInstanceId", schemaPath: "#/properties/replacesTabInstanceId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                      return false;
                                    } else {
                                      if (func1(data10) < 1) {
                                        validate32.errors = [{ instancePath: instancePath + "/replacesTabInstanceId", schemaPath: "#/properties/replacesTabInstanceId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                        return false;
                                      }
                                    }
                                  } else {
                                    validate32.errors = [{ instancePath: instancePath + "/replacesTabInstanceId", schemaPath: "#/properties/replacesTabInstanceId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                    return false;
                                  }
                                }
                                var valid0 = _errs21 === errors;
                              } else {
                                var valid0 = true;
                              }
                              if (valid0) {
                                if (data.membershipReason !== void 0) {
                                  let data11 = data.membershipReason;
                                  const _errs23 = errors;
                                  if (!(data11 === "root" || data11 === "manual_add" || data11 === "derived" || data11 === "replacement")) {
                                    validate32.errors = [{ instancePath: instancePath + "/membershipReason", schemaPath: "#/properties/membershipReason/enum", keyword: "enum", params: { allowedValues: schema50.properties.membershipReason.enum }, message: "must be equal to one of the allowed values" }];
                                    return false;
                                  }
                                  var valid0 = _errs23 === errors;
                                } else {
                                  var valid0 = true;
                                }
                                if (valid0) {
                                  if (data.lineageEvidence !== void 0) {
                                    let data12 = data.lineageEvidence;
                                    const _errs24 = errors;
                                    if (errors === _errs24) {
                                      if (Array.isArray(data12)) {
                                        var valid2 = true;
                                        const len1 = data12.length;
                                        for (let i1 = 0; i1 < len1; i1++) {
                                          let data13 = data12[i1];
                                          const _errs26 = errors;
                                          if (errors === _errs26) {
                                            if (data13 && typeof data13 == "object" && !Array.isArray(data13)) {
                                              let missing1;
                                              if (data13.source === void 0 && (missing1 = "source") || data13.sourceBrowserTabId === void 0 && (missing1 = "sourceBrowserTabId") || data13.targetBrowserTabId === void 0 && (missing1 = "targetBrowserTabId") || data13.observedAt === void 0 && (missing1 = "observedAt") || data13.observedSeq === void 0 && (missing1 = "observedSeq")) {
                                                validate32.errors = [{ instancePath: instancePath + "/lineageEvidence/" + i1, schemaPath: "#/properties/lineageEvidence/items/required", keyword: "required", params: { missingProperty: missing1 }, message: "must have required property '" + missing1 + "'" }];
                                                return false;
                                              } else {
                                                if (data13.source !== void 0) {
                                                  const _errs28 = errors;
                                                  if (typeof data13.source !== "string") {
                                                    validate32.errors = [{ instancePath: instancePath + "/lineageEvidence/" + i1 + "/source", schemaPath: "#/properties/lineageEvidence/items/properties/source/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                    return false;
                                                  }
                                                  var valid3 = _errs28 === errors;
                                                } else {
                                                  var valid3 = true;
                                                }
                                                if (valid3) {
                                                  if (data13.sourceBrowserTabId !== void 0) {
                                                    let data15 = data13.sourceBrowserTabId;
                                                    const _errs30 = errors;
                                                    if (!(typeof data15 == "number" && (!(data15 % 1) && !isNaN(data15)))) {
                                                      validate32.errors = [{ instancePath: instancePath + "/lineageEvidence/" + i1 + "/sourceBrowserTabId", schemaPath: "#/properties/lineageEvidence/items/properties/sourceBrowserTabId/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                      return false;
                                                    }
                                                    var valid3 = _errs30 === errors;
                                                  } else {
                                                    var valid3 = true;
                                                  }
                                                  if (valid3) {
                                                    if (data13.targetBrowserTabId !== void 0) {
                                                      let data16 = data13.targetBrowserTabId;
                                                      const _errs32 = errors;
                                                      if (!(typeof data16 == "number" && (!(data16 % 1) && !isNaN(data16)))) {
                                                        validate32.errors = [{ instancePath: instancePath + "/lineageEvidence/" + i1 + "/targetBrowserTabId", schemaPath: "#/properties/lineageEvidence/items/properties/targetBrowserTabId/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                        return false;
                                                      }
                                                      var valid3 = _errs32 === errors;
                                                    } else {
                                                      var valid3 = true;
                                                    }
                                                    if (valid3) {
                                                      if (data13.observedAt !== void 0) {
                                                        const _errs34 = errors;
                                                        if (typeof data13.observedAt !== "string") {
                                                          validate32.errors = [{ instancePath: instancePath + "/lineageEvidence/" + i1 + "/observedAt", schemaPath: "#/properties/lineageEvidence/items/properties/observedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                          return false;
                                                        }
                                                        var valid3 = _errs34 === errors;
                                                      } else {
                                                        var valid3 = true;
                                                      }
                                                      if (valid3) {
                                                        if (data13.observedSeq !== void 0) {
                                                          let data18 = data13.observedSeq;
                                                          const _errs36 = errors;
                                                          if (!(typeof data18 == "number" && (!(data18 % 1) && !isNaN(data18)))) {
                                                            validate32.errors = [{ instancePath: instancePath + "/lineageEvidence/" + i1 + "/observedSeq", schemaPath: "#/properties/lineageEvidence/items/properties/observedSeq/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                            return false;
                                                          }
                                                          if (errors === _errs36) {
                                                            if (typeof data18 == "number") {
                                                              if (data18 < 0 || isNaN(data18)) {
                                                                validate32.errors = [{ instancePath: instancePath + "/lineageEvidence/" + i1 + "/observedSeq", schemaPath: "#/properties/lineageEvidence/items/properties/observedSeq/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                                return false;
                                                              }
                                                            }
                                                          }
                                                          var valid3 = _errs36 === errors;
                                                        } else {
                                                          var valid3 = true;
                                                        }
                                                      }
                                                    }
                                                  }
                                                }
                                              }
                                            } else {
                                              validate32.errors = [{ instancePath: instancePath + "/lineageEvidence/" + i1, schemaPath: "#/properties/lineageEvidence/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                              return false;
                                            }
                                          }
                                          var valid2 = _errs26 === errors;
                                          if (!valid2) {
                                            break;
                                          }
                                        }
                                      } else {
                                        validate32.errors = [{ instancePath: instancePath + "/lineageEvidence", schemaPath: "#/properties/lineageEvidence/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                        return false;
                                      }
                                    }
                                    var valid0 = _errs24 === errors;
                                  } else {
                                    var valid0 = true;
                                  }
                                  if (valid0) {
                                    if (data.scopeGrantedAt !== void 0) {
                                      const _errs38 = errors;
                                      if (typeof data.scopeGrantedAt !== "string") {
                                        validate32.errors = [{ instancePath: instancePath + "/scopeGrantedAt", schemaPath: "#/properties/scopeGrantedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                        return false;
                                      }
                                      var valid0 = _errs38 === errors;
                                    } else {
                                      var valid0 = true;
                                    }
                                    if (valid0) {
                                      if (data.scopeGrantedSeq !== void 0) {
                                        let data20 = data.scopeGrantedSeq;
                                        const _errs40 = errors;
                                        if (!(typeof data20 == "number" && (!(data20 % 1) && !isNaN(data20)))) {
                                          validate32.errors = [{ instancePath: instancePath + "/scopeGrantedSeq", schemaPath: "#/properties/scopeGrantedSeq/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                          return false;
                                        }
                                        if (errors === _errs40) {
                                          if (typeof data20 == "number") {
                                            if (data20 < 0 || isNaN(data20)) {
                                              validate32.errors = [{ instancePath: instancePath + "/scopeGrantedSeq", schemaPath: "#/properties/scopeGrantedSeq/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                              return false;
                                            }
                                          }
                                        }
                                        var valid0 = _errs40 === errors;
                                      } else {
                                        var valid0 = true;
                                      }
                                      if (valid0) {
                                        if (data.grantCommandId !== void 0) {
                                          let data21 = data.grantCommandId;
                                          const _errs42 = errors;
                                          if (errors === _errs42) {
                                            if (typeof data21 === "string") {
                                              if (func1(data21) > 256) {
                                                validate32.errors = [{ instancePath: instancePath + "/grantCommandId", schemaPath: "#/properties/grantCommandId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                                return false;
                                              } else {
                                                if (func1(data21) < 1) {
                                                  validate32.errors = [{ instancePath: instancePath + "/grantCommandId", schemaPath: "#/properties/grantCommandId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                  return false;
                                                }
                                              }
                                            } else {
                                              validate32.errors = [{ instancePath: instancePath + "/grantCommandId", schemaPath: "#/properties/grantCommandId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                              return false;
                                            }
                                          }
                                          var valid0 = _errs42 === errors;
                                        } else {
                                          var valid0 = true;
                                        }
                                        if (valid0) {
                                          if (data.lineageConfirmedAt !== void 0) {
                                            const _errs44 = errors;
                                            if (typeof data.lineageConfirmedAt !== "string") {
                                              validate32.errors = [{ instancePath: instancePath + "/lineageConfirmedAt", schemaPath: "#/properties/lineageConfirmedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                              return false;
                                            }
                                            var valid0 = _errs44 === errors;
                                          } else {
                                            var valid0 = true;
                                          }
                                          if (valid0) {
                                            if (data.lifecycle !== void 0) {
                                              let data23 = data.lifecycle;
                                              const _errs46 = errors;
                                              if (!(data23 === "OPEN" || data23 === "CLOSED" || data23 === "REPLACED")) {
                                                validate32.errors = [{ instancePath: instancePath + "/lifecycle", schemaPath: "#/properties/lifecycle/enum", keyword: "enum", params: { allowedValues: schema50.properties.lifecycle.enum }, message: "must be equal to one of the allowed values" }];
                                                return false;
                                              }
                                              var valid0 = _errs46 === errors;
                                            } else {
                                              var valid0 = true;
                                            }
                                            if (valid0) {
                                              if (data.captureState !== void 0) {
                                                let data24 = data.captureState;
                                                const _errs47 = errors;
                                                if (!(data24 === "PENDING" || data24 === "ATTACHING" || data24 === "ACTIVE" || data24 === "DEGRADED" || data24 === "BLOCKED" || data24 === "STOPPED")) {
                                                  validate32.errors = [{ instancePath: instancePath + "/captureState", schemaPath: "#/properties/captureState/enum", keyword: "enum", params: { allowedValues: schema50.properties.captureState.enum }, message: "must be equal to one of the allowed values" }];
                                                  return false;
                                                }
                                                var valid0 = _errs47 === errors;
                                              } else {
                                                var valid0 = true;
                                              }
                                              if (valid0) {
                                                if (data.captureGeneration !== void 0) {
                                                  let data25 = data.captureGeneration;
                                                  const _errs48 = errors;
                                                  if (!(typeof data25 == "number" && (!(data25 % 1) && !isNaN(data25)))) {
                                                    validate32.errors = [{ instancePath: instancePath + "/captureGeneration", schemaPath: "#/properties/captureGeneration/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                    return false;
                                                  }
                                                  if (errors === _errs48) {
                                                    if (typeof data25 == "number") {
                                                      if (data25 < 0 || isNaN(data25)) {
                                                        validate32.errors = [{ instancePath: instancePath + "/captureGeneration", schemaPath: "#/properties/captureGeneration/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                        return false;
                                                      }
                                                    }
                                                  }
                                                  var valid0 = _errs48 === errors;
                                                } else {
                                                  var valid0 = true;
                                                }
                                                if (valid0) {
                                                  if (data.accepting !== void 0) {
                                                    const _errs50 = errors;
                                                    if (typeof data.accepting !== "boolean") {
                                                      validate32.errors = [{ instancePath: instancePath + "/accepting", schemaPath: "#/properties/accepting/type", keyword: "type", params: { type: "boolean" }, message: "must be boolean" }];
                                                      return false;
                                                    }
                                                    var valid0 = _errs50 === errors;
                                                  } else {
                                                    var valid0 = true;
                                                  }
                                                  if (valid0) {
                                                    if (data.channels !== void 0) {
                                                      let data27 = data.channels;
                                                      const _errs52 = errors;
                                                      if (errors === _errs52) {
                                                        if (data27 && typeof data27 == "object" && !Array.isArray(data27)) {
                                                          let missing2;
                                                          if (data27.page === void 0 && (missing2 = "page") || data27.semantic === void 0 && (missing2 = "semantic") || data27.network === void 0 && (missing2 = "network") || data27.runtime === void 0 && (missing2 = "runtime") || data27.screenshot === void 0 && (missing2 = "screenshot")) {
                                                            validate32.errors = [{ instancePath: instancePath + "/channels", schemaPath: "#/properties/channels/required", keyword: "required", params: { missingProperty: missing2 }, message: "must have required property '" + missing2 + "'" }];
                                                            return false;
                                                          } else {
                                                            if (data27.page !== void 0) {
                                                              let data28 = data27.page;
                                                              const _errs54 = errors;
                                                              const _errs55 = errors;
                                                              if (errors === _errs55) {
                                                                if (data28 && typeof data28 == "object" && !Array.isArray(data28)) {
                                                                  let missing3;
                                                                  if (data28.state === void 0 && (missing3 = "state") || data28.generation === void 0 && (missing3 = "generation")) {
                                                                    validate32.errors = [{ instancePath: instancePath + "/channels/page", schemaPath: "#/$defs/channel/required", keyword: "required", params: { missingProperty: missing3 }, message: "must have required property '" + missing3 + "'" }];
                                                                    return false;
                                                                  } else {
                                                                    if (data28.state !== void 0) {
                                                                      let data29 = data28.state;
                                                                      const _errs57 = errors;
                                                                      if (!(data29 === "PENDING" || data29 === "ACTIVE" || data29 === "BLOCKED" || data29 === "LOST" || data29 === "STOPPED")) {
                                                                        validate32.errors = [{ instancePath: instancePath + "/channels/page/state", schemaPath: "#/$defs/channel/properties/state/enum", keyword: "enum", params: { allowedValues: schema46.properties.state.enum }, message: "must be equal to one of the allowed values" }];
                                                                        return false;
                                                                      }
                                                                      var valid6 = _errs57 === errors;
                                                                    } else {
                                                                      var valid6 = true;
                                                                    }
                                                                    if (valid6) {
                                                                      if (data28.generation !== void 0) {
                                                                        let data30 = data28.generation;
                                                                        const _errs58 = errors;
                                                                        if (!(typeof data30 == "number" && (!(data30 % 1) && !isNaN(data30)))) {
                                                                          validate32.errors = [{ instancePath: instancePath + "/channels/page/generation", schemaPath: "#/$defs/channel/properties/generation/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                          return false;
                                                                        }
                                                                        if (errors === _errs58) {
                                                                          if (typeof data30 == "number") {
                                                                            if (data30 < 0 || isNaN(data30)) {
                                                                              validate32.errors = [{ instancePath: instancePath + "/channels/page/generation", schemaPath: "#/$defs/channel/properties/generation/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                                              return false;
                                                                            }
                                                                          }
                                                                        }
                                                                        var valid6 = _errs58 === errors;
                                                                      } else {
                                                                        var valid6 = true;
                                                                      }
                                                                      if (valid6) {
                                                                        if (data28.readyAt !== void 0) {
                                                                          const _errs60 = errors;
                                                                          if (typeof data28.readyAt !== "string") {
                                                                            validate32.errors = [{ instancePath: instancePath + "/channels/page/readyAt", schemaPath: "#/$defs/channel/properties/readyAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                            return false;
                                                                          }
                                                                          var valid6 = _errs60 === errors;
                                                                        } else {
                                                                          var valid6 = true;
                                                                        }
                                                                        if (valid6) {
                                                                          if (data28.stoppedAt !== void 0) {
                                                                            const _errs62 = errors;
                                                                            if (typeof data28.stoppedAt !== "string") {
                                                                              validate32.errors = [{ instancePath: instancePath + "/channels/page/stoppedAt", schemaPath: "#/$defs/channel/properties/stoppedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                              return false;
                                                                            }
                                                                            var valid6 = _errs62 === errors;
                                                                          } else {
                                                                            var valid6 = true;
                                                                          }
                                                                          if (valid6) {
                                                                            if (data28.reason !== void 0) {
                                                                              const _errs64 = errors;
                                                                              if (typeof data28.reason !== "string") {
                                                                                validate32.errors = [{ instancePath: instancePath + "/channels/page/reason", schemaPath: "#/$defs/channel/properties/reason/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                return false;
                                                                              }
                                                                              var valid6 = _errs64 === errors;
                                                                            } else {
                                                                              var valid6 = true;
                                                                            }
                                                                          }
                                                                        }
                                                                      }
                                                                    }
                                                                  }
                                                                } else {
                                                                  validate32.errors = [{ instancePath: instancePath + "/channels/page", schemaPath: "#/$defs/channel/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                  return false;
                                                                }
                                                              }
                                                              var valid4 = _errs54 === errors;
                                                            } else {
                                                              var valid4 = true;
                                                            }
                                                            if (valid4) {
                                                              if (data27.semantic !== void 0) {
                                                                let data34 = data27.semantic;
                                                                const _errs66 = errors;
                                                                const _errs67 = errors;
                                                                if (errors === _errs67) {
                                                                  if (data34 && typeof data34 == "object" && !Array.isArray(data34)) {
                                                                    let missing4;
                                                                    if (data34.state === void 0 && (missing4 = "state") || data34.generation === void 0 && (missing4 = "generation")) {
                                                                      validate32.errors = [{ instancePath: instancePath + "/channels/semantic", schemaPath: "#/$defs/channel/required", keyword: "required", params: { missingProperty: missing4 }, message: "must have required property '" + missing4 + "'" }];
                                                                      return false;
                                                                    } else {
                                                                      if (data34.state !== void 0) {
                                                                        let data35 = data34.state;
                                                                        const _errs69 = errors;
                                                                        if (!(data35 === "PENDING" || data35 === "ACTIVE" || data35 === "BLOCKED" || data35 === "LOST" || data35 === "STOPPED")) {
                                                                          validate32.errors = [{ instancePath: instancePath + "/channels/semantic/state", schemaPath: "#/$defs/channel/properties/state/enum", keyword: "enum", params: { allowedValues: schema46.properties.state.enum }, message: "must be equal to one of the allowed values" }];
                                                                          return false;
                                                                        }
                                                                        var valid8 = _errs69 === errors;
                                                                      } else {
                                                                        var valid8 = true;
                                                                      }
                                                                      if (valid8) {
                                                                        if (data34.generation !== void 0) {
                                                                          let data36 = data34.generation;
                                                                          const _errs70 = errors;
                                                                          if (!(typeof data36 == "number" && (!(data36 % 1) && !isNaN(data36)))) {
                                                                            validate32.errors = [{ instancePath: instancePath + "/channels/semantic/generation", schemaPath: "#/$defs/channel/properties/generation/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                            return false;
                                                                          }
                                                                          if (errors === _errs70) {
                                                                            if (typeof data36 == "number") {
                                                                              if (data36 < 0 || isNaN(data36)) {
                                                                                validate32.errors = [{ instancePath: instancePath + "/channels/semantic/generation", schemaPath: "#/$defs/channel/properties/generation/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                                                return false;
                                                                              }
                                                                            }
                                                                          }
                                                                          var valid8 = _errs70 === errors;
                                                                        } else {
                                                                          var valid8 = true;
                                                                        }
                                                                        if (valid8) {
                                                                          if (data34.readyAt !== void 0) {
                                                                            const _errs72 = errors;
                                                                            if (typeof data34.readyAt !== "string") {
                                                                              validate32.errors = [{ instancePath: instancePath + "/channels/semantic/readyAt", schemaPath: "#/$defs/channel/properties/readyAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                              return false;
                                                                            }
                                                                            var valid8 = _errs72 === errors;
                                                                          } else {
                                                                            var valid8 = true;
                                                                          }
                                                                          if (valid8) {
                                                                            if (data34.stoppedAt !== void 0) {
                                                                              const _errs74 = errors;
                                                                              if (typeof data34.stoppedAt !== "string") {
                                                                                validate32.errors = [{ instancePath: instancePath + "/channels/semantic/stoppedAt", schemaPath: "#/$defs/channel/properties/stoppedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                return false;
                                                                              }
                                                                              var valid8 = _errs74 === errors;
                                                                            } else {
                                                                              var valid8 = true;
                                                                            }
                                                                            if (valid8) {
                                                                              if (data34.reason !== void 0) {
                                                                                const _errs76 = errors;
                                                                                if (typeof data34.reason !== "string") {
                                                                                  validate32.errors = [{ instancePath: instancePath + "/channels/semantic/reason", schemaPath: "#/$defs/channel/properties/reason/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                  return false;
                                                                                }
                                                                                var valid8 = _errs76 === errors;
                                                                              } else {
                                                                                var valid8 = true;
                                                                              }
                                                                            }
                                                                          }
                                                                        }
                                                                      }
                                                                    }
                                                                  } else {
                                                                    validate32.errors = [{ instancePath: instancePath + "/channels/semantic", schemaPath: "#/$defs/channel/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                    return false;
                                                                  }
                                                                }
                                                                var valid4 = _errs66 === errors;
                                                              } else {
                                                                var valid4 = true;
                                                              }
                                                              if (valid4) {
                                                                if (data27.network !== void 0) {
                                                                  let data40 = data27.network;
                                                                  const _errs78 = errors;
                                                                  const _errs79 = errors;
                                                                  if (errors === _errs79) {
                                                                    if (data40 && typeof data40 == "object" && !Array.isArray(data40)) {
                                                                      let missing5;
                                                                      if (data40.state === void 0 && (missing5 = "state") || data40.generation === void 0 && (missing5 = "generation")) {
                                                                        validate32.errors = [{ instancePath: instancePath + "/channels/network", schemaPath: "#/$defs/channel/required", keyword: "required", params: { missingProperty: missing5 }, message: "must have required property '" + missing5 + "'" }];
                                                                        return false;
                                                                      } else {
                                                                        if (data40.state !== void 0) {
                                                                          let data41 = data40.state;
                                                                          const _errs81 = errors;
                                                                          if (!(data41 === "PENDING" || data41 === "ACTIVE" || data41 === "BLOCKED" || data41 === "LOST" || data41 === "STOPPED")) {
                                                                            validate32.errors = [{ instancePath: instancePath + "/channels/network/state", schemaPath: "#/$defs/channel/properties/state/enum", keyword: "enum", params: { allowedValues: schema46.properties.state.enum }, message: "must be equal to one of the allowed values" }];
                                                                            return false;
                                                                          }
                                                                          var valid10 = _errs81 === errors;
                                                                        } else {
                                                                          var valid10 = true;
                                                                        }
                                                                        if (valid10) {
                                                                          if (data40.generation !== void 0) {
                                                                            let data42 = data40.generation;
                                                                            const _errs82 = errors;
                                                                            if (!(typeof data42 == "number" && (!(data42 % 1) && !isNaN(data42)))) {
                                                                              validate32.errors = [{ instancePath: instancePath + "/channels/network/generation", schemaPath: "#/$defs/channel/properties/generation/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                              return false;
                                                                            }
                                                                            if (errors === _errs82) {
                                                                              if (typeof data42 == "number") {
                                                                                if (data42 < 0 || isNaN(data42)) {
                                                                                  validate32.errors = [{ instancePath: instancePath + "/channels/network/generation", schemaPath: "#/$defs/channel/properties/generation/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                                                  return false;
                                                                                }
                                                                              }
                                                                            }
                                                                            var valid10 = _errs82 === errors;
                                                                          } else {
                                                                            var valid10 = true;
                                                                          }
                                                                          if (valid10) {
                                                                            if (data40.readyAt !== void 0) {
                                                                              const _errs84 = errors;
                                                                              if (typeof data40.readyAt !== "string") {
                                                                                validate32.errors = [{ instancePath: instancePath + "/channels/network/readyAt", schemaPath: "#/$defs/channel/properties/readyAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                return false;
                                                                              }
                                                                              var valid10 = _errs84 === errors;
                                                                            } else {
                                                                              var valid10 = true;
                                                                            }
                                                                            if (valid10) {
                                                                              if (data40.stoppedAt !== void 0) {
                                                                                const _errs86 = errors;
                                                                                if (typeof data40.stoppedAt !== "string") {
                                                                                  validate32.errors = [{ instancePath: instancePath + "/channels/network/stoppedAt", schemaPath: "#/$defs/channel/properties/stoppedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                  return false;
                                                                                }
                                                                                var valid10 = _errs86 === errors;
                                                                              } else {
                                                                                var valid10 = true;
                                                                              }
                                                                              if (valid10) {
                                                                                if (data40.reason !== void 0) {
                                                                                  const _errs88 = errors;
                                                                                  if (typeof data40.reason !== "string") {
                                                                                    validate32.errors = [{ instancePath: instancePath + "/channels/network/reason", schemaPath: "#/$defs/channel/properties/reason/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                    return false;
                                                                                  }
                                                                                  var valid10 = _errs88 === errors;
                                                                                } else {
                                                                                  var valid10 = true;
                                                                                }
                                                                              }
                                                                            }
                                                                          }
                                                                        }
                                                                      }
                                                                    } else {
                                                                      validate32.errors = [{ instancePath: instancePath + "/channels/network", schemaPath: "#/$defs/channel/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                      return false;
                                                                    }
                                                                  }
                                                                  var valid4 = _errs78 === errors;
                                                                } else {
                                                                  var valid4 = true;
                                                                }
                                                                if (valid4) {
                                                                  if (data27.runtime !== void 0) {
                                                                    let data46 = data27.runtime;
                                                                    const _errs90 = errors;
                                                                    const _errs91 = errors;
                                                                    if (errors === _errs91) {
                                                                      if (data46 && typeof data46 == "object" && !Array.isArray(data46)) {
                                                                        let missing6;
                                                                        if (data46.state === void 0 && (missing6 = "state") || data46.generation === void 0 && (missing6 = "generation")) {
                                                                          validate32.errors = [{ instancePath: instancePath + "/channels/runtime", schemaPath: "#/$defs/channel/required", keyword: "required", params: { missingProperty: missing6 }, message: "must have required property '" + missing6 + "'" }];
                                                                          return false;
                                                                        } else {
                                                                          if (data46.state !== void 0) {
                                                                            let data47 = data46.state;
                                                                            const _errs93 = errors;
                                                                            if (!(data47 === "PENDING" || data47 === "ACTIVE" || data47 === "BLOCKED" || data47 === "LOST" || data47 === "STOPPED")) {
                                                                              validate32.errors = [{ instancePath: instancePath + "/channels/runtime/state", schemaPath: "#/$defs/channel/properties/state/enum", keyword: "enum", params: { allowedValues: schema46.properties.state.enum }, message: "must be equal to one of the allowed values" }];
                                                                              return false;
                                                                            }
                                                                            var valid12 = _errs93 === errors;
                                                                          } else {
                                                                            var valid12 = true;
                                                                          }
                                                                          if (valid12) {
                                                                            if (data46.generation !== void 0) {
                                                                              let data48 = data46.generation;
                                                                              const _errs94 = errors;
                                                                              if (!(typeof data48 == "number" && (!(data48 % 1) && !isNaN(data48)))) {
                                                                                validate32.errors = [{ instancePath: instancePath + "/channels/runtime/generation", schemaPath: "#/$defs/channel/properties/generation/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                return false;
                                                                              }
                                                                              if (errors === _errs94) {
                                                                                if (typeof data48 == "number") {
                                                                                  if (data48 < 0 || isNaN(data48)) {
                                                                                    validate32.errors = [{ instancePath: instancePath + "/channels/runtime/generation", schemaPath: "#/$defs/channel/properties/generation/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                                                    return false;
                                                                                  }
                                                                                }
                                                                              }
                                                                              var valid12 = _errs94 === errors;
                                                                            } else {
                                                                              var valid12 = true;
                                                                            }
                                                                            if (valid12) {
                                                                              if (data46.readyAt !== void 0) {
                                                                                const _errs96 = errors;
                                                                                if (typeof data46.readyAt !== "string") {
                                                                                  validate32.errors = [{ instancePath: instancePath + "/channels/runtime/readyAt", schemaPath: "#/$defs/channel/properties/readyAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                  return false;
                                                                                }
                                                                                var valid12 = _errs96 === errors;
                                                                              } else {
                                                                                var valid12 = true;
                                                                              }
                                                                              if (valid12) {
                                                                                if (data46.stoppedAt !== void 0) {
                                                                                  const _errs98 = errors;
                                                                                  if (typeof data46.stoppedAt !== "string") {
                                                                                    validate32.errors = [{ instancePath: instancePath + "/channels/runtime/stoppedAt", schemaPath: "#/$defs/channel/properties/stoppedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                    return false;
                                                                                  }
                                                                                  var valid12 = _errs98 === errors;
                                                                                } else {
                                                                                  var valid12 = true;
                                                                                }
                                                                                if (valid12) {
                                                                                  if (data46.reason !== void 0) {
                                                                                    const _errs100 = errors;
                                                                                    if (typeof data46.reason !== "string") {
                                                                                      validate32.errors = [{ instancePath: instancePath + "/channels/runtime/reason", schemaPath: "#/$defs/channel/properties/reason/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                      return false;
                                                                                    }
                                                                                    var valid12 = _errs100 === errors;
                                                                                  } else {
                                                                                    var valid12 = true;
                                                                                  }
                                                                                }
                                                                              }
                                                                            }
                                                                          }
                                                                        }
                                                                      } else {
                                                                        validate32.errors = [{ instancePath: instancePath + "/channels/runtime", schemaPath: "#/$defs/channel/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                        return false;
                                                                      }
                                                                    }
                                                                    var valid4 = _errs90 === errors;
                                                                  } else {
                                                                    var valid4 = true;
                                                                  }
                                                                  if (valid4) {
                                                                    if (data27.screenshot !== void 0) {
                                                                      let data52 = data27.screenshot;
                                                                      const _errs102 = errors;
                                                                      const _errs103 = errors;
                                                                      if (errors === _errs103) {
                                                                        if (data52 && typeof data52 == "object" && !Array.isArray(data52)) {
                                                                          let missing7;
                                                                          if (data52.state === void 0 && (missing7 = "state") || data52.generation === void 0 && (missing7 = "generation")) {
                                                                            validate32.errors = [{ instancePath: instancePath + "/channels/screenshot", schemaPath: "#/$defs/channel/required", keyword: "required", params: { missingProperty: missing7 }, message: "must have required property '" + missing7 + "'" }];
                                                                            return false;
                                                                          } else {
                                                                            if (data52.state !== void 0) {
                                                                              let data53 = data52.state;
                                                                              const _errs105 = errors;
                                                                              if (!(data53 === "PENDING" || data53 === "ACTIVE" || data53 === "BLOCKED" || data53 === "LOST" || data53 === "STOPPED")) {
                                                                                validate32.errors = [{ instancePath: instancePath + "/channels/screenshot/state", schemaPath: "#/$defs/channel/properties/state/enum", keyword: "enum", params: { allowedValues: schema46.properties.state.enum }, message: "must be equal to one of the allowed values" }];
                                                                                return false;
                                                                              }
                                                                              var valid14 = _errs105 === errors;
                                                                            } else {
                                                                              var valid14 = true;
                                                                            }
                                                                            if (valid14) {
                                                                              if (data52.generation !== void 0) {
                                                                                let data54 = data52.generation;
                                                                                const _errs106 = errors;
                                                                                if (!(typeof data54 == "number" && (!(data54 % 1) && !isNaN(data54)))) {
                                                                                  validate32.errors = [{ instancePath: instancePath + "/channels/screenshot/generation", schemaPath: "#/$defs/channel/properties/generation/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                                  return false;
                                                                                }
                                                                                if (errors === _errs106) {
                                                                                  if (typeof data54 == "number") {
                                                                                    if (data54 < 0 || isNaN(data54)) {
                                                                                      validate32.errors = [{ instancePath: instancePath + "/channels/screenshot/generation", schemaPath: "#/$defs/channel/properties/generation/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                                                      return false;
                                                                                    }
                                                                                  }
                                                                                }
                                                                                var valid14 = _errs106 === errors;
                                                                              } else {
                                                                                var valid14 = true;
                                                                              }
                                                                              if (valid14) {
                                                                                if (data52.readyAt !== void 0) {
                                                                                  const _errs108 = errors;
                                                                                  if (typeof data52.readyAt !== "string") {
                                                                                    validate32.errors = [{ instancePath: instancePath + "/channels/screenshot/readyAt", schemaPath: "#/$defs/channel/properties/readyAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                    return false;
                                                                                  }
                                                                                  var valid14 = _errs108 === errors;
                                                                                } else {
                                                                                  var valid14 = true;
                                                                                }
                                                                                if (valid14) {
                                                                                  if (data52.stoppedAt !== void 0) {
                                                                                    const _errs110 = errors;
                                                                                    if (typeof data52.stoppedAt !== "string") {
                                                                                      validate32.errors = [{ instancePath: instancePath + "/channels/screenshot/stoppedAt", schemaPath: "#/$defs/channel/properties/stoppedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                      return false;
                                                                                    }
                                                                                    var valid14 = _errs110 === errors;
                                                                                  } else {
                                                                                    var valid14 = true;
                                                                                  }
                                                                                  if (valid14) {
                                                                                    if (data52.reason !== void 0) {
                                                                                      const _errs112 = errors;
                                                                                      if (typeof data52.reason !== "string") {
                                                                                        validate32.errors = [{ instancePath: instancePath + "/channels/screenshot/reason", schemaPath: "#/$defs/channel/properties/reason/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                        return false;
                                                                                      }
                                                                                      var valid14 = _errs112 === errors;
                                                                                    } else {
                                                                                      var valid14 = true;
                                                                                    }
                                                                                  }
                                                                                }
                                                                              }
                                                                            }
                                                                          }
                                                                        } else {
                                                                          validate32.errors = [{ instancePath: instancePath + "/channels/screenshot", schemaPath: "#/$defs/channel/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                          return false;
                                                                        }
                                                                      }
                                                                      var valid4 = _errs102 === errors;
                                                                    } else {
                                                                      var valid4 = true;
                                                                    }
                                                                  }
                                                                }
                                                              }
                                                            }
                                                          }
                                                        } else {
                                                          validate32.errors = [{ instancePath: instancePath + "/channels", schemaPath: "#/properties/channels/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                          return false;
                                                        }
                                                      }
                                                      var valid0 = _errs52 === errors;
                                                    } else {
                                                      var valid0 = true;
                                                    }
                                                    if (valid0) {
                                                      if (data.quality !== void 0) {
                                                        let data58 = data.quality;
                                                        const _errs114 = errors;
                                                        if (!(data58 === "complete_within_declared_scope" || data58 === "partial" || data58 === "unavailable")) {
                                                          validate32.errors = [{ instancePath: instancePath + "/quality", schemaPath: "#/properties/quality/enum", keyword: "enum", params: { allowedValues: schema50.properties.quality.enum }, message: "must be equal to one of the allowed values" }];
                                                          return false;
                                                        }
                                                        var valid0 = _errs114 === errors;
                                                      } else {
                                                        var valid0 = true;
                                                      }
                                                      if (valid0) {
                                                        if (data.possibleInitialGap !== void 0) {
                                                          const _errs115 = errors;
                                                          if (typeof data.possibleInitialGap !== "boolean") {
                                                            validate32.errors = [{ instancePath: instancePath + "/possibleInitialGap", schemaPath: "#/properties/possibleInitialGap/type", keyword: "type", params: { type: "boolean" }, message: "must be boolean" }];
                                                            return false;
                                                          }
                                                          var valid0 = _errs115 === errors;
                                                        } else {
                                                          var valid0 = true;
                                                        }
                                                        if (valid0) {
                                                          if (data.finalFlushConfirmed !== void 0) {
                                                            const _errs117 = errors;
                                                            if (typeof data.finalFlushConfirmed !== "boolean") {
                                                              validate32.errors = [{ instancePath: instancePath + "/finalFlushConfirmed", schemaPath: "#/properties/finalFlushConfirmed/type", keyword: "type", params: { type: "boolean" }, message: "must be boolean" }];
                                                              return false;
                                                            }
                                                            var valid0 = _errs117 === errors;
                                                          } else {
                                                            var valid0 = true;
                                                          }
                                                          if (valid0) {
                                                            if (data.lateResults !== void 0) {
                                                              let data61 = data.lateResults;
                                                              const _errs119 = errors;
                                                              if (!(typeof data61 == "number" && (!(data61 % 1) && !isNaN(data61)))) {
                                                                validate32.errors = [{ instancePath: instancePath + "/lateResults", schemaPath: "#/properties/lateResults/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                                return false;
                                                              }
                                                              if (errors === _errs119) {
                                                                if (typeof data61 == "number") {
                                                                  if (data61 < 0 || isNaN(data61)) {
                                                                    validate32.errors = [{ instancePath: instancePath + "/lateResults", schemaPath: "#/properties/lateResults/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                                    return false;
                                                                  }
                                                                }
                                                              }
                                                              var valid0 = _errs119 === errors;
                                                            } else {
                                                              var valid0 = true;
                                                            }
                                                            if (valid0) {
                                                              if (data.documents !== void 0) {
                                                                let data62 = data.documents;
                                                                const _errs121 = errors;
                                                                if (errors === _errs121) {
                                                                  if (Array.isArray(data62)) {
                                                                    var valid15 = true;
                                                                    const len2 = data62.length;
                                                                    for (let i2 = 0; i2 < len2; i2++) {
                                                                      const _errs123 = errors;
                                                                      if (!validate31(data62[i2], { instancePath: instancePath + "/documents/" + i2, parentData: data62, parentDataProperty: i2, rootData, dynamicAnchors })) {
                                                                        vErrors = vErrors === null ? validate31.errors : vErrors.concat(validate31.errors);
                                                                        errors = vErrors.length;
                                                                      }
                                                                      var valid15 = _errs123 === errors;
                                                                      if (!valid15) {
                                                                        break;
                                                                      }
                                                                    }
                                                                  } else {
                                                                    validate32.errors = [{ instancePath: instancePath + "/documents", schemaPath: "#/properties/documents/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                                    return false;
                                                                  }
                                                                }
                                                                var valid0 = _errs121 === errors;
                                                              } else {
                                                                var valid0 = true;
                                                              }
                                                            }
                                                          }
                                                        }
                                                      }
                                                    }
                                                  }
                                                }
                                              }
                                            }
                                          }
                                        }
                                      }
                                    }
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        } else {
          validate32.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate32.errors = vErrors;
      return errors === 0;
    }
    validate32.evaluated = { "props": { "recordingId": true, "browserRunId": true, "tabInstanceId": true, "browserTabId": true, "windowId": true, "title": true, "url": true, "parentTabInstanceId": true, "rootTabInstanceIds": true, "replacesTabInstanceId": true, "membershipReason": true, "lineageEvidence": true, "scopeGrantedAt": true, "scopeGrantedSeq": true, "grantCommandId": true, "lineageConfirmedAt": true, "lifecycle": true, "captureState": true, "captureGeneration": true, "accepting": true, "channels": true, "quality": true, "possibleInitialGap": true, "finalFlushConfirmed": true, "lateResults": true, "documents": true }, "dynamicProps": false, "dynamicItems": false };
    exports.elementRef = validate34;
    function validate34(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate34.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.recorderStreamId === void 0 && (missing0 = "recorderStreamId") || data.nodeId === void 0 && (missing0 = "nodeId")) {
            validate34.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.recorderStreamId !== void 0) {
              let data0 = data.recorderStreamId;
              const _errs1 = errors;
              if (errors === _errs1) {
                if (typeof data0 === "string") {
                  if (func1(data0) > 256) {
                    validate34.errors = [{ instancePath: instancePath + "/recorderStreamId", schemaPath: "#/properties/recorderStreamId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                    return false;
                  } else {
                    if (func1(data0) < 1) {
                      validate34.errors = [{ instancePath: instancePath + "/recorderStreamId", schemaPath: "#/properties/recorderStreamId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                      return false;
                    }
                  }
                } else {
                  validate34.errors = [{ instancePath: instancePath + "/recorderStreamId", schemaPath: "#/properties/recorderStreamId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                  return false;
                }
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.nodeId !== void 0) {
                let data1 = data.nodeId;
                const _errs3 = errors;
                if (!(typeof data1 == "number" && (!(data1 % 1) && !isNaN(data1)))) {
                  validate34.errors = [{ instancePath: instancePath + "/nodeId", schemaPath: "#/properties/nodeId/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                  return false;
                }
                if (errors === _errs3) {
                  if (typeof data1 == "number") {
                    if (data1 < 0 || isNaN(data1)) {
                      validate34.errors = [{ instancePath: instancePath + "/nodeId", schemaPath: "#/properties/nodeId/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                      return false;
                    }
                  }
                }
                var valid0 = _errs3 === errors;
              } else {
                var valid0 = true;
              }
            }
          }
        } else {
          validate34.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate34.errors = vErrors;
      return errors === 0;
    }
    validate34.evaluated = { "props": { "recorderStreamId": true, "nodeId": true }, "dynamicProps": false, "dynamicItems": false };
    exports.semanticTarget = validate35;
    function validate35(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate35.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      const _errs0 = errors;
      let valid0 = false;
      const _errs1 = errors;
      if (errors === _errs1) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          if (data.elementRef !== void 0) {
            let data0 = data.elementRef;
            const _errs4 = errors;
            let valid2 = false;
            const _errs5 = errors;
            const _errs6 = errors;
            if (errors === _errs6) {
              if (data0 && typeof data0 == "object" && !Array.isArray(data0)) {
                let missing0;
                if (data0.recorderStreamId === void 0 && (missing0 = "recorderStreamId") || data0.nodeId === void 0 && (missing0 = "nodeId")) {
                  const err0 = { instancePath: instancePath + "/elementRef", schemaPath: "#/$defs/elementRef/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" };
                  if (vErrors === null) {
                    vErrors = [err0];
                  } else {
                    vErrors.push(err0);
                  }
                  errors++;
                } else {
                  if (data0.recorderStreamId !== void 0) {
                    let data1 = data0.recorderStreamId;
                    const _errs8 = errors;
                    if (errors === _errs8) {
                      if (typeof data1 === "string") {
                        if (func1(data1) > 256) {
                          const err1 = { instancePath: instancePath + "/elementRef/recorderStreamId", schemaPath: "#/$defs/elementRef/properties/recorderStreamId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" };
                          if (vErrors === null) {
                            vErrors = [err1];
                          } else {
                            vErrors.push(err1);
                          }
                          errors++;
                        } else {
                          if (func1(data1) < 1) {
                            const err2 = { instancePath: instancePath + "/elementRef/recorderStreamId", schemaPath: "#/$defs/elementRef/properties/recorderStreamId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" };
                            if (vErrors === null) {
                              vErrors = [err2];
                            } else {
                              vErrors.push(err2);
                            }
                            errors++;
                          }
                        }
                      } else {
                        const err3 = { instancePath: instancePath + "/elementRef/recorderStreamId", schemaPath: "#/$defs/elementRef/properties/recorderStreamId/type", keyword: "type", params: { type: "string" }, message: "must be string" };
                        if (vErrors === null) {
                          vErrors = [err3];
                        } else {
                          vErrors.push(err3);
                        }
                        errors++;
                      }
                    }
                    var valid4 = _errs8 === errors;
                  } else {
                    var valid4 = true;
                  }
                  if (valid4) {
                    if (data0.nodeId !== void 0) {
                      let data2 = data0.nodeId;
                      const _errs10 = errors;
                      if (!(typeof data2 == "number" && (!(data2 % 1) && !isNaN(data2)))) {
                        const err4 = { instancePath: instancePath + "/elementRef/nodeId", schemaPath: "#/$defs/elementRef/properties/nodeId/type", keyword: "type", params: { type: "integer" }, message: "must be integer" };
                        if (vErrors === null) {
                          vErrors = [err4];
                        } else {
                          vErrors.push(err4);
                        }
                        errors++;
                      }
                      if (errors === _errs10) {
                        if (typeof data2 == "number") {
                          if (data2 < 0 || isNaN(data2)) {
                            const err5 = { instancePath: instancePath + "/elementRef/nodeId", schemaPath: "#/$defs/elementRef/properties/nodeId/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" };
                            if (vErrors === null) {
                              vErrors = [err5];
                            } else {
                              vErrors.push(err5);
                            }
                            errors++;
                          }
                        }
                      }
                      var valid4 = _errs10 === errors;
                    } else {
                      var valid4 = true;
                    }
                  }
                }
              } else {
                const err6 = { instancePath: instancePath + "/elementRef", schemaPath: "#/$defs/elementRef/type", keyword: "type", params: { type: "object" }, message: "must be object" };
                if (vErrors === null) {
                  vErrors = [err6];
                } else {
                  vErrors.push(err6);
                }
                errors++;
              }
            }
            var _valid1 = _errs5 === errors;
            valid2 = valid2 || _valid1;
            if (_valid1) {
              var props0 = {};
              props0.recorderStreamId = true;
              props0.nodeId = true;
            }
            const _errs12 = errors;
            if (data0 !== null) {
              const err7 = { instancePath: instancePath + "/elementRef", schemaPath: "#/anyOf/0/properties/elementRef/anyOf/1/type", keyword: "type", params: { type: "null" }, message: "must be null" };
              if (vErrors === null) {
                vErrors = [err7];
              } else {
                vErrors.push(err7);
              }
              errors++;
            }
            var _valid1 = _errs12 === errors;
            valid2 = valid2 || _valid1;
            if (!valid2) {
              const err8 = { instancePath: instancePath + "/elementRef", schemaPath: "#/anyOf/0/properties/elementRef/anyOf", keyword: "anyOf", params: {}, message: "must match a schema in anyOf" };
              if (vErrors === null) {
                vErrors = [err8];
              } else {
                vErrors.push(err8);
              }
              errors++;
            } else {
              errors = _errs4;
              if (vErrors !== null) {
                if (_errs4) {
                  vErrors.length = _errs4;
                } else {
                  vErrors = null;
                }
              }
            }
          }
        } else {
          const err9 = { instancePath, schemaPath: "#/anyOf/0/type", keyword: "type", params: { type: "object" }, message: "must be object" };
          if (vErrors === null) {
            vErrors = [err9];
          } else {
            vErrors.push(err9);
          }
          errors++;
        }
      }
      var _valid0 = _errs1 === errors;
      valid0 = valid0 || _valid0;
      if (_valid0) {
        var props1 = {};
        props1.elementRef = true;
      }
      const _errs14 = errors;
      if (data !== null) {
        const err10 = { instancePath, schemaPath: "#/anyOf/1/type", keyword: "type", params: { type: "null" }, message: "must be null" };
        if (vErrors === null) {
          vErrors = [err10];
        } else {
          vErrors.push(err10);
        }
        errors++;
      }
      var _valid0 = _errs14 === errors;
      valid0 = valid0 || _valid0;
      if (!valid0) {
        const err11 = { instancePath, schemaPath: "#/anyOf", keyword: "anyOf", params: {}, message: "must match a schema in anyOf" };
        if (vErrors === null) {
          vErrors = [err11];
        } else {
          vErrors.push(err11);
        }
        errors++;
        validate35.errors = vErrors;
        return false;
      } else {
        errors = _errs0;
        if (vErrors !== null) {
          if (_errs0) {
            vErrors.length = _errs0;
          } else {
            vErrors = null;
          }
        }
      }
      validate35.errors = vErrors;
      evaluated0.props = props1;
      return errors === 0;
    }
    validate35.evaluated = { "dynamicProps": true, "dynamicItems": false };
    exports.payload = validate36;
    function validate36(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate36.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          if (data.action !== void 0) {
            const _errs1 = errors;
            if (typeof data.action !== "string") {
              validate36.errors = [{ instancePath: instancePath + "/action", schemaPath: "#/properties/action/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
              return false;
            }
            var valid0 = _errs1 === errors;
          } else {
            var valid0 = true;
          }
          if (valid0) {
            if (data.evidenceRefs !== void 0) {
              let data1 = data.evidenceRefs;
              const _errs3 = errors;
              if (errors === _errs3) {
                if (Array.isArray(data1)) {
                  var valid1 = true;
                  const len0 = data1.length;
                  for (let i0 = 0; i0 < len0; i0++) {
                    let data2 = data1[i0];
                    const _errs5 = errors;
                    if (errors === _errs5) {
                      if (typeof data2 === "string") {
                        if (func1(data2) > 256) {
                          validate36.errors = [{ instancePath: instancePath + "/evidenceRefs/" + i0, schemaPath: "#/properties/evidenceRefs/items/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                          return false;
                        } else {
                          if (func1(data2) < 1) {
                            validate36.errors = [{ instancePath: instancePath + "/evidenceRefs/" + i0, schemaPath: "#/properties/evidenceRefs/items/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                            return false;
                          }
                        }
                      } else {
                        validate36.errors = [{ instancePath: instancePath + "/evidenceRefs/" + i0, schemaPath: "#/properties/evidenceRefs/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                        return false;
                      }
                    }
                    var valid1 = _errs5 === errors;
                    if (!valid1) {
                      break;
                    }
                  }
                } else {
                  validate36.errors = [{ instancePath: instancePath + "/evidenceRefs", schemaPath: "#/properties/evidenceRefs/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                  return false;
                }
              }
              var valid0 = _errs3 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.target !== void 0) {
                const _errs7 = errors;
                if (!validate35(data.target, { instancePath: instancePath + "/target", parentData: data, parentDataProperty: "target", rootData, dynamicAnchors })) {
                  vErrors = vErrors === null ? validate35.errors : vErrors.concat(validate35.errors);
                  errors = vErrors.length;
                }
                var valid0 = _errs7 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.nodeContexts !== void 0) {
                  let data4 = data.nodeContexts;
                  const _errs8 = errors;
                  if (errors === _errs8) {
                    if (Array.isArray(data4)) {
                      var valid2 = true;
                      const len1 = data4.length;
                      for (let i1 = 0; i1 < len1; i1++) {
                        let data5 = data4[i1];
                        const _errs10 = errors;
                        if (errors === _errs10) {
                          if (data5 && typeof data5 == "object" && !Array.isArray(data5)) {
                            let missing0;
                            if (data5.nodeId === void 0 && (missing0 = "nodeId") || data5.recorderStreamId === void 0 && (missing0 = "recorderStreamId") || data5.context === void 0 && (missing0 = "context")) {
                              validate36.errors = [{ instancePath: instancePath + "/nodeContexts/" + i1, schemaPath: "#/properties/nodeContexts/items/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
                              return false;
                            } else {
                              if (data5.nodeId !== void 0) {
                                let data6 = data5.nodeId;
                                const _errs12 = errors;
                                if (!(typeof data6 == "number" && (!(data6 % 1) && !isNaN(data6)))) {
                                  validate36.errors = [{ instancePath: instancePath + "/nodeContexts/" + i1 + "/nodeId", schemaPath: "#/properties/nodeContexts/items/properties/nodeId/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                  return false;
                                }
                                if (errors === _errs12) {
                                  if (typeof data6 == "number") {
                                    if (data6 < 0 || isNaN(data6)) {
                                      validate36.errors = [{ instancePath: instancePath + "/nodeContexts/" + i1 + "/nodeId", schemaPath: "#/properties/nodeContexts/items/properties/nodeId/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                      return false;
                                    }
                                  }
                                }
                                var valid3 = _errs12 === errors;
                              } else {
                                var valid3 = true;
                              }
                              if (valid3) {
                                if (data5.recorderStreamId !== void 0) {
                                  let data7 = data5.recorderStreamId;
                                  const _errs14 = errors;
                                  if (errors === _errs14) {
                                    if (typeof data7 === "string") {
                                      if (func1(data7) > 256) {
                                        validate36.errors = [{ instancePath: instancePath + "/nodeContexts/" + i1 + "/recorderStreamId", schemaPath: "#/properties/nodeContexts/items/properties/recorderStreamId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                        return false;
                                      } else {
                                        if (func1(data7) < 1) {
                                          validate36.errors = [{ instancePath: instancePath + "/nodeContexts/" + i1 + "/recorderStreamId", schemaPath: "#/properties/nodeContexts/items/properties/recorderStreamId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                          return false;
                                        }
                                      }
                                    } else {
                                      validate36.errors = [{ instancePath: instancePath + "/nodeContexts/" + i1 + "/recorderStreamId", schemaPath: "#/properties/nodeContexts/items/properties/recorderStreamId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                      return false;
                                    }
                                  }
                                  var valid3 = _errs14 === errors;
                                } else {
                                  var valid3 = true;
                                }
                                if (valid3) {
                                  if (data5.documentRoot !== void 0) {
                                    const _errs16 = errors;
                                    if (typeof data5.documentRoot !== "boolean") {
                                      validate36.errors = [{ instancePath: instancePath + "/nodeContexts/" + i1 + "/documentRoot", schemaPath: "#/properties/nodeContexts/items/properties/documentRoot/type", keyword: "type", params: { type: "boolean" }, message: "must be boolean" }];
                                      return false;
                                    }
                                    var valid3 = _errs16 === errors;
                                  } else {
                                    var valid3 = true;
                                  }
                                  if (valid3) {
                                    if (data5.context !== void 0) {
                                      let data9 = data5.context;
                                      const _errs18 = errors;
                                      const _errs19 = errors;
                                      if (errors === _errs19) {
                                        if (data9 && typeof data9 == "object" && !Array.isArray(data9)) {
                                          let missing1;
                                          if (data9.chromeFrameId === void 0 && (missing1 = "chromeFrameId") || data9.documentId === void 0 && (missing1 = "documentId")) {
                                            validate36.errors = [{ instancePath: instancePath + "/nodeContexts/" + i1 + "/context", schemaPath: "#/$defs/context/required", keyword: "required", params: { missingProperty: missing1 }, message: "must have required property '" + missing1 + "'" }];
                                            return false;
                                          } else {
                                            if (data9.chromeFrameId !== void 0) {
                                              let data10 = data9.chromeFrameId;
                                              const _errs21 = errors;
                                              if (!(typeof data10 == "number" && (!(data10 % 1) && !isNaN(data10))) && data10 !== null) {
                                                validate36.errors = [{ instancePath: instancePath + "/nodeContexts/" + i1 + "/context/chromeFrameId", schemaPath: "#/$defs/context/properties/chromeFrameId/type", keyword: "type", params: { type: schema37.properties.chromeFrameId.type }, message: "must be integer,null" }];
                                                return false;
                                              }
                                              var valid5 = _errs21 === errors;
                                            } else {
                                              var valid5 = true;
                                            }
                                            if (valid5) {
                                              if (data9.documentId !== void 0) {
                                                let data11 = data9.documentId;
                                                const _errs23 = errors;
                                                if (typeof data11 !== "string" && data11 !== null) {
                                                  validate36.errors = [{ instancePath: instancePath + "/nodeContexts/" + i1 + "/context/documentId", schemaPath: "#/$defs/context/properties/documentId/type", keyword: "type", params: { type: schema37.properties.documentId.type }, message: "must be string,null" }];
                                                  return false;
                                                }
                                                var valid5 = _errs23 === errors;
                                              } else {
                                                var valid5 = true;
                                              }
                                              if (valid5) {
                                                if (data9.verifiedBy !== void 0) {
                                                  const _errs25 = errors;
                                                  if (typeof data9.verifiedBy !== "string") {
                                                    validate36.errors = [{ instancePath: instancePath + "/nodeContexts/" + i1 + "/context/verifiedBy", schemaPath: "#/$defs/context/properties/verifiedBy/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                    return false;
                                                  }
                                                  var valid5 = _errs25 === errors;
                                                } else {
                                                  var valid5 = true;
                                                }
                                                if (valid5) {
                                                  if (data9.status !== void 0) {
                                                    const _errs27 = errors;
                                                    if (typeof data9.status !== "string") {
                                                      validate36.errors = [{ instancePath: instancePath + "/nodeContexts/" + i1 + "/context/status", schemaPath: "#/$defs/context/properties/status/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                      return false;
                                                    }
                                                    var valid5 = _errs27 === errors;
                                                  } else {
                                                    var valid5 = true;
                                                  }
                                                  if (valid5) {
                                                    if (data9.reason !== void 0) {
                                                      const _errs29 = errors;
                                                      if (typeof data9.reason !== "string") {
                                                        validate36.errors = [{ instancePath: instancePath + "/nodeContexts/" + i1 + "/context/reason", schemaPath: "#/$defs/context/properties/reason/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                        return false;
                                                      }
                                                      var valid5 = _errs29 === errors;
                                                    } else {
                                                      var valid5 = true;
                                                    }
                                                  }
                                                }
                                              }
                                            }
                                          }
                                        } else {
                                          validate36.errors = [{ instancePath: instancePath + "/nodeContexts/" + i1 + "/context", schemaPath: "#/$defs/context/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                          return false;
                                        }
                                      }
                                      var valid3 = _errs18 === errors;
                                    } else {
                                      var valid3 = true;
                                    }
                                  }
                                }
                              }
                            }
                          } else {
                            validate36.errors = [{ instancePath: instancePath + "/nodeContexts/" + i1, schemaPath: "#/properties/nodeContexts/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                            return false;
                          }
                        }
                        var valid2 = _errs10 === errors;
                        if (!valid2) {
                          break;
                        }
                      }
                    } else {
                      validate36.errors = [{ instancePath: instancePath + "/nodeContexts", schemaPath: "#/properties/nodeContexts/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                      return false;
                    }
                  }
                  var valid0 = _errs8 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.before !== void 0) {
                    let data15 = data.before;
                    const _errs31 = errors;
                    if (!(data15 && typeof data15 == "object" && !Array.isArray(data15))) {
                      validate36.errors = [{ instancePath: instancePath + "/before", schemaPath: "#/properties/before/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                      return false;
                    }
                    var valid0 = _errs31 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.after !== void 0) {
                      let data16 = data.after;
                      const _errs33 = errors;
                      if (!(data16 && typeof data16 == "object" && !Array.isArray(data16))) {
                        validate36.errors = [{ instancePath: instancePath + "/after", schemaPath: "#/properties/after/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                        return false;
                      }
                      var valid0 = _errs33 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.context !== void 0) {
                        let data17 = data.context;
                        const _errs35 = errors;
                        if (!(data17 && typeof data17 == "object" && !Array.isArray(data17))) {
                          validate36.errors = [{ instancePath: instancePath + "/context", schemaPath: "#/properties/context/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                          return false;
                        }
                        var valid0 = _errs35 === errors;
                      } else {
                        var valid0 = true;
                      }
                      if (valid0) {
                        if (data.phase !== void 0) {
                          const _errs37 = errors;
                          if (typeof data.phase !== "string") {
                            validate36.errors = [{ instancePath: instancePath + "/phase", schemaPath: "#/properties/phase/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                            return false;
                          }
                          var valid0 = _errs37 === errors;
                        } else {
                          var valid0 = true;
                        }
                        if (valid0) {
                          if (data.omissions !== void 0) {
                            let data19 = data.omissions;
                            const _errs39 = errors;
                            if (errors === _errs39) {
                              if (Array.isArray(data19)) {
                                if (data19.length > 4096) {
                                  validate36.errors = [{ instancePath: instancePath + "/omissions", schemaPath: "#/properties/omissions/maxItems", keyword: "maxItems", params: { limit: 4096 }, message: "must NOT have more than 4096 items" }];
                                  return false;
                                } else {
                                  var valid6 = true;
                                  const len2 = data19.length;
                                  for (let i2 = 0; i2 < len2; i2++) {
                                    let data20 = data19[i2];
                                    const _errs41 = errors;
                                    if (errors === _errs41) {
                                      if (data20 && typeof data20 == "object" && !Array.isArray(data20)) {
                                        let missing2;
                                        if (data20.scope === void 0 && (missing2 = "scope") || data20.count === void 0 && (missing2 = "count") || data20.exact === void 0 && (missing2 = "exact") || data20.reason === void 0 && (missing2 = "reason")) {
                                          validate36.errors = [{ instancePath: instancePath + "/omissions/" + i2, schemaPath: "#/properties/omissions/items/required", keyword: "required", params: { missingProperty: missing2 }, message: "must have required property '" + missing2 + "'" }];
                                          return false;
                                        } else {
                                          if (data20.scope !== void 0) {
                                            const _errs43 = errors;
                                            if (typeof data20.scope !== "string") {
                                              validate36.errors = [{ instancePath: instancePath + "/omissions/" + i2 + "/scope", schemaPath: "#/properties/omissions/items/properties/scope/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                              return false;
                                            }
                                            var valid7 = _errs43 === errors;
                                          } else {
                                            var valid7 = true;
                                          }
                                          if (valid7) {
                                            if (data20.count !== void 0) {
                                              let data22 = data20.count;
                                              const _errs45 = errors;
                                              if (!(typeof data22 == "number" && (!(data22 % 1) && !isNaN(data22)))) {
                                                validate36.errors = [{ instancePath: instancePath + "/omissions/" + i2 + "/count", schemaPath: "#/properties/omissions/items/properties/count/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                return false;
                                              }
                                              if (errors === _errs45) {
                                                if (typeof data22 == "number") {
                                                  if (data22 < 1 || isNaN(data22)) {
                                                    validate36.errors = [{ instancePath: instancePath + "/omissions/" + i2 + "/count", schemaPath: "#/properties/omissions/items/properties/count/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                                    return false;
                                                  }
                                                }
                                              }
                                              var valid7 = _errs45 === errors;
                                            } else {
                                              var valid7 = true;
                                            }
                                            if (valid7) {
                                              if (data20.exact !== void 0) {
                                                const _errs47 = errors;
                                                if (typeof data20.exact !== "boolean") {
                                                  validate36.errors = [{ instancePath: instancePath + "/omissions/" + i2 + "/exact", schemaPath: "#/properties/omissions/items/properties/exact/type", keyword: "type", params: { type: "boolean" }, message: "must be boolean" }];
                                                  return false;
                                                }
                                                var valid7 = _errs47 === errors;
                                              } else {
                                                var valid7 = true;
                                              }
                                              if (valid7) {
                                                if (data20.reason !== void 0) {
                                                  const _errs49 = errors;
                                                  if (typeof data20.reason !== "string") {
                                                    validate36.errors = [{ instancePath: instancePath + "/omissions/" + i2 + "/reason", schemaPath: "#/properties/omissions/items/properties/reason/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                    return false;
                                                  }
                                                  var valid7 = _errs49 === errors;
                                                } else {
                                                  var valid7 = true;
                                                }
                                              }
                                            }
                                          }
                                        }
                                      } else {
                                        validate36.errors = [{ instancePath: instancePath + "/omissions/" + i2, schemaPath: "#/properties/omissions/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                        return false;
                                      }
                                    }
                                    var valid6 = _errs41 === errors;
                                    if (!valid6) {
                                      break;
                                    }
                                  }
                                }
                              } else {
                                validate36.errors = [{ instancePath: instancePath + "/omissions", schemaPath: "#/properties/omissions/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                return false;
                              }
                            }
                            var valid0 = _errs39 === errors;
                          } else {
                            var valid0 = true;
                          }
                          if (valid0) {
                            if (data.observation !== void 0) {
                              let data25 = data.observation;
                              const _errs51 = errors;
                              if (errors === _errs51) {
                                if (data25 && typeof data25 == "object" && !Array.isArray(data25)) {
                                  let missing3;
                                  if (data25.sourceTime === void 0 && (missing3 = "sourceTime") || data25.sourceClock === void 0 && (missing3 = "sourceClock")) {
                                    validate36.errors = [{ instancePath: instancePath + "/observation", schemaPath: "#/properties/observation/required", keyword: "required", params: { missingProperty: missing3 }, message: "must have required property '" + missing3 + "'" }];
                                    return false;
                                  } else {
                                    if (data25.sourceTime !== void 0) {
                                      const _errs53 = errors;
                                      if (!(typeof data25.sourceTime == "number")) {
                                        validate36.errors = [{ instancePath: instancePath + "/observation/sourceTime", schemaPath: "#/properties/observation/properties/sourceTime/type", keyword: "type", params: { type: "number" }, message: "must be number" }];
                                        return false;
                                      }
                                      var valid8 = _errs53 === errors;
                                    } else {
                                      var valid8 = true;
                                    }
                                    if (valid8) {
                                      if (data25.sourceClock !== void 0) {
                                        const _errs55 = errors;
                                        if ("document_performance_ms" !== data25.sourceClock) {
                                          validate36.errors = [{ instancePath: instancePath + "/observation/sourceClock", schemaPath: "#/properties/observation/properties/sourceClock/const", keyword: "const", params: { allowedValue: "document_performance_ms" }, message: "must be equal to constant" }];
                                          return false;
                                        }
                                        var valid8 = _errs55 === errors;
                                      } else {
                                        var valid8 = true;
                                      }
                                    }
                                  }
                                } else {
                                  validate36.errors = [{ instancePath: instancePath + "/observation", schemaPath: "#/properties/observation/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                  return false;
                                }
                              }
                              var valid0 = _errs51 === errors;
                            } else {
                              var valid0 = true;
                            }
                            if (valid0) {
                              if (data.documentContext !== void 0) {
                                let data28 = data.documentContext;
                                const _errs56 = errors;
                                const _errs57 = errors;
                                let valid9 = false;
                                const _errs58 = errors;
                                const _errs59 = errors;
                                if (errors === _errs59) {
                                  if (data28 && typeof data28 == "object" && !Array.isArray(data28)) {
                                    let missing4;
                                    if (data28.chromeFrameId === void 0 && (missing4 = "chromeFrameId") || data28.documentId === void 0 && (missing4 = "documentId")) {
                                      const err0 = { instancePath: instancePath + "/documentContext", schemaPath: "#/$defs/context/required", keyword: "required", params: { missingProperty: missing4 }, message: "must have required property '" + missing4 + "'" };
                                      if (vErrors === null) {
                                        vErrors = [err0];
                                      } else {
                                        vErrors.push(err0);
                                      }
                                      errors++;
                                    } else {
                                      if (data28.chromeFrameId !== void 0) {
                                        let data29 = data28.chromeFrameId;
                                        const _errs61 = errors;
                                        if (!(typeof data29 == "number" && (!(data29 % 1) && !isNaN(data29))) && data29 !== null) {
                                          const err1 = { instancePath: instancePath + "/documentContext/chromeFrameId", schemaPath: "#/$defs/context/properties/chromeFrameId/type", keyword: "type", params: { type: schema37.properties.chromeFrameId.type }, message: "must be integer,null" };
                                          if (vErrors === null) {
                                            vErrors = [err1];
                                          } else {
                                            vErrors.push(err1);
                                          }
                                          errors++;
                                        }
                                        var valid11 = _errs61 === errors;
                                      } else {
                                        var valid11 = true;
                                      }
                                      if (valid11) {
                                        if (data28.documentId !== void 0) {
                                          let data30 = data28.documentId;
                                          const _errs63 = errors;
                                          if (typeof data30 !== "string" && data30 !== null) {
                                            const err2 = { instancePath: instancePath + "/documentContext/documentId", schemaPath: "#/$defs/context/properties/documentId/type", keyword: "type", params: { type: schema37.properties.documentId.type }, message: "must be string,null" };
                                            if (vErrors === null) {
                                              vErrors = [err2];
                                            } else {
                                              vErrors.push(err2);
                                            }
                                            errors++;
                                          }
                                          var valid11 = _errs63 === errors;
                                        } else {
                                          var valid11 = true;
                                        }
                                        if (valid11) {
                                          if (data28.verifiedBy !== void 0) {
                                            const _errs65 = errors;
                                            if (typeof data28.verifiedBy !== "string") {
                                              const err3 = { instancePath: instancePath + "/documentContext/verifiedBy", schemaPath: "#/$defs/context/properties/verifiedBy/type", keyword: "type", params: { type: "string" }, message: "must be string" };
                                              if (vErrors === null) {
                                                vErrors = [err3];
                                              } else {
                                                vErrors.push(err3);
                                              }
                                              errors++;
                                            }
                                            var valid11 = _errs65 === errors;
                                          } else {
                                            var valid11 = true;
                                          }
                                          if (valid11) {
                                            if (data28.status !== void 0) {
                                              const _errs67 = errors;
                                              if (typeof data28.status !== "string") {
                                                const err4 = { instancePath: instancePath + "/documentContext/status", schemaPath: "#/$defs/context/properties/status/type", keyword: "type", params: { type: "string" }, message: "must be string" };
                                                if (vErrors === null) {
                                                  vErrors = [err4];
                                                } else {
                                                  vErrors.push(err4);
                                                }
                                                errors++;
                                              }
                                              var valid11 = _errs67 === errors;
                                            } else {
                                              var valid11 = true;
                                            }
                                            if (valid11) {
                                              if (data28.reason !== void 0) {
                                                const _errs69 = errors;
                                                if (typeof data28.reason !== "string") {
                                                  const err5 = { instancePath: instancePath + "/documentContext/reason", schemaPath: "#/$defs/context/properties/reason/type", keyword: "type", params: { type: "string" }, message: "must be string" };
                                                  if (vErrors === null) {
                                                    vErrors = [err5];
                                                  } else {
                                                    vErrors.push(err5);
                                                  }
                                                  errors++;
                                                }
                                                var valid11 = _errs69 === errors;
                                              } else {
                                                var valid11 = true;
                                              }
                                            }
                                          }
                                        }
                                      }
                                    }
                                  } else {
                                    const err6 = { instancePath: instancePath + "/documentContext", schemaPath: "#/$defs/context/type", keyword: "type", params: { type: "object" }, message: "must be object" };
                                    if (vErrors === null) {
                                      vErrors = [err6];
                                    } else {
                                      vErrors.push(err6);
                                    }
                                    errors++;
                                  }
                                }
                                var _valid0 = _errs58 === errors;
                                valid9 = valid9 || _valid0;
                                if (_valid0) {
                                  var props1 = {};
                                  props1.chromeFrameId = true;
                                  props1.documentId = true;
                                  props1.verifiedBy = true;
                                  props1.status = true;
                                  props1.reason = true;
                                }
                                const _errs71 = errors;
                                if (data28 !== null) {
                                  const err7 = { instancePath: instancePath + "/documentContext", schemaPath: "#/properties/documentContext/anyOf/1/type", keyword: "type", params: { type: "null" }, message: "must be null" };
                                  if (vErrors === null) {
                                    vErrors = [err7];
                                  } else {
                                    vErrors.push(err7);
                                  }
                                  errors++;
                                }
                                var _valid0 = _errs71 === errors;
                                valid9 = valid9 || _valid0;
                                if (!valid9) {
                                  const err8 = { instancePath: instancePath + "/documentContext", schemaPath: "#/properties/documentContext/anyOf", keyword: "anyOf", params: {}, message: "must match a schema in anyOf" };
                                  if (vErrors === null) {
                                    vErrors = [err8];
                                  } else {
                                    vErrors.push(err8);
                                  }
                                  errors++;
                                  validate36.errors = vErrors;
                                  return false;
                                } else {
                                  errors = _errs57;
                                  if (vErrors !== null) {
                                    if (_errs57) {
                                      vErrors.length = _errs57;
                                    } else {
                                      vErrors = null;
                                    }
                                  }
                                }
                                var valid0 = _errs56 === errors;
                              } else {
                                var valid0 = true;
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        } else {
          validate36.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate36.errors = vErrors;
      return errors === 0;
    }
    validate36.evaluated = { "props": { "action": true, "evidenceRefs": true, "target": true, "nodeContexts": true, "before": true, "after": true, "context": true, "phase": true, "omissions": true, "observation": true, "documentContext": true }, "dynamicProps": false, "dynamicItems": false };
    exports.event = validate38;
    var schema62 = { "type": "object", "required": ["schemaVersion", "eventId", "recordingId", "browserRunId", "streamId", "tabInstanceId", "browserTabId", "windowId", "emitterContext", "subjectContext", "source", "sourceSeq", "kind", "sourceTime", "sourceClock", "observedAt", "normalizedAt", "captureGeneration", "channel", "channelGeneration", "payload", "quality"], "properties": { "schemaVersion": { "const": "3.0.0" }, "eventId": { "type": "string", "minLength": 1, "maxLength": 256 }, "recordingId": { "type": "string", "minLength": 1, "maxLength": 256 }, "browserRunId": { "type": "string", "minLength": 1, "maxLength": 256 }, "streamId": { "type": "string", "minLength": 1, "maxLength": 256 }, "tabInstanceId": { "type": ["string", "null"] }, "browserTabId": { "type": ["integer", "null"] }, "windowId": { "type": ["integer", "null"] }, "emitterContext": { "$ref": "#/$defs/contextOrNull" }, "subjectContext": { "$ref": "#/$defs/contextOrNull" }, "source": { "type": "string" }, "recorderStreamId": { "type": "string", "minLength": 1, "maxLength": 256 }, "sourceSeq": { "type": "integer", "minimum": 1 }, "kind": { "type": "string" }, "sourceTime": { "type": ["number", "null"] }, "sourceClock": { "type": "string" }, "observedAt": { "type": "string" }, "normalizedAt": { "type": "null" }, "captureGeneration": { "type": "integer", "minimum": 0 }, "channel": { "enum": ["control", "page", "semantic", "network", "runtime", "screenshot"] }, "channelGeneration": { "type": "integer", "minimum": 0 }, "payload": { "$ref": "#/$defs/payload" }, "quality": { "type": "object", "required": ["redacted", "truncated", "limitations"], "properties": { "redacted": { "type": "boolean" }, "truncated": { "type": "boolean" }, "limitations": { "type": "array", "items": { "type": "string" } } } } }, "allOf": [{ "if": { "properties": { "kind": { "const": "ui.action" } } }, "then": { "properties": { "payload": { "required": ["action", "evidenceRefs"] } } } }, { "if": { "properties": { "kind": { "const": "rrweb.event" } } }, "then": { "properties": { "payload": { "required": ["rrwebEvent"], "properties": { "rrwebEvent": { "type": "object", "required": ["type", "timestamp"], "properties": { "type": { "type": "integer", "minimum": 0, "maximum": 6 }, "timestamp": { "type": "number" }, "data": { "type": "object" } } } } } } } }, { "if": { "properties": { "kind": { "enum": ["ui.state_snapshot", "ui.action"] } } }, "then": { "properties": { "payload": { "properties": { "before": { "$ref": "#/$defs/semanticBefore" }, "after": { "properties": { "metadataFacts": { "type": "array", "maxItems": 32, "items": { "$ref": "#/$defs/correlationFact" } } } } } } } } }] };
    var schema64 = { "type": "object", "required": ["field", "source", "value", "component", "observedAt"], "properties": { "field": { "enum": ["frontendBuildId", "backendBuildId", "serviceInstance", "requestId", "traceId", "spanId"] }, "source": { "type": "string" }, "value": { "type": "string", "minLength": 1, "maxLength": 256 }, "component": { "type": "string", "minLength": 1, "maxLength": 80 }, "observedAt": { "type": "string" } } };
    function validate38(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate38.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      const _errs1 = errors;
      const _errs2 = errors;
      let valid1 = true;
      const _errs3 = errors;
      if (data && typeof data == "object" && !Array.isArray(data)) {
        if (data.kind !== void 0) {
          if ("ui.action" !== data.kind) {
            const err0 = {};
            if (vErrors === null) {
              vErrors = [err0];
            } else {
              vErrors.push(err0);
            }
            errors++;
          }
        }
      }
      var _valid0 = _errs3 === errors;
      errors = _errs2;
      if (vErrors !== null) {
        if (_errs2) {
          vErrors.length = _errs2;
        } else {
          vErrors = null;
        }
      }
      if (_valid0) {
        const _errs5 = errors;
        if (data && typeof data == "object" && !Array.isArray(data)) {
          if (data.payload !== void 0) {
            let data1 = data.payload;
            if (data1 && typeof data1 == "object" && !Array.isArray(data1)) {
              let missing0;
              if (data1.action === void 0 && (missing0 = "action") || data1.evidenceRefs === void 0 && (missing0 = "evidenceRefs")) {
                validate38.errors = [{ instancePath: instancePath + "/payload", schemaPath: "#/allOf/0/then/properties/payload/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
                return false;
              }
            }
          }
        }
        var _valid0 = _errs5 === errors;
        valid1 = _valid0;
        if (valid1) {
          var props0 = {};
          props0.payload = true;
          props0.kind = true;
        }
      }
      if (!valid1) {
        const err1 = { instancePath, schemaPath: "#/allOf/0/if", keyword: "if", params: { failingKeyword: "then" }, message: 'must match "then" schema' };
        if (vErrors === null) {
          vErrors = [err1];
        } else {
          vErrors.push(err1);
        }
        errors++;
        validate38.errors = vErrors;
        return false;
      }
      var valid0 = _errs1 === errors;
      if (valid0) {
        const _errs7 = errors;
        const _errs8 = errors;
        let valid4 = true;
        const _errs9 = errors;
        if (data && typeof data == "object" && !Array.isArray(data)) {
          if (data.kind !== void 0) {
            if ("rrweb.event" !== data.kind) {
              const err2 = {};
              if (vErrors === null) {
                vErrors = [err2];
              } else {
                vErrors.push(err2);
              }
              errors++;
            }
          }
        }
        var _valid1 = _errs9 === errors;
        errors = _errs8;
        if (vErrors !== null) {
          if (_errs8) {
            vErrors.length = _errs8;
          } else {
            vErrors = null;
          }
        }
        if (_valid1) {
          const _errs11 = errors;
          if (data && typeof data == "object" && !Array.isArray(data)) {
            if (data.payload !== void 0) {
              let data3 = data.payload;
              if (data3 && typeof data3 == "object" && !Array.isArray(data3)) {
                let missing1;
                if (data3.rrwebEvent === void 0 && (missing1 = "rrwebEvent")) {
                  validate38.errors = [{ instancePath: instancePath + "/payload", schemaPath: "#/allOf/1/then/properties/payload/required", keyword: "required", params: { missingProperty: missing1 }, message: "must have required property '" + missing1 + "'" }];
                  return false;
                } else {
                  if (data3.rrwebEvent !== void 0) {
                    let data4 = data3.rrwebEvent;
                    const _errs13 = errors;
                    if (errors === _errs13) {
                      if (data4 && typeof data4 == "object" && !Array.isArray(data4)) {
                        let missing2;
                        if (data4.type === void 0 && (missing2 = "type") || data4.timestamp === void 0 && (missing2 = "timestamp")) {
                          validate38.errors = [{ instancePath: instancePath + "/payload/rrwebEvent", schemaPath: "#/allOf/1/then/properties/payload/properties/rrwebEvent/required", keyword: "required", params: { missingProperty: missing2 }, message: "must have required property '" + missing2 + "'" }];
                          return false;
                        } else {
                          if (data4.type !== void 0) {
                            let data5 = data4.type;
                            const _errs15 = errors;
                            if (!(typeof data5 == "number" && (!(data5 % 1) && !isNaN(data5)))) {
                              validate38.errors = [{ instancePath: instancePath + "/payload/rrwebEvent/type", schemaPath: "#/allOf/1/then/properties/payload/properties/rrwebEvent/properties/type/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                              return false;
                            }
                            if (errors === _errs15) {
                              if (typeof data5 == "number") {
                                if (data5 > 6 || isNaN(data5)) {
                                  validate38.errors = [{ instancePath: instancePath + "/payload/rrwebEvent/type", schemaPath: "#/allOf/1/then/properties/payload/properties/rrwebEvent/properties/type/maximum", keyword: "maximum", params: { comparison: "<=", limit: 6 }, message: "must be <= 6" }];
                                  return false;
                                } else {
                                  if (data5 < 0 || isNaN(data5)) {
                                    validate38.errors = [{ instancePath: instancePath + "/payload/rrwebEvent/type", schemaPath: "#/allOf/1/then/properties/payload/properties/rrwebEvent/properties/type/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                    return false;
                                  }
                                }
                              }
                            }
                            var valid8 = _errs15 === errors;
                          } else {
                            var valid8 = true;
                          }
                          if (valid8) {
                            if (data4.timestamp !== void 0) {
                              const _errs17 = errors;
                              if (!(typeof data4.timestamp == "number")) {
                                validate38.errors = [{ instancePath: instancePath + "/payload/rrwebEvent/timestamp", schemaPath: "#/allOf/1/then/properties/payload/properties/rrwebEvent/properties/timestamp/type", keyword: "type", params: { type: "number" }, message: "must be number" }];
                                return false;
                              }
                              var valid8 = _errs17 === errors;
                            } else {
                              var valid8 = true;
                            }
                            if (valid8) {
                              if (data4.data !== void 0) {
                                let data7 = data4.data;
                                const _errs19 = errors;
                                if (!(data7 && typeof data7 == "object" && !Array.isArray(data7))) {
                                  validate38.errors = [{ instancePath: instancePath + "/payload/rrwebEvent/data", schemaPath: "#/allOf/1/then/properties/payload/properties/rrwebEvent/properties/data/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                  return false;
                                }
                                var valid8 = _errs19 === errors;
                              } else {
                                var valid8 = true;
                              }
                            }
                          }
                        }
                      } else {
                        validate38.errors = [{ instancePath: instancePath + "/payload/rrwebEvent", schemaPath: "#/allOf/1/then/properties/payload/properties/rrwebEvent/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                        return false;
                      }
                    }
                  }
                }
              }
            }
          }
          var _valid1 = _errs11 === errors;
          valid4 = _valid1;
          if (valid4) {
            var props1 = {};
            props1.payload = true;
            props1.kind = true;
          }
        }
        if (!valid4) {
          const err3 = { instancePath, schemaPath: "#/allOf/1/if", keyword: "if", params: { failingKeyword: "then" }, message: 'must match "then" schema' };
          if (vErrors === null) {
            vErrors = [err3];
          } else {
            vErrors.push(err3);
          }
          errors++;
          validate38.errors = vErrors;
          return false;
        }
        var valid0 = _errs7 === errors;
        if (valid0) {
          if (props0 !== true && props1 !== void 0) {
            if (props1 === true) {
              props0 = true;
            } else {
              props0 = props0 || {};
              Object.assign(props0, props1);
            }
          }
          const _errs21 = errors;
          const _errs22 = errors;
          let valid9 = true;
          const _errs23 = errors;
          if (data && typeof data == "object" && !Array.isArray(data)) {
            if (data.kind !== void 0) {
              let data8 = data.kind;
              if (!(data8 === "ui.state_snapshot" || data8 === "ui.action")) {
                const err4 = {};
                if (vErrors === null) {
                  vErrors = [err4];
                } else {
                  vErrors.push(err4);
                }
                errors++;
              }
            }
          }
          var _valid2 = _errs23 === errors;
          errors = _errs22;
          if (vErrors !== null) {
            if (_errs22) {
              vErrors.length = _errs22;
            } else {
              vErrors = null;
            }
          }
          if (_valid2) {
            const _errs25 = errors;
            if (data && typeof data == "object" && !Array.isArray(data)) {
              if (data.payload !== void 0) {
                let data9 = data.payload;
                if (data9 && typeof data9 == "object" && !Array.isArray(data9)) {
                  if (data9.before !== void 0) {
                    let data10 = data9.before;
                    const _errs27 = errors;
                    const _errs29 = errors;
                    let valid14 = false;
                    let passing0 = null;
                    const _errs30 = errors;
                    if (errors === _errs30) {
                      if (data10 && typeof data10 == "object" && !Array.isArray(data10)) {
                        let missing3;
                        if (data10.status === void 0 && (missing3 = "status") || data10.reason === void 0 && (missing3 = "reason")) {
                          const err5 = { instancePath: instancePath + "/payload/before", schemaPath: "#/$defs/semanticBefore/oneOf/0/required", keyword: "required", params: { missingProperty: missing3 }, message: "must have required property '" + missing3 + "'" };
                          if (vErrors === null) {
                            vErrors = [err5];
                          } else {
                            vErrors.push(err5);
                          }
                          errors++;
                        } else {
                          if (data10.status !== void 0) {
                            const _errs32 = errors;
                            if ("unavailable" !== data10.status) {
                              const err6 = { instancePath: instancePath + "/payload/before/status", schemaPath: "#/$defs/semanticBefore/oneOf/0/properties/status/const", keyword: "const", params: { allowedValue: "unavailable" }, message: "must be equal to constant" };
                              if (vErrors === null) {
                                vErrors = [err6];
                              } else {
                                vErrors.push(err6);
                              }
                              errors++;
                            }
                            var valid15 = _errs32 === errors;
                          } else {
                            var valid15 = true;
                          }
                          if (valid15) {
                            if (data10.reason !== void 0) {
                              const _errs33 = errors;
                              if (typeof data10.reason !== "string") {
                                const err7 = { instancePath: instancePath + "/payload/before/reason", schemaPath: "#/$defs/semanticBefore/oneOf/0/properties/reason/type", keyword: "type", params: { type: "string" }, message: "must be string" };
                                if (vErrors === null) {
                                  vErrors = [err7];
                                } else {
                                  vErrors.push(err7);
                                }
                                errors++;
                              }
                              var valid15 = _errs33 === errors;
                            } else {
                              var valid15 = true;
                            }
                          }
                        }
                      } else {
                        const err8 = { instancePath: instancePath + "/payload/before", schemaPath: "#/$defs/semanticBefore/oneOf/0/type", keyword: "type", params: { type: "object" }, message: "must be object" };
                        if (vErrors === null) {
                          vErrors = [err8];
                        } else {
                          vErrors.push(err8);
                        }
                        errors++;
                      }
                    }
                    var _valid3 = _errs30 === errors;
                    if (_valid3) {
                      valid14 = true;
                      passing0 = 0;
                      var props2 = {};
                      props2.status = true;
                      props2.reason = true;
                    }
                    const _errs35 = errors;
                    if (errors === _errs35) {
                      if (data10 && typeof data10 == "object" && !Array.isArray(data10)) {
                        let missing4;
                        if (data10.status === void 0 && (missing4 = "status") || data10.snapshotRef === void 0 && (missing4 = "snapshotRef") || data10.observedAt === void 0 && (missing4 = "observedAt") || data10.sourceTime === void 0 && (missing4 = "sourceTime")) {
                          const err9 = { instancePath: instancePath + "/payload/before", schemaPath: "#/$defs/semanticBefore/oneOf/1/required", keyword: "required", params: { missingProperty: missing4 }, message: "must have required property '" + missing4 + "'" };
                          if (vErrors === null) {
                            vErrors = [err9];
                          } else {
                            vErrors.push(err9);
                          }
                          errors++;
                        } else {
                          if (data10.status !== void 0) {
                            const _errs37 = errors;
                            if ("observed" !== data10.status) {
                              const err10 = { instancePath: instancePath + "/payload/before/status", schemaPath: "#/$defs/semanticBefore/oneOf/1/properties/status/const", keyword: "const", params: { allowedValue: "observed" }, message: "must be equal to constant" };
                              if (vErrors === null) {
                                vErrors = [err10];
                              } else {
                                vErrors.push(err10);
                              }
                              errors++;
                            }
                            var valid16 = _errs37 === errors;
                          } else {
                            var valid16 = true;
                          }
                          if (valid16) {
                            if (data10.snapshotRef !== void 0) {
                              let data14 = data10.snapshotRef;
                              const _errs38 = errors;
                              if (errors === _errs38) {
                                if (typeof data14 === "string") {
                                  if (func1(data14) < 1) {
                                    const err11 = { instancePath: instancePath + "/payload/before/snapshotRef", schemaPath: "#/$defs/semanticBefore/oneOf/1/properties/snapshotRef/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" };
                                    if (vErrors === null) {
                                      vErrors = [err11];
                                    } else {
                                      vErrors.push(err11);
                                    }
                                    errors++;
                                  }
                                } else {
                                  const err12 = { instancePath: instancePath + "/payload/before/snapshotRef", schemaPath: "#/$defs/semanticBefore/oneOf/1/properties/snapshotRef/type", keyword: "type", params: { type: "string" }, message: "must be string" };
                                  if (vErrors === null) {
                                    vErrors = [err12];
                                  } else {
                                    vErrors.push(err12);
                                  }
                                  errors++;
                                }
                              }
                              var valid16 = _errs38 === errors;
                            } else {
                              var valid16 = true;
                            }
                            if (valid16) {
                              if (data10.observedAt !== void 0) {
                                const _errs40 = errors;
                                if (typeof data10.observedAt !== "string") {
                                  const err13 = { instancePath: instancePath + "/payload/before/observedAt", schemaPath: "#/$defs/semanticBefore/oneOf/1/properties/observedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" };
                                  if (vErrors === null) {
                                    vErrors = [err13];
                                  } else {
                                    vErrors.push(err13);
                                  }
                                  errors++;
                                }
                                var valid16 = _errs40 === errors;
                              } else {
                                var valid16 = true;
                              }
                              if (valid16) {
                                if (data10.sourceTime !== void 0) {
                                  const _errs42 = errors;
                                  if (!(typeof data10.sourceTime == "number")) {
                                    const err14 = { instancePath: instancePath + "/payload/before/sourceTime", schemaPath: "#/$defs/semanticBefore/oneOf/1/properties/sourceTime/type", keyword: "type", params: { type: "number" }, message: "must be number" };
                                    if (vErrors === null) {
                                      vErrors = [err14];
                                    } else {
                                      vErrors.push(err14);
                                    }
                                    errors++;
                                  }
                                  var valid16 = _errs42 === errors;
                                } else {
                                  var valid16 = true;
                                }
                              }
                            }
                          }
                        }
                      } else {
                        const err15 = { instancePath: instancePath + "/payload/before", schemaPath: "#/$defs/semanticBefore/oneOf/1/type", keyword: "type", params: { type: "object" }, message: "must be object" };
                        if (vErrors === null) {
                          vErrors = [err15];
                        } else {
                          vErrors.push(err15);
                        }
                        errors++;
                      }
                    }
                    var _valid3 = _errs35 === errors;
                    if (_valid3 && valid14) {
                      valid14 = false;
                      passing0 = [passing0, 1];
                    } else {
                      if (_valid3) {
                        valid14 = true;
                        passing0 = 1;
                        if (props2 !== true) {
                          props2 = props2 || {};
                          props2.status = true;
                          props2.snapshotRef = true;
                          props2.observedAt = true;
                          props2.sourceTime = true;
                        }
                      }
                    }
                    if (!valid14) {
                      const err16 = { instancePath: instancePath + "/payload/before", schemaPath: "#/$defs/semanticBefore/oneOf", keyword: "oneOf", params: { passingSchemas: passing0 }, message: "must match exactly one schema in oneOf" };
                      if (vErrors === null) {
                        vErrors = [err16];
                      } else {
                        vErrors.push(err16);
                      }
                      errors++;
                      validate38.errors = vErrors;
                      return false;
                    } else {
                      errors = _errs29;
                      if (vErrors !== null) {
                        if (_errs29) {
                          vErrors.length = _errs29;
                        } else {
                          vErrors = null;
                        }
                      }
                    }
                    var valid12 = _errs27 === errors;
                  } else {
                    var valid12 = true;
                  }
                  if (valid12) {
                    if (data9.after !== void 0) {
                      let data17 = data9.after;
                      const _errs44 = errors;
                      if (data17 && typeof data17 == "object" && !Array.isArray(data17)) {
                        if (data17.metadataFacts !== void 0) {
                          let data18 = data17.metadataFacts;
                          const _errs45 = errors;
                          if (errors === _errs45) {
                            if (Array.isArray(data18)) {
                              if (data18.length > 32) {
                                validate38.errors = [{ instancePath: instancePath + "/payload/after/metadataFacts", schemaPath: "#/allOf/2/then/properties/payload/properties/after/properties/metadataFacts/maxItems", keyword: "maxItems", params: { limit: 32 }, message: "must NOT have more than 32 items" }];
                                return false;
                              } else {
                                var valid18 = true;
                                const len0 = data18.length;
                                for (let i0 = 0; i0 < len0; i0++) {
                                  let data19 = data18[i0];
                                  const _errs47 = errors;
                                  const _errs48 = errors;
                                  if (errors === _errs48) {
                                    if (data19 && typeof data19 == "object" && !Array.isArray(data19)) {
                                      let missing5;
                                      if (data19.field === void 0 && (missing5 = "field") || data19.source === void 0 && (missing5 = "source") || data19.value === void 0 && (missing5 = "value") || data19.component === void 0 && (missing5 = "component") || data19.observedAt === void 0 && (missing5 = "observedAt")) {
                                        validate38.errors = [{ instancePath: instancePath + "/payload/after/metadataFacts/" + i0, schemaPath: "#/$defs/correlationFact/required", keyword: "required", params: { missingProperty: missing5 }, message: "must have required property '" + missing5 + "'" }];
                                        return false;
                                      } else {
                                        if (data19.field !== void 0) {
                                          let data20 = data19.field;
                                          const _errs50 = errors;
                                          if (!(data20 === "frontendBuildId" || data20 === "backendBuildId" || data20 === "serviceInstance" || data20 === "requestId" || data20 === "traceId" || data20 === "spanId")) {
                                            validate38.errors = [{ instancePath: instancePath + "/payload/after/metadataFacts/" + i0 + "/field", schemaPath: "#/$defs/correlationFact/properties/field/enum", keyword: "enum", params: { allowedValues: schema64.properties.field.enum }, message: "must be equal to one of the allowed values" }];
                                            return false;
                                          }
                                          var valid20 = _errs50 === errors;
                                        } else {
                                          var valid20 = true;
                                        }
                                        if (valid20) {
                                          if (data19.source !== void 0) {
                                            const _errs51 = errors;
                                            if (typeof data19.source !== "string") {
                                              validate38.errors = [{ instancePath: instancePath + "/payload/after/metadataFacts/" + i0 + "/source", schemaPath: "#/$defs/correlationFact/properties/source/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                              return false;
                                            }
                                            var valid20 = _errs51 === errors;
                                          } else {
                                            var valid20 = true;
                                          }
                                          if (valid20) {
                                            if (data19.value !== void 0) {
                                              let data22 = data19.value;
                                              const _errs53 = errors;
                                              if (errors === _errs53) {
                                                if (typeof data22 === "string") {
                                                  if (func1(data22) > 256) {
                                                    validate38.errors = [{ instancePath: instancePath + "/payload/after/metadataFacts/" + i0 + "/value", schemaPath: "#/$defs/correlationFact/properties/value/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                                    return false;
                                                  } else {
                                                    if (func1(data22) < 1) {
                                                      validate38.errors = [{ instancePath: instancePath + "/payload/after/metadataFacts/" + i0 + "/value", schemaPath: "#/$defs/correlationFact/properties/value/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                      return false;
                                                    }
                                                  }
                                                } else {
                                                  validate38.errors = [{ instancePath: instancePath + "/payload/after/metadataFacts/" + i0 + "/value", schemaPath: "#/$defs/correlationFact/properties/value/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                  return false;
                                                }
                                              }
                                              var valid20 = _errs53 === errors;
                                            } else {
                                              var valid20 = true;
                                            }
                                            if (valid20) {
                                              if (data19.component !== void 0) {
                                                let data23 = data19.component;
                                                const _errs55 = errors;
                                                if (errors === _errs55) {
                                                  if (typeof data23 === "string") {
                                                    if (func1(data23) > 80) {
                                                      validate38.errors = [{ instancePath: instancePath + "/payload/after/metadataFacts/" + i0 + "/component", schemaPath: "#/$defs/correlationFact/properties/component/maxLength", keyword: "maxLength", params: { limit: 80 }, message: "must NOT have more than 80 characters" }];
                                                      return false;
                                                    } else {
                                                      if (func1(data23) < 1) {
                                                        validate38.errors = [{ instancePath: instancePath + "/payload/after/metadataFacts/" + i0 + "/component", schemaPath: "#/$defs/correlationFact/properties/component/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                        return false;
                                                      }
                                                    }
                                                  } else {
                                                    validate38.errors = [{ instancePath: instancePath + "/payload/after/metadataFacts/" + i0 + "/component", schemaPath: "#/$defs/correlationFact/properties/component/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                    return false;
                                                  }
                                                }
                                                var valid20 = _errs55 === errors;
                                              } else {
                                                var valid20 = true;
                                              }
                                              if (valid20) {
                                                if (data19.observedAt !== void 0) {
                                                  const _errs57 = errors;
                                                  if (typeof data19.observedAt !== "string") {
                                                    validate38.errors = [{ instancePath: instancePath + "/payload/after/metadataFacts/" + i0 + "/observedAt", schemaPath: "#/$defs/correlationFact/properties/observedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                    return false;
                                                  }
                                                  var valid20 = _errs57 === errors;
                                                } else {
                                                  var valid20 = true;
                                                }
                                              }
                                            }
                                          }
                                        }
                                      }
                                    } else {
                                      validate38.errors = [{ instancePath: instancePath + "/payload/after/metadataFacts/" + i0, schemaPath: "#/$defs/correlationFact/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                      return false;
                                    }
                                  }
                                  var valid18 = _errs47 === errors;
                                  if (!valid18) {
                                    break;
                                  }
                                }
                              }
                            } else {
                              validate38.errors = [{ instancePath: instancePath + "/payload/after/metadataFacts", schemaPath: "#/allOf/2/then/properties/payload/properties/after/properties/metadataFacts/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                              return false;
                            }
                          }
                        }
                      }
                      var valid12 = _errs44 === errors;
                    } else {
                      var valid12 = true;
                    }
                  }
                }
              }
            }
            var _valid2 = _errs25 === errors;
            valid9 = _valid2;
            if (valid9) {
              var props3 = {};
              props3.payload = true;
              props3.kind = true;
            }
          }
          if (!valid9) {
            const err17 = { instancePath, schemaPath: "#/allOf/2/if", keyword: "if", params: { failingKeyword: "then" }, message: 'must match "then" schema' };
            if (vErrors === null) {
              vErrors = [err17];
            } else {
              vErrors.push(err17);
            }
            errors++;
            validate38.errors = vErrors;
            return false;
          }
          var valid0 = _errs21 === errors;
          if (valid0) {
            if (props0 !== true && props3 !== void 0) {
              if (props3 === true) {
                props0 = true;
              } else {
                props0 = props0 || {};
                Object.assign(props0, props3);
              }
            }
          }
        }
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing6;
          if (data.schemaVersion === void 0 && (missing6 = "schemaVersion") || data.eventId === void 0 && (missing6 = "eventId") || data.recordingId === void 0 && (missing6 = "recordingId") || data.browserRunId === void 0 && (missing6 = "browserRunId") || data.streamId === void 0 && (missing6 = "streamId") || data.tabInstanceId === void 0 && (missing6 = "tabInstanceId") || data.browserTabId === void 0 && (missing6 = "browserTabId") || data.windowId === void 0 && (missing6 = "windowId") || data.emitterContext === void 0 && (missing6 = "emitterContext") || data.subjectContext === void 0 && (missing6 = "subjectContext") || data.source === void 0 && (missing6 = "source") || data.sourceSeq === void 0 && (missing6 = "sourceSeq") || data.kind === void 0 && (missing6 = "kind") || data.sourceTime === void 0 && (missing6 = "sourceTime") || data.sourceClock === void 0 && (missing6 = "sourceClock") || data.observedAt === void 0 && (missing6 = "observedAt") || data.normalizedAt === void 0 && (missing6 = "normalizedAt") || data.captureGeneration === void 0 && (missing6 = "captureGeneration") || data.channel === void 0 && (missing6 = "channel") || data.channelGeneration === void 0 && (missing6 = "channelGeneration") || data.payload === void 0 && (missing6 = "payload") || data.quality === void 0 && (missing6 = "quality")) {
            validate38.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing6 }, message: "must have required property '" + missing6 + "'" }];
            return false;
          } else {
            if (props0 !== true) {
              props0 = props0 || {};
              props0.schemaVersion = true;
              props0.eventId = true;
              props0.recordingId = true;
              props0.browserRunId = true;
              props0.streamId = true;
              props0.tabInstanceId = true;
              props0.browserTabId = true;
              props0.windowId = true;
              props0.emitterContext = true;
              props0.subjectContext = true;
              props0.source = true;
              props0.recorderStreamId = true;
              props0.sourceSeq = true;
              props0.kind = true;
              props0.sourceTime = true;
              props0.sourceClock = true;
              props0.observedAt = true;
              props0.normalizedAt = true;
              props0.captureGeneration = true;
              props0.channel = true;
              props0.channelGeneration = true;
              props0.payload = true;
              props0.quality = true;
            }
            if (data.schemaVersion !== void 0) {
              const _errs59 = errors;
              if ("3.0.0" !== data.schemaVersion) {
                validate38.errors = [{ instancePath: instancePath + "/schemaVersion", schemaPath: "#/properties/schemaVersion/const", keyword: "const", params: { allowedValue: "3.0.0" }, message: "must be equal to constant" }];
                return false;
              }
              var valid21 = _errs59 === errors;
            } else {
              var valid21 = true;
            }
            if (valid21) {
              if (data.eventId !== void 0) {
                let data26 = data.eventId;
                const _errs60 = errors;
                if (errors === _errs60) {
                  if (typeof data26 === "string") {
                    if (func1(data26) > 256) {
                      validate38.errors = [{ instancePath: instancePath + "/eventId", schemaPath: "#/properties/eventId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                      return false;
                    } else {
                      if (func1(data26) < 1) {
                        validate38.errors = [{ instancePath: instancePath + "/eventId", schemaPath: "#/properties/eventId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                        return false;
                      }
                    }
                  } else {
                    validate38.errors = [{ instancePath: instancePath + "/eventId", schemaPath: "#/properties/eventId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                    return false;
                  }
                }
                var valid21 = _errs60 === errors;
              } else {
                var valid21 = true;
              }
              if (valid21) {
                if (data.recordingId !== void 0) {
                  let data27 = data.recordingId;
                  const _errs62 = errors;
                  if (errors === _errs62) {
                    if (typeof data27 === "string") {
                      if (func1(data27) > 256) {
                        validate38.errors = [{ instancePath: instancePath + "/recordingId", schemaPath: "#/properties/recordingId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                        return false;
                      } else {
                        if (func1(data27) < 1) {
                          validate38.errors = [{ instancePath: instancePath + "/recordingId", schemaPath: "#/properties/recordingId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                          return false;
                        }
                      }
                    } else {
                      validate38.errors = [{ instancePath: instancePath + "/recordingId", schemaPath: "#/properties/recordingId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                      return false;
                    }
                  }
                  var valid21 = _errs62 === errors;
                } else {
                  var valid21 = true;
                }
                if (valid21) {
                  if (data.browserRunId !== void 0) {
                    let data28 = data.browserRunId;
                    const _errs64 = errors;
                    if (errors === _errs64) {
                      if (typeof data28 === "string") {
                        if (func1(data28) > 256) {
                          validate38.errors = [{ instancePath: instancePath + "/browserRunId", schemaPath: "#/properties/browserRunId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                          return false;
                        } else {
                          if (func1(data28) < 1) {
                            validate38.errors = [{ instancePath: instancePath + "/browserRunId", schemaPath: "#/properties/browserRunId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                            return false;
                          }
                        }
                      } else {
                        validate38.errors = [{ instancePath: instancePath + "/browserRunId", schemaPath: "#/properties/browserRunId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                        return false;
                      }
                    }
                    var valid21 = _errs64 === errors;
                  } else {
                    var valid21 = true;
                  }
                  if (valid21) {
                    if (data.streamId !== void 0) {
                      let data29 = data.streamId;
                      const _errs66 = errors;
                      if (errors === _errs66) {
                        if (typeof data29 === "string") {
                          if (func1(data29) > 256) {
                            validate38.errors = [{ instancePath: instancePath + "/streamId", schemaPath: "#/properties/streamId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                            return false;
                          } else {
                            if (func1(data29) < 1) {
                              validate38.errors = [{ instancePath: instancePath + "/streamId", schemaPath: "#/properties/streamId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                              return false;
                            }
                          }
                        } else {
                          validate38.errors = [{ instancePath: instancePath + "/streamId", schemaPath: "#/properties/streamId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                          return false;
                        }
                      }
                      var valid21 = _errs66 === errors;
                    } else {
                      var valid21 = true;
                    }
                    if (valid21) {
                      if (data.tabInstanceId !== void 0) {
                        let data30 = data.tabInstanceId;
                        const _errs68 = errors;
                        if (typeof data30 !== "string" && data30 !== null) {
                          validate38.errors = [{ instancePath: instancePath + "/tabInstanceId", schemaPath: "#/properties/tabInstanceId/type", keyword: "type", params: { type: schema62.properties.tabInstanceId.type }, message: "must be string,null" }];
                          return false;
                        }
                        var valid21 = _errs68 === errors;
                      } else {
                        var valid21 = true;
                      }
                      if (valid21) {
                        if (data.browserTabId !== void 0) {
                          let data31 = data.browserTabId;
                          const _errs70 = errors;
                          if (!(typeof data31 == "number" && (!(data31 % 1) && !isNaN(data31))) && data31 !== null) {
                            validate38.errors = [{ instancePath: instancePath + "/browserTabId", schemaPath: "#/properties/browserTabId/type", keyword: "type", params: { type: schema62.properties.browserTabId.type }, message: "must be integer,null" }];
                            return false;
                          }
                          var valid21 = _errs70 === errors;
                        } else {
                          var valid21 = true;
                        }
                        if (valid21) {
                          if (data.windowId !== void 0) {
                            let data32 = data.windowId;
                            const _errs72 = errors;
                            if (!(typeof data32 == "number" && (!(data32 % 1) && !isNaN(data32))) && data32 !== null) {
                              validate38.errors = [{ instancePath: instancePath + "/windowId", schemaPath: "#/properties/windowId/type", keyword: "type", params: { type: schema62.properties.windowId.type }, message: "must be integer,null" }];
                              return false;
                            }
                            var valid21 = _errs72 === errors;
                          } else {
                            var valid21 = true;
                          }
                          if (valid21) {
                            if (data.emitterContext !== void 0) {
                              const _errs74 = errors;
                              if (!validate24(data.emitterContext, { instancePath: instancePath + "/emitterContext", parentData: data, parentDataProperty: "emitterContext", rootData, dynamicAnchors })) {
                                vErrors = vErrors === null ? validate24.errors : vErrors.concat(validate24.errors);
                                errors = vErrors.length;
                              }
                              var valid21 = _errs74 === errors;
                            } else {
                              var valid21 = true;
                            }
                            if (valid21) {
                              if (data.subjectContext !== void 0) {
                                const _errs75 = errors;
                                if (!validate24(data.subjectContext, { instancePath: instancePath + "/subjectContext", parentData: data, parentDataProperty: "subjectContext", rootData, dynamicAnchors })) {
                                  vErrors = vErrors === null ? validate24.errors : vErrors.concat(validate24.errors);
                                  errors = vErrors.length;
                                }
                                var valid21 = _errs75 === errors;
                              } else {
                                var valid21 = true;
                              }
                              if (valid21) {
                                if (data.source !== void 0) {
                                  const _errs76 = errors;
                                  if (typeof data.source !== "string") {
                                    validate38.errors = [{ instancePath: instancePath + "/source", schemaPath: "#/properties/source/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                    return false;
                                  }
                                  var valid21 = _errs76 === errors;
                                } else {
                                  var valid21 = true;
                                }
                                if (valid21) {
                                  if (data.recorderStreamId !== void 0) {
                                    let data36 = data.recorderStreamId;
                                    const _errs78 = errors;
                                    if (errors === _errs78) {
                                      if (typeof data36 === "string") {
                                        if (func1(data36) > 256) {
                                          validate38.errors = [{ instancePath: instancePath + "/recorderStreamId", schemaPath: "#/properties/recorderStreamId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                          return false;
                                        } else {
                                          if (func1(data36) < 1) {
                                            validate38.errors = [{ instancePath: instancePath + "/recorderStreamId", schemaPath: "#/properties/recorderStreamId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                            return false;
                                          }
                                        }
                                      } else {
                                        validate38.errors = [{ instancePath: instancePath + "/recorderStreamId", schemaPath: "#/properties/recorderStreamId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                        return false;
                                      }
                                    }
                                    var valid21 = _errs78 === errors;
                                  } else {
                                    var valid21 = true;
                                  }
                                  if (valid21) {
                                    if (data.sourceSeq !== void 0) {
                                      let data37 = data.sourceSeq;
                                      const _errs80 = errors;
                                      if (!(typeof data37 == "number" && (!(data37 % 1) && !isNaN(data37)))) {
                                        validate38.errors = [{ instancePath: instancePath + "/sourceSeq", schemaPath: "#/properties/sourceSeq/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                        return false;
                                      }
                                      if (errors === _errs80) {
                                        if (typeof data37 == "number") {
                                          if (data37 < 1 || isNaN(data37)) {
                                            validate38.errors = [{ instancePath: instancePath + "/sourceSeq", schemaPath: "#/properties/sourceSeq/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                                            return false;
                                          }
                                        }
                                      }
                                      var valid21 = _errs80 === errors;
                                    } else {
                                      var valid21 = true;
                                    }
                                    if (valid21) {
                                      if (data.kind !== void 0) {
                                        const _errs82 = errors;
                                        if (typeof data.kind !== "string") {
                                          validate38.errors = [{ instancePath: instancePath + "/kind", schemaPath: "#/properties/kind/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                          return false;
                                        }
                                        var valid21 = _errs82 === errors;
                                      } else {
                                        var valid21 = true;
                                      }
                                      if (valid21) {
                                        if (data.sourceTime !== void 0) {
                                          let data39 = data.sourceTime;
                                          const _errs84 = errors;
                                          if (!(typeof data39 == "number") && data39 !== null) {
                                            validate38.errors = [{ instancePath: instancePath + "/sourceTime", schemaPath: "#/properties/sourceTime/type", keyword: "type", params: { type: schema62.properties.sourceTime.type }, message: "must be number,null" }];
                                            return false;
                                          }
                                          var valid21 = _errs84 === errors;
                                        } else {
                                          var valid21 = true;
                                        }
                                        if (valid21) {
                                          if (data.sourceClock !== void 0) {
                                            const _errs86 = errors;
                                            if (typeof data.sourceClock !== "string") {
                                              validate38.errors = [{ instancePath: instancePath + "/sourceClock", schemaPath: "#/properties/sourceClock/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                              return false;
                                            }
                                            var valid21 = _errs86 === errors;
                                          } else {
                                            var valid21 = true;
                                          }
                                          if (valid21) {
                                            if (data.observedAt !== void 0) {
                                              const _errs88 = errors;
                                              if (typeof data.observedAt !== "string") {
                                                validate38.errors = [{ instancePath: instancePath + "/observedAt", schemaPath: "#/properties/observedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                return false;
                                              }
                                              var valid21 = _errs88 === errors;
                                            } else {
                                              var valid21 = true;
                                            }
                                            if (valid21) {
                                              if (data.normalizedAt !== void 0) {
                                                const _errs90 = errors;
                                                if (data.normalizedAt !== null) {
                                                  validate38.errors = [{ instancePath: instancePath + "/normalizedAt", schemaPath: "#/properties/normalizedAt/type", keyword: "type", params: { type: "null" }, message: "must be null" }];
                                                  return false;
                                                }
                                                var valid21 = _errs90 === errors;
                                              } else {
                                                var valid21 = true;
                                              }
                                              if (valid21) {
                                                if (data.captureGeneration !== void 0) {
                                                  let data43 = data.captureGeneration;
                                                  const _errs92 = errors;
                                                  if (!(typeof data43 == "number" && (!(data43 % 1) && !isNaN(data43)))) {
                                                    validate38.errors = [{ instancePath: instancePath + "/captureGeneration", schemaPath: "#/properties/captureGeneration/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                    return false;
                                                  }
                                                  if (errors === _errs92) {
                                                    if (typeof data43 == "number") {
                                                      if (data43 < 0 || isNaN(data43)) {
                                                        validate38.errors = [{ instancePath: instancePath + "/captureGeneration", schemaPath: "#/properties/captureGeneration/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                        return false;
                                                      }
                                                    }
                                                  }
                                                  var valid21 = _errs92 === errors;
                                                } else {
                                                  var valid21 = true;
                                                }
                                                if (valid21) {
                                                  if (data.channel !== void 0) {
                                                    let data44 = data.channel;
                                                    const _errs94 = errors;
                                                    if (!(data44 === "control" || data44 === "page" || data44 === "semantic" || data44 === "network" || data44 === "runtime" || data44 === "screenshot")) {
                                                      validate38.errors = [{ instancePath: instancePath + "/channel", schemaPath: "#/properties/channel/enum", keyword: "enum", params: { allowedValues: schema62.properties.channel.enum }, message: "must be equal to one of the allowed values" }];
                                                      return false;
                                                    }
                                                    var valid21 = _errs94 === errors;
                                                  } else {
                                                    var valid21 = true;
                                                  }
                                                  if (valid21) {
                                                    if (data.channelGeneration !== void 0) {
                                                      let data45 = data.channelGeneration;
                                                      const _errs95 = errors;
                                                      if (!(typeof data45 == "number" && (!(data45 % 1) && !isNaN(data45)))) {
                                                        validate38.errors = [{ instancePath: instancePath + "/channelGeneration", schemaPath: "#/properties/channelGeneration/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                        return false;
                                                      }
                                                      if (errors === _errs95) {
                                                        if (typeof data45 == "number") {
                                                          if (data45 < 0 || isNaN(data45)) {
                                                            validate38.errors = [{ instancePath: instancePath + "/channelGeneration", schemaPath: "#/properties/channelGeneration/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                            return false;
                                                          }
                                                        }
                                                      }
                                                      var valid21 = _errs95 === errors;
                                                    } else {
                                                      var valid21 = true;
                                                    }
                                                    if (valid21) {
                                                      if (data.payload !== void 0) {
                                                        const _errs97 = errors;
                                                        if (!validate36(data.payload, { instancePath: instancePath + "/payload", parentData: data, parentDataProperty: "payload", rootData, dynamicAnchors })) {
                                                          vErrors = vErrors === null ? validate36.errors : vErrors.concat(validate36.errors);
                                                          errors = vErrors.length;
                                                        }
                                                        var valid21 = _errs97 === errors;
                                                      } else {
                                                        var valid21 = true;
                                                      }
                                                      if (valid21) {
                                                        if (data.quality !== void 0) {
                                                          let data47 = data.quality;
                                                          const _errs98 = errors;
                                                          if (errors === _errs98) {
                                                            if (data47 && typeof data47 == "object" && !Array.isArray(data47)) {
                                                              let missing7;
                                                              if (data47.redacted === void 0 && (missing7 = "redacted") || data47.truncated === void 0 && (missing7 = "truncated") || data47.limitations === void 0 && (missing7 = "limitations")) {
                                                                validate38.errors = [{ instancePath: instancePath + "/quality", schemaPath: "#/properties/quality/required", keyword: "required", params: { missingProperty: missing7 }, message: "must have required property '" + missing7 + "'" }];
                                                                return false;
                                                              } else {
                                                                if (data47.redacted !== void 0) {
                                                                  const _errs100 = errors;
                                                                  if (typeof data47.redacted !== "boolean") {
                                                                    validate38.errors = [{ instancePath: instancePath + "/quality/redacted", schemaPath: "#/properties/quality/properties/redacted/type", keyword: "type", params: { type: "boolean" }, message: "must be boolean" }];
                                                                    return false;
                                                                  }
                                                                  var valid22 = _errs100 === errors;
                                                                } else {
                                                                  var valid22 = true;
                                                                }
                                                                if (valid22) {
                                                                  if (data47.truncated !== void 0) {
                                                                    const _errs102 = errors;
                                                                    if (typeof data47.truncated !== "boolean") {
                                                                      validate38.errors = [{ instancePath: instancePath + "/quality/truncated", schemaPath: "#/properties/quality/properties/truncated/type", keyword: "type", params: { type: "boolean" }, message: "must be boolean" }];
                                                                      return false;
                                                                    }
                                                                    var valid22 = _errs102 === errors;
                                                                  } else {
                                                                    var valid22 = true;
                                                                  }
                                                                  if (valid22) {
                                                                    if (data47.limitations !== void 0) {
                                                                      let data50 = data47.limitations;
                                                                      const _errs104 = errors;
                                                                      if (errors === _errs104) {
                                                                        if (Array.isArray(data50)) {
                                                                          var valid23 = true;
                                                                          const len1 = data50.length;
                                                                          for (let i1 = 0; i1 < len1; i1++) {
                                                                            const _errs106 = errors;
                                                                            if (typeof data50[i1] !== "string") {
                                                                              validate38.errors = [{ instancePath: instancePath + "/quality/limitations/" + i1, schemaPath: "#/properties/quality/properties/limitations/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                              return false;
                                                                            }
                                                                            var valid23 = _errs106 === errors;
                                                                            if (!valid23) {
                                                                              break;
                                                                            }
                                                                          }
                                                                        } else {
                                                                          validate38.errors = [{ instancePath: instancePath + "/quality/limitations", schemaPath: "#/properties/quality/properties/limitations/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                                          return false;
                                                                        }
                                                                      }
                                                                      var valid22 = _errs104 === errors;
                                                                    } else {
                                                                      var valid22 = true;
                                                                    }
                                                                  }
                                                                }
                                                              }
                                                            } else {
                                                              validate38.errors = [{ instancePath: instancePath + "/quality", schemaPath: "#/properties/quality/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                              return false;
                                                            }
                                                          }
                                                          var valid21 = _errs98 === errors;
                                                        } else {
                                                          var valid21 = true;
                                                        }
                                                      }
                                                    }
                                                  }
                                                }
                                              }
                                            }
                                          }
                                        }
                                      }
                                    }
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        } else {
          validate38.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate38.errors = vErrors;
      evaluated0.props = props0;
      return errors === 0;
    }
    validate38.evaluated = { "dynamicProps": true, "dynamicItems": false };
    exports.network = validate42;
    var schema65 = { "type": "object", "required": ["schemaVersion", "requestKey", "recordingId", "browserRunId", "tabInstanceId", "debuggerSessionKey", "cdpRequestId", "redirectOrdinal", "chromeFrameId", "request", "response", "networkOutcome", "businessOutcome", "serverCorrelation", "startedAt", "sourceClock", "evidenceRefs", "actionCandidates", "extraInfoStatus"], "properties": { "schemaVersion": { "const": "3.0.0" }, "requestKey": { "type": "string", "minLength": 1, "maxLength": 256 }, "recordingId": { "type": "string", "minLength": 1, "maxLength": 256 }, "browserRunId": { "type": "string", "minLength": 1, "maxLength": 256 }, "tabInstanceId": { "type": "string", "minLength": 1, "maxLength": 256 }, "debuggerSessionKey": { "type": "string", "minLength": 1, "maxLength": 256 }, "cdpRequestId": { "type": "string", "minLength": 1, "maxLength": 256 }, "redirectOrdinal": { "type": "integer", "minimum": 0 }, "cdpFrameId": { "type": "string" }, "loaderId": { "type": "string" }, "chromeFrameId": { "type": ["integer", "null"] }, "documentId": { "type": ["string", "null"] }, "frameMappingReason": { "type": "string" }, "request": { "allOf": [{ "$ref": "#/$defs/body" }, { "type": "object", "required": ["method", "url", "headers", "type"], "properties": { "method": { "type": "string" }, "url": { "type": "string" }, "headers": { "type": "object", "additionalProperties": { "type": "string" } }, "type": { "type": "string" } } }] }, "response": { "allOf": [{ "$ref": "#/$defs/body" }, { "type": "object", "required": ["httpStatus", "headers"], "properties": { "httpStatus": { "anyOf": [{ "type": "number" }, { "const": "unknown" }] }, "headers": { "type": "object", "additionalProperties": { "type": "string" } } } }] }, "networkOutcome": { "enum": ["finished", "failed", "incomplete"] }, "businessOutcome": { "enum": ["success", "failure", "unknown"] }, "serverCorrelation": { "type": "object", "required": ["requestId", "requestIdSource", "traceId", "traceIdSource"], "properties": { "requestId": { "type": ["string", "null"] }, "requestIdSource": { "type": ["string", "null"] }, "traceId": { "type": ["string", "null"] }, "traceIdSource": { "type": ["string", "null"] }, "spanId": { "type": ["string", "null"] } } }, "startedAt": { "type": "string" }, "sourceClock": { "type": "string" }, "evidenceRefs": { "type": "array", "items": { "type": "string", "minLength": 1, "maxLength": 256 } }, "actionCandidates": { "type": "array", "items": { "type": "object", "required": ["actionId", "basis", "confirmed"], "properties": { "actionId": { "type": "string", "minLength": 1, "maxLength": 256 }, "basis": { "type": "string" }, "confirmed": { "const": false } } } }, "extraInfoStatus": { "type": "string" }, "correlationFacts": { "type": "array", "items": { "$ref": "#/$defs/correlationFact" } } } };
    function validate42(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate42.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.schemaVersion === void 0 && (missing0 = "schemaVersion") || data.requestKey === void 0 && (missing0 = "requestKey") || data.recordingId === void 0 && (missing0 = "recordingId") || data.browserRunId === void 0 && (missing0 = "browserRunId") || data.tabInstanceId === void 0 && (missing0 = "tabInstanceId") || data.debuggerSessionKey === void 0 && (missing0 = "debuggerSessionKey") || data.cdpRequestId === void 0 && (missing0 = "cdpRequestId") || data.redirectOrdinal === void 0 && (missing0 = "redirectOrdinal") || data.chromeFrameId === void 0 && (missing0 = "chromeFrameId") || data.request === void 0 && (missing0 = "request") || data.response === void 0 && (missing0 = "response") || data.networkOutcome === void 0 && (missing0 = "networkOutcome") || data.businessOutcome === void 0 && (missing0 = "businessOutcome") || data.serverCorrelation === void 0 && (missing0 = "serverCorrelation") || data.startedAt === void 0 && (missing0 = "startedAt") || data.sourceClock === void 0 && (missing0 = "sourceClock") || data.evidenceRefs === void 0 && (missing0 = "evidenceRefs") || data.actionCandidates === void 0 && (missing0 = "actionCandidates") || data.extraInfoStatus === void 0 && (missing0 = "extraInfoStatus")) {
            validate42.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.schemaVersion !== void 0) {
              const _errs1 = errors;
              if ("3.0.0" !== data.schemaVersion) {
                validate42.errors = [{ instancePath: instancePath + "/schemaVersion", schemaPath: "#/properties/schemaVersion/const", keyword: "const", params: { allowedValue: "3.0.0" }, message: "must be equal to constant" }];
                return false;
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.requestKey !== void 0) {
                let data1 = data.requestKey;
                const _errs2 = errors;
                if (errors === _errs2) {
                  if (typeof data1 === "string") {
                    if (func1(data1) > 256) {
                      validate42.errors = [{ instancePath: instancePath + "/requestKey", schemaPath: "#/properties/requestKey/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                      return false;
                    } else {
                      if (func1(data1) < 1) {
                        validate42.errors = [{ instancePath: instancePath + "/requestKey", schemaPath: "#/properties/requestKey/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                        return false;
                      }
                    }
                  } else {
                    validate42.errors = [{ instancePath: instancePath + "/requestKey", schemaPath: "#/properties/requestKey/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                    return false;
                  }
                }
                var valid0 = _errs2 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.recordingId !== void 0) {
                  let data2 = data.recordingId;
                  const _errs4 = errors;
                  if (errors === _errs4) {
                    if (typeof data2 === "string") {
                      if (func1(data2) > 256) {
                        validate42.errors = [{ instancePath: instancePath + "/recordingId", schemaPath: "#/properties/recordingId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                        return false;
                      } else {
                        if (func1(data2) < 1) {
                          validate42.errors = [{ instancePath: instancePath + "/recordingId", schemaPath: "#/properties/recordingId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                          return false;
                        }
                      }
                    } else {
                      validate42.errors = [{ instancePath: instancePath + "/recordingId", schemaPath: "#/properties/recordingId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                      return false;
                    }
                  }
                  var valid0 = _errs4 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.browserRunId !== void 0) {
                    let data3 = data.browserRunId;
                    const _errs6 = errors;
                    if (errors === _errs6) {
                      if (typeof data3 === "string") {
                        if (func1(data3) > 256) {
                          validate42.errors = [{ instancePath: instancePath + "/browserRunId", schemaPath: "#/properties/browserRunId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                          return false;
                        } else {
                          if (func1(data3) < 1) {
                            validate42.errors = [{ instancePath: instancePath + "/browserRunId", schemaPath: "#/properties/browserRunId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                            return false;
                          }
                        }
                      } else {
                        validate42.errors = [{ instancePath: instancePath + "/browserRunId", schemaPath: "#/properties/browserRunId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                        return false;
                      }
                    }
                    var valid0 = _errs6 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.tabInstanceId !== void 0) {
                      let data4 = data.tabInstanceId;
                      const _errs8 = errors;
                      if (errors === _errs8) {
                        if (typeof data4 === "string") {
                          if (func1(data4) > 256) {
                            validate42.errors = [{ instancePath: instancePath + "/tabInstanceId", schemaPath: "#/properties/tabInstanceId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                            return false;
                          } else {
                            if (func1(data4) < 1) {
                              validate42.errors = [{ instancePath: instancePath + "/tabInstanceId", schemaPath: "#/properties/tabInstanceId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                              return false;
                            }
                          }
                        } else {
                          validate42.errors = [{ instancePath: instancePath + "/tabInstanceId", schemaPath: "#/properties/tabInstanceId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                          return false;
                        }
                      }
                      var valid0 = _errs8 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.debuggerSessionKey !== void 0) {
                        let data5 = data.debuggerSessionKey;
                        const _errs10 = errors;
                        if (errors === _errs10) {
                          if (typeof data5 === "string") {
                            if (func1(data5) > 256) {
                              validate42.errors = [{ instancePath: instancePath + "/debuggerSessionKey", schemaPath: "#/properties/debuggerSessionKey/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                              return false;
                            } else {
                              if (func1(data5) < 1) {
                                validate42.errors = [{ instancePath: instancePath + "/debuggerSessionKey", schemaPath: "#/properties/debuggerSessionKey/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                return false;
                              }
                            }
                          } else {
                            validate42.errors = [{ instancePath: instancePath + "/debuggerSessionKey", schemaPath: "#/properties/debuggerSessionKey/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                            return false;
                          }
                        }
                        var valid0 = _errs10 === errors;
                      } else {
                        var valid0 = true;
                      }
                      if (valid0) {
                        if (data.cdpRequestId !== void 0) {
                          let data6 = data.cdpRequestId;
                          const _errs12 = errors;
                          if (errors === _errs12) {
                            if (typeof data6 === "string") {
                              if (func1(data6) > 256) {
                                validate42.errors = [{ instancePath: instancePath + "/cdpRequestId", schemaPath: "#/properties/cdpRequestId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                return false;
                              } else {
                                if (func1(data6) < 1) {
                                  validate42.errors = [{ instancePath: instancePath + "/cdpRequestId", schemaPath: "#/properties/cdpRequestId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                  return false;
                                }
                              }
                            } else {
                              validate42.errors = [{ instancePath: instancePath + "/cdpRequestId", schemaPath: "#/properties/cdpRequestId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                              return false;
                            }
                          }
                          var valid0 = _errs12 === errors;
                        } else {
                          var valid0 = true;
                        }
                        if (valid0) {
                          if (data.redirectOrdinal !== void 0) {
                            let data7 = data.redirectOrdinal;
                            const _errs14 = errors;
                            if (!(typeof data7 == "number" && (!(data7 % 1) && !isNaN(data7)))) {
                              validate42.errors = [{ instancePath: instancePath + "/redirectOrdinal", schemaPath: "#/properties/redirectOrdinal/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                              return false;
                            }
                            if (errors === _errs14) {
                              if (typeof data7 == "number") {
                                if (data7 < 0 || isNaN(data7)) {
                                  validate42.errors = [{ instancePath: instancePath + "/redirectOrdinal", schemaPath: "#/properties/redirectOrdinal/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                  return false;
                                }
                              }
                            }
                            var valid0 = _errs14 === errors;
                          } else {
                            var valid0 = true;
                          }
                          if (valid0) {
                            if (data.cdpFrameId !== void 0) {
                              const _errs16 = errors;
                              if (typeof data.cdpFrameId !== "string") {
                                validate42.errors = [{ instancePath: instancePath + "/cdpFrameId", schemaPath: "#/properties/cdpFrameId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                return false;
                              }
                              var valid0 = _errs16 === errors;
                            } else {
                              var valid0 = true;
                            }
                            if (valid0) {
                              if (data.loaderId !== void 0) {
                                const _errs18 = errors;
                                if (typeof data.loaderId !== "string") {
                                  validate42.errors = [{ instancePath: instancePath + "/loaderId", schemaPath: "#/properties/loaderId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                  return false;
                                }
                                var valid0 = _errs18 === errors;
                              } else {
                                var valid0 = true;
                              }
                              if (valid0) {
                                if (data.chromeFrameId !== void 0) {
                                  let data10 = data.chromeFrameId;
                                  const _errs20 = errors;
                                  if (!(typeof data10 == "number" && (!(data10 % 1) && !isNaN(data10))) && data10 !== null) {
                                    validate42.errors = [{ instancePath: instancePath + "/chromeFrameId", schemaPath: "#/properties/chromeFrameId/type", keyword: "type", params: { type: schema65.properties.chromeFrameId.type }, message: "must be integer,null" }];
                                    return false;
                                  }
                                  var valid0 = _errs20 === errors;
                                } else {
                                  var valid0 = true;
                                }
                                if (valid0) {
                                  if (data.documentId !== void 0) {
                                    let data11 = data.documentId;
                                    const _errs22 = errors;
                                    if (typeof data11 !== "string" && data11 !== null) {
                                      validate42.errors = [{ instancePath: instancePath + "/documentId", schemaPath: "#/properties/documentId/type", keyword: "type", params: { type: schema65.properties.documentId.type }, message: "must be string,null" }];
                                      return false;
                                    }
                                    var valid0 = _errs22 === errors;
                                  } else {
                                    var valid0 = true;
                                  }
                                  if (valid0) {
                                    if (data.frameMappingReason !== void 0) {
                                      const _errs24 = errors;
                                      if (typeof data.frameMappingReason !== "string") {
                                        validate42.errors = [{ instancePath: instancePath + "/frameMappingReason", schemaPath: "#/properties/frameMappingReason/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                        return false;
                                      }
                                      var valid0 = _errs24 === errors;
                                    } else {
                                      var valid0 = true;
                                    }
                                    if (valid0) {
                                      if (data.request !== void 0) {
                                        let data13 = data.request;
                                        const _errs26 = errors;
                                        const _errs27 = errors;
                                        const _errs28 = errors;
                                        if (errors === _errs28) {
                                          if (data13 && typeof data13 == "object" && !Array.isArray(data13)) {
                                            let missing1;
                                            if (data13.bodyCaptureStatus === void 0 && (missing1 = "bodyCaptureStatus") || data13.bodyRef === void 0 && (missing1 = "bodyRef") || data13.bodyCaptureReason === void 0 && (missing1 = "bodyCaptureReason") || data13.redactionStatus === void 0 && (missing1 = "redactionStatus")) {
                                              validate42.errors = [{ instancePath: instancePath + "/request", schemaPath: "#/$defs/body/required", keyword: "required", params: { missingProperty: missing1 }, message: "must have required property '" + missing1 + "'" }];
                                              return false;
                                            } else {
                                              if (data13.bodyCaptureStatus !== void 0) {
                                                let data14 = data13.bodyCaptureStatus;
                                                const _errs30 = errors;
                                                if (!(data14 === "captured" || data14 === "empty" || data14 === "not_applicable" || data14 === "truncated" || data14 === "excluded_by_policy" || data14 === "unavailable" || data14 === "incomplete_target_closed" || data14 === "incomplete_session_stopped")) {
                                                  validate42.errors = [{ instancePath: instancePath + "/request/bodyCaptureStatus", schemaPath: "#/$defs/body/properties/bodyCaptureStatus/enum", keyword: "enum", params: { allowedValues: schema41.properties.bodyCaptureStatus.enum }, message: "must be equal to one of the allowed values" }];
                                                  return false;
                                                }
                                                var valid3 = _errs30 === errors;
                                              } else {
                                                var valid3 = true;
                                              }
                                              if (valid3) {
                                                if (data13.bodyRef !== void 0) {
                                                  let data15 = data13.bodyRef;
                                                  const _errs31 = errors;
                                                  if (typeof data15 !== "string" && data15 !== null) {
                                                    validate42.errors = [{ instancePath: instancePath + "/request/bodyRef", schemaPath: "#/$defs/body/properties/bodyRef/type", keyword: "type", params: { type: schema41.properties.bodyRef.type }, message: "must be string,null" }];
                                                    return false;
                                                  }
                                                  var valid3 = _errs31 === errors;
                                                } else {
                                                  var valid3 = true;
                                                }
                                                if (valid3) {
                                                  if (data13.bodyCaptureReason !== void 0) {
                                                    let data16 = data13.bodyCaptureReason;
                                                    const _errs33 = errors;
                                                    if (typeof data16 !== "string" && data16 !== null) {
                                                      validate42.errors = [{ instancePath: instancePath + "/request/bodyCaptureReason", schemaPath: "#/$defs/body/properties/bodyCaptureReason/type", keyword: "type", params: { type: schema41.properties.bodyCaptureReason.type }, message: "must be string,null" }];
                                                      return false;
                                                    }
                                                    var valid3 = _errs33 === errors;
                                                  } else {
                                                    var valid3 = true;
                                                  }
                                                  if (valid3) {
                                                    if (data13.redactionStatus !== void 0) {
                                                      let data17 = data13.redactionStatus;
                                                      const _errs35 = errors;
                                                      if (!(data17 === "none" || data17 === "applied" || data17 === "fully_masked" || data17 === "failed_excluded")) {
                                                        validate42.errors = [{ instancePath: instancePath + "/request/redactionStatus", schemaPath: "#/$defs/body/properties/redactionStatus/enum", keyword: "enum", params: { allowedValues: schema41.properties.redactionStatus.enum }, message: "must be equal to one of the allowed values" }];
                                                        return false;
                                                      }
                                                      var valid3 = _errs35 === errors;
                                                    } else {
                                                      var valid3 = true;
                                                    }
                                                    if (valid3) {
                                                      if (data13.originalBytes !== void 0) {
                                                        let data18 = data13.originalBytes;
                                                        const _errs36 = errors;
                                                        if (!(typeof data18 == "number" && (!(data18 % 1) && !isNaN(data18)))) {
                                                          validate42.errors = [{ instancePath: instancePath + "/request/originalBytes", schemaPath: "#/$defs/body/properties/originalBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                          return false;
                                                        }
                                                        if (errors === _errs36) {
                                                          if (typeof data18 == "number") {
                                                            if (data18 < 0 || isNaN(data18)) {
                                                              validate42.errors = [{ instancePath: instancePath + "/request/originalBytes", schemaPath: "#/$defs/body/properties/originalBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                              return false;
                                                            }
                                                          }
                                                        }
                                                        var valid3 = _errs36 === errors;
                                                      } else {
                                                        var valid3 = true;
                                                      }
                                                      if (valid3) {
                                                        if (data13.savedBytes !== void 0) {
                                                          let data19 = data13.savedBytes;
                                                          const _errs38 = errors;
                                                          if (!(typeof data19 == "number" && (!(data19 % 1) && !isNaN(data19)))) {
                                                            validate42.errors = [{ instancePath: instancePath + "/request/savedBytes", schemaPath: "#/$defs/body/properties/savedBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                            return false;
                                                          }
                                                          if (errors === _errs38) {
                                                            if (typeof data19 == "number") {
                                                              if (data19 < 0 || isNaN(data19)) {
                                                                validate42.errors = [{ instancePath: instancePath + "/request/savedBytes", schemaPath: "#/$defs/body/properties/savedBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                                return false;
                                                              }
                                                            }
                                                          }
                                                          var valid3 = _errs38 === errors;
                                                        } else {
                                                          var valid3 = true;
                                                        }
                                                      }
                                                    }
                                                  }
                                                }
                                              }
                                            }
                                          } else {
                                            validate42.errors = [{ instancePath: instancePath + "/request", schemaPath: "#/$defs/body/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                            return false;
                                          }
                                        }
                                        var valid1 = _errs27 === errors;
                                        if (valid1) {
                                          const _errs40 = errors;
                                          if (errors === _errs40) {
                                            if (data13 && typeof data13 == "object" && !Array.isArray(data13)) {
                                              let missing2;
                                              if (data13.method === void 0 && (missing2 = "method") || data13.url === void 0 && (missing2 = "url") || data13.headers === void 0 && (missing2 = "headers") || data13.type === void 0 && (missing2 = "type")) {
                                                validate42.errors = [{ instancePath: instancePath + "/request", schemaPath: "#/properties/request/allOf/1/required", keyword: "required", params: { missingProperty: missing2 }, message: "must have required property '" + missing2 + "'" }];
                                                return false;
                                              } else {
                                                if (data13.method !== void 0) {
                                                  const _errs42 = errors;
                                                  if (typeof data13.method !== "string") {
                                                    validate42.errors = [{ instancePath: instancePath + "/request/method", schemaPath: "#/properties/request/allOf/1/properties/method/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                    return false;
                                                  }
                                                  var valid4 = _errs42 === errors;
                                                } else {
                                                  var valid4 = true;
                                                }
                                                if (valid4) {
                                                  if (data13.url !== void 0) {
                                                    const _errs44 = errors;
                                                    if (typeof data13.url !== "string") {
                                                      validate42.errors = [{ instancePath: instancePath + "/request/url", schemaPath: "#/properties/request/allOf/1/properties/url/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                      return false;
                                                    }
                                                    var valid4 = _errs44 === errors;
                                                  } else {
                                                    var valid4 = true;
                                                  }
                                                  if (valid4) {
                                                    if (data13.headers !== void 0) {
                                                      let data22 = data13.headers;
                                                      const _errs46 = errors;
                                                      if (errors === _errs46) {
                                                        if (data22 && typeof data22 == "object" && !Array.isArray(data22)) {
                                                          for (const key0 in data22) {
                                                            const _errs49 = errors;
                                                            if (typeof data22[key0] !== "string") {
                                                              validate42.errors = [{ instancePath: instancePath + "/request/headers/" + key0.replace(/~/g, "~0").replace(/\//g, "~1"), schemaPath: "#/properties/request/allOf/1/properties/headers/additionalProperties/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                              return false;
                                                            }
                                                            var valid5 = _errs49 === errors;
                                                            if (!valid5) {
                                                              break;
                                                            }
                                                          }
                                                        } else {
                                                          validate42.errors = [{ instancePath: instancePath + "/request/headers", schemaPath: "#/properties/request/allOf/1/properties/headers/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                          return false;
                                                        }
                                                      }
                                                      var valid4 = _errs46 === errors;
                                                    } else {
                                                      var valid4 = true;
                                                    }
                                                    if (valid4) {
                                                      if (data13.type !== void 0) {
                                                        const _errs51 = errors;
                                                        if (typeof data13.type !== "string") {
                                                          validate42.errors = [{ instancePath: instancePath + "/request/type", schemaPath: "#/properties/request/allOf/1/properties/type/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                          return false;
                                                        }
                                                        var valid4 = _errs51 === errors;
                                                      } else {
                                                        var valid4 = true;
                                                      }
                                                    }
                                                  }
                                                }
                                              }
                                            } else {
                                              validate42.errors = [{ instancePath: instancePath + "/request", schemaPath: "#/properties/request/allOf/1/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                              return false;
                                            }
                                          }
                                          var valid1 = _errs40 === errors;
                                        }
                                        var valid0 = _errs26 === errors;
                                      } else {
                                        var valid0 = true;
                                      }
                                      if (valid0) {
                                        if (data.response !== void 0) {
                                          let data25 = data.response;
                                          const _errs53 = errors;
                                          const _errs54 = errors;
                                          const _errs55 = errors;
                                          if (errors === _errs55) {
                                            if (data25 && typeof data25 == "object" && !Array.isArray(data25)) {
                                              let missing3;
                                              if (data25.bodyCaptureStatus === void 0 && (missing3 = "bodyCaptureStatus") || data25.bodyRef === void 0 && (missing3 = "bodyRef") || data25.bodyCaptureReason === void 0 && (missing3 = "bodyCaptureReason") || data25.redactionStatus === void 0 && (missing3 = "redactionStatus")) {
                                                validate42.errors = [{ instancePath: instancePath + "/response", schemaPath: "#/$defs/body/required", keyword: "required", params: { missingProperty: missing3 }, message: "must have required property '" + missing3 + "'" }];
                                                return false;
                                              } else {
                                                if (data25.bodyCaptureStatus !== void 0) {
                                                  let data26 = data25.bodyCaptureStatus;
                                                  const _errs57 = errors;
                                                  if (!(data26 === "captured" || data26 === "empty" || data26 === "not_applicable" || data26 === "truncated" || data26 === "excluded_by_policy" || data26 === "unavailable" || data26 === "incomplete_target_closed" || data26 === "incomplete_session_stopped")) {
                                                    validate42.errors = [{ instancePath: instancePath + "/response/bodyCaptureStatus", schemaPath: "#/$defs/body/properties/bodyCaptureStatus/enum", keyword: "enum", params: { allowedValues: schema41.properties.bodyCaptureStatus.enum }, message: "must be equal to one of the allowed values" }];
                                                    return false;
                                                  }
                                                  var valid8 = _errs57 === errors;
                                                } else {
                                                  var valid8 = true;
                                                }
                                                if (valid8) {
                                                  if (data25.bodyRef !== void 0) {
                                                    let data27 = data25.bodyRef;
                                                    const _errs58 = errors;
                                                    if (typeof data27 !== "string" && data27 !== null) {
                                                      validate42.errors = [{ instancePath: instancePath + "/response/bodyRef", schemaPath: "#/$defs/body/properties/bodyRef/type", keyword: "type", params: { type: schema41.properties.bodyRef.type }, message: "must be string,null" }];
                                                      return false;
                                                    }
                                                    var valid8 = _errs58 === errors;
                                                  } else {
                                                    var valid8 = true;
                                                  }
                                                  if (valid8) {
                                                    if (data25.bodyCaptureReason !== void 0) {
                                                      let data28 = data25.bodyCaptureReason;
                                                      const _errs60 = errors;
                                                      if (typeof data28 !== "string" && data28 !== null) {
                                                        validate42.errors = [{ instancePath: instancePath + "/response/bodyCaptureReason", schemaPath: "#/$defs/body/properties/bodyCaptureReason/type", keyword: "type", params: { type: schema41.properties.bodyCaptureReason.type }, message: "must be string,null" }];
                                                        return false;
                                                      }
                                                      var valid8 = _errs60 === errors;
                                                    } else {
                                                      var valid8 = true;
                                                    }
                                                    if (valid8) {
                                                      if (data25.redactionStatus !== void 0) {
                                                        let data29 = data25.redactionStatus;
                                                        const _errs62 = errors;
                                                        if (!(data29 === "none" || data29 === "applied" || data29 === "fully_masked" || data29 === "failed_excluded")) {
                                                          validate42.errors = [{ instancePath: instancePath + "/response/redactionStatus", schemaPath: "#/$defs/body/properties/redactionStatus/enum", keyword: "enum", params: { allowedValues: schema41.properties.redactionStatus.enum }, message: "must be equal to one of the allowed values" }];
                                                          return false;
                                                        }
                                                        var valid8 = _errs62 === errors;
                                                      } else {
                                                        var valid8 = true;
                                                      }
                                                      if (valid8) {
                                                        if (data25.originalBytes !== void 0) {
                                                          let data30 = data25.originalBytes;
                                                          const _errs63 = errors;
                                                          if (!(typeof data30 == "number" && (!(data30 % 1) && !isNaN(data30)))) {
                                                            validate42.errors = [{ instancePath: instancePath + "/response/originalBytes", schemaPath: "#/$defs/body/properties/originalBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                            return false;
                                                          }
                                                          if (errors === _errs63) {
                                                            if (typeof data30 == "number") {
                                                              if (data30 < 0 || isNaN(data30)) {
                                                                validate42.errors = [{ instancePath: instancePath + "/response/originalBytes", schemaPath: "#/$defs/body/properties/originalBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                                return false;
                                                              }
                                                            }
                                                          }
                                                          var valid8 = _errs63 === errors;
                                                        } else {
                                                          var valid8 = true;
                                                        }
                                                        if (valid8) {
                                                          if (data25.savedBytes !== void 0) {
                                                            let data31 = data25.savedBytes;
                                                            const _errs65 = errors;
                                                            if (!(typeof data31 == "number" && (!(data31 % 1) && !isNaN(data31)))) {
                                                              validate42.errors = [{ instancePath: instancePath + "/response/savedBytes", schemaPath: "#/$defs/body/properties/savedBytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                                                              return false;
                                                            }
                                                            if (errors === _errs65) {
                                                              if (typeof data31 == "number") {
                                                                if (data31 < 0 || isNaN(data31)) {
                                                                  validate42.errors = [{ instancePath: instancePath + "/response/savedBytes", schemaPath: "#/$defs/body/properties/savedBytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                                                  return false;
                                                                }
                                                              }
                                                            }
                                                            var valid8 = _errs65 === errors;
                                                          } else {
                                                            var valid8 = true;
                                                          }
                                                        }
                                                      }
                                                    }
                                                  }
                                                }
                                              }
                                            } else {
                                              validate42.errors = [{ instancePath: instancePath + "/response", schemaPath: "#/$defs/body/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                              return false;
                                            }
                                          }
                                          var valid6 = _errs54 === errors;
                                          if (valid6) {
                                            const _errs67 = errors;
                                            if (errors === _errs67) {
                                              if (data25 && typeof data25 == "object" && !Array.isArray(data25)) {
                                                let missing4;
                                                if (data25.httpStatus === void 0 && (missing4 = "httpStatus") || data25.headers === void 0 && (missing4 = "headers")) {
                                                  validate42.errors = [{ instancePath: instancePath + "/response", schemaPath: "#/properties/response/allOf/1/required", keyword: "required", params: { missingProperty: missing4 }, message: "must have required property '" + missing4 + "'" }];
                                                  return false;
                                                } else {
                                                  if (data25.httpStatus !== void 0) {
                                                    let data32 = data25.httpStatus;
                                                    const _errs69 = errors;
                                                    const _errs70 = errors;
                                                    let valid10 = false;
                                                    const _errs71 = errors;
                                                    if (!(typeof data32 == "number")) {
                                                      const err0 = { instancePath: instancePath + "/response/httpStatus", schemaPath: "#/properties/response/allOf/1/properties/httpStatus/anyOf/0/type", keyword: "type", params: { type: "number" }, message: "must be number" };
                                                      if (vErrors === null) {
                                                        vErrors = [err0];
                                                      } else {
                                                        vErrors.push(err0);
                                                      }
                                                      errors++;
                                                    }
                                                    var _valid0 = _errs71 === errors;
                                                    valid10 = valid10 || _valid0;
                                                    const _errs73 = errors;
                                                    if ("unknown" !== data32) {
                                                      const err1 = { instancePath: instancePath + "/response/httpStatus", schemaPath: "#/properties/response/allOf/1/properties/httpStatus/anyOf/1/const", keyword: "const", params: { allowedValue: "unknown" }, message: "must be equal to constant" };
                                                      if (vErrors === null) {
                                                        vErrors = [err1];
                                                      } else {
                                                        vErrors.push(err1);
                                                      }
                                                      errors++;
                                                    }
                                                    var _valid0 = _errs73 === errors;
                                                    valid10 = valid10 || _valid0;
                                                    if (!valid10) {
                                                      const err2 = { instancePath: instancePath + "/response/httpStatus", schemaPath: "#/properties/response/allOf/1/properties/httpStatus/anyOf", keyword: "anyOf", params: {}, message: "must match a schema in anyOf" };
                                                      if (vErrors === null) {
                                                        vErrors = [err2];
                                                      } else {
                                                        vErrors.push(err2);
                                                      }
                                                      errors++;
                                                      validate42.errors = vErrors;
                                                      return false;
                                                    } else {
                                                      errors = _errs70;
                                                      if (vErrors !== null) {
                                                        if (_errs70) {
                                                          vErrors.length = _errs70;
                                                        } else {
                                                          vErrors = null;
                                                        }
                                                      }
                                                    }
                                                    var valid9 = _errs69 === errors;
                                                  } else {
                                                    var valid9 = true;
                                                  }
                                                  if (valid9) {
                                                    if (data25.headers !== void 0) {
                                                      let data33 = data25.headers;
                                                      const _errs74 = errors;
                                                      if (errors === _errs74) {
                                                        if (data33 && typeof data33 == "object" && !Array.isArray(data33)) {
                                                          for (const key1 in data33) {
                                                            const _errs77 = errors;
                                                            if (typeof data33[key1] !== "string") {
                                                              validate42.errors = [{ instancePath: instancePath + "/response/headers/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"), schemaPath: "#/properties/response/allOf/1/properties/headers/additionalProperties/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                              return false;
                                                            }
                                                            var valid11 = _errs77 === errors;
                                                            if (!valid11) {
                                                              break;
                                                            }
                                                          }
                                                        } else {
                                                          validate42.errors = [{ instancePath: instancePath + "/response/headers", schemaPath: "#/properties/response/allOf/1/properties/headers/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                          return false;
                                                        }
                                                      }
                                                      var valid9 = _errs74 === errors;
                                                    } else {
                                                      var valid9 = true;
                                                    }
                                                  }
                                                }
                                              } else {
                                                validate42.errors = [{ instancePath: instancePath + "/response", schemaPath: "#/properties/response/allOf/1/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                return false;
                                              }
                                            }
                                            var valid6 = _errs67 === errors;
                                          }
                                          var valid0 = _errs53 === errors;
                                        } else {
                                          var valid0 = true;
                                        }
                                        if (valid0) {
                                          if (data.networkOutcome !== void 0) {
                                            let data35 = data.networkOutcome;
                                            const _errs79 = errors;
                                            if (!(data35 === "finished" || data35 === "failed" || data35 === "incomplete")) {
                                              validate42.errors = [{ instancePath: instancePath + "/networkOutcome", schemaPath: "#/properties/networkOutcome/enum", keyword: "enum", params: { allowedValues: schema65.properties.networkOutcome.enum }, message: "must be equal to one of the allowed values" }];
                                              return false;
                                            }
                                            var valid0 = _errs79 === errors;
                                          } else {
                                            var valid0 = true;
                                          }
                                          if (valid0) {
                                            if (data.businessOutcome !== void 0) {
                                              let data36 = data.businessOutcome;
                                              const _errs80 = errors;
                                              if (!(data36 === "success" || data36 === "failure" || data36 === "unknown")) {
                                                validate42.errors = [{ instancePath: instancePath + "/businessOutcome", schemaPath: "#/properties/businessOutcome/enum", keyword: "enum", params: { allowedValues: schema65.properties.businessOutcome.enum }, message: "must be equal to one of the allowed values" }];
                                                return false;
                                              }
                                              var valid0 = _errs80 === errors;
                                            } else {
                                              var valid0 = true;
                                            }
                                            if (valid0) {
                                              if (data.serverCorrelation !== void 0) {
                                                let data37 = data.serverCorrelation;
                                                const _errs81 = errors;
                                                if (errors === _errs81) {
                                                  if (data37 && typeof data37 == "object" && !Array.isArray(data37)) {
                                                    let missing5;
                                                    if (data37.requestId === void 0 && (missing5 = "requestId") || data37.requestIdSource === void 0 && (missing5 = "requestIdSource") || data37.traceId === void 0 && (missing5 = "traceId") || data37.traceIdSource === void 0 && (missing5 = "traceIdSource")) {
                                                      validate42.errors = [{ instancePath: instancePath + "/serverCorrelation", schemaPath: "#/properties/serverCorrelation/required", keyword: "required", params: { missingProperty: missing5 }, message: "must have required property '" + missing5 + "'" }];
                                                      return false;
                                                    } else {
                                                      if (data37.requestId !== void 0) {
                                                        let data38 = data37.requestId;
                                                        const _errs83 = errors;
                                                        if (typeof data38 !== "string" && data38 !== null) {
                                                          validate42.errors = [{ instancePath: instancePath + "/serverCorrelation/requestId", schemaPath: "#/properties/serverCorrelation/properties/requestId/type", keyword: "type", params: { type: schema65.properties.serverCorrelation.properties.requestId.type }, message: "must be string,null" }];
                                                          return false;
                                                        }
                                                        var valid12 = _errs83 === errors;
                                                      } else {
                                                        var valid12 = true;
                                                      }
                                                      if (valid12) {
                                                        if (data37.requestIdSource !== void 0) {
                                                          let data39 = data37.requestIdSource;
                                                          const _errs85 = errors;
                                                          if (typeof data39 !== "string" && data39 !== null) {
                                                            validate42.errors = [{ instancePath: instancePath + "/serverCorrelation/requestIdSource", schemaPath: "#/properties/serverCorrelation/properties/requestIdSource/type", keyword: "type", params: { type: schema65.properties.serverCorrelation.properties.requestIdSource.type }, message: "must be string,null" }];
                                                            return false;
                                                          }
                                                          var valid12 = _errs85 === errors;
                                                        } else {
                                                          var valid12 = true;
                                                        }
                                                        if (valid12) {
                                                          if (data37.traceId !== void 0) {
                                                            let data40 = data37.traceId;
                                                            const _errs87 = errors;
                                                            if (typeof data40 !== "string" && data40 !== null) {
                                                              validate42.errors = [{ instancePath: instancePath + "/serverCorrelation/traceId", schemaPath: "#/properties/serverCorrelation/properties/traceId/type", keyword: "type", params: { type: schema65.properties.serverCorrelation.properties.traceId.type }, message: "must be string,null" }];
                                                              return false;
                                                            }
                                                            var valid12 = _errs87 === errors;
                                                          } else {
                                                            var valid12 = true;
                                                          }
                                                          if (valid12) {
                                                            if (data37.traceIdSource !== void 0) {
                                                              let data41 = data37.traceIdSource;
                                                              const _errs89 = errors;
                                                              if (typeof data41 !== "string" && data41 !== null) {
                                                                validate42.errors = [{ instancePath: instancePath + "/serverCorrelation/traceIdSource", schemaPath: "#/properties/serverCorrelation/properties/traceIdSource/type", keyword: "type", params: { type: schema65.properties.serverCorrelation.properties.traceIdSource.type }, message: "must be string,null" }];
                                                                return false;
                                                              }
                                                              var valid12 = _errs89 === errors;
                                                            } else {
                                                              var valid12 = true;
                                                            }
                                                            if (valid12) {
                                                              if (data37.spanId !== void 0) {
                                                                let data42 = data37.spanId;
                                                                const _errs91 = errors;
                                                                if (typeof data42 !== "string" && data42 !== null) {
                                                                  validate42.errors = [{ instancePath: instancePath + "/serverCorrelation/spanId", schemaPath: "#/properties/serverCorrelation/properties/spanId/type", keyword: "type", params: { type: schema65.properties.serverCorrelation.properties.spanId.type }, message: "must be string,null" }];
                                                                  return false;
                                                                }
                                                                var valid12 = _errs91 === errors;
                                                              } else {
                                                                var valid12 = true;
                                                              }
                                                            }
                                                          }
                                                        }
                                                      }
                                                    }
                                                  } else {
                                                    validate42.errors = [{ instancePath: instancePath + "/serverCorrelation", schemaPath: "#/properties/serverCorrelation/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                    return false;
                                                  }
                                                }
                                                var valid0 = _errs81 === errors;
                                              } else {
                                                var valid0 = true;
                                              }
                                              if (valid0) {
                                                if (data.startedAt !== void 0) {
                                                  const _errs93 = errors;
                                                  if (typeof data.startedAt !== "string") {
                                                    validate42.errors = [{ instancePath: instancePath + "/startedAt", schemaPath: "#/properties/startedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                    return false;
                                                  }
                                                  var valid0 = _errs93 === errors;
                                                } else {
                                                  var valid0 = true;
                                                }
                                                if (valid0) {
                                                  if (data.sourceClock !== void 0) {
                                                    const _errs95 = errors;
                                                    if (typeof data.sourceClock !== "string") {
                                                      validate42.errors = [{ instancePath: instancePath + "/sourceClock", schemaPath: "#/properties/sourceClock/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                      return false;
                                                    }
                                                    var valid0 = _errs95 === errors;
                                                  } else {
                                                    var valid0 = true;
                                                  }
                                                  if (valid0) {
                                                    if (data.evidenceRefs !== void 0) {
                                                      let data45 = data.evidenceRefs;
                                                      const _errs97 = errors;
                                                      if (errors === _errs97) {
                                                        if (Array.isArray(data45)) {
                                                          var valid13 = true;
                                                          const len0 = data45.length;
                                                          for (let i0 = 0; i0 < len0; i0++) {
                                                            let data46 = data45[i0];
                                                            const _errs99 = errors;
                                                            if (errors === _errs99) {
                                                              if (typeof data46 === "string") {
                                                                if (func1(data46) > 256) {
                                                                  validate42.errors = [{ instancePath: instancePath + "/evidenceRefs/" + i0, schemaPath: "#/properties/evidenceRefs/items/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                                                  return false;
                                                                } else {
                                                                  if (func1(data46) < 1) {
                                                                    validate42.errors = [{ instancePath: instancePath + "/evidenceRefs/" + i0, schemaPath: "#/properties/evidenceRefs/items/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                    return false;
                                                                  }
                                                                }
                                                              } else {
                                                                validate42.errors = [{ instancePath: instancePath + "/evidenceRefs/" + i0, schemaPath: "#/properties/evidenceRefs/items/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                return false;
                                                              }
                                                            }
                                                            var valid13 = _errs99 === errors;
                                                            if (!valid13) {
                                                              break;
                                                            }
                                                          }
                                                        } else {
                                                          validate42.errors = [{ instancePath: instancePath + "/evidenceRefs", schemaPath: "#/properties/evidenceRefs/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                          return false;
                                                        }
                                                      }
                                                      var valid0 = _errs97 === errors;
                                                    } else {
                                                      var valid0 = true;
                                                    }
                                                    if (valid0) {
                                                      if (data.actionCandidates !== void 0) {
                                                        let data47 = data.actionCandidates;
                                                        const _errs101 = errors;
                                                        if (errors === _errs101) {
                                                          if (Array.isArray(data47)) {
                                                            var valid14 = true;
                                                            const len1 = data47.length;
                                                            for (let i1 = 0; i1 < len1; i1++) {
                                                              let data48 = data47[i1];
                                                              const _errs103 = errors;
                                                              if (errors === _errs103) {
                                                                if (data48 && typeof data48 == "object" && !Array.isArray(data48)) {
                                                                  let missing6;
                                                                  if (data48.actionId === void 0 && (missing6 = "actionId") || data48.basis === void 0 && (missing6 = "basis") || data48.confirmed === void 0 && (missing6 = "confirmed")) {
                                                                    validate42.errors = [{ instancePath: instancePath + "/actionCandidates/" + i1, schemaPath: "#/properties/actionCandidates/items/required", keyword: "required", params: { missingProperty: missing6 }, message: "must have required property '" + missing6 + "'" }];
                                                                    return false;
                                                                  } else {
                                                                    if (data48.actionId !== void 0) {
                                                                      let data49 = data48.actionId;
                                                                      const _errs105 = errors;
                                                                      if (errors === _errs105) {
                                                                        if (typeof data49 === "string") {
                                                                          if (func1(data49) > 256) {
                                                                            validate42.errors = [{ instancePath: instancePath + "/actionCandidates/" + i1 + "/actionId", schemaPath: "#/properties/actionCandidates/items/properties/actionId/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                                                            return false;
                                                                          } else {
                                                                            if (func1(data49) < 1) {
                                                                              validate42.errors = [{ instancePath: instancePath + "/actionCandidates/" + i1 + "/actionId", schemaPath: "#/properties/actionCandidates/items/properties/actionId/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                              return false;
                                                                            }
                                                                          }
                                                                        } else {
                                                                          validate42.errors = [{ instancePath: instancePath + "/actionCandidates/" + i1 + "/actionId", schemaPath: "#/properties/actionCandidates/items/properties/actionId/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                          return false;
                                                                        }
                                                                      }
                                                                      var valid15 = _errs105 === errors;
                                                                    } else {
                                                                      var valid15 = true;
                                                                    }
                                                                    if (valid15) {
                                                                      if (data48.basis !== void 0) {
                                                                        const _errs107 = errors;
                                                                        if (typeof data48.basis !== "string") {
                                                                          validate42.errors = [{ instancePath: instancePath + "/actionCandidates/" + i1 + "/basis", schemaPath: "#/properties/actionCandidates/items/properties/basis/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                          return false;
                                                                        }
                                                                        var valid15 = _errs107 === errors;
                                                                      } else {
                                                                        var valid15 = true;
                                                                      }
                                                                      if (valid15) {
                                                                        if (data48.confirmed !== void 0) {
                                                                          const _errs109 = errors;
                                                                          if (false !== data48.confirmed) {
                                                                            validate42.errors = [{ instancePath: instancePath + "/actionCandidates/" + i1 + "/confirmed", schemaPath: "#/properties/actionCandidates/items/properties/confirmed/const", keyword: "const", params: { allowedValue: false }, message: "must be equal to constant" }];
                                                                            return false;
                                                                          }
                                                                          var valid15 = _errs109 === errors;
                                                                        } else {
                                                                          var valid15 = true;
                                                                        }
                                                                      }
                                                                    }
                                                                  }
                                                                } else {
                                                                  validate42.errors = [{ instancePath: instancePath + "/actionCandidates/" + i1, schemaPath: "#/properties/actionCandidates/items/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                  return false;
                                                                }
                                                              }
                                                              var valid14 = _errs103 === errors;
                                                              if (!valid14) {
                                                                break;
                                                              }
                                                            }
                                                          } else {
                                                            validate42.errors = [{ instancePath: instancePath + "/actionCandidates", schemaPath: "#/properties/actionCandidates/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                            return false;
                                                          }
                                                        }
                                                        var valid0 = _errs101 === errors;
                                                      } else {
                                                        var valid0 = true;
                                                      }
                                                      if (valid0) {
                                                        if (data.extraInfoStatus !== void 0) {
                                                          const _errs110 = errors;
                                                          if (typeof data.extraInfoStatus !== "string") {
                                                            validate42.errors = [{ instancePath: instancePath + "/extraInfoStatus", schemaPath: "#/properties/extraInfoStatus/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                            return false;
                                                          }
                                                          var valid0 = _errs110 === errors;
                                                        } else {
                                                          var valid0 = true;
                                                        }
                                                        if (valid0) {
                                                          if (data.correlationFacts !== void 0) {
                                                            let data53 = data.correlationFacts;
                                                            const _errs112 = errors;
                                                            if (errors === _errs112) {
                                                              if (Array.isArray(data53)) {
                                                                var valid16 = true;
                                                                const len2 = data53.length;
                                                                for (let i2 = 0; i2 < len2; i2++) {
                                                                  let data54 = data53[i2];
                                                                  const _errs114 = errors;
                                                                  const _errs115 = errors;
                                                                  if (errors === _errs115) {
                                                                    if (data54 && typeof data54 == "object" && !Array.isArray(data54)) {
                                                                      let missing7;
                                                                      if (data54.field === void 0 && (missing7 = "field") || data54.source === void 0 && (missing7 = "source") || data54.value === void 0 && (missing7 = "value") || data54.component === void 0 && (missing7 = "component") || data54.observedAt === void 0 && (missing7 = "observedAt")) {
                                                                        validate42.errors = [{ instancePath: instancePath + "/correlationFacts/" + i2, schemaPath: "#/$defs/correlationFact/required", keyword: "required", params: { missingProperty: missing7 }, message: "must have required property '" + missing7 + "'" }];
                                                                        return false;
                                                                      } else {
                                                                        if (data54.field !== void 0) {
                                                                          let data55 = data54.field;
                                                                          const _errs117 = errors;
                                                                          if (!(data55 === "frontendBuildId" || data55 === "backendBuildId" || data55 === "serviceInstance" || data55 === "requestId" || data55 === "traceId" || data55 === "spanId")) {
                                                                            validate42.errors = [{ instancePath: instancePath + "/correlationFacts/" + i2 + "/field", schemaPath: "#/$defs/correlationFact/properties/field/enum", keyword: "enum", params: { allowedValues: schema64.properties.field.enum }, message: "must be equal to one of the allowed values" }];
                                                                            return false;
                                                                          }
                                                                          var valid18 = _errs117 === errors;
                                                                        } else {
                                                                          var valid18 = true;
                                                                        }
                                                                        if (valid18) {
                                                                          if (data54.source !== void 0) {
                                                                            const _errs118 = errors;
                                                                            if (typeof data54.source !== "string") {
                                                                              validate42.errors = [{ instancePath: instancePath + "/correlationFacts/" + i2 + "/source", schemaPath: "#/$defs/correlationFact/properties/source/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                              return false;
                                                                            }
                                                                            var valid18 = _errs118 === errors;
                                                                          } else {
                                                                            var valid18 = true;
                                                                          }
                                                                          if (valid18) {
                                                                            if (data54.value !== void 0) {
                                                                              let data57 = data54.value;
                                                                              const _errs120 = errors;
                                                                              if (errors === _errs120) {
                                                                                if (typeof data57 === "string") {
                                                                                  if (func1(data57) > 256) {
                                                                                    validate42.errors = [{ instancePath: instancePath + "/correlationFacts/" + i2 + "/value", schemaPath: "#/$defs/correlationFact/properties/value/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                                                                                    return false;
                                                                                  } else {
                                                                                    if (func1(data57) < 1) {
                                                                                      validate42.errors = [{ instancePath: instancePath + "/correlationFacts/" + i2 + "/value", schemaPath: "#/$defs/correlationFact/properties/value/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                      return false;
                                                                                    }
                                                                                  }
                                                                                } else {
                                                                                  validate42.errors = [{ instancePath: instancePath + "/correlationFacts/" + i2 + "/value", schemaPath: "#/$defs/correlationFact/properties/value/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                  return false;
                                                                                }
                                                                              }
                                                                              var valid18 = _errs120 === errors;
                                                                            } else {
                                                                              var valid18 = true;
                                                                            }
                                                                            if (valid18) {
                                                                              if (data54.component !== void 0) {
                                                                                let data58 = data54.component;
                                                                                const _errs122 = errors;
                                                                                if (errors === _errs122) {
                                                                                  if (typeof data58 === "string") {
                                                                                    if (func1(data58) > 80) {
                                                                                      validate42.errors = [{ instancePath: instancePath + "/correlationFacts/" + i2 + "/component", schemaPath: "#/$defs/correlationFact/properties/component/maxLength", keyword: "maxLength", params: { limit: 80 }, message: "must NOT have more than 80 characters" }];
                                                                                      return false;
                                                                                    } else {
                                                                                      if (func1(data58) < 1) {
                                                                                        validate42.errors = [{ instancePath: instancePath + "/correlationFacts/" + i2 + "/component", schemaPath: "#/$defs/correlationFact/properties/component/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                                                                                        return false;
                                                                                      }
                                                                                    }
                                                                                  } else {
                                                                                    validate42.errors = [{ instancePath: instancePath + "/correlationFacts/" + i2 + "/component", schemaPath: "#/$defs/correlationFact/properties/component/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                    return false;
                                                                                  }
                                                                                }
                                                                                var valid18 = _errs122 === errors;
                                                                              } else {
                                                                                var valid18 = true;
                                                                              }
                                                                              if (valid18) {
                                                                                if (data54.observedAt !== void 0) {
                                                                                  const _errs124 = errors;
                                                                                  if (typeof data54.observedAt !== "string") {
                                                                                    validate42.errors = [{ instancePath: instancePath + "/correlationFacts/" + i2 + "/observedAt", schemaPath: "#/$defs/correlationFact/properties/observedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                                                                                    return false;
                                                                                  }
                                                                                  var valid18 = _errs124 === errors;
                                                                                } else {
                                                                                  var valid18 = true;
                                                                                }
                                                                              }
                                                                            }
                                                                          }
                                                                        }
                                                                      }
                                                                    } else {
                                                                      validate42.errors = [{ instancePath: instancePath + "/correlationFacts/" + i2, schemaPath: "#/$defs/correlationFact/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                                                                      return false;
                                                                    }
                                                                  }
                                                                  var valid16 = _errs114 === errors;
                                                                  if (!valid16) {
                                                                    break;
                                                                  }
                                                                }
                                                              } else {
                                                                validate42.errors = [{ instancePath: instancePath + "/correlationFacts", schemaPath: "#/properties/correlationFacts/type", keyword: "type", params: { type: "array" }, message: "must be array" }];
                                                                return false;
                                                              }
                                                            }
                                                            var valid0 = _errs112 === errors;
                                                          } else {
                                                            var valid0 = true;
                                                          }
                                                        }
                                                      }
                                                    }
                                                  }
                                                }
                                              }
                                            }
                                          }
                                        }
                                      }
                                    }
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        } else {
          validate42.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate42.errors = vErrors;
      return errors === 0;
    }
    validate42.evaluated = { "props": { "schemaVersion": true, "requestKey": true, "recordingId": true, "browserRunId": true, "tabInstanceId": true, "debuggerSessionKey": true, "cdpRequestId": true, "redirectOrdinal": true, "cdpFrameId": true, "loaderId": true, "chromeFrameId": true, "documentId": true, "frameMappingReason": true, "request": true, "response": true, "networkOutcome": true, "businessOutcome": true, "serverCorrelation": true, "startedAt": true, "sourceClock": true, "evidenceRefs": true, "actionCandidates": true, "extraInfoStatus": true, "correlationFacts": true }, "dynamicProps": false, "dynamicItems": false };
    exports.file = validate43;
    function validate43(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate43.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.path === void 0 && (missing0 = "path") || data.mime === void 0 && (missing0 = "mime") || data.bytes === void 0 && (missing0 = "bytes") || data.sha256 === void 0 && (missing0 = "sha256") || data.streamId === void 0 && (missing0 = "streamId") || data.firstSeq === void 0 && (missing0 = "firstSeq") || data.lastSeq === void 0 && (missing0 = "lastSeq") || data.events === void 0 && (missing0 = "events")) {
            validate43.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.path !== void 0) {
              let data0 = data.path;
              const _errs1 = errors;
              if (errors === _errs1) {
                if (typeof data0 === "string") {
                  if (!pattern9.test(data0)) {
                    validate43.errors = [{ instancePath: instancePath + "/path", schemaPath: "#/properties/path/pattern", keyword: "pattern", params: { pattern: "^[a-zA-Z0-9_./-]+$" }, message: 'must match pattern "^[a-zA-Z0-9_./-]+$"' }];
                    return false;
                  }
                } else {
                  validate43.errors = [{ instancePath: instancePath + "/path", schemaPath: "#/properties/path/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                  return false;
                }
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.mime !== void 0) {
                const _errs3 = errors;
                if (typeof data.mime !== "string") {
                  validate43.errors = [{ instancePath: instancePath + "/mime", schemaPath: "#/properties/mime/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                  return false;
                }
                var valid0 = _errs3 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.bytes !== void 0) {
                  let data2 = data.bytes;
                  const _errs5 = errors;
                  if (!(typeof data2 == "number" && (!(data2 % 1) && !isNaN(data2)))) {
                    validate43.errors = [{ instancePath: instancePath + "/bytes", schemaPath: "#/properties/bytes/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                    return false;
                  }
                  if (errors === _errs5) {
                    if (typeof data2 == "number") {
                      if (data2 < 0 || isNaN(data2)) {
                        validate43.errors = [{ instancePath: instancePath + "/bytes", schemaPath: "#/properties/bytes/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                        return false;
                      }
                    }
                  }
                  var valid0 = _errs5 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.sha256 !== void 0) {
                    let data3 = data.sha256;
                    const _errs7 = errors;
                    if (errors === _errs7) {
                      if (typeof data3 === "string") {
                        if (!pattern10.test(data3)) {
                          validate43.errors = [{ instancePath: instancePath + "/sha256", schemaPath: "#/properties/sha256/pattern", keyword: "pattern", params: { pattern: "^[0-9a-f]{64}$" }, message: 'must match pattern "^[0-9a-f]{64}$"' }];
                          return false;
                        }
                      } else {
                        validate43.errors = [{ instancePath: instancePath + "/sha256", schemaPath: "#/properties/sha256/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                        return false;
                      }
                    }
                    var valid0 = _errs7 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.streamId !== void 0) {
                      let data4 = data.streamId;
                      const _errs9 = errors;
                      if (typeof data4 !== "string" && data4 !== null) {
                        validate43.errors = [{ instancePath: instancePath + "/streamId", schemaPath: "#/properties/streamId/type", keyword: "type", params: { type: schema36.properties.streamId.type }, message: "must be string,null" }];
                        return false;
                      }
                      var valid0 = _errs9 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.firstSeq !== void 0) {
                        let data5 = data.firstSeq;
                        const _errs11 = errors;
                        if (!(typeof data5 == "number" && (!(data5 % 1) && !isNaN(data5))) && data5 !== null) {
                          validate43.errors = [{ instancePath: instancePath + "/firstSeq", schemaPath: "#/properties/firstSeq/type", keyword: "type", params: { type: schema36.properties.firstSeq.type }, message: "must be integer,null" }];
                          return false;
                        }
                        var valid0 = _errs11 === errors;
                      } else {
                        var valid0 = true;
                      }
                      if (valid0) {
                        if (data.lastSeq !== void 0) {
                          let data6 = data.lastSeq;
                          const _errs13 = errors;
                          if (!(typeof data6 == "number" && (!(data6 % 1) && !isNaN(data6))) && data6 !== null) {
                            validate43.errors = [{ instancePath: instancePath + "/lastSeq", schemaPath: "#/properties/lastSeq/type", keyword: "type", params: { type: schema36.properties.lastSeq.type }, message: "must be integer,null" }];
                            return false;
                          }
                          var valid0 = _errs13 === errors;
                        } else {
                          var valid0 = true;
                        }
                        if (valid0) {
                          if (data.events !== void 0) {
                            let data7 = data.events;
                            const _errs15 = errors;
                            if (!(typeof data7 == "number" && (!(data7 % 1) && !isNaN(data7)))) {
                              validate43.errors = [{ instancePath: instancePath + "/events", schemaPath: "#/properties/events/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                              return false;
                            }
                            if (errors === _errs15) {
                              if (typeof data7 == "number") {
                                if (data7 < 0 || isNaN(data7)) {
                                  validate43.errors = [{ instancePath: instancePath + "/events", schemaPath: "#/properties/events/minimum", keyword: "minimum", params: { comparison: ">=", limit: 0 }, message: "must be >= 0" }];
                                  return false;
                                }
                              }
                            }
                            var valid0 = _errs15 === errors;
                          } else {
                            var valid0 = true;
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        } else {
          validate43.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate43.errors = vErrors;
      return errors === 0;
    }
    validate43.evaluated = { "props": { "path": true, "mime": true, "bytes": true, "sha256": true, "streamId": true, "firstSeq": true, "lastSeq": true, "events": true }, "dynamicProps": false, "dynamicItems": false };
    exports.pagePacket = validate44;
    var schema70 = { "type": "object", "required": ["seq", "kind", "sourceTime", "payload"], "properties": { "seq": { "type": "integer", "minimum": 1 }, "kind": { "enum": ["rrweb.event", "ui.observation", "capture.page_diagnostic"] }, "sourceTime": { "type": "number" }, "payload": { "type": "object" } } };
    function validate44(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate44.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.seq === void 0 && (missing0 = "seq") || data.kind === void 0 && (missing0 = "kind") || data.sourceTime === void 0 && (missing0 = "sourceTime") || data.payload === void 0 && (missing0 = "payload")) {
            validate44.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.seq !== void 0) {
              let data0 = data.seq;
              const _errs1 = errors;
              if (!(typeof data0 == "number" && (!(data0 % 1) && !isNaN(data0)))) {
                validate44.errors = [{ instancePath: instancePath + "/seq", schemaPath: "#/properties/seq/type", keyword: "type", params: { type: "integer" }, message: "must be integer" }];
                return false;
              }
              if (errors === _errs1) {
                if (typeof data0 == "number") {
                  if (data0 < 1 || isNaN(data0)) {
                    validate44.errors = [{ instancePath: instancePath + "/seq", schemaPath: "#/properties/seq/minimum", keyword: "minimum", params: { comparison: ">=", limit: 1 }, message: "must be >= 1" }];
                    return false;
                  }
                }
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.kind !== void 0) {
                let data1 = data.kind;
                const _errs3 = errors;
                if (!(data1 === "rrweb.event" || data1 === "ui.observation" || data1 === "capture.page_diagnostic")) {
                  validate44.errors = [{ instancePath: instancePath + "/kind", schemaPath: "#/properties/kind/enum", keyword: "enum", params: { allowedValues: schema70.properties.kind.enum }, message: "must be equal to one of the allowed values" }];
                  return false;
                }
                var valid0 = _errs3 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.sourceTime !== void 0) {
                  const _errs4 = errors;
                  if (!(typeof data.sourceTime == "number")) {
                    validate44.errors = [{ instancePath: instancePath + "/sourceTime", schemaPath: "#/properties/sourceTime/type", keyword: "type", params: { type: "number" }, message: "must be number" }];
                    return false;
                  }
                  var valid0 = _errs4 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.payload !== void 0) {
                    let data3 = data.payload;
                    const _errs6 = errors;
                    if (!(data3 && typeof data3 == "object" && !Array.isArray(data3))) {
                      validate44.errors = [{ instancePath: instancePath + "/payload", schemaPath: "#/properties/payload/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
                      return false;
                    }
                    var valid0 = _errs6 === errors;
                  } else {
                    var valid0 = true;
                  }
                }
              }
            }
          }
        } else {
          validate44.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate44.errors = vErrors;
      return errors === 0;
    }
    validate44.evaluated = { "props": { "seq": true, "kind": true, "sourceTime": true, "payload": true }, "dynamicProps": false, "dynamicItems": false };
    exports.correlationFact = validate45;
    function validate45(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate45.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      if (errors === 0) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.field === void 0 && (missing0 = "field") || data.source === void 0 && (missing0 = "source") || data.value === void 0 && (missing0 = "value") || data.component === void 0 && (missing0 = "component") || data.observedAt === void 0 && (missing0 = "observedAt")) {
            validate45.errors = [{ instancePath, schemaPath: "#/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" }];
            return false;
          } else {
            if (data.field !== void 0) {
              let data0 = data.field;
              const _errs1 = errors;
              if (!(data0 === "frontendBuildId" || data0 === "backendBuildId" || data0 === "serviceInstance" || data0 === "requestId" || data0 === "traceId" || data0 === "spanId")) {
                validate45.errors = [{ instancePath: instancePath + "/field", schemaPath: "#/properties/field/enum", keyword: "enum", params: { allowedValues: schema64.properties.field.enum }, message: "must be equal to one of the allowed values" }];
                return false;
              }
              var valid0 = _errs1 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.source !== void 0) {
                const _errs2 = errors;
                if (typeof data.source !== "string") {
                  validate45.errors = [{ instancePath: instancePath + "/source", schemaPath: "#/properties/source/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                  return false;
                }
                var valid0 = _errs2 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.value !== void 0) {
                  let data2 = data.value;
                  const _errs4 = errors;
                  if (errors === _errs4) {
                    if (typeof data2 === "string") {
                      if (func1(data2) > 256) {
                        validate45.errors = [{ instancePath: instancePath + "/value", schemaPath: "#/properties/value/maxLength", keyword: "maxLength", params: { limit: 256 }, message: "must NOT have more than 256 characters" }];
                        return false;
                      } else {
                        if (func1(data2) < 1) {
                          validate45.errors = [{ instancePath: instancePath + "/value", schemaPath: "#/properties/value/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                          return false;
                        }
                      }
                    } else {
                      validate45.errors = [{ instancePath: instancePath + "/value", schemaPath: "#/properties/value/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                      return false;
                    }
                  }
                  var valid0 = _errs4 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.component !== void 0) {
                    let data3 = data.component;
                    const _errs6 = errors;
                    if (errors === _errs6) {
                      if (typeof data3 === "string") {
                        if (func1(data3) > 80) {
                          validate45.errors = [{ instancePath: instancePath + "/component", schemaPath: "#/properties/component/maxLength", keyword: "maxLength", params: { limit: 80 }, message: "must NOT have more than 80 characters" }];
                          return false;
                        } else {
                          if (func1(data3) < 1) {
                            validate45.errors = [{ instancePath: instancePath + "/component", schemaPath: "#/properties/component/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" }];
                            return false;
                          }
                        }
                      } else {
                        validate45.errors = [{ instancePath: instancePath + "/component", schemaPath: "#/properties/component/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                        return false;
                      }
                    }
                    var valid0 = _errs6 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.observedAt !== void 0) {
                      const _errs8 = errors;
                      if (typeof data.observedAt !== "string") {
                        validate45.errors = [{ instancePath: instancePath + "/observedAt", schemaPath: "#/properties/observedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" }];
                        return false;
                      }
                      var valid0 = _errs8 === errors;
                    } else {
                      var valid0 = true;
                    }
                  }
                }
              }
            }
          }
        } else {
          validate45.errors = [{ instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" }];
          return false;
        }
      }
      validate45.errors = vErrors;
      return errors === 0;
    }
    validate45.evaluated = { "props": { "field": true, "source": true, "value": true, "component": true, "observedAt": true }, "dynamicProps": false, "dynamicItems": false };
    exports.semanticBefore = validate46;
    function validate46(data, { instancePath = "", parentData, parentDataProperty, rootData = data, dynamicAnchors = {} } = {}) {
      let vErrors = null;
      let errors = 0;
      const evaluated0 = validate46.evaluated;
      if (evaluated0.dynamicProps) {
        evaluated0.props = void 0;
      }
      if (evaluated0.dynamicItems) {
        evaluated0.items = void 0;
      }
      const _errs0 = errors;
      let valid0 = false;
      let passing0 = null;
      const _errs1 = errors;
      if (errors === _errs1) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing0;
          if (data.status === void 0 && (missing0 = "status") || data.reason === void 0 && (missing0 = "reason")) {
            const err0 = { instancePath, schemaPath: "#/oneOf/0/required", keyword: "required", params: { missingProperty: missing0 }, message: "must have required property '" + missing0 + "'" };
            if (vErrors === null) {
              vErrors = [err0];
            } else {
              vErrors.push(err0);
            }
            errors++;
          } else {
            if (data.status !== void 0) {
              const _errs3 = errors;
              if ("unavailable" !== data.status) {
                const err1 = { instancePath: instancePath + "/status", schemaPath: "#/oneOf/0/properties/status/const", keyword: "const", params: { allowedValue: "unavailable" }, message: "must be equal to constant" };
                if (vErrors === null) {
                  vErrors = [err1];
                } else {
                  vErrors.push(err1);
                }
                errors++;
              }
              var valid1 = _errs3 === errors;
            } else {
              var valid1 = true;
            }
            if (valid1) {
              if (data.reason !== void 0) {
                const _errs4 = errors;
                if (typeof data.reason !== "string") {
                  const err2 = { instancePath: instancePath + "/reason", schemaPath: "#/oneOf/0/properties/reason/type", keyword: "type", params: { type: "string" }, message: "must be string" };
                  if (vErrors === null) {
                    vErrors = [err2];
                  } else {
                    vErrors.push(err2);
                  }
                  errors++;
                }
                var valid1 = _errs4 === errors;
              } else {
                var valid1 = true;
              }
            }
          }
        } else {
          const err3 = { instancePath, schemaPath: "#/oneOf/0/type", keyword: "type", params: { type: "object" }, message: "must be object" };
          if (vErrors === null) {
            vErrors = [err3];
          } else {
            vErrors.push(err3);
          }
          errors++;
        }
      }
      var _valid0 = _errs1 === errors;
      if (_valid0) {
        valid0 = true;
        passing0 = 0;
        var props0 = {};
        props0.status = true;
        props0.reason = true;
      }
      const _errs6 = errors;
      if (errors === _errs6) {
        if (data && typeof data == "object" && !Array.isArray(data)) {
          let missing1;
          if (data.status === void 0 && (missing1 = "status") || data.snapshotRef === void 0 && (missing1 = "snapshotRef") || data.observedAt === void 0 && (missing1 = "observedAt") || data.sourceTime === void 0 && (missing1 = "sourceTime")) {
            const err4 = { instancePath, schemaPath: "#/oneOf/1/required", keyword: "required", params: { missingProperty: missing1 }, message: "must have required property '" + missing1 + "'" };
            if (vErrors === null) {
              vErrors = [err4];
            } else {
              vErrors.push(err4);
            }
            errors++;
          } else {
            if (data.status !== void 0) {
              const _errs8 = errors;
              if ("observed" !== data.status) {
                const err5 = { instancePath: instancePath + "/status", schemaPath: "#/oneOf/1/properties/status/const", keyword: "const", params: { allowedValue: "observed" }, message: "must be equal to constant" };
                if (vErrors === null) {
                  vErrors = [err5];
                } else {
                  vErrors.push(err5);
                }
                errors++;
              }
              var valid2 = _errs8 === errors;
            } else {
              var valid2 = true;
            }
            if (valid2) {
              if (data.snapshotRef !== void 0) {
                let data3 = data.snapshotRef;
                const _errs9 = errors;
                if (errors === _errs9) {
                  if (typeof data3 === "string") {
                    if (func1(data3) < 1) {
                      const err6 = { instancePath: instancePath + "/snapshotRef", schemaPath: "#/oneOf/1/properties/snapshotRef/minLength", keyword: "minLength", params: { limit: 1 }, message: "must NOT have fewer than 1 characters" };
                      if (vErrors === null) {
                        vErrors = [err6];
                      } else {
                        vErrors.push(err6);
                      }
                      errors++;
                    }
                  } else {
                    const err7 = { instancePath: instancePath + "/snapshotRef", schemaPath: "#/oneOf/1/properties/snapshotRef/type", keyword: "type", params: { type: "string" }, message: "must be string" };
                    if (vErrors === null) {
                      vErrors = [err7];
                    } else {
                      vErrors.push(err7);
                    }
                    errors++;
                  }
                }
                var valid2 = _errs9 === errors;
              } else {
                var valid2 = true;
              }
              if (valid2) {
                if (data.observedAt !== void 0) {
                  const _errs11 = errors;
                  if (typeof data.observedAt !== "string") {
                    const err8 = { instancePath: instancePath + "/observedAt", schemaPath: "#/oneOf/1/properties/observedAt/type", keyword: "type", params: { type: "string" }, message: "must be string" };
                    if (vErrors === null) {
                      vErrors = [err8];
                    } else {
                      vErrors.push(err8);
                    }
                    errors++;
                  }
                  var valid2 = _errs11 === errors;
                } else {
                  var valid2 = true;
                }
                if (valid2) {
                  if (data.sourceTime !== void 0) {
                    const _errs13 = errors;
                    if (!(typeof data.sourceTime == "number")) {
                      const err9 = { instancePath: instancePath + "/sourceTime", schemaPath: "#/oneOf/1/properties/sourceTime/type", keyword: "type", params: { type: "number" }, message: "must be number" };
                      if (vErrors === null) {
                        vErrors = [err9];
                      } else {
                        vErrors.push(err9);
                      }
                      errors++;
                    }
                    var valid2 = _errs13 === errors;
                  } else {
                    var valid2 = true;
                  }
                }
              }
            }
          }
        } else {
          const err10 = { instancePath, schemaPath: "#/oneOf/1/type", keyword: "type", params: { type: "object" }, message: "must be object" };
          if (vErrors === null) {
            vErrors = [err10];
          } else {
            vErrors.push(err10);
          }
          errors++;
        }
      }
      var _valid0 = _errs6 === errors;
      if (_valid0 && valid0) {
        valid0 = false;
        passing0 = [passing0, 1];
      } else {
        if (_valid0) {
          valid0 = true;
          passing0 = 1;
          if (props0 !== true) {
            props0 = props0 || {};
            props0.status = true;
            props0.snapshotRef = true;
            props0.observedAt = true;
            props0.sourceTime = true;
          }
        }
      }
      if (!valid0) {
        const err11 = { instancePath, schemaPath: "#/oneOf", keyword: "oneOf", params: { passingSchemas: passing0 }, message: "must match exactly one schema in oneOf" };
        if (vErrors === null) {
          vErrors = [err11];
        } else {
          vErrors.push(err11);
        }
        errors++;
        validate46.errors = vErrors;
        return false;
      } else {
        errors = _errs0;
        if (vErrors !== null) {
          if (_errs0) {
            vErrors.length = _errs0;
          } else {
            vErrors = null;
          }
        }
      }
      validate46.errors = vErrors;
      evaluated0.props = props0;
      return errors === 0;
    }
    validate46.evaluated = { "dynamicProps": true, "dynamicItems": false };
  }
});
export default require_stdin();
