from app.shared.exceptions import NonRetryableExecutionError


def require_not_archived(status: object) -> None:
    if status == "archived":
        raise NonRetryableExecutionError(
            "Archived record is read-only",
            safe_message="已归档记录只读",
            error_code="record_archived",
        )


def require_archive_eligible(
    status: object,
    *,
    published: bool = True,
    protected: bool = False,
    in_use: bool = False,
) -> None:
    require_not_archived(status)
    if protected:
        message = "系统内置记录不能归档"
    elif in_use:
        message = "记录仍被活动配置引用，请先解除引用"
    elif published and status != "disabled":
        message = "请先停用已启用的记录再归档"
    else:
        return
    raise NonRetryableExecutionError(
        "Record cannot be archived", safe_message=message, error_code="archive_blocked"
    )
