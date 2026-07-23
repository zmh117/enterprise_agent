import type { LucideIcon } from "lucide-react"
import {
  BellRingIcon,
  BotIcon,
  BracesIcon,
  Building2Icon,
  CableIcon,
  CircleGaugeIcon,
  ClipboardCheckIcon,
  HistoryIcon,
  KeyRoundIcon,
  LayoutDashboardIcon,
  MessagesSquareIcon,
  NetworkIcon,
  PackageCheckIcon,
  RadioTowerIcon,
  ScrollTextIcon,
  ShieldCheckIcon,
  UsersIcon,
  WorkflowIcon,
} from "lucide-react"

export const prototypeMeta = {
  label: "原型数据",
  environment: "示例环境 · production-sandbox",
  fixturePolicy:
    "所有人员、账号、运行记录、时间与数量均为本地虚构数据，不读取后端。",
} as const

export type NavigationItem = {
  label: string
  icon: LucideIcon
  active?: boolean
}

export type NavigationGroup = {
  label: string
  items: NavigationItem[]
}

export const navigationGroups: NavigationGroup[] = [
  {
    label: "工作台",
    items: [{ label: "总览", icon: LayoutDashboardIcon, active: true }],
  },
  {
    label: "业务应用",
    items: [
      { label: "应用列表", icon: PackageCheckIcon },
      { label: "流程设计", icon: WorkflowIcon },
      { label: "渠道与触发器", icon: RadioTowerIcon },
      { label: "发布管理", icon: HistoryIcon },
    ],
  },
  {
    label: "Agent 配置",
    items: [
      { label: "Agent Profile", icon: BotIcon },
      { label: "Skill", icon: BracesIcon },
      { label: "上下文策略", icon: NetworkIcon },
    ],
  },
  {
    label: "API 能力",
    items: [
      { label: "能力目录", icon: CableIcon },
      { label: "应用授权", icon: ShieldCheckIcon },
      { label: "平台连接", icon: Building2Icon },
    ],
  },
  {
    label: "运行中心",
    items: [
      { label: "Agent 任务", icon: CircleGaugeIcon },
      { label: "会话记录", icon: MessagesSquareIcon },
      { label: "调用与投递", icon: BellRingIcon },
    ],
  },
  {
    label: "系统管理",
    items: [
      { label: "用户与外部身份", icon: UsersIcon },
      { label: "角色与授权", icon: KeyRoundIcon },
      { label: "审计日志", icon: ScrollTextIcon },
      { label: "环境管理", icon: ClipboardCheckIcon },
    ],
  },
]

export const overviewMetrics = [
  { label: "业务应用", value: "3", note: "覆盖三种入口" },
  { label: "Agent Profile", value: "2", note: "共享一个 Runtime" },
  { label: "API Capability", value: "18", note: "只读能力示例" },
  { label: "示例运行", value: "126", note: "静态记录，非实时" },
] as const

export type BusinessApplication = {
  id: string
  name: string
  description: string
  icon: LucideIcon
  tone: "indigo" | "cyan" | "amber"
  profile: string
  workflow: string
  trigger: string
  capabilities: number
  delivery: string
  environment: string
  release: string
  identity: string
}

export const businessApplications: BusinessApplication[] = [
  {
    id: "APP-DEMO-PRIVATE",
    name: "钉钉私聊诊断助手",
    description: "面向人员的一对一连续诊断，会话与调用主体都按当前发送人解析。",
    icon: BotIcon,
    tone: "indigo",
    profile: "生产故障诊断 · r3",
    workflow: "private-diagnosis · v2",
    trigger: "钉钉私聊消息",
    capabilities: 6,
    delivery: "回复原私聊",
    environment: "示例生产环境",
    release: "评审中",
    identity: "应用 + 租户 + 钉钉用户",
  },
  {
    id: "APP-DEMO-GROUP",
    name: "钉钉群聊诊断助手",
    description:
      "群保存会话上下文；每条消息仍按发送人的内部身份和数据权限执行。",
    icon: MessagesSquareIcon,
    tone: "cyan",
    profile: "生产故障诊断 · r3",
    workflow: "group-diagnosis · v1",
    trigger: "群聊 @机器人",
    capabilities: 5,
    delivery: "回复原群聊",
    environment: "示例生产环境",
    release: "草稿",
    identity: "群会话 ≠ 群共享身份",
  },
  {
    id: "APP-DEMO-WEBHOOK",
    name: "Webhook 告警分析助手",
    description:
      "以服务账号接收已验签告警，固定查询基础信息后交由 Agent 综合分析。",
    icon: BellRingIcon,
    tone: "amber",
    profile: "告警分析 · r2",
    workflow: "alert-triage · v4",
    trigger: "签名 Webhook",
    capabilities: 7,
    delivery: "钉钉告警群",
    environment: "示例生产环境",
    release: "已冻结示例",
    identity: "服务账号 · alarm-demo",
  },
]

export const applicationWorkspaces = [
  { name: "应用概览", description: "装配关系、负责人和状态" },
  { name: "流程设计", description: "触发、确定性节点与 Agent 节点" },
  { name: "渠道与触发器", description: "入口、会话策略与投递目标" },
  { name: "能力授权", description: "应用级 Capability 白名单" },
  { name: "发布管理", description: "冻结引用版本与回滚记录" },
] as const

