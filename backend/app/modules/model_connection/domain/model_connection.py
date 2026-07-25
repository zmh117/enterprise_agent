from __future__ import annotations

from dataclasses import dataclass


ANTHROPIC_COMPATIBLE_PROTOCOL = "anthropic_compatible"
DEFAULT_MODEL_CONNECTION_CODE = "default-deepseek-anthropic"


@dataclass(frozen=True)
class ModelConnectionConfig:
    protocol: str
    base_url: str
    model: str
    default_opus_model: str
    default_sonnet_model: str
    default_haiku_model: str
    subagent_model: str
    effort_level: str
    schema_version: int = 1

    def as_dict(self) -> dict[str, str | int]:
        return {
            "schema_version": self.schema_version,
            "protocol": self.protocol,
            "base_url": self.base_url,
            "model": self.model,
            "default_opus_model": self.default_opus_model,
            "default_sonnet_model": self.default_sonnet_model,
            "default_haiku_model": self.default_haiku_model,
            "subagent_model": self.subagent_model,
            "effort_level": self.effort_level,
        }


@dataclass(frozen=True)
class ModelRuntimeBinding:
    protocol: str
    base_url: str
    model: str
    default_opus_model: str
    default_sonnet_model: str
    default_haiku_model: str
    subagent_model: str
    effort_level: str
    connection_id: str = ""
    connection_code: str = ""
    connection_revision_id: str = ""
    connection_revision: int = 0
    config_hash: str = ""
    secret_ref: str = ""
    legacy: bool = False

    def public_provenance(self) -> dict[str, object]:
        return {
            "protocol": self.protocol,
            "provider_host": self.provider_host,
            "model": self.model,
            "default_opus_model": self.default_opus_model,
            "default_sonnet_model": self.default_sonnet_model,
            "default_haiku_model": self.default_haiku_model,
            "subagent_model": self.subagent_model,
            "effort_level": self.effort_level,
            "connection_id": self.connection_id,
            "connection_code": self.connection_code,
            "connection_revision_id": self.connection_revision_id,
            "connection_revision": self.connection_revision,
            "config_hash": self.config_hash,
            "legacy": self.legacy,
        }

    @property
    def provider_host(self) -> str:
        from urllib.parse import urlsplit

        try:
            return (urlsplit(self.base_url).hostname or "default").lower()
        except ValueError:
            return "invalid"
