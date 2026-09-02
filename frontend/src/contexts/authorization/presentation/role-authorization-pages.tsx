import {
  useEffect,
  useMemo,
  useState,
  type FormEvent,
  type ReactNode,
} from "react"
import {
  ArrowLeftIcon,
  LoaderCircleIcon,
  PlusIcon,
  SaveIcon,
  ShieldCheckIcon,
  UsersIcon,
} from "lucide-react"
import { Link, useNavigate, useParams } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  useAdminCapabilityCatalog,
  useAssignableCatalog,
  useCreateRole,
  useExplainAuthorization,
  useRole,
  useRoleAudit,
  useRoles,
  useUpdateRoleAdmin,
  useUpdateRoleBusiness,
  useUpdateRoleMembers,
  useUpdateRoleMetadata,
} from "@/contexts/authorization/application/role-authorization-queries"
import { useAdminCapabilitySummary } from "@/contexts/auth/application/admin-capability-query"
import type {
  AdminCapability,
  CatalogApplication,
  CatalogEnvironment,
  Role,
  RoleDetail,
} from "@/contexts/authorization/domain/role-authorization"
import { useUsers } from "@/contexts/users/application/user-queries"
import { formatDate } from "@/contexts/users/presentation/format-date"
import { RequestError } from "@/contexts/users/presentation/user-ui"

const nativeSelectClass =
  "h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus:border-ring focus:ring-3 focus:ring-ring/30"

const roleTemplates = {
  blank: {
    label: "空白角色",
    description: "",
    purposeTags: [] as string[],
  },
  business_reader: {
    label: "业务应用只读角色",
    description: "用于配置业务应用、只读能力和明确的数据范围。",
    purposeTags: ["业务访问"],
  },
  admin_operator: {
    label: "后台管理角色",
    description: "用于按模块配置管理后台功能权限，不包含任何业务应用权限。",
    purposeTags: ["平台管理"],
  },
} as const

