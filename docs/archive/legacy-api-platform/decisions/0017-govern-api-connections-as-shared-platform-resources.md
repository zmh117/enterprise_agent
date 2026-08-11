# API Connection 作为共享平台资源独立治理

Base URL、允许主机、Authentication Profile、TLS、超时和响应限制属于平台级 API Connection。多个 API Capability 可以复用同一已发布 Connection Revision，Capability 页面不得内联修改地址、认证 Header 或 Secret。Connection 新版本不会自动改变既有 Capability Release 或 Application Publication；依赖方必须重新验证并显式发布升级。第一版按 ADR-0032 只治理一个逻辑 ONES 实例，其他 Provider 仍可拥有各自 Connection。
