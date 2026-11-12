from dataclasses import dataclass
import re
from typing import Any
from app.shared.exceptions import NonRetryableExecutionError
from app.modules.knowledge.domain.code_operation_errors import CODE_OPERATION_MESSAGES


# These resources cannot enter a current catalog or a new source capability.
# Authentication, storage failures and unknown errors must still propagate.
UNAVAILABLE_RESOURCE_CODES = frozenset(
    {
        "knowledge_resource_unavailable",
        "knowledge_source_unavailable",
        "knowledge_source_changed",
        "knowledge_index_unavailable",
    }
)


class KnowledgeGovernanceError(NonRetryableExecutionError):
    def __init__(self, code: str) -> None:
        super().__init__(
            code,
            error_code=code,
            safe_message={
                **CODE_OPERATION_MESSAGES,
                "knowledge_ops_input_invalid": "运维参数无效，请检查操作类型、计划及日期",
                "knowledge_ops_not_found": "运维任务不存在，请刷新任务记录",
                "knowledge_ops_busy": "已有构建或启停任务，请等待其完成",
                "knowledge_ops_queue_full": "运维任务队列已满，请等待现有任务完成",
                "knowledge_ops_idempotency_conflict": "该请求标识已用于不同操作，请重新发起",
                "knowledge_ops_retry_required": "当前计划有未完成的失败任务，请在任务记录中重试",
                "knowledge_ops_state_conflict": "任务状态已变化，请刷新后重试",
                "knowledge_ops_build_required": "请先成功构建知识库镜像",
                "knowledge_ops_mount_invalid": "知识运维执行器路径映射无效，请运行部署兼容预检并重建执行器",
                "knowledge_sync_configuration_changed": "采集配置已变化，请刷新计划；旧任务不能跨配置续跑",
                "knowledge_collection_scope_changed": "已有采集记录的来源范围不能修改，请创建新的采集计划",
                "knowledge_collection_disabled": "请先启用采集计划，再执行同步或补采",
                "knowledge_collection_backfill_requires_baseline": "首次全量采集完成后才能执行指定日期补采",
                "knowledge_collection_range_invalid": "补采日期必须在首次采集起始日与今天之间，且起始日期不能晚于结束日期",
                "knowledge_sync_content_location_mismatch": "该资源使用外部内容库，当前受管采集只写平台内容库",
                "knowledge_input_invalid": "知识资源参数无效",
                "knowledge_resource_config_unsupported": "知识资源配置版本不受支持，请检查发布兼容接续",
                "knowledge_resource_maintenance_scope_changed": "受影响知识资源与维护清单不一致，请重新核对；未变更任何发布",
                "knowledge_storage_config_invalid": "知识存储连接配置无效，请选择凭据中心引用，不要填写密码或 DSN",
                "knowledge_storage_unavailable": "知识内容存储不可用，请检查连接、内容表结构和读取权限",
                "knowledge_storage_readonly_unavailable": "知识内容连接未启用只读事务，请检查数据库连接设置；无需更换管理员账号",
                "knowledge_storage_credentials_unavailable": "知识连接凭据缺失、已停用或不可用，请检查凭据中心",
                "knowledge_revision_conflict": "知识配置已变化，请刷新后重试",
                "knowledge_source_unavailable": "知识库本地数据来源或文档身份不完整，请检查导入数据",
                "knowledge_source_changed": "知识库数据或工作项归属已变化，请检查数据并重新保存、验证和发布",
                "knowledge_verifier_unavailable": "受信 ONES 来源核验服务尚未配置",
                "knowledge_verification_failed": "知识资源连接验证失败，请检查 PostgreSQL、索引配置及 Embedding/Qdrant 服务",
                "knowledge_verification_timeout": "知识资源连接检查超时（最多 30 秒），请检查数据库与服务连接后重试",
                "knowledge_verification_busy": "知识来源核验繁忙，请稍后重试",
                "knowledge_verification_job_invalid": "请使用本人正在运行且已获 ONES 详情权限的业务应用任务进行核验",
                "knowledge_resource_unavailable": "知识检索资源未发布或已停用",
                "knowledge_resource_code_unavailable": "当前任务没有可用的该编码知识库，请核对资源编码及应用、角色授权",
                "knowledge_resource_conflict": "该知识库已有启用的检索资源或资源编码重复",
                "knowledge_resource_changed": "知识检索资源已变化，请重新查询",
                "knowledge_index_unavailable": "知识索引尚未就绪或与当前配置不匹配",
                "knowledge_job_denied": "当前任务没有有效的业务应用知识库权限",
                "knowledge_principal_refresh_failed": "知识检索身份续期失败，请重新发起查询",
                "knowledge_authorization_changed": "知识库授权已变化，请重新查询",
                "knowledge_readability_busy": "知识可读性检查繁忙，请稍后重试",
                "knowledge_readability_timeout": "知识可读性检查超时，请重试",
                "knowledge_readability_failed": "知识可读性检查未完成，请检查权限与服务状态",
                "knowledge_candidate_invalid": "知识候选已失效，请重新检索",
                "knowledge_source_identity_invalid": "请核验本人 ONES 身份及默认 Team",
                "knowledge_cursor_invalid": "知识库分页游标无效或已过期，请从第一页重新查询",
                "knowledge_cursor_stale": "知识库授权或资源已变化，请从第一页重新查询",
                "knowledge_search_budget_exhausted": "知识检索或当前任务预算已耗尽，请重试",
                "knowledge_search_dependency_failed": "知识检索依赖服务异常，请稍后重试",
                "knowledge_embedding_busy": "知识检索向量化服务繁忙，请稍后重试；不是内容数据库故障",
                "knowledge_embedding_read_timeout": "知识检索向量化服务超时，请检查模型服务负载后重试",
                "knowledge_embedding_unavailable": "知识检索向量化服务不可用或模型配置不匹配，请检查 Embedding 服务",
                "knowledge_search_busy": "知识检索繁忙，请稍后重试",
                "knowledge_rerank_busy": "知识重排服务繁忙，请稍后重试；不代表没有相关记录",
                "knowledge_rerank_unavailable": "知识重排服务不可用或模型配置不匹配，请检查重排服务",
                "knowledge_rerank_read_timeout": "知识重排超时，请检查模型负载或任务剩余预算",
                "knowledge_rerank_input_limit": "查询超出重排模型的输入预算，请保留关键症状后缩短查询",
            }.get(code, "知识资源操作失败"),
        )


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def checked_identifier(value: Any) -> str:
    # ONES UUID 是其原生短标识，不能强制转换为 RFC UUID，也不能接受显示名称/URL。
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is None
    ):
        raise KnowledgeGovernanceError("knowledge_input_invalid")
    return value


def checked_hash(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise KnowledgeGovernanceError("knowledge_input_invalid")
    return value


def checked_revision(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise KnowledgeGovernanceError("knowledge_input_invalid")
    return value


@dataclass(frozen=True, repr=False)
class SourceItem:
    document_id: str
    revision_id: str
    task_id: str
    project_id: str
    content_hash: str