export const platformFlow = [
  { label: "Channel", description: "钉钉 / Webhook" },
  { label: "Business Application", description: "业务入口装配" },
  { label: "Workflow", description: "确定性流程" },
  { label: "Agent Runtime", description: "共享执行内核" },
  { label: "Capability Gateway", description: "授权与审计" },
  { label: "API Platform", description: "受控业务 API" },
  { label: "Delivery", description: "原会话 / 通知" },
] as const

export const workflowPreviews = [
  {
    name: "钉钉私聊",
    mode: "动态能力",
    steps: [
      "私聊触发",
      "身份解析",
      "加载人员会话",
      "Agent 自主选择只读能力",
      "回复原私聊",
    ],
  },
  {
    name: "钉钉群聊",
    mode: "逐消息授权",
    steps: [
      "群聊 @机器人",
      "识别当前发送人",
      "加载群会话",
      "按发送人授权 Agent",
      "回复原群聊",
    ],
  },
  {
    name: "Webhook 告警",
    mode: "固定节点 + Agent",
    steps: [
      "验签与幂等",
      "固定 API · 告警详情",
      "固定 API · 相关日志",
      "Agent 综合分析",
      "钉钉投递",
    ],
  },
] as const

export const capabilities = [
  {
    code: "log.query.application",
    name: "查询应用日志",
    description: "按系统、范围和时间检索受控日志摘要",
    risk: "低风险 · 只读",
    environment: "生产示例",
    status: "可用于评审",
  },
  {
    code: "order.query.detail",
    name: "查询订单详情",
    description: "按可信主体的数据范围获取订单状态",
    risk: "低风险 · 只读",
    environment: "生产示例",
    status: "可用于评审",
  },
  {
    code: "cache.query.status",
    name: "查询缓存状态",
    description: "查询业务缓存状态，不暴露底层实现",
    risk: "低风险 · 只读",
    environment: "测试示例",
    status: "待适配",
  },
] as const

export const permissionIntersection = [
  "平台已发布",
  "应用已授权",
  "Workflow 节点允许",
  "Agent Profile 允许",
  "当前主体数据权限",
] as const

export const releaseSnapshot = [
  ["Profile Revision", "diagnosis-profile · r3"],
  ["Workflow Revision", "private-diagnosis · v2"],
  ["Capability Version", "capability-set · 2026-demo-03"],
  ["Channel Binding", "dingtalk-private · demo-v1"],
  ["Policy Revision", "read-only-policy · r5"],
] as const

export const sampleRuns = [
  {
    id: "RUN-DEMO-0126",
    app: "钉钉私聊诊断助手",
    actor: "USR-DEMO-001",
    status: "完成示例",
    duration: "38s",
  },
  {
    id: "RUN-DEMO-0125",
    app: "Webhook 告警分析助手",
    actor: "SVC-DEMO-ALARM",
    status: "处理中示例",
    duration: "1m 12s",
  },
  {
    id: "RUN-DEMO-0124",
    app: "钉钉群聊诊断助手",
    actor: "USR-DEMO-002",
    status: "权限拦截示例",
    duration: "4s",
  },
] as const

export const identityFixture = {
  internalUser: {
    id: "USR-DEMO-001",
    name: "示例用户 A",
    roles: ["诊断应用使用者", "示例 A 区域只读"],
  },
  identities: [
    {
      provider: "钉钉",
      subject: "DING-DEMO-0357",
      connection: "示例企业 · ding-demo",
      purposes: ["消息来源", "投递目标"],
      status: "已验证",
      source: "管理员手工绑定",
    },
    {
      provider: "ONES",
      subject: "ONES-DEMO-1088",
      connection: "示例研发空间 · ones-demo",
      purposes: ["需求主体", "任务与缺陷主体"],
      status: "已验证",
      source: "自助验证",
    },
    {
      provider: "其他系统",
      subject: "EXT-DEMO-PENDING",
      connection: "未来连接扩展位",
      purposes: ["目录引用"],
      status: "待关联",
      source: "目录匹配建议 · 未自动绑定",
    },
  ],
} as const

export const identityStatuses = [
  { label: "已验证", value: 12, note: "手工绑定 / 自助验证" },
  { label: "待关联", value: 3, note: "只给出非敏感匹配提示" },
  { label: "冲突", value: 1, note: "必须人工处理唯一性" },
  { label: "停用", value: 2, note: "保留审计，不参与解析" },
] as const

export const groupIdentityExamples = [
  {
    member: "群成员 A",
    internal: "USR-DEMO-001",
    ones: "ONES-DEMO-1088",
    scope: "示例 A 区域",
  },
  {
    member: "群成员 B",
    internal: "USR-DEMO-002",
    ones: "ONES-DEMO-2042",
    scope: "示例 B 区域",
  },
] as const

export const managementArchitecture = [
  "外部系统接入",
  "用户与外部身份",
  "角色与授权",
  "Webhook / 服务账号",
  "审计日志",
  "环境管理",
] as const

export const buildStatuses = [
  { label: "概念原型", items: "本页信息架构与视觉结构", tone: "indigo" },
  {
    label: "后端已有基础",
    items: "内部用户、外部身份、Agent 任务与投递记录",
    tone: "emerald",
  },
  {
    label: "需要适配",
    items: "业务应用、Capability Gateway、版本化 Workflow",
    tone: "amber",
  },
  {
    label: "尚未实现",
    items: "真实编辑、发布、绑定与控制面 API",
    tone: "slate",
  },
] as const

export const forbiddenOperations = [
  "任意 SQL",
  "Redis 命令",
  "LogQL",
  "Shell",
  "任意 HTTP",
  "高风险写操作",
] as const
