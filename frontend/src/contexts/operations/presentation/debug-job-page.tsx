import { useMemo, useState, type FormEvent } from "react"
import {
  BugPlayIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  ShieldCheckIcon,
} from "lucide-react"
import { useNavigate } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import {
  useCreateDebugJob,
  useDebugJobOptions,
} from "@/contexts/operations/application/debug-job-queries"
import { ApiError } from "@/shared/api/api-client"

export function DebugJobPage() {
  const options = useDebugJobOptions()
  const create = useCreateDebugJob()
  const navigate = useNavigate()
  const [form, setForm] = useState({
    application_id: "",
    execution_scope_id: "",
    delivery_binding_id: "",
    message: "",
    idempotency_key: "",
  })
  const application = useMemo(
    () =>
      options.data?.applications.find(
        (item) => item.id === form.application_id
      ),
    [form.application_id, options.data?.applications]
  )

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate(form, {
      onSuccess: (result) =>
        navigate(`/operations/jobs/${encodeURIComponent(result.job_id)}`),
    })
  }

  return (
    <PageFrame>
      <header>
        <div className="flex items-center gap-2 text-xs font-medium text-primary">
          <BugPlayIcon className="size-4" aria-hidden="true" />
          RUNTIME CENTER
        </div>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">发起调试</h1>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-muted-foreground">
              不依赖外部 Channel，使用当前登录用户发起真实 Agent
              Job。应用、执行范围与 Delivery 均来自服务端授权选项，默认不投递。
            </p>
          </div>
          <Button
            variant="outline"
            onClick={() => void options.refetch()}
            disabled={options.isFetching}
          >
            <RefreshCwIcon
              className={options.isFetching ? "animate-spin" : ""}
              aria-hidden="true"
            />
            刷新授权选项
          </Button>
        </div>
      </header>

      <Card className="border-dashed shadow-none">
        <CardContent className="flex gap-3 py-4 text-sm">
          <ShieldCheckIcon
            className="mt-0.5 size-4 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
          <p className="leading-6 text-muted-foreground">
            页面不接受 user_id、Agent ID、Resource Revision、任意 Connector
            或自定义 reply route；后端会再次按当前用户、应用发布和 Execution
            Scope 校验。
          </p>
        </CardContent>
      </Card>

      {options.isLoading ? (
        <Skeleton className="h-80 w-full" />
      ) : options.isError ? (
        <MutationError error={options.error} />
      ) : !options.data?.applications.length ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <BugPlayIcon aria-hidden="true" />
            </EmptyMedia>
            <EmptyTitle>没有可用的调试应用</EmptyTitle>
            <EmptyDescription>
              当前用户需要 agent.debug.execute、已发布应用角色和至少一个
              Execution Scope。
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>创建 Agent Debug Job</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={submit} className="space-y-5">
              <FieldGroup className="grid gap-4 md:grid-cols-2">
                <Field>
                  <FieldLabel>业务应用发布</FieldLabel>
                  <Select
                    value={form.application_id}
                    onValueChange={(value) =>
                      setForm({
                        ...form,
                        application_id: String(value ?? ""),
                        execution_scope_id: "",
                        delivery_binding_id: "",
                      })
                    }
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="选择可用应用" />
                    </SelectTrigger>
                    <SelectContent>
                      {options.data.applications.map((item) => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.name} · r{item.publication_revision}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field>
                  <FieldLabel>Execution Scope</FieldLabel>
                  <Select
                    disabled={!application}
                    value={form.execution_scope_id}
                    onValueChange={(value) =>
                      setForm({
                        ...form,
                        execution_scope_id: String(value ?? ""),
                      })
                    }
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="选择已授权范围" />
                    </SelectTrigger>
                    <SelectContent>
                      {(application?.execution_scopes ?? []).map((scope) => (
                        <SelectItem key={scope.id} value={scope.id}>
                          {scope.scope_key}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field>
                  <FieldLabel>Delivery</FieldLabel>
                  <Select
                    disabled={!application}
                    value={form.delivery_binding_id || "__none"}
                    onValueChange={(value) =>
                      setForm({
                        ...form,
                        delivery_binding_id:
                          value === "__none" ? "" : String(value ?? ""),
                      })
                    }
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__none">
                        none（默认，不投递）
                      </SelectItem>
                      {(application?.delivery_bindings ?? []).map((binding) => (
                        <SelectItem
                          key={binding.binding_id}
                          value={binding.binding_id}
                        >
                          {binding.delivery_type} · {binding.connector_id}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FieldDescription>
                    只能选择应用发布中已有且已授权的 binding。
                  </FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="debug-idempotency">
                    幂等键（可选）
                  </FieldLabel>
                  <Input
                    id="debug-idempotency"
                    maxLength={240}
                    autoComplete="off"
                    value={form.idempotency_key}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        idempotency_key: event.target.value,
                      })
                    }
                    placeholder="diagnosis-20260729-001"
                  />
                  <FieldDescription>
                    同一用户、应用发布和范围下重复提交会返回同一个 Job。
                  </FieldDescription>
                </Field>
              </FieldGroup>
              <Field>
                <FieldLabel htmlFor="debug-message">调试问题</FieldLabel>
                <Textarea
                  id="debug-message"
                  required
                  minLength={1}
                  maxLength={20000}
                  className="min-h-40"
                  value={form.message}
                  onChange={(event) =>
                    setForm({ ...form, message: event.target.value })
                  }
                  placeholder="请检查当前范围内数据库、Redis 与日志的异常关联，只执行只读诊断。"
                />
              </Field>
              {application ? (
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">{application.code}</Badge>
                  <Badge variant="outline">
                    publication {application.publication_id}
                  </Badge>
                  <Badge variant="outline">{application.project_code}</Badge>
                </div>
              ) : null}
              <MutationError error={create.error} />
              <Button
                type="submit"
                disabled={
                  create.isPending ||
                  !form.application_id ||
                  !form.execution_scope_id
                }
              >
                {create.isPending ? (
                  <LoaderCircleIcon
                    className="animate-spin"
                    aria-hidden="true"
                  />
                ) : null}
                创建并查看运行详情
              </Button>
            </form>
          </CardContent>
        </Card>
      )}
    </PageFrame>
  )
}

function MutationError({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <FieldError>
      {error instanceof ApiError ? error.message : "操作失败，请刷新后重试。"}
    </FieldError>
  )
}

function PageFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      {children}
    </div>
  )
}
