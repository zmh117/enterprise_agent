import { ArchiveAction } from "@/shared/presentation/archive-action"
import { updateRoleMetadata } from "@/contexts/authorization/infrastructure/role-authorization-api"
import { McpToolGroups } from "@/shared/presentation/mcp-tool-groups"
import {
  ListEmpty,
  ListPage,
  ListPager,
  ListResults,
  ListSearch,
  ListStatus,
  RefreshList,
} from "@/shared/presentation/list-page"
import {
  LIST_PAGE_SIZE,
  useListNavigation,
  useListReturn,
} from "@/shared/presentation/list-navigation"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { FormDialog, FormDialogCancel } from "@/shared/presentation/form-dialog"
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
  useRoleChoices,
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
  const list = useListNavigation()
  const search = list.params.get("q") ?? ""
  const status = list.params.get("status") ?? ""
  const origin = list.params.get("origin") ?? ""
  const clear = () => list.filter({ q: "", status: "", origin: "" })
  const filtered = !!(search || status || origin)
  const [creating, setCreating] = useState(false)
  const roles = useRoles({
    search,
    status,
    origin,
    offset: (list.page - 1) * LIST_PAGE_SIZE,
    limit: LIST_PAGE_SIZE,
  })
  const capabilities = useAdminCapabilitySummary()
  const canManage = Boolean(
    capabilities.data?.capabilities.includes("authorization.manage")
  )

  return (
    <ListPage
      title="角色与授权"
      actions={
        <>
          <RefreshList
            refresh={() => void roles.refetch()}
            busy={roles.isFetching}
          />
          <Button disabled={!canManage} onClick={() => setCreating(true)}>
            <PlusIcon />
            新建角色
          </Button>
        </>
      }
    >
      {!canManage ? (
        <ReadOnlyNotice text="当前账号只能查看角色，不能创建或修改角色授权。" />
      ) : null}

      {creating ? <CreateRoleCard onClose={() => setCreating(false)} /> : null}

      <div className="flex flex-wrap items-center gap-2">
        <ListSearch
          label="搜索角色"
          placeholder="搜索角色名称、编码或说明"
          value={search}
          onCommit={(q) => list.filter({ q })}
        />
        <select
          aria-label="角色状态"
          className={nativeSelectClass}
          value={status}
          onChange={(event) => list.filter({ status: event.target.value })}
        >
          <option value="">全部状态</option>
          <option value="enabled">已启用</option>
          <option value="disabled">已停用</option>
          <option value="archived">已归档</option>
        </select>
        <select
          aria-label="角色来源"
          className={nativeSelectClass}
          value={origin}
          onChange={(event) => list.filter({ origin: event.target.value })}
        >
          <option value="">全部来源</option>
          <option value="system">系统角色</option>
          <option value="custom">自定义角色</option>
        </select>
        {filtered && (
          <Button variant="ghost" size="sm" onClick={clear}>
            重置
          </Button>
        )}
      </div>
      {roles.isLoading && <Loading text="正在加载角色…" />}
      <RequestError error={roles.error} />
      {roles.data && (
        <ListResults>
          {roles.data.items.length ? (
            <Table aria-label="角色列表">
              <TableHeader>
                <TableRow>
                  <TableHead>角色</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>来源</TableHead>
                  <TableHead className="hidden sm:table-cell">成员</TableHead>
                  <TableHead className="hidden md:table-cell">
                    后台能力
                  </TableHead>
                  <TableHead className="hidden md:table-cell">
                    业务应用
                  </TableHead>
                  {canManage && (
                    <TableHead className="text-right">操作</TableHead>
                  )}
                </TableRow>
              </TableHeader>
              <TableBody>
                {roles.data.items.map((role) => (
                  <TableRow key={role.id}>
                    <TableCell>
                      <Link
                        className="font-medium hover:underline"
                        to={`/users/roles/${encodeURIComponent(role.id)}`}
                        state={list.detailState}
                      >
                        {role.name}
                      </Link>
                      {role.protected && (
                        <ShieldCheckIcon
                          className="ml-1 inline size-3"
                          aria-label="受保护角色"
                        />
                      )}
                      <p className="max-w-40 truncate font-mono text-xs text-muted-foreground">
                        {role.code}
                      </p>
                    </TableCell>
                    <TableCell>
                      <ListStatus status={role.status} />
                    </TableCell>
                    <TableCell>
                      {role.origin === "system" ? "系统角色" : "自定义角色"}
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">
                      {role.member_count}
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      {role.admin_capability_count}
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      {role.application_count}
                    </TableCell>
                    {canManage && (
                      <TableCell className="text-right">
                        {role.origin === "custom" &&
                          !role.protected &&
                          role.status === "disabled" && (
                            <ArchiveAction
                              name={role.name}
                              queryKey={["role-authorization"]}
                              archive={() =>
                                updateRoleMetadata(role.id, {
                                  expected_revision: role.metadata_revision,
                                  name: role.name,
                                  description: role.description,
                                  purpose_tags: role.purpose_tags,
                                  status: "archived",
                                  confirmed: true,
                                  reason: "归档角色",
                                })
                              }
                            />
                          )}
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <ListEmpty
              title={filtered ? "没有符合条件的角色" : "还没有角色"}
              clear={filtered ? clear : undefined}
            />
          )}
          <ListPager
            count={`共 ${roles.data.page.total} 个角色`}
            page={list.page}
            pages={Math.ceil(roles.data.page.total / LIST_PAGE_SIZE)}
            previous={() => list.numberedPage(list.page - 1)}
            next={
              list.page * LIST_PAGE_SIZE < roles.data.page.total
                ? () => list.numberedPage(list.page + 1)
                : undefined
            }
          />
        </ListResults>
      )}
    </ListPage>
  )
}

function CreateRoleCard({ onClose }: { onClose: () => void }) {
  const choices = useRoleChoices()
  const list = useListNavigation()
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
        onSuccess: (detail) =>
          navigate(`/users/roles/${detail.role.id}`, {
            state: list.detailState,
          }),
      }
    )
  }

  return (
    <FormDialog
      title="新建自定义角色"
      onClose={onClose}
      pending={mutation.isPending}
    >
      <form className="space-y-4" onSubmit={submit}>
        <RequestError error={choices.error} />
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
              {(choices.data ?? [])
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
          <FormDialogCancel disabled={mutation.isPending} />
        </div>
      </form>
    </FormDialog>
  )
}

export function RoleDetailPage() {
  const listReturn = useListReturn("/users/roles")
  const { roleId = "" } = useParams()
  const query = useRole(roleId)
  if (query.isLoading) return <Loading text="正在加载角色配置…" />
  if (query.isError || !query.data) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 px-6 py-10">
        <h1 className="text-2xl font-semibold">无法加载角色</h1>
        <RequestError error={query.error} />
        <Link
          {...listReturn}
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
  const listReturn = useListReturn("/users/roles")
  const role = detail.role
  const capabilities = useAdminCapabilitySummary()
  const canManage =
    role.status !== "archived" &&
    Boolean(capabilities.data?.capabilities.includes("authorization.manage"))
  const canAssign =
    role.status !== "archived" &&
    Boolean(capabilities.data?.capabilities.includes("authorization.assign"))
  return (
    <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <div>
        <Link
          {...listReturn}
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
            {
              { enabled: "已启用", disabled: "已停用", archived: "已归档" }[
                role.status
              ]
            }
          </Badge>
          {role.protected ? <Badge>受保护系统角色</Badge> : null}
        </div>
        <p className="mt-2 font-mono text-xs text-muted-foreground">
          {role.code} · {role.id}
        </p>
      </header>

      <Tabs defaultValue="metadata">
        <TabsList
          variant="line"
          className="h-auto max-w-full justify-start overflow-x-auto"
        >
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
          <MembersPanel detail={detail} canAssign={canAssign} />
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
        <CardDescription>{query.data?.notice}</CardDescription>
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

function MembersPanel({
  detail,
  canAssign,
}: {
  detail: RoleDetail
  canAssign: boolean
}) {
  const [search, setSearch] = useState("")
  const [page, setPage] = useState(1)
  const filter = (q: string) => {
    setSearch(q)
    setPage(1)
  }
  const role = detail.role
  const users = useUsers({
    search,
    page,
    pageSize: LIST_PAGE_SIZE,
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
          成员授权到期即失效。含后台能力的角色仅支持人员账号。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!canAssign && <ReadOnlyNotice text="当前账号只能查看角色成员。" />}
        <ListSearch
          label="搜索角色成员候选人"
          placeholder="搜索姓名、账号或邮箱"
          value={search}
          onCommit={filter}
        />
        {users.isLoading ? <Loading text="正在加载人员…" /> : null}
        <RequestError error={users.error ?? mutation.error} />
        <ListResults>
          <div className="divide-y">
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
                      disabled={!canAssign}
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
                    disabled={!canAssign || !selected?.enabled}
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
          {users.data && (
            <>
              {!users.data.users.length && (
                <ListEmpty
                  title="没有符合条件的人员"
                  clear={search ? () => filter("") : undefined}
                />
              )}
              <ListPager
                page={page}
                pages={users.data.pagination.total_pages}
                count={`共 ${users.data.pagination.total} 人`}
                previous={() => setPage(page - 1)}
                next={
                  page < users.data.pagination.total_pages
                    ? () => setPage(page + 1)
                    : undefined
                }
              />
            </>
          )}
        </ListResults>
        <Button
          disabled={!canAssign || !dirty || mutation.isPending}
          onClick={save}
        >
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
  knowledgeBaseIds: Set<string>
}

type KnowledgeBaseGrantDetail =
  RoleDetail["business"]["applications"][number]["knowledge_base_details"][number]

function historicalKnowledgeBaseLabel(base?: KnowledgeBaseGrantDetail) {
  if (!base) return "知识库信息暂不可用"
  const name = base.display_name.trim() || base.code || "知识库"
  const reasons = {
    missing: "记录已不存在",
    resource_missing: "尚未配置检索资源",
    archived: "已归档",
    disabled: "已停用",
    unpublished: "尚未发布",
    publication_invalid: "的发布记录无效",
  }
  return base.unavailable_reason
    ? `${name}${reasons[base.unavailable_reason]}`
    : `${name}不在你的可授权范围内`
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
        knowledgeBaseIds: new Set(application.knowledge_base_ids),
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
        knowledge_base_ids: [...value.knowledgeBaseIds].sort(),
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
          knowledgeBaseDetails={
            detail.business.applications.find(
              (access) => access.application_id === application.id
            )?.knowledge_base_details ?? []
          }
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
  knowledgeBaseDetails,
  onChange,
}: {
  application: CatalogApplication
  topology: CatalogEnvironment[]
  selected?: ApplicationSelection
  knowledgeBaseDetails: KnowledgeBaseGrantDetail[]
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
  const unavailableKnowledgeBaseIds = selected
    ? [...selected.knowledgeBaseIds].filter(
        (id) => !application.knowledge_bases.some((base) => base.id === id)
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
                  ? {
                      toolIdentifiers: new Set(),
                      scopeKeys: new Set(),
                      knowledgeBaseIds: new Set(),
                    }
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
            <div className="mt-3 space-y-3">
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
                      MCP Tool 已从当前应用 Publication
                      移除，请取消选择后保存新授权；历史角色审计和既有 Job
                      快照不会被改写。
                    </span>
                  </span>
                </label>
              ))}
              <McpToolGroups
                tools={application.mcp_tools.map((tool) => ({
                  ...tool,
                  identifier: tool.tool_identifier,
                  ariaLabel: `${tool.display_name_zh} ${tool.tool_identifier}`,
                  read_only: tool.effect !== "mutation",
                }))}
                selected={selected.toolIdentifiers}
                onChange={(ids) =>
                  update({ ...selected, toolIdentifiers: new Set(ids) })
                }
              />
              {application.mcp_tools.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  此应用未装配 MCP Tool，仅可授予应用调用权限。
                </p>
              ) : null}
            </div>
          </div>
          <div>
            <h3 className="text-sm font-medium">知识库使用范围</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              仅列出“工具资源”中已发布且启用的知识资源，名称与工具资源一致；尚未发布、已归档、停用或尚未配置资源的知识库不能新增授权。勾选只对当前应用生效；实际检索还需本应用的工具授权、有效发布资源和本人
              ONES 可读权限。
            </p>
            {application.knowledge_bases.length > 0 ? (
              <label className="mt-3 flex items-center gap-2 text-sm">
                <Checkbox
                  checked={application.knowledge_bases.every((base) =>
                    selected.knowledgeBaseIds.has(base.id)
                  )}
                  onCheckedChange={(checked) => {
                    const ids = new Set(selected.knowledgeBaseIds)
                    application.knowledge_bases.forEach((base) =>
                      checked ? ids.add(base.id) : ids.delete(base.id)
                    )
                    update({ ...selected, knowledgeBaseIds: ids })
                  }}
                />
                当前全部知识库（保存明确 ID，未来新增不自动授权）
              </label>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">
                当前没有可授权的知识库。
              </p>
            )}
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {application.knowledge_bases.map((base) => (
                <label
                  key={base.id}
                  className="flex items-start gap-3 rounded-md border p-3 text-sm"
                >
                  <Checkbox
                    aria-label={`${application.name} 知识库 ${base.display_name} ${base.id}`}
                    checked={selected.knowledgeBaseIds.has(base.id)}
                    onCheckedChange={(checked) => {
                      const ids = new Set(selected.knowledgeBaseIds)
                      if (checked) ids.add(base.id)
                      else ids.delete(base.id)
                      update({ ...selected, knowledgeBaseIds: ids })
                    }}
                  />
                  <span>
                    {base.display_name}
                    <span className="block font-mono text-xs break-all text-muted-foreground">
                      {base.id}
                    </span>
                  </span>
                </label>
              ))}
            </div>
            {unavailableKnowledgeBaseIds.length > 0 ? (
              <div
                className="mt-3 space-y-2 rounded-md border border-destructive/50 p-3"
                aria-label={`${application.name} 历史知识库授权`}
              >
                <p className="text-xs text-muted-foreground">
                  以下知识库已有授权，但当前不能新增授权。保持勾选会保留原授权；取消勾选并保存会撤销本角色的授权，不会删除知识库。
                </p>
                {unavailableKnowledgeBaseIds.map((id) => (
                  <label
                    key={id}
                    className="flex items-start gap-3 rounded-md border border-destructive/50 p-3 text-sm"
                  >
                    <Checkbox
                      aria-label={`${application.name} 移除不可授权知识库 ${id}`}
                      checked
                      onCheckedChange={() => {
                        const ids = new Set(selected.knowledgeBaseIds)
                        ids.delete(id)
                        update({ ...selected, knowledgeBaseIds: ids })
                      }}
                    />
                    <span className="min-w-0 break-words">
                      {historicalKnowledgeBaseLabel(
                        knowledgeBaseDetails.find((base) => base.id === id)
                      )}
                      <span className="mt-1 block font-mono text-xs break-all text-muted-foreground">
                        ID：{id}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            ) : null}
            <p
              className="mt-3 text-xs break-all text-muted-foreground"
              aria-label={`${application.name} 知识库授权预览`}
            >
              保存的知识库 ID：
              {[...selected.knowledgeBaseIds].sort().join("、") ||
                "无（本角色不授予此应用知识库权限）"}
              。取消勾选并保存会撤销本记录授权；其他角色的完整允许仍可生效。
            </p>
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
  const [knowledgeBaseId, setKnowledgeBaseId] = useState("")

  const application = catalog.data?.applications.find(
    (item) => item.id === applicationId
  )
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>有效权限模拟</CardTitle>
        <CardDescription>
          检查当前角色、应用、工具与知识库范围；不代表资源已发布、Job 已授权或
          ONES 可读性已通过。
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
                setKnowledgeBaseId("")
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
          <Labeled label="知识库范围">
            <select
              className={`${nativeSelectClass} w-full`}
              value={knowledgeBaseId}
              disabled={!capability}
              onChange={(event) => setKnowledgeBaseId(event.target.value)}
            >
              <option value="">不检查知识库</option>
              {application?.knowledge_bases.map((base) => (
                <option key={base.id} value={base.id}>
                  {base.display_name}（{base.id}）
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
              knowledge_base_id: capability ? knowledgeBaseId : "",
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
        [...selection.knowledgeBaseIds].sort(),
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
    application_knowledge_base_denied:
      "当前应用没有同一条角色记录共同授予所选工具与知识库。",
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
