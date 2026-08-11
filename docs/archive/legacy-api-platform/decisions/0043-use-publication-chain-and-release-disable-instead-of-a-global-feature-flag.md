# 使用发布链和 Release 禁用，不新增全局功能开关

第一版不新增受治理 API Capability 的全局 Feature Flag，也不新增功能开关管理页面。新能力只有依次完成 API Connection、Capability Release、Agent Publication 和 Application Publication 的显式配置发布后，才会进入钉钉运行时；任一环节未完成均不会改变现有内部只读 Tool。紧急回退通过具体 Capability Release 的 `DISABLED` 状态使新调用失败关闭，不删除发布历史、用户绑定或加密凭据。全局开关会与发布运维状态形成第二套真相来源，因此不采用。
