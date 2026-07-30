# Handler 映射使用受限类型化字段投影

管理员只能通过受限字段映射配置 Capability 输入、系统上下文、外部请求和 Capability 输出之间的投影。平台在发布时把映射编译为不可变 Mapping Plan，并校验字段存在性、类型、系统字段所有权及大小边界。系统不提供 Jinja、JavaScript、Python、通用条件循环、环境变量或 Secret 读取能力，避免配置层成为脚本运行时。
