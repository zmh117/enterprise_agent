"""Fixed source-tool refusal facts, safe for ordinary tool audit."""

MESSAGES = {
    "CODE_READ_GRANT_REQUIRED": "尚未取得源码读取授权，请先完成指定版本的检出核验",
    "CODE_CHECKOUT_IDENTITY_CHANGED": "检出目录身份异常，需要维护核验后再使用",
    "CODE_CHECKOUT_SOURCE_MISMATCH": "源码版本或路径类型不匹配；Read 指定文件，Glob 指定目录，Grep 支持授权目录或文件",
    "CODE_CHECKOUT_DIRTY": "源码路径未受 SVN 管理、已删除或内容有本地改动，请核验检出目录",
    "CODE_CHECKOUT_PERMISSION_DENIED": "Runtime 无权读取检出目录，请管理员检查目录权限",
    "CODE_CHECKOUT_METADATA_INVALID": "SVN 工作副本元数据无效，请管理员核验检出目录",
    "CODE_CHECKOUT_FORMAT_UNSUPPORTED": "SVN 工作副本格式不受支持，请管理员核验检出目录",
    "CODE_CHECKOUT_CHANGED": "分析期间工作副本或文件内容发生变化，请重新核验指定版本",
    "CODE_CHECKOUT_PRISTINE_CHANGED": "SVN 原始文件校验失败，请管理员核验检出目录",
    "CODE_PATH_INVALID": "源码路径必须为仓库内的有效相对路径，不能包含上级目录或 .svn",
    "CODE_SOURCE_GRANT_DENIED": "源码读取授权无效，请检查分析状态",
    "CODE_SOURCE_GRANT_CHANGED": "源码读取授权已变化，请重新核验",
    "CODE_SOURCE_READS_CLOSED": "本次源码分析已结束，不能继续读取",
    "CODE_SOURCE_PATH_DENIED": "所选源码路径不在本次授权范围内",
    "CODE_SOURCE_GLOB_DIRECTORY_REQUIRED": "Glob 请指定授权的源码子目录，或以明确的顶层目录名开头的 pattern；不能直接遍历源码根目录",
    "CODE_SOURCE_SEARCH_INVALID": "Grep 支持 path、pattern、glob、output_mode(content/files_with_matches)、-i、-n、-A/-B/-C(0–5)、head_limit(1–200)；glob 使用 *、**、?、[]，不支持花括号；请缩小授权路径或文件模式",
    "CODE_SOURCE_READ_INVALID": "Read 仅接受 file_path、offset、limit；请指定单个源码文件",
    "CODE_SOURCE_READ_LIMIT": "Read 的 offset 须为正整数，limit 为 1–400；读取范围不能为空且内容不能超过 64 KiB，请缩小有效行范围",
    "CODE_SOURCE_SENSITIVE": "源码文件包含受限文件名或敏感内容，不能读取或搜索",
    "CODE_SOURCE_KEYWORDS_UNSUPPORTED": "源码文件使用了尚不支持核验的 SVN 关键字展开，不能作为证据读取",
    "CODE_SOURCE_SEARCH_OUTPUT_UNSUPPORTED": "搜索结果格式无法核验，请检查 Runtime 与 SDK 的兼容性",
    "CODE_SOURCE_SEARCH_LIMIT": "搜索超出限制：Grep 最多 64 个候选文件、32 MiB，目录枚举最多 10000 项；Glob 最多返回 100 项。请缩小目录或 glob",
    "CODE_SOURCE_SEARCH_UNAVAILABLE": "本次源码搜索工作区不可用",
    "code_notes_path_denied": "代码分析笔记只能用 Write 保存到当前 Job 的 work/notes/ 下 .md 或 .txt 文件",
    "sandbox_file_limit_exceeded": "临时文件超过单文件上限，请缩小搜索范围或笔记内容",
    "sandbox_file_count_exceeded": "当前 Job 临时文件数已达上限，请缩小搜索范围",
    "sandbox_capacity_exceeded": "当前 Job 临时工作区容量不足，请缩小搜索范围",
    "CODE_SOURCE_READ_OUTPUT_UNSUPPORTED": "Read 返回内容格式无法核验，不能作为源码证据",
    "CODE_SOURCE_TOOL_DENIED": "本次任务不允许使用该源码工具",
    "CODE_SOURCE_INPUT_INVALID": "源码工具参数无效",
    "CODE_SOURCE_CALL_ID_REQUIRED": "源码工具缺少调用标识",
    "CODE_SOURCE_WRITE_DENIED": "源码目录仅允许读取",
    "CODE_SOURCE_EVIDENCE_UNVERIFIED": "源码读取结果未通过证据核验",
}


def code_tool_failure(code: str) -> dict[str, str]:
    code = code if code in MESSAGES else "CODE_SOURCE_TOOL_DENIED"
    return {"code": code, "retry_class": "NEVER", "safe_message": MESSAGES[code]}
