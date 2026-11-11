export const codeCheckoutErrors: Record<string, string> = {
  code_svn_request_failed:
    "SVN 命令执行失败，需结合执行步骤和 SVN 错误号确定原因。",
  CODE_CHECKOUT_CONNECTION_UNAVAILABLE:
    "无法确认该目录的原始 SVN 连接，请核对检出记录与连接配置。",
  CODE_REGISTRATION_CHANGED:
    "该目录的 SVN 连接不属于当前知识库，或连接信息已变更。请核对目录所属知识库和原始连接。",
  code_svn_unavailable:
    "SVN 执行未完成。旧错误记录无法区分超时与容器执行异常，请更新服务后重新发起操作获取具体原因。",
  CODE_SVN_EXECUTABLE_NOT_FOUND:
    "检出服务容器中找不到 SVN 命令，请重新构建并更新 knowledge-sync。",
  CODE_SVN_EXECUTION_DENIED:
    "检出服务容器无权运行 SVN 命令，请检查容器执行权限。",
  CODE_SVN_START_FAILED:
    "检出服务无法启动 SVN 命令，请检查容器资源和运行状态。",
  CODE_SVN_LOCAL_IO_FAILED:
    "SVN 执行期间发生本地读写错误，请检查容器挂载、磁盘和权限。",
  CODE_SVN_INFO_TIMEOUT: "SVN 仓库或工作副本信息检查超时。",
  CODE_SVN_LIST_TIMEOUT:
    "SVN 文件清单读取超时，请缩小选择范围或检查仓库响应速度。",
  CODE_SVN_PROPGET_TIMEOUT: "SVN 外部引用检查超时，请检查仓库规模与响应速度。",
  CODE_SVN_CHECKOUT_TIMEOUT: "SVN 工作副本创建超时，请检查网络和目标磁盘性能。",
  CODE_SVN_UPDATE_TIMEOUT:
    "SVN 文件下载或版本更新超时，请缩小选择范围，检查网络和目标磁盘性能。",
  CODE_SVN_STATUS_TIMEOUT: "SVN 工作副本状态核验超时，请检查目标磁盘性能。",
  CODE_SVN_LOG_TIMEOUT: "SVN 提交记录查询超时，请缩小查询范围。",
  CODE_SVN_DIFF_TIMEOUT: "SVN 差异查询超时，请缩小查询范围。",
  CODE_SVN_BLAME_TIMEOUT: "SVN 行历史查询超时，请缩小查询范围。",
  CODE_SVN_CAT_TIMEOUT: "SVN 文件内容读取超时，请检查仓库响应速度。",
  code_svn_response_too_large:
    "SVN 返回的数据超过单次处理上限，请将仓库地址缩小到需要的子目录后重试。",
  code_source_inventory_limit: "目录条目超过处理上限，请缩小检出范围。",
  code_checkout_directory_limit: "当前目录下的文件夹过多，请缩小仓库地址范围。",
  CODE_HISTORY_RESPONSE_TOO_LARGE: "当前目录预览过大，请缩小仓库地址范围。",
  CODE_RESULT_BUFFER_FULL: "目录浏览服务繁忙，请稍后重试。",
  CODE_RESULT_EXPIRED: "目录预览已过期，请重试加载。",
  CODE_BROWSE_DIRECTORY_REQUIRED: "该路径不是可浏览的目录，请重新浏览仓库。",
  CODE_CHECKOUT_BROWSE_REQUIRED: "浏览身份已失效，请重新浏览仓库。",
  CODE_CONFIGURATION_CHANGED: "知识库配置已变化，请重新浏览仓库。",
  CODE_SVN_AUTH_FAILED: "SVN 用户名或密码不正确，请更新连接后重试。",
  CODE_SVN_ACCESS_DENIED: "SVN 账号没有访问所选仓库或路径的权限。",
  CODE_SVN_CERTIFICATE_INVALID:
    "SVN 证书校验失败，请部署人员配置受信任的证书。",
  CODE_SVN_CONNECTION_FAILED: "无法连接 SVN，请检查地址和容器网络。",
  CODE_SVN_WC_CLEANUP_REQUIRED:
    "SVN 工作副本上一次操作尚未完成，请确认原进程已停止后进行维护核验。系统不会自动清理或续拉。",
  CODE_SVN_WC_LOCKED:
    "SVN 工作副本被锁定，请核对是否仍有操作运行或存在中断遗留锁。",
  CODE_SVN_WC_DB_FAILED:
    "SVN 工作副本元数据数据库异常，请结合 SVN 原始错误号检查磁盘、挂载和工作副本状态。",
  CODE_SVN_CREDENTIAL_UNAVAILABLE: "SVN 凭据缺失或已停用，请重新配置连接。",
  CODE_CHECKOUT_IDENTITY_CHANGED: "检出目录身份异常，需要维护核验后再使用。",
  CODE_CHECKOUT_PERMISSION_DENIED:
    "检出目录权限不足，请检查执行器与 Runtime 的共享读取权限。",
  code_checkout_destination_exists:
    "目标目录已存在，请填写新的子目录名。已有内容未覆盖。",
  code_checkout_create_failed:
    "无法创建检出目录，请检查挂载目录权限、可用空间和磁盘状态。",
  code_checkout_publish_failed:
    "检出目录发布失败。旧版服务在 Windows 共享盘上可能不支持目录改名，请更新 knowledge-sync 后重新检出。",
  code_checkout_atomic_publish_unavailable:
    "旧版服务缺少目录发布所需的文件系统能力，请更新 knowledge-sync 后重新检出。",
  code_checkout_externals_unsupported:
    "仓库含有 SVN 外部引用，本次未检出。请由部署人员确认外部依赖范围。",
  code_checkout_interrupted: "后台执行已中断，请重新发起任务。",
  code_checkout_access_denied: "执行时管理员权限已失效。",
  code_checkout_registration_changed: "仓库登记已变更，请重新浏览目录。",
}
