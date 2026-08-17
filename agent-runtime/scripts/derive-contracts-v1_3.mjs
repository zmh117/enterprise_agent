import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const runtimeRoot = resolve(scriptDir, "..");
const sourceRoot = resolve(runtimeRoot, "contracts/v1.2");
const targetRoot = resolve(runtimeRoot, "contracts/v1.3");
const checkOnly = process.argv.includes("--check");

function upgrade(value) {
  if (typeof value === "string") {
    return value.replaceAll("V12", "V13").replaceAll("v1.2", "v1.3").replaceAll("1.2", "1.3");
  }
  if (Array.isArray(value)) return value.map(upgrade);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, child]) => [upgrade(key), upgrade(child)]));
  }
  return value;
}

function canonicalValue(value) {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, canonicalValue(child)])
    );
  }
  return value;
}

function requestDigest(value) {
  const digestInput = { ...value };
  delete digestInput.request_digest;
  return createHash("sha256")
    .update(JSON.stringify(canonicalValue(digestInput)), "utf8")
    .digest("hex");
}

const sourceSchema = JSON.parse(await readFile(resolve(sourceRoot, "protocol.schema.json"), "utf8"));
const schema = upgrade(sourceSchema);
schema.title = "Enterprise Agent Runtime Protocol V1.3";
schema.$defs.FileFormatPolicyVersion = { const: "text-v2" };
schema.$defs.TextFormatCode = { enum: ["TXT", "LOG", "MARKDOWN"] };
schema.$defs.FileAction = {
  enum: ["READ_METADATA", "MATERIALIZE", "EDIT", "COMMIT", "RETAIN", "DELIVER"]
};
schema.$defs.JobFileManifestItem = {
  type: "object",
  additionalProperties: false,
  required: [
    "file_id", "version_id", "display_name", "format_code", "source_kind",
    "allowed_actions", "auto_materialize", "conflict_candidate",
    "source_received_at", "version_created_at"
  ],
  properties: {
    file_id: { $ref: "#/$defs/Identifier" },
    version_id: { $ref: "#/$defs/Identifier" },
    display_name: {
      type: "string",
      minLength: 1,
      maxLength: 255,
      pattern: "^[^/\\\\\\u0000]+\\.(?:txt|log|md)$"
    },
    format_code: { $ref: "#/$defs/TextFormatCode" },
    source_kind: {
      enum: ["CURRENT_MESSAGE", "EXPLICIT_REFERENCE", "WORKSPACE", "CONFLICT"]
    },
    allowed_actions: {
      type: "array",
      maxItems: 6,
      uniqueItems: true,
      items: { $ref: "#/$defs/FileAction" }
    },
    auto_materialize: { type: "boolean" },
    conflict_candidate: { type: "boolean" },
    source_received_at: { type: ["string", "null"], maxLength: 64 },
    version_created_at: { type: "string", minLength: 1, maxLength: 64 }
  }
};
schema.$defs.JobFileManifest = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema_version", "file_format_policy_version", "manifest_hash", "observed_at", "items"
  ],
  properties: {
    schema_version: { const: 3 },
    file_format_policy_version: { $ref: "#/$defs/FileFormatPolicyVersion" },
    manifest_hash: { $ref: "#/$defs/Sha256Digest" },
    observed_at: { type: "string", minLength: 1, maxLength: 64 },
    items: {
      type: "array",
      maxItems: 40,
      items: { $ref: "#/$defs/JobFileManifestItem" }
    }
  }
};
schema.$defs.FileContext = {
  type: "object",
  additionalProperties: false,
  required: ["file_format_policy_version", "file_manifest"],
  properties: {
    file_format_policy_version: { $ref: "#/$defs/FileFormatPolicyVersion" },
    file_manifest: {
      oneOf: [{ $ref: "#/$defs/JobFileManifest" }, { type: "null" }]
    }
  }
};
const execution = schema.$defs.AgentExecutionRequestV13;
execution.required.push("file_context");
execution.properties.file_context = { $ref: "#/$defs/FileContext" };

const outputs = new Map();
outputs.set("protocol.schema.json", `${JSON.stringify(schema, null, 2)}\n`);
for (const name of ["errors.json", "limits.json"]) {
  const value = upgrade(JSON.parse(await readFile(resolve(sourceRoot, name), "utf8")));
  outputs.set(name, `${JSON.stringify(value, null, 2)}\n`);
}
for (const name of await readdir(resolve(sourceRoot, "golden"))) {
  if (!name.endsWith(".json")) continue;
  const value = upgrade(
    JSON.parse(await readFile(resolve(sourceRoot, "golden", name), "utf8"))
  );
  if (name === "execution-request.json") {
    value.file_context = {
      file_format_policy_version: "text-v2",
      file_manifest: null
    };
    value.request_digest = requestDigest(value);
  }
  outputs.set(`golden/${name}`, `${JSON.stringify(value, null, 2)}\n`);
}

let changed = false;
for (const [name, content] of outputs) {
  const path = resolve(targetRoot, name);
  let current = "";
  try {
    current = await readFile(path, "utf8");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  if (current === content) continue;
  changed = true;
  if (!checkOnly) {
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, content, "utf8");
  }
}
if (checkOnly && changed) throw new Error("derived runtime v1.3 contracts are out of date");
