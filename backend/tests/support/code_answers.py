"""Synthetic code knowledge setup; no source credentials, network or model calls."""

import json
from pathlib import Path
from datetime import timedelta

from app.modules.agent.infrastructure.runtime_pool_store import (
    RuntimePoolStore,
    database_now,
    timestamp,
)
from app.modules.agent.infrastructure.runtime_protocol import canonical_request_digest
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.knowledge.domain.code_answers import CodeAnalysisContext
from app.modules.knowledge.domain.code_configuration import CODE_CHUNK_PROFILE
from app.modules.knowledge.infrastructure.embedding_profile import profile
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_analysis_store import CodeAnalysisStore
from app.modules.knowledge.infrastructure.storage import insert

CODE_INDEX_ID = "10000000-0000-4000-8000-000000000001"


def code_configuration(runtime, tmp_path):
    store = CodeAnalysisStore(runtime.database, authorize=lambda context: None)
    source = store.register_repository(
        "00000000-0000-0000-0000-000000000001", "trunk", "https://svn.invalid/repository"
    )
    root = tmp_path / "root"
    root.mkdir()
    (root / "mes").mkdir()
    checkout = store.register_checkout(
        source_id=source,
        root_key="code-svn-checkout",
        root=root,
        relative_dir="mes",
        selected_paths=[""],
    )
    stamp = now()
    insert(
        runtime.database,
        "knowledge_base",
        dict(
            id="code-kb",
            code="code-kb",
            display_name="Code",
            description="",
            state="storage_only",
            kind="code",
            created_at=stamp,
        ),
    )
    insert(
        runtime.database,
        "retrieval_resource",
        dict(
            id="code-resource",
            knowledge_base_id="code-kb",
            code="code-resource",
            name="Code",
            created_by="user_local_admin",
            created_at=stamp,
            updated_at=stamp,
        ),
    )
    insert(
        runtime.database,
        "vector_index",
        dict(
            id=CODE_INDEX_ID,
            code="code-index",
            knowledge_base_id="code-kb",
            profile=profile(),
            profile_hash=digest(profile()),
            chunk_profile_hash=CODE_CHUNK_PROFILE.fingerprint,
            corpus_hash="0" * 64,
            collection_name="code-fixture",
            expected_document_count=0,
            expected_chunk_count=0,
            state="READY",
            source_id=source,
            incremental=1,
            created_at=stamp,
            updated_at=stamp,
        ),
    )
    insert(
        runtime.database,
        "retrieval_revision",
        dict(
            id="code-config",
            resource_id="code-resource",
            revision=1,
            profile_hash="0" * 64,
            corpus_hash="0" * 64,
            config_hash="0" * 64,
            created_by="user_local_admin",
            created_at=stamp,
            configuration_version=5,
            index_id=CODE_INDEX_ID,
        ),
    )
    insert(
        runtime.database,
        "code_resource_config",
        dict(
            revision_id="code-config",
            source_id=source,
            checkout_id=checkout["id"],
            svn_access_ref="synthetic",
            allowed_paths_json=[""],
        ),
    )
    runtime.database.execute(
        f"UPDATE {store.t('retrieval_resource')} SET published_revision_id=? WHERE id=?",
        ("code-config", "code-resource"),
    )
    runtime.database.execute(
        f"UPDATE {store.t('code_checkout')} SET state='ready',verified_revision=100,verified_at=? WHERE id=?",
        (stamp, checkout["id"]),
    )
    return store, source, checkout, root


def analysis_context(runtime, source, checkout, *, key="one", revision=100):
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="code-" + key,
            requester_id="user_local_admin",
            user_message="Synthetic code question r100",
            source_channel="debug_api",
        )
    )
    request = json.loads(
        Path("contracts/agent-runtime/v1.5/golden/execution-request.json").read_text()
    )
    request.update(
        job_id=job.id,
        invocation_id=job.id + ".attempt-0",
        app_user_id="user_local_admin",
        mcp_servers=[],
    )
    request["request_digest"] = canonical_request_digest(request)
    pool = RuntimePoolStore(runtime.database)
    pool.prepare(
        request,
        attempt=0,
        admission_deadline_at=timestamp(database_now(runtime.database) + timedelta(seconds=3600)),
    )
    assert pool.admit(request["invocation_id"], request["request_digest"], "node-a", "owner-" + key)
    invocation = pool.require(request["invocation_id"], request["request_digest"])
    runtime.database.execute("UPDATE agent_job SET status='RUNNING' WHERE id=?", (job.id,))
    return CodeAnalysisContext(
        job.id,
        request["invocation_id"],
        "owner-" + key,
        "user_local_admin",
        "code-kb",
        "code-config",
        source,
        checkout["id"],
        revision,
        "search-" + key,
        digest("Synthetic code question"),
        "b" * 64,
        invocation["execution_deadline_at"],
    )


def confirm(store, context, analysis):
    operation = store.db.execute_one(
        f"SELECT id FROM {store.t('code_svn_operation')} WHERE analysis_id=?", (analysis["id"],)
    )
    stamp = timestamp(database_now(store.db))
    store.db.execute(
        f"UPDATE {store.t('code_svn_operation')} SET state='running',owner_instance_id='svn-worker',claim_version=1,lease_until=?,started_at=? WHERE id=?",
        (timestamp(database_now(store.db) + timedelta(seconds=30)), stamp, operation["id"]),
    )
    return store.confirm_reading(context, operation["id"], owner="svn-worker", claim=1)
