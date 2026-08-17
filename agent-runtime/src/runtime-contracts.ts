import type {
  AgentExecutionRequestV1,
  RuntimeEvent as RuntimeEventV1,
  RuntimeFailure as RuntimeFailureV1,
  RuntimeProvenance as RuntimeProvenanceV1,
  TerminalResult as TerminalResultV1,
  ToolEvent as ToolEventV1,
  Usage as UsageV1
} from "./generated/contracts.js";
import type {
  AgentExecutionRequestV11,
  RuntimeEvent as RuntimeEventV11,
  RuntimeFailure as RuntimeFailureV11,
  RuntimeProvenance as RuntimeProvenanceV11,
  TerminalResult as TerminalResultV11,
  ToolEvent as ToolEventV11,
  Usage as UsageV11
} from "./generated/contracts-v1_1.js";
import type {
  AgentExecutionRequestV12,
  ApiRetry,
  ExecutionAccounting,
  ModelCall,
  RuntimeEvent as RuntimeEventV12,
  RuntimeFailure as RuntimeFailureV12,
  RuntimeInitialization,
  RuntimeProvenance as RuntimeProvenanceV12,
  TerminalResult as TerminalResultV12,
  ToolEvent as ToolEventV12,
  Usage as UsageV12
} from "./generated/contracts-v1_2.js";
import type {
  AgentExecutionRequestV13,
  FileAction,
  FileContext,
  FileFormatPolicyVersion,
  JobFileManifest,
  JobFileManifestItem,
  RuntimeEvent as RuntimeEventV13,
  RuntimeFailure as RuntimeFailureV13,
  RuntimeProvenance as RuntimeProvenanceV13,
  TerminalResult as TerminalResultV13,
  TextFormatCode,
  ToolEvent as ToolEventV13,
  Usage as UsageV13
} from "./generated/contracts-v1_3.js";
import {
  assertContract as assertV1Contract,
  type ContractName as ContractNameV1
} from "./generated/validators.js";
import {
  assertContract as assertV11Contract,
  type ContractName as ContractNameV11
} from "./generated/validators-v1_1.js";
import {
  assertContract as assertV12Contract,
  type ContractName as ContractNameV12
} from "./generated/validators-v1_2.js";
import {
  assertContract as assertV13Contract,
  type ContractName as ContractNameV13
} from "./generated/validators-v1_3.js";

export const CURRENT_PROTOCOL_VERSION = "1.3" as const;
export const SUPPORTED_PROTOCOL_VERSIONS = ["1.0", "1.1", "1.2", CURRENT_PROTOCOL_VERSION] as const;
export type RuntimeProtocolVersion = (typeof SUPPORTED_PROTOCOL_VERSIONS)[number];
export type AgentExecutionRequest = AgentExecutionRequestV1 | AgentExecutionRequestV11 | AgentExecutionRequestV12 | AgentExecutionRequestV13;
export type RuntimeEvent = RuntimeEventV1 | RuntimeEventV11 | RuntimeEventV12 | RuntimeEventV13;
export type RuntimeFailure = RuntimeFailureV1 | RuntimeFailureV11 | RuntimeFailureV12 | RuntimeFailureV13;
export type RuntimeProvenance = RuntimeProvenanceV1 | RuntimeProvenanceV11 | RuntimeProvenanceV12 | RuntimeProvenanceV13;
export type TerminalResult = TerminalResultV1 | TerminalResultV11 | TerminalResultV12 | TerminalResultV13;
export type ToolEvent = ToolEventV1 | ToolEventV11 | ToolEventV12 | ToolEventV13;
export type Usage = UsageV1 | UsageV11 | UsageV12 | UsageV13;
export type { ApiRetry, ExecutionAccounting, ModelCall, RuntimeInitialization };
export type {
  FileAction,
  FileContext,
  FileFormatPolicyVersion,
  JobFileManifest,
  JobFileManifestItem,
  TextFormatCode
};

export function isRuntimeProtocolVersion(value: unknown): value is RuntimeProtocolVersion {
  return SUPPORTED_PROTOCOL_VERSIONS.some((version) => version === value);
}

export function assertRuntimeContract(
  name: ContractNameV1 | ContractNameV11 | ContractNameV12 | ContractNameV13,
  payload: unknown,
  protocolVersion: RuntimeProtocolVersion
): void {
  if (protocolVersion === "1.3") {
    assertV13Contract(name as ContractNameV13, payload);
    return;
  }
  if (protocolVersion === "1.2") {
    assertV12Contract(name as ContractNameV12, payload);
    return;
  }
  if (protocolVersion === "1.1") {
    assertV11Contract(name as ContractNameV11, payload);
    return;
  }
  assertV1Contract(name as ContractNameV1, payload);
}

export function protocolVersionOf(value: { protocol_version: RuntimeProtocolVersion }): RuntimeProtocolVersion {
  return value.protocol_version;
}