export function RoleAuthorizationPage() {
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState("")
  const [origin, setOrigin] = useState("")
  const [creating, setCreating] = useState(false)
  const roles = useRoles({ search, status, origin })
  const capabilities = useAdminCapabilitySummary()
  const canManage = Boolean(
    capabilities.data?.capabilities.includes("authorization.manage")
  )

  return (
    <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <header className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <Badge variant="outline">统一授权中心</Badge>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight">
            角色与授权
          </h1>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
            一个角色可以同时包含管理后台功能权限和业务应用只读权限。多角色允许并集，显式拒绝优先。
          </p>
        </div>
        <Button
          disabled={!canManage}
          onClick={() => setCreating((value) => !value)}
        >
          <PlusIcon aria-hidden="true" />
          新建角色
        </Button>
      </header>
      {!canManage ? (
        <ReadOnlyNotice text="当前账号只能查看角色，不能创建或修改角色授权。" />
      ) : null}

      {creating ? (
        <CreateRoleCard
          roles={roles.data?.items ?? []}
          onClose={() => setCreating(false)}
        />
      ) : null}

      <Card className="shadow-none">
        <CardContent className="grid gap-3 pt-6 md:grid-cols-[minmax(0,1fr)_180px_180px]">
          <Input
            aria-label="搜索角色"
            placeholder="搜索角色名称、编码或说明"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select
            aria-label="角色状态"
            className={nativeSelectClass}
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="">全部状态</option>
            <option value="enabled">已启用</option>
            <option value="disabled">已停用</option>
          </select>
          <select
            aria-label="角色来源"
            className={nativeSelectClass}
            value={origin}
            onChange={(event) => setOrigin(event.target.value)}
          >
            <option value="">全部来源</option>
            <option value="system">系统角色</option>
            <option value="custom">自定义角色</option>
          </select>
        </CardContent>
      </Card>

      {roles.isLoading ? <Loading text="正在加载角色…" /> : null}
      <RequestError error={roles.error} />
      {roles.data && roles.data.items.length === 0 ? (
        <EmptyState text="没有符合条件的角色" />
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        {roles.data?.items.map((role) => (
          <RoleCard key={role.id} role={role} />
        ))}
      </div>
    </div>
  )
}

function CreateRoleCard({
  roles,
  onClose,
}: {
  roles: Role[]
  onClose: () => void
}) {
  const navigate = useNavigate()
  const mutation = useCreateRole()
  const [name, setName] = useState("")
  const [code, setCode] = useState("")
  const [description, setDescription] = useState("")
  const [copyFrom, setCopyFrom] = useState("")
  const [template, setTemplate] = useState<keyof typeof roleTemplates>("blank")

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const selectedTemplate = roleTemplates[template]
    mutation.mutate(
      {
        name: name.trim(),
        code: code.trim(),
        description: description.trim() || selectedTemplate.description,
        purpose_tags: [...selectedTemplate.purposeTags],
        copy_from_role_id: copyFrom || undefined,
      },
      {
        onSuccess: (detail) => navigate(`/users/roles/${detail.role.id}`),
      }
    )
  }

  return (
    <Card className="border-primary/30 shadow-none">
      <CardHeader>
        <CardTitle>新建自定义角色</CardTitle>
        <CardDescription>
          可以空白创建、从安全模板起步或复制已有角色。模板只预填用途和说明，不会暗中授予权限；复制不会包含成员。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={submit}>
          <div className="grid gap-4 md:grid-cols-2">
            <Labeled label="角色名称">
              <Input
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </Labeled>
            <Labeled
              label="角色编码"
              hint="创建后不可修改，例如 readonly-operator"
            >
              <Input
                required
                pattern="[a-z][a-z0-9-]{1,63}"
                value={code}
                onChange={(event) => setCode(event.target.value)}
              />
            </Labeled>
            <Labeled label="复制来源">
              <select
                className={`${nativeSelectClass} w-full`}
                value={copyFrom}
                onChange={(event) => {
                  setCopyFrom(event.target.value)
                  if (event.target.value) setTemplate("blank")
                }}
              >
                <option value="">不复制已有角色</option>
                {roles
                  .filter((role) => !role.protected)
                  .map((role) => (
                    <option key={role.id} value={role.id}>
                      {role.name}（不复制成员）
                    </option>
                  ))}
              </select>
            </Labeled>
            <Labeled label="起始模板" hint="复制已有角色时模板自动切换为空白">
              <select
                className={`${nativeSelectClass} w-full`}
                value={template}
                disabled={Boolean(copyFrom)}
                onChange={(event) => {
                  const value = event.target.value as keyof typeof roleTemplates
                  setTemplate(value)
                  if (!description.trim()) {
                    setDescription(roleTemplates[value].description)
                  }
                }}
              >
                {Object.entries(roleTemplates).map(([value, item]) => (
                  <option key={value} value={value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </Labeled>
            <Labeled label="角色说明">
              <Input
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </Labeled>
          </div>
          <RequestError error={mutation.error} />
          <div className="flex gap-2">
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? (
                <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
              ) : (
                <PlusIcon aria-hidden="true" />
              )}
              创建角色
            </Button>
            <Button type="button" variant="outline" onClick={onClose}>
              取消
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function RoleCard({ role }: { role: Role }) {
  return (
    <Card className="shadow-none transition-colors hover:border-primary/40">
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle>{role.name}</CardTitle>
              <Badge
                variant={role.status === "enabled" ? "secondary" : "outline"}
              >
                {role.status === "enabled" ? "已启用" : "已停用"}
              </Badge>
              <Badge variant="outline">
                {role.origin === "system" ? "系统角色" : "自定义角色"}
              </Badge>
            </div>
            <CardDescription className="mt-2 font-mono">
              {role.code}
            </CardDescription>
          </div>
          {role.protected ? (
            <ShieldCheckIcon
              className="size-5 text-primary"
              aria-label="受保护角色"
            />
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="min-h-10 text-sm text-muted-foreground">
          {role.description || "暂无说明"}
        </p>
        <div className="grid grid-cols-3 gap-2 text-center text-xs">
          <SummaryNumber label="成员" value={role.member_count} />
          <SummaryNumber label="后台能力" value={role.admin_capability_count} />
          <SummaryNumber label="业务应用" value={role.application_count} />
        </div>
        <Button
          variant="outline"
          className="w-full"
          render={<Link to={`/users/roles/${role.id}`} />}
        >
          查看并配置
        </Button>
      </CardContent>
    </Card>
  )
}

export function RoleDetailPage() {
  const { roleId = "" } = useParams()
  const query = useRole(roleId)
  if (query.isLoading) return <Loading text="正在加载角色配置…" />
  if (query.isError || !query.data) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 px-6 py-10">
        <h1 className="text-2xl font-semibold">无法加载角色</h1>
        <RequestError error={query.error} />
        <Link
          to="/users/roles"
          className={buttonVariants({ variant: "outline" })}
        >
          返回角色列表
        </Link>
      </div>
    )
  }
  return (
    <RoleDetailContent
      key={[
        roleId,
        query.data.role.metadata_revision,
        query.data.role.admin_revision,
        query.data.role.business_revision,
        query.data.role.membership_revision,
      ].join("-")}
      detail={query.data}
    />
  )
}

function RoleDetailContent({ detail }: { detail: RoleDetail }) {
  const role = detail.role
  const capabilities = useAdminCapabilitySummary()
  const canManage = Boolean(
    capabilities.data?.capabilities.includes("authorization.manage")
  )
  const canAssign = Boolean(
    capabilities.data?.capabilities.includes("authorization.assign")
  )
  return (
    <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <div>
        <Link
          to="/users/roles"
          className={buttonVariants({ variant: "ghost", size: "sm" })}
        >
          <ArrowLeftIcon aria-hidden="true" />
          返回角色列表
        </Link>
      </div>
      <header>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">{role.name}</h1>
          <Badge variant={role.status === "enabled" ? "secondary" : "outline"}>
            {role.status === "enabled" ? "已启用" : "已停用"}
          </Badge>
          {role.protected ? <Badge>受保护系统角色</Badge> : null}
        </div>
        <p className="mt-2 font-mono text-xs text-muted-foreground">
          {role.code} · {role.id}
        </p>
      </header>

      <Tabs defaultValue="metadata">
        <TabsList className="max-w-full flex-wrap">
          <TabsTrigger value="metadata">基本信息</TabsTrigger>
          <TabsTrigger value="members">成员</TabsTrigger>
          <TabsTrigger value="admin">管理后台能力</TabsTrigger>
          <TabsTrigger value="business">业务应用与数据范围</TabsTrigger>
          <TabsTrigger value="preview">有效权限预览</TabsTrigger>
          <TabsTrigger value="audit">操作记录</TabsTrigger>
        </TabsList>
        <TabsContent value="metadata">
          <ReadOnlySection disabled={!canManage}>
            <MetadataPanel role={role} />
          </ReadOnlySection>
        </TabsContent>
        <TabsContent value="members">
          <ReadOnlySection disabled={!canAssign}>
            <MembersPanel detail={detail} />
          </ReadOnlySection>
        </TabsContent>
        <TabsContent value="admin">
          <ReadOnlySection disabled={!canManage}>
            <AdminCapabilitiesPanel detail={detail} />
          </ReadOnlySection>
        </TabsContent>
        <TabsContent value="business">
          <ReadOnlySection disabled={!canManage}>
            <BusinessAccessPanel detail={detail} />
          </ReadOnlySection>
        </TabsContent>
        <TabsContent value="preview">
          <AuthorizationPreviewPanel />
        </TabsContent>
        <TabsContent value="audit">
          <RoleAuditPanel roleId={role.id} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function RoleAuditPanel({ roleId }: { roleId: string }) {
  const query = useRoleAudit(roleId)
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>操作记录</CardTitle>
        <CardDescription>
          {query.data?.notice ??
            "角色基本信息、后台能力、业务范围和成员变更均写入平台安全审计。"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {query.isLoading ? <Loading text="正在加载操作记录…" /> : null}
        <RequestError error={query.error} />
        <div className="divide-y rounded-lg border">
          {query.data?.items.map((item) => (
            <div
              key={item.id}
              className="grid gap-1 p-3 text-sm sm:grid-cols-[minmax(0,1fr)_auto]"
            >
              <div>
                <span className="font-medium">{item.action_zh}</span>
                <span className="ml-2 text-xs text-muted-foreground">
                  操作者：{item.actor_id || "系统"}
                </span>
              </div>
              <span className="text-xs text-muted-foreground">
                {formatDate(item.created_at)}
              </span>
            </div>
          ))}
          {query.data?.items.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">
              暂无角色操作记录。
            </p>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}

function ReadOnlySection({
  disabled,
  children,
}: {
  disabled: boolean
  children: ReactNode
}) {
  return (
    <fieldset
      disabled={disabled}
      className="min-w-0 space-y-3 disabled:pointer-events-none disabled:opacity-75"
    >
      {disabled ? (
        <ReadOnlyNotice text="当前账号只能查看此授权区，提交不会包含或覆盖这里的配置。" />
      ) : null}
      {children}
    </fieldset>
  )
}

function ReadOnlyNotice({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      {text}
    </div>
  )
}

function MetadataPanel({ role }: { role: Role }) {
  const mutation = useUpdateRoleMetadata(role.id)
  const [name, setName] = useState(role.name)
  const [description, setDescription] = useState(role.description)
  const [tags, setTags] = useState(role.purpose_tags.join("、"))
  const [status, setStatus] = useState(role.status)
  const dirty =
    name !== role.name ||
    description !== role.description ||
    tags !== role.purpose_tags.join("、") ||
    status !== role.status
  useUnsavedWarning(dirty)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    mutation.mutate({
      expected_revision: role.metadata_revision,
      name,
      description,
      purpose_tags: tags
        .split(/[、,]/)
        .map((value) => value.trim())
        .filter(Boolean),
      status,
      confirmed: status === "disabled",
      reason: status === "disabled" ? "停用角色" : "",
    })
  }

  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>基本信息</CardTitle>
        <CardDescription>
          角色编码创建后不可修改。系统角色不能停用，也不能覆盖其隐式能力。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={submit}>
          <div className="grid gap-4 md:grid-cols-2">
            <Labeled label="角色名称">
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </Labeled>
            <Labeled label="角色编码">
              <Input value={role.code} disabled />
            </Labeled>
            <Labeled label="用途标签" hint="使用顿号或逗号分隔">
              <Input
                value={tags}
                onChange={(event) => setTags(event.target.value)}
              />
            </Labeled>
            <Labeled label="状态">
              <select
                className={`${nativeSelectClass} w-full`}
                value={status}
                disabled={role.protected}
                onChange={(event) =>
                  setStatus(event.target.value as "enabled" | "disabled")
                }
              >
                <option value="enabled">已启用</option>
                <option value="disabled">已停用</option>
              </select>
            </Labeled>
          </div>
          <Labeled label="角色说明">
            <textarea
              className="min-h-24 w-full rounded-md border border-input bg-transparent p-3 text-sm outline-none focus:border-ring"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Labeled>
          <RequestError error={mutation.error} />
          <Button type="submit" disabled={!dirty || mutation.isPending}>
            <SaveIcon aria-hidden="true" />
            保存基本信息
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

function MembersPanel({ detail }: { detail: RoleDetail }) {
  const role = detail.role
  const users = useUsers({
    search: "",
    page: 1,
    pageSize: 100,
    includeDisabled: true,
  })
  const mutation = useUpdateRoleMembers(role.id)
  const current = new Map(
    detail.membership.members.map((member) => [
      member.id,
      {
        enabled: member.membership_status === "enabled",
        expires_at: member.expires_at ?? "",
      },
    ])
  )
  const [selection, setSelection] = useState(current)
  const dirty = JSON.stringify([...selection]) !== JSON.stringify([...current])
  useUnsavedWarning(dirty)

  const save = () => {
    const allUserIds = new Set([...current.keys(), ...selection.keys()])
    mutation.mutate({
      expected_revision: detail.membership.revision,
      confirmed: role.protected,
      changes: [...allUserIds]
        .filter((userId) => {
          const before = current.get(userId)
          const after = selection.get(userId)
          return JSON.stringify(before) !== JSON.stringify(after)
        })
        .map((userId) => ({
          user_id: userId,
          enabled: selection.get(userId)?.enabled ?? false,
          expires_at: selection.get(userId)?.expires_at || null,
          source: "manual",
        })),
    })
  }

  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>角色成员</CardTitle>
        <CardDescription>
          成员关系可设置失效时间；到期后会立即从新的授权决策中排除。服务账号不能加入含后台能力的角色。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {users.isLoading ? <Loading text="正在加载人员…" /> : null}
        <RequestError error={users.error ?? mutation.error} />
        <div className="divide-y rounded-lg border">
          {users.data?.users.map((user) => {
            const selected = selection.get(user.id)
            return (
              <div
                key={user.id}
                className="grid gap-3 p-3 md:grid-cols-[minmax(0,1fr)_auto_220px] md:items-center"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{user.display_name}</span>
                    <Badge variant="outline">
                      {user.account_type === "human" ? "人员" : "服务账号"}
                    </Badge>
                  </div>
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    {user.username}
                  </p>
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={Boolean(selected?.enabled)}
                    onCheckedChange={(checked) => {
                      const next = new Map(selection)
                      next.set(user.id, {
                        enabled: Boolean(checked),
                        expires_at: selected?.expires_at ?? "",
                      })
                      setSelection(next)
                    }}
                  />
                  角色成员
                </label>
                <Input
                  type="datetime-local"
                  aria-label={`${user.display_name}的成员失效时间`}
                  disabled={!selected?.enabled}
                  value={toLocalDateTime(selected?.expires_at ?? "")}
                  onChange={(event) => {
                    const next = new Map(selection)
                    next.set(user.id, {
                      enabled: true,
                      expires_at: event.target.value
                        ? new Date(event.target.value).toISOString()
                        : "",
                    })
                    setSelection(next)
                  }}
                />
              </div>
            )
          })}
        </div>
        <Button disabled={!dirty || mutation.isPending} onClick={save}>
          <UsersIcon aria-hidden="true" />
          原子保存成员变更
        </Button>
      </CardContent>
    </Card>
  )
}

function AdminCapabilitiesPanel({ detail }: { detail: RoleDetail }) {
  const role = detail.role
  const catalog = useAdminCapabilityCatalog()
  const mutation = useUpdateRoleAdmin(role.id)
  const currentCodes = new Set(
    detail.admin.bindings.map((binding) => binding.capability_code)
  )
  const [selectedCodes, setSelectedCodes] = useState(currentCodes)
  const [confirmed, setConfirmed] = useState(false)
  const [reason, setReason] = useState("")
  const dirty =
    JSON.stringify([...selectedCodes].sort()) !==
    JSON.stringify([...currentCodes].sort())
  useUnsavedWarning(dirty)

  const definitions = new Map(
    catalog.data?.items.map((item) => [item.code, item]) ?? []
  )
  const grouped = useMemo(() => {
    const result = new Map<string, AdminCapability[]>()
    for (const capability of catalog.data?.items ?? []) {
      const items = result.get(capability.module) ?? []
      items.push(capability)
      result.set(capability.module, items)
    }
    return result
  }, [catalog.data])

  const toggle = (capability: AdminCapability, checked: boolean) => {
    const next = new Set(selectedCodes)
    if (checked) {
      addWithDependencies(next, capability.code, definitions)
    } else {
      next.delete(capability.code)
      for (const item of definitions.values()) {
        if (item.dependencies.includes(capability.code)) next.delete(item.code)
      }
    }
    setSelectedCodes(next)
  }

  const save = () =>
    mutation.mutate({
      expected_revision: detail.admin.revision,
      bindings: [...selectedCodes].map((capability_code) => ({
        capability_code,
        resource_code: "*",
      })),
      confirmed,
      reason,
    })

  if (detail.admin.implicit_all) {
    return (
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>全部管理后台能力</CardTitle>
          <CardDescription>
            `platform-admin`
            自动拥有管理目录当前及未来新增能力，但不会因此获得业务应用、工具或数据访问权限。
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {[...grouped.entries()].map(([module, capabilities]) => (
        <Card key={module} className="shadow-none">
          <CardHeader>
            <CardTitle className="text-base">{moduleLabel(module)}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {capabilities.map((capability) => (
              <label
                key={capability.code}
                className="flex items-start gap-3 rounded-lg border p-3"
              >
                <Checkbox
                  checked={selectedCodes.has(capability.code)}
                  onCheckedChange={(checked) =>
                    toggle(capability, Boolean(checked))
                  }
                />
                <span>
                  <span className="flex flex-wrap items-center gap-2 font-medium">
                    {capability.display_name_zh}
                    {capability.risk_level === "high" ? (
                      <Badge variant="destructive">高风险</Badge>
                    ) : null}
                  </span>
                  <span className="mt-1 block font-mono text-xs text-muted-foreground">
                    {capability.code}
                  </span>
                  {capability.dependencies.length ? (
                    <span className="mt-1 block text-xs text-muted-foreground">
                      自动依赖：{capability.dependencies.join("、")}
                    </span>
                  ) : null}
                </span>
              </label>
            ))}
          </CardContent>
        </Card>
      ))}
      <RiskConfirmation
        confirmed={confirmed}
        reason={reason}
        onConfirmed={setConfirmed}
        onReason={setReason}
      />
      <RequestError error={catalog.error ?? mutation.error} />
      <Button disabled={!dirty || mutation.isPending} onClick={save}>
        <SaveIcon aria-hidden="true" />
        原子保存后台能力
      </Button>
    </div>
  )
}

type ApplicationSelection = {
  toolIdentifiers: Set<string>
  scopeKeys: Set<string>
}

function BusinessAccessPanel({ detail }: { detail: RoleDetail }) {
  const role = detail.role
  const catalog = useAssignableCatalog()
  const mutation = useUpdateRoleBusiness(role.id)
  const initial = new Map<string, ApplicationSelection>(
    detail.business.applications.map((application) => [
      application.application_id,
      {
        toolIdentifiers: new Set(application.tool_identifiers),
        scopeKeys: new Set(application.scopes.map((scope) => scope.scope_key)),
      },
    ])
  )
  const [selection, setSelection] = useState(initial)
  const [confirmed, setConfirmed] = useState(false)
  const [reason, setReason] = useState("")
  const dirty =
    serializeApplicationSelection(selection) !==
    serializeApplicationSelection(initial)
  useUnsavedWarning(dirty)

  if (role.protected) {
    return (
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>未配置业务访问</CardTitle>
          <CardDescription>
            受保护的 `platform-admin`
            只管理控制面，不允许在此角色中配置业务应用、工具或数据访问。
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  const save = () => {
    const topologyByScope = explicitScopeMap(catalog.data?.topology ?? [])
    mutation.mutate({
      expected_revision: detail.business.revision,
      confirmed,
      reason,
      applications: [...selection.entries()].map(([application_id, value]) => ({
        application_id,
        tool_identifiers: [...value.toolIdentifiers],
        scopes: [...value.scopeKeys]
          .map((key) => topologyByScope.get(key))
          .filter(Boolean),
      })),
    })
  }

  return (
    <div className="space-y-4">
      <Card className="border-primary/20 bg-primary/5 shadow-none">
        <CardContent className="pt-6 text-sm">
          {catalog.data?.scope_notice ??
            "“当前全部”保存当前已有范围的明确集合，未来新增资源不会自动获得。"}
        </CardContent>
      </Card>
      {catalog.data?.applications.map((application) => (
        <BusinessApplicationCard
          key={application.id}
          application={application}
          topology={catalog.data?.topology ?? []}
          selected={selection.get(application.id)}
          onChange={(nextValue) => {
            const next = new Map(selection)
            if (nextValue) next.set(application.id, nextValue)
            else next.delete(application.id)
            setSelection(next)
          }}
        />
      ))}
      {catalog.data?.applications.length === 0 ? (
        <EmptyState text="当前没有可授权的业务应用" />
      ) : null}
      <RiskConfirmation
        confirmed={confirmed}
        reason={reason}
        onConfirmed={setConfirmed}
        onReason={setReason}
      />
      <RequestError error={catalog.error ?? mutation.error} />
      <Button disabled={!dirty || mutation.isPending} onClick={save}>
        <SaveIcon aria-hidden="true" />
        原子保存业务授权
      </Button>
    </div>
  )
}

function BusinessApplicationCard({
  application,
  topology,
  selected,
  onChange,
}: {
  application: CatalogApplication
  topology: CatalogEnvironment[]
  selected?: ApplicationSelection
  onChange: (selection?: ApplicationSelection) => void
}) {
  const enabled = Boolean(selected)
  const update = (next: ApplicationSelection) => onChange(next)
  const currentToolIdentifiers = new Set(
    application.mcp_tools.map((tool) => tool.tool_identifier)
  )
  const removedToolIdentifiers = selected
    ? [...selected.toolIdentifiers].filter(
        (identifier) => !currentToolIdentifiers.has(identifier)
      )
    : []
  return (
    <Card className="shadow-none">
      <CardHeader>
        <label className="flex items-start gap-3">
          <Checkbox
            checked={enabled}
            onCheckedChange={(checked) =>
              onChange(
                checked
                  ? { toolIdentifiers: new Set(), scopeKeys: new Set() }
                  : undefined
              )
            }
          />
          <span>
            <CardTitle className="text-base">{application.name}</CardTitle>
            <CardDescription className="mt-1">
              {application.code} · {application.project_code}
            </CardDescription>
          </span>
        </label>
      </CardHeader>
      {enabled && selected ? (
        <CardContent className="space-y-5">
          <div>
            <h3 className="text-sm font-medium">MCP Tool 使用权限</h3>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {removedToolIdentifiers.map((identifier) => (
                <label
                  key={identifier}
                  className="flex items-start gap-3 rounded-md border border-destructive/50 bg-destructive/5 p-3 text-sm"
                >
                  <Checkbox
                    className="mt-0.5"
                    aria-label={`MCP Tool ${identifier}`}
                    checked
                    onCheckedChange={(checked) => {
                      if (checked) return
                      const identifiers = new Set(selected.toolIdentifiers)
                      identifiers.delete(identifier)
                      update({ ...selected, toolIdentifiers: identifiers })
                    }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block font-mono text-xs">
                      {identifier}
                    </span>
                    <span className="mt-1 block text-xs leading-5 text-destructive">
                      MCP Tool 已从当前应用 Publication 移除，请取消选择后保存新授权；历史角色审计和既有 Job 快照不会被改写。
                    </span>
                  </span>
                </label>
              ))}
              {application.mcp_tools.map((tool) => (
                <label
                  key={tool.tool_identifier}
                  className="flex items-start gap-3 rounded-md border p-3 text-sm"
                >
                  <Checkbox
                    className="mt-0.5"
                    aria-label={`${tool.display_name_zh} ${tool.tool_identifier}`}
                    checked={selected.toolIdentifiers.has(
                      tool.tool_identifier
                    )}
                    onCheckedChange={(checked) => {
                      const identifiers = new Set(selected.toolIdentifiers)
                      if (checked) identifiers.add(tool.tool_identifier)
                      else identifiers.delete(tool.tool_identifier)
                      update({ ...selected, toolIdentifiers: identifiers })
                    }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block">
                      <span>{tool.display_name_zh}</span>{" "}
                      <span className="font-mono text-xs text-muted-foreground">
                        {tool.tool_identifier}
                      </span>
                    </span>
                    <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                      {tool.description.trim() || "暂无工具说明。"}
                    </span>
                    <span className="mt-1 block text-xs text-muted-foreground">
                      {tool.effect === "mutation" ? "写入" : "只读"}
                      {tool.confirmation_policy === "external_action_card_v1"
                        ? " · 每次需原用户确认卡片"
                        : ""}
                    </span>
                  </span>
                </label>
              ))}
              {application.mcp_tools.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  此应用未装配 MCP Tool，仅可授予应用调用权限。
                </p>
              ) : null}
            </div>
          </div>
          <div>
            <h3 className="text-sm font-medium">local 数据范围</h3>
            <div className="mt-3 space-y-3">
              {topology.map((environment) => (
                <ScopeTree
                  key={environment.id}
                  environment={environment}
                  selected={selected.scopeKeys}
                  onChange={(scopeKeys) => update({ ...selected, scopeKeys })}
                />
              ))}
            </div>
          </div>
        </CardContent>
      ) : null}
    </Card>
  )
}

function ScopeTree({
  environment,
  selected,
  onChange,
}: {
  environment: CatalogEnvironment
  selected: Set<string>
  onChange: (value: Set<string>) => void
}) {
  const environmentKey = environment.code
  const allBaseKeys = environment.bases.map(
    (base) => `${environment.code}/${base.code}`
  )
  const toggleMany = (keys: string[], checked: boolean) => {
    const next = new Set(selected)
    keys.forEach((key) => (checked ? next.add(key) : next.delete(key)))
    onChange(next)
  }
  return (
    <div className="rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">
          {environment.display_name || environment.code}
        </span>
        {allBaseKeys.length > 0 ? (
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <Checkbox
              checked={allBaseKeys.every((key) => selected.has(key))}
              onCheckedChange={(checked) =>
                toggleMany(allBaseKeys, Boolean(checked))
              }
            />
            当前全部基地（保存明确集合）
          </label>
        ) : (
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <Checkbox
              checked={selected.has(environmentKey)}
              onCheckedChange={(checked) =>
                toggleMany([environmentKey], Boolean(checked))
              }
            />
            选择 {environment.code} 环境
          </label>
        )}
      </div>
      {environment.bases.length > 0 ? (
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          {environment.bases.map((base) => {
            const baseKey = `${environment.code}/${base.code}`
            const workshopKeys = base.workshops.map(
              (workshop) => `${baseKey}/${workshop.code}`
            )
            return (
              <div key={base.id} className="rounded-md bg-muted/40 p-3">
                <label className="flex items-center gap-2 text-sm font-medium">
                  <Checkbox
                    checked={selected.has(baseKey)}
                    onCheckedChange={(checked) =>
                      toggleMany([baseKey], Boolean(checked))
                    }
                  />
                  {base.display_name || base.code}
                </label>
                {workshopKeys.length ? (
                  <>
                    <label className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                      <Checkbox
                        checked={workshopKeys.every((key) => selected.has(key))}
                        onCheckedChange={(checked) =>
                          toggleMany(workshopKeys, Boolean(checked))
                        }
                      />
                      当前全部车间（保存明确集合）
                    </label>
                    <div className="mt-2 space-y-2 pl-6">
                      {base.workshops.map((workshop) => {
                        const key = `${baseKey}/${workshop.code}`
                        return (
                          <label
                            key={workshop.id}
                            className="flex items-center gap-2 text-xs"
                          >
                            <Checkbox
                              checked={selected.has(key)}
                              onCheckedChange={(checked) =>
                                toggleMany([key], Boolean(checked))
                              }
                            />
                            {workshop.display_name || workshop.code}
                          </label>
                        )
                      })}
                    </div>
                  </>
                ) : null}
              </div>
            )
          })}
        </div>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">
          此环境没有基地层级，环境本身就是可授权的业务目标。
        </p>
      )}
    </div>
  )
}

function AuthorizationPreviewPanel() {
  const users = useUsers({
    search: "",
    page: 1,
    pageSize: 100,
    includeDisabled: false,
  })
  const catalog = useAssignableCatalog()
  const mutation = useExplainAuthorization()
  const [userId, setUserId] = useState("")
  const [applicationId, setApplicationId] = useState("")
  const [capability, setCapability] = useState("")

  const application = catalog.data?.applications.find(
    (item) => item.id === applicationId
  )
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>有效权限模拟</CardTitle>
        <CardDescription>
          使用与真实运行链一致的求值器，结果只显示安全的角色、应用、能力和范围摘要。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 md:grid-cols-3">
          <Labeled label="用户">
            <select
              className={`${nativeSelectClass} w-full`}
              value={userId}
              onChange={(event) => setUserId(event.target.value)}
            >
              <option value="">请选择用户</option>
              {users.data?.users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.display_name}（{user.username}）
                </option>
              ))}
            </select>
          </Labeled>
          <Labeled label="业务应用">
            <select
              className={`${nativeSelectClass} w-full`}
              value={applicationId}
              onChange={(event) => {
                setApplicationId(event.target.value)
                setCapability("")
              }}
            >
              <option value="">请选择业务应用</option>
              {catalog.data?.applications.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </Labeled>
          <Labeled label="MCP Tool">
            <select
              className={`${nativeSelectClass} w-full`}
              value={capability}
              onChange={(event) => setCapability(event.target.value)}
            >
              <option value="">仅模拟应用调用</option>
              {application?.mcp_tools.map((item) => (
                <option key={item.tool_identifier} value={item.tool_identifier}>
                  {item.tool_identifier}
                </option>
              ))}
            </select>
          </Labeled>
        </div>
        <Button
          disabled={!userId || !applicationId || mutation.isPending}
          onClick={() =>
            mutation.mutate({
              user_id: userId,
              application_id: applicationId,
              tool_identifier: capability,
              environment: "",
              base: "",
              workshop: "",
              stage: "invoke",
            })
          }
        >
          模拟授权决策
        </Button>
        <RequestError error={users.error ?? catalog.error ?? mutation.error} />
        {mutation.data ? (
          <div
            className={`rounded-lg border p-4 ${
              mutation.data.decision.allowed
                ? "border-emerald-300 bg-emerald-50"
                : "border-destructive/30 bg-destructive/5"
            }`}
          >
            <p className="font-medium">
              {mutation.data.decision.allowed ? "允许访问" : "拒绝访问"}
            </p>
            <p className="mt-2 text-sm">
              {decisionMessage(mutation.data.decision.reason)}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              来源角色：
              {mutation.data.decision.source_role_codes.join("、") || "无"}
            </p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function RiskConfirmation({
  confirmed,
  reason,
  onConfirmed,
  onReason,
}: {
  confirmed: boolean
  reason: string
  onConfirmed: (value: boolean) => void
  onReason: (value: string) => void
}) {
  return (
    <Card className="border-amber-300 bg-amber-50 shadow-none">
      <CardContent className="space-y-3 pt-6">
        <label className="flex items-center gap-2 text-sm font-medium">
          <Checkbox
            checked={confirmed}
            onCheckedChange={(checked) => onConfirmed(Boolean(checked))}
          />
          我已确认本次高风险授权变更及受影响成员
        </label>
        <Input
          aria-label="授权变更原因"
          placeholder="填写变更原因（高风险变更必填）"
          value={reason}
          onChange={(event) => onReason(event.target.value)}
        />
      </CardContent>
    </Card>
  )
}

function Labeled({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <label className="space-y-2">
      <span className="block text-sm font-medium">{label}</span>
      {children}
      {hint ? (
        <span className="block text-xs text-muted-foreground">{hint}</span>
      ) : null}
    </label>
  )
}

function SummaryNumber({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-muted/50 p-2">
      <p className="text-lg font-semibold">{value}</p>
      <p className="text-muted-foreground">{label}</p>
    </div>
  )
}

function Loading({ text }: { text: string }) {
  return (
    <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-muted-foreground">
      <LoaderCircleIcon className="size-4 animate-spin" aria-hidden="true" />
      {text}
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return (
    <Card className="border-dashed shadow-none">
      <CardContent className="py-12 text-center text-sm text-muted-foreground">
        {text}
      </CardContent>
    </Card>
  )
}

function useUnsavedWarning(dirty: boolean) {
  useEffect(() => {
    const listener = (event: BeforeUnloadEvent) => {
      if (!dirty) return
      event.preventDefault()
    }
    window.addEventListener("beforeunload", listener)
    return () => window.removeEventListener("beforeunload", listener)
  }, [dirty])
}

function addWithDependencies(
  target: Set<string>,
  code: string,
  definitions: Map<string, AdminCapability>
) {
  if (target.has(code)) return
  target.add(code)
  definitions
    .get(code)
    ?.dependencies.forEach((dependency) =>
      addWithDependencies(target, dependency, definitions)
    )
}

function moduleLabel(module: string) {
  const labels: Record<string, string> = {
    dashboard: "工作台",
    applications: "业务应用",
    channels: "渠道与触发器",
    agents: "Agent 配置",
    users: "人员与外部身份",
    authorization: "角色与授权",
    operations: "运行中心",
    audit: "审计",
    platform: "平台配置与密钥",
  }
  return labels[module] ?? module
}

function explicitScopeMap(topology: CatalogEnvironment[]) {
  const result = new Map<
    string,
    { environment_id: string; base_id?: string; workshop_id?: string }
  >()
  for (const environment of topology) {
    result.set(environment.code, { environment_id: environment.id })
    for (const base of environment.bases) {
      const baseKey = `${environment.code}/${base.code}`
      result.set(baseKey, {
        environment_id: environment.id,
        base_id: base.id,
      })
      for (const workshop of base.workshops) {
        result.set(`${baseKey}/${workshop.code}`, {
          environment_id: environment.id,
          base_id: base.id,
          workshop_id: workshop.id,
        })
      }
    }
  }
  return result
}

function serializeApplicationSelection(
  value: Map<string, ApplicationSelection>
) {
  return JSON.stringify(
    [...value.entries()]
      .map(([applicationId, selection]) => [
        applicationId,
        [...selection.toolIdentifiers].sort(),
        [...selection.scopeKeys].sort(),
      ])
      .sort()
  )
}

function toLocalDateTime(value: string) {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function decisionMessage(reason: string) {
  const messages: Record<string, string> = {
    application_role_allow: "用户通过有效角色获得该业务应用权限。",
    no_application_role: "用户未获得该业务应用的使用权限。",
    application_tool_safety_ceiling:
      "所选 MCP Tool 超出业务应用安全上限，角色不能授予。",
    application_tool_denied: "角色未授予所选 MCP Tool。",
    application_scope_denied: "角色未授予所选数据范围。",
    user_disabled: "用户已停用。",
    application_disabled: "业务应用已停用。",
  }
  return messages[reason] ?? "授权求值已完成，请根据安全原因编码联系管理员。"
}
