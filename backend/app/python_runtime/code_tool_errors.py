"""Fixed source-tool refusal facts, safe for ordinary tool audit."""

MESSAGES = {
    "CODE_READ_GRANT_REQUIRED": "尚未取得源码读取授权，请先完成指定版本的检出核验",
    "CODE_CHECKOUT_IDENTITY_CHANGED": "检出目录身份异常，需要维护核验后再使用",
    "CODE_SOURCE_GRANT_DENIED": "源码读取授权无效，请检查分析状态",
    "CODE_SOURCE_GRANT_CHANGED": "源码读取授权已变化，请重新核验",
    "CODE_SOURCE_READS_CLOSED": "本次源码分析已结束，不能继续读取",
    "CODE_SOURCE_PATH_DENIED": "所选源码路径不在本次授权范围内",
    "CODE_SOURCE_GLOB_DIRECTORY_REQUIRED": "请先指定授权范围内的源码子目录",
    "CODE_SOURCE_GREP_FILENAMES_ONLY": "源码搜索只允许返回文件名，再读取文件核验",
    "CODE_SOURCE_SEARCH_INVALID": "源码搜索参数不符合受控查询要求",
    "CODE_SOURCE_READ_INVALID": "源码读取参数无效",
    "CODE_SOURCE_TOOL_DENIED": "本次任务不允许使用该源码工具",
    "CODE_SOURCE_INPUT_INVALID": "源码工具参数无效",
    "CODE_SOURCE_CALL_ID_REQUIRED": "源码工具缺少调用标识",
    "CODE_SOURCE_WRITE_DENIED": "源码目录仅允许读取",
    "CODE_SOURCE_EVIDENCE_UNVERIFIED": "源码读取结果未通过证据核验",
}


def code_tool_failure(code: str) -> dict[str, str]:
    code = code if code in MESSAGES else "CODE_SOURCE_TOOL_DENIED"
    return {"code": code, "retry_class": "NEVER", "safe_message": MESSAGES[code]}
