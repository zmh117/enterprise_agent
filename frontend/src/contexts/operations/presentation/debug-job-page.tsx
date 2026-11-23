import { ListPage, RefreshList } from "@/shared/presentation/list-page"
import { useMemo, useState, type FormEvent } from "react"
import { BugPlayIcon, LoaderCircleIcon } from "lucide-react"
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
    <ListPage
      title="发起调试"
      actions={
        <RefreshList
          refresh={() => void options.refetch()}
          busy={options.isFetching}
        />
      }
    >
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
            <CardTitle>调试参数</CardTitle>
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
                  <FieldLabel>结果投递</FieldLabel>
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
                      <SelectItem value="__none">默认不投递</SelectItem>
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
                    默认不投递。可选择应用已授权的投递目标。
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
                    同一用户、应用版本和范围内，相同幂等键只创建一个任务。
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
              <p className="text-xs text-muted-foreground">
                提交后将以当前账号执行真实任务。
              </p>
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
    </ListPage>
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
