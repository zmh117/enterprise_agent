"""保存单个不可变修订与来源关系；事务、当前指针和收录由调用用例负责。"""

from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.normalization import PreparedRecord, digest
from app.modules.knowledge.infrastructure.storage import insert, table
from app.shared.database import Database


def save_revision(
    database: Database,
    record: PreparedRecord,
    *,
    source_id: str,
    document_id: str,
    revision_id: str,
    import_run_id: str,
    revision_no: int,
) -> None:
    insert(
        database,
        "document_revision",
        {
            "id": revision_id,
            "document_id": document_id,
            "revision_no": revision_no,
            "import_run_id": import_run_id,
            **record.values,
            "content_hash": record.content_hash,
            "ingested_at": now(),
        },
    )
    for relation in record.relations:
        key = digest({"owner": record.external_id, **relation})
        target = database.execute_one(
            f"select id from {table(database, 'document')} "
            "where source_id=? and source_object_type='ones_work_item' and external_id=?",
            (source_id, relation["target_external_id"]),
        )
        insert(
            database,
            "document_relation",
            {
                "id": stable_id("relation", revision_id, key),
                "evidence_document_id": document_id,
                "evidence_revision_id": revision_id,
                "relation_key": key,
                "from_source_id": source_id,
                "from_object_type": "ones_work_item",
                "from_external_id": record.external_id,
                "from_document_id": document_id,
                "to_source_id": source_id,
                "to_object_type": "ones_work_item",
                "to_external_id": relation["target_external_id"],
                "to_document_id": target["id"] if target else None,
                "source_relation_type": relation["source_relation_type"],
                "source_direction": relation["source_direction"],
                "mapping_state": "unmapped",
                "observed_at": now(),
            },
        )
