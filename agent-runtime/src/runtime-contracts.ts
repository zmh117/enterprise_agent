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

export type RuntimeProtocolVersion = "1.0" | "1.1" | "1.2";
export type AgentExecutionRequest = AgentExecutionRequestV1 | AgentExecutionRequestV11 | AgentExecutionRequestV12;
export type RuntimeEvent = RuntimeEventV1 | RuntimeEventV11 | RuntimeEventV12;
export type RuntimeFailure = RuntimeFailureV1 | RuntimeFailureV11 | RuntimeFailureV12;
export type RuntimeProvenance = RuntimeProvenanceV1 | RuntimeProvenanceV11 | RuntimeProvenanceV12;
export type TerminalResult = TerminalResultV1 | TerminalResultV11 | TerminalResultV12;
export type ToolEvent = ToolEventV1 | ToolEventV11 | ToolEventV12;
export type Usage = UsageV1 | UsageV11 | UsageV12;
export type { ApiRetry, ExecutionAccounting, ModelCall, RuntimeInitialization };

export function assertRuntimeContract(
  name: ContractNameV1 | ContractNameV11 | ContractNameV12,
  payload: unknown,
  protocolVersion: RuntimeProtocolVersion
): void {
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
