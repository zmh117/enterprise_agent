import assert from "node:assert/strict";
import { createCipheriv, createHash, createHmac } from "node:crypto";
import { test } from "node:test";

import type { DraftModelProbeRequest } from "../src/generated/contracts.js";
import {
  ModelProbeEnvelopeDecryptor,
  ModelProbeEnvelopeError
} from "../src/model-probe-envelope.js";

const now = 2_000_000_000;
const masterKey = Buffer.from(Array.from({ length: 32 }, (_value, index) => index));
const material = `EA_MASTER_KEY_V1:${masterKey.toString("base64url")}`;

function request(): DraftModelProbeRequest {
  const config = {
    schema_version: 1,
    protocol: "anthropic_compatible",
    base_url: "https://api.deepseek.com/anthropic",
    model: "deepseek-chat",
    default_opus_model: "deepseek-chat",
    default_sonnet_model: "deepseek-chat",
    default_haiku_model: "deepseek-chat",
    subagent_model: "deepseek-chat",
    effort_level: "max"
  };
  const configHash = createHash("sha256")
    .update(JSON.stringify(Object.fromEntries(Object.entries(config).sort())), "utf8")
    .digest("hex");
  const probeId = "probe-draft-envelope-test";
  const expiresAt = now + 30;
  const nonce = Buffer.from("000102030405060708090a0b", "hex");
  const key = createHmac("sha256", masterKey)
    .update("enterprise-agent:model-probe-envelope:v1", "utf8")
    .digest();
  const cipher = createCipheriv("aes-256-gcm", key, nonce);
  cipher.setAAD(
    Buffer.from(
      `model-probe-envelope|v1|${probeId}|typescript-v1|${configHash}|${expiresAt}`,
      "utf8"
    )
  );
  const plaintext = Buffer.from(
    JSON.stringify({ api_key: "fixture-draft-key", config, schema_version: 1 }),
    "utf8"
  );
  const encrypted = Buffer.concat([cipher.update(plaintext), cipher.final(), cipher.getAuthTag()]);
  plaintext.fill(0);
  key.fill(0);
  return {
    protocol_version: "1.0",
    runtime_kind: "typescript-v1",
    probe_id: probeId,
    config_hash: configHash,
    credential_envelope: {
      algorithm: "AES-256-GCM-DERIVED-PROBE-V1",
      nonce: nonce.toString("base64url"),
      ciphertext: encrypted.toString("base64url"),
      expires_at: expiresAt
    },
    timeout_seconds: 15
  };
}

test("draft probe envelope decrypts once and rejects replay", () => {
  const decryptor = ModelProbeEnvelopeDecryptor.fromMaterial(material, () => now);
  const payload = request();

  const decrypted = decryptor.decrypt(payload);

  assert.equal(decrypted.config.model, "deepseek-chat");
  assert.equal(decrypted.apiKey, "fixture-draft-key");
  assert.throws(() => decryptor.decrypt(payload), ModelProbeEnvelopeError);
  assert.equal(JSON.stringify(payload).includes("fixture-draft-key"), false);
});

test("draft probe envelope binds ciphertext to the Runtime request", () => {
  const decryptor = ModelProbeEnvelopeDecryptor.fromMaterial(material, () => now);
  const payload = request();
  const tampered = { ...payload, config_hash: "f".repeat(64) };

  assert.throws(() => decryptor.decrypt(tampered), ModelProbeEnvelopeError);
});
