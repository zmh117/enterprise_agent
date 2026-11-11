export const codeCheckoutErrors: Record<string, string> = {
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
  CODE_SVN_CREDENTIAL_UNAVAILABLE: "SVN 凭据缺失或已停用，请重新配置连接。",
  CODE_CHECKOUT_IDENTITY_CHANGED: "检出目录身份异常，需要维护核验后再使用。",
  CODE_CHECKOUT_PERMISSION_DENIED:
    "检出目录权限不足，请检查执行器与 Runtime 的共享读取权限。",
  code_checkout_destination_exists:
    "目标目录已存在，请填写新的子目录名。已有内容未覆盖。",
  code_checkout_externals_unsupported:
    "仓库含有 SVN 外部引用，本次未检出。请由部署人员确认外部依赖范围。",
  code_checkout_interrupted: "后台执行已中断，请重新发起任务。",
  code_checkout_access_denied: "执行时管理员权限已失效。",
  code_checkout_registration_changed: "仓库登记已变更，请重新浏览目录。",
}
