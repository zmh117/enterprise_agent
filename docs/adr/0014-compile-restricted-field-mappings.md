# Handler 映射使用受限类型化字段投影

管理员只能通过受限字段映射配置 Capability 输入、系统上下文、外部请求和 Capability 输出之间的投影。Agent 可写字段只能来自 Capability Input Schema，User ID、默认 Team、Token 等系统字段保持平台所有。第一版按 ADR-0045 仅支持字段与对象投影、数组逐项投影、固定常量、有限基础类型转换和固定默认值。平台在发布时把映射编译为不可变 Mapping Plan，并校验字段存在性、类型、系统字段所有权及大小边界。系统不提供 Jinja、JavaScript、Python、通用条件循环、过滤表达式、环境变量或 Secret 读取能力，避免配置层成为脚本运行时。
