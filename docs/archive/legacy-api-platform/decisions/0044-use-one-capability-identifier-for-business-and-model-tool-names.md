# 业务标识与模型 Tool 名统一使用 cap__ 命名空间

受治理 API Capability 不再维护点号业务 Code 与转换后的模型 Tool 名两套标识，而统一使用一个 Capability Identifier，例如 `cap__ones__work_item__search`。`cap__` 是受治理 Capability 的保留前缀；后续以双下划线分隔 Provider、Domain 和 Operation 层级，层级内使用小写 snake_case，总长不超过 128 字符。该标识同时用于业务主键、模型 Tool 名、Agent/Application 配置引用和审计记录，发布时必须全局唯一。现有和未来内部 Tool 不得使用 `cap__` 前缀。Capability 必须使用允许连续下划线的专用校验器，不能复用当前会拒绝该格式的通用业务 Code 校验规则。
