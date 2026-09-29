入口
你本地 ADMIN_WEB_PORT=11111，打开：

http://localhost:11111（或你配置的 WEB_ALLOWED_ORIGINS）

侧栏：平台治理 → 凭据中心

怎么填
在「新建平台 Secret」：

字段 填法
凭据编码
ones-collector（必须和配置里一致）
用途
例如 ONES 知识库全量采集
Secret 明文
一整段 JSON（仅两项，不能多字段）
明文格式：

{"token":"<ONES登录Token>","user_id":"<ONES用户UUID>"}
保存后引用就是：secret://platform/ones-collector
页面之后只显示引用，不会再回显明文。
