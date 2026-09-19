from app.modules.identity.application.principal_jwt import PrincipalTokenError
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.shared.exceptions import AppError, NonRetryableExecutionError


def failure(code: str) -> AppError:
    return NonRetryableExecutionError(
        code,
        error_code=code,
        safe_message={
            "knowledge_mcp_authentication_failed": "知识服务身份凭证无效",
            "knowledge_mcp_context_invalid": "知识服务执行上下文不匹配",
            "knowledge_mcp_input_invalid": "知识服务请求格式无效",
            "knowledge_mcp_result_invalid": "知识服务返回结果无效",
            "knowledge_mcp_unavailable": "知识服务暂时不可用，请稍后重试",
            "knowledge_mcp_cancelled": "知识服务调用已取消",
            "knowledge_mcp_busy": "知识服务繁忙，请稍后重试",
            "knowledge_mcp_tool_not_found": "当前知识工具未注册",
        }.get(code, "知识服务请求被拒绝"),
    )


def safe_failure(exc: Exception) -> AppError:
    # 不回显 SDK、数据库、Provider 异常或参数校验 detail。
    if isinstance(exc, PrincipalTokenError):
        return failure("knowledge_mcp_authentication_failed")
    if isinstance(exc, KnowledgeGovernanceError):
        return KnowledgeGovernanceError(exc.error_code)
    if isinstance(exc, AppError) and exc.error_code in {
        "knowledge_mcp_authentication_failed",
        "knowledge_mcp_context_invalid",
        "knowledge_mcp_input_invalid",
        "knowledge_mcp_result_invalid",
        "knowledge_mcp_tool_not_found",
        "knowledge_mcp_cancelled",
        "knowledge_mcp_busy",
    }:
        return failure(exc.error_code)
    return failure("knowledge_mcp_unavailable")
