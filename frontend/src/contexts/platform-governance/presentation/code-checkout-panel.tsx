import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { File, Folder } from "lucide-react"
import { apiRequest } from "@/shared/api/api-client"
import { createRequestKey } from "@/lib/request-key"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { KnowledgeError, KnowledgeField } from "./knowledge-resource-ui"

import {
  codeOperationSchema as jobSchema,
  useCodeCheckouts,
} from "../application/code-checkout-query"
const base = "/api/platform/knowledge/code"
const states: Record<string, string> = {
  queued: "等待执行",
  running: "正在执行",
  succeeded: "已完成",
  failed: "失败",
  interrupted: "已中断",
}
const errors: Record<string, string> = {
  CODE_SVN_AUTH_FAILED: "SVN 用户名或密码不正确，请更新连接后重试。",
  CODE_SVN_ACCESS_DENIED: "SVN 账号没有访问所选仓库或路径的权限。",
  CODE_SVN_CERTIFICATE_INVALID:
    "SVN 证书校验失败，请部署人员配置受信任的证书。",
  CODE_SVN_CONNECTION_FAILED: "无法连接 SVN，请检查地址和容器网络。",
  CODE_SVN_CREDENTIAL_UNAVAILABLE: "SVN 凭据缺失或已停用，请重新配置连接。",
  CODE_CHECKOUT_IDENTITY_CHANGED: "检出目录身份异常，需要维护核验后再使用。",
  CODE_CHECKOUT_PERMISSION_DENIED:
    "检出目录权限不足，请检查执行器与 Runtime 的共享读取权限。",
  code_checkout_destination_exists:
    "目标目录已存在，请填写新的子目录名。已有内容未覆盖。",
  code_checkout_externals_unsupported:
    "仓库含有 SVN 外部引用，本次未检出。请由部署人员确认外部依赖范围。",
  code_checkout_interrupted: "后台执行已中断，请重新发起任务。",
  code_checkout_access_denied: "执行时管理员权限已失效。",
  code_checkout_registration_changed: "仓库登记已变更，请重新浏览目录。",
}

function isLoopback(value: string) {
  try {
    return ["localhost", "127.0.0.1", "[::1]"].includes(new URL(value).hostname)
  } catch {
    return false
  }
}

export function CodeCheckoutPanel({ resourceId }: { resourceId: string }) {
  const cache = useQueryClient()
  const [urlInput, setUrl] = useState<string>()
  const [revision, setRevision] = useState("")
  const [browseId, setBrowseId] = useState<string>()
  const [selected, setSelected] = useState<string[]>([])
  const [folder, setFolder] = useState("mes")
  const [notice, setNotice] = useState("")
  const [authentication, setAuthentication] = useState("anonymous")
  const [savedConnection, setSavedConnection] = useState<{
    id: string
    url: string
    authentication: string
    username: string
  }>()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const snapshot = useCodeCheckouts(resourceId)
  const url = urlInput ?? snapshot.data?.registrations[0]?.url ?? ""
  const reuseSaved =
    savedConnection?.url === url.trim() &&
    savedConnection.authentication === authentication &&
    (authentication === "anonymous" || savedConnection.username === username) &&
    !password
  const selectedConnection = reuseSaved ? savedConnection.id : undefined
  const browse = useQuery({
    queryKey: ["code-checkout-browse", browseId],
    enabled: Boolean(browseId),
    refetchOnWindowFocus: false,
    refetchInterval: (query) =>
      ["succeeded", "failed", "interrupted"].includes(
        query.state.data?.state ?? ""
      )
        ? false
        : 1000,
    queryFn: async () =>
      jobSchema.parse(
        await apiRequest(`${base}/operations/${encodeURIComponent(browseId!)}`)
      ),
  })
  const submit = useMutation({
    mutationFn: async (kind: "browse" | "checkout") => {
      let connectionId = selectedConnection
      if (kind === "browse" && !connectionId) {
        try {
          const connection = z.object({ id: z.string() }).parse(
            await apiRequest(
              `${base}/resources/${encodeURIComponent(resourceId)}/connections`,
              {
                method: "POST",
                body: {
                  url: url.trim(),
                  authentication,
                  ...(authentication === "account"
                    ? { username, password }
                    : {}),
                },
              }
            )
          )
          connectionId = connection.id
          setSavedConnection({
            id: connection.id,
            url: url.trim(),
            authentication,
            username,
          })
          void cache.invalidateQueries({ queryKey: ["code-checkouts"] })
        } finally {
          setPassword("")
        }
      }
      return z.object({ id: z.string() }).parse(
        await apiRequest(
          `${base}/resources/${encodeURIComponent(resourceId)}/${kind === "browse" ? "browse" : "checkouts"}`,
          {
            method: "POST",
            body:
              kind === "browse"
                ? {
                    url: url.trim(),
                    revision: revision ? Number(revision) : null,
                    request_key: createRequestKey(),
                    ...(connectionId ? { connection_id: connectionId } : {}),
                  }
                : {
                    browse_job_id: browseId,
                    paths: selected,
                    folder,
                    request_key: createRequestKey(),
                  },
          }
        )
      )
    },
    onSuccess: (job, kind) => {
      if (kind === "browse") {
        setBrowseId(job.id)
        setSelected([])
      } else setNotice("检出任务已登记，关闭或刷新页面不影响后台执行。")
      void cache.invalidateQueries({ queryKey: ["code-checkouts"] })
    },
  })
  function resetBrowse() {
    setBrowseId(undefined)
    setSelected([])
  }
  const ready =
    browse.data?.state === "succeeded" && !browse.data.result_expired
  return (
    <section
      className="space-y-4 rounded-lg border p-4"
      aria-label="SVN 工程检出"
      data-testid="code-svn-checkout"
    >
      <div>
        <h3 className="font-medium">SVN 工程检出</h3>
        <p className="text-sm text-muted-foreground">
          从 SVN 多选文件或目录，由 Docker 检出完整工程。问答时按用户指定的 SVN
          版本核验。
        </p>
      </div>
      <KnowledgeError error={snapshot.error || browse.error || submit.error} />
      {snapshot.data && !snapshot.data.enabled ? (
        <p>尚未启用 SVN 检出，请由部署人员配置仓库和检出目录。</p>
      ) : (
        <>
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              resetBrowse()
              submit.mutate("browse")
            }}
          >
            <KnowledgeField label="SVN 仓库地址">
              <Input
                aria-label="SVN 仓库地址"
                disabled={submit.isPending}
                value={url}
                onChange={(e) => {
                  setUrl(e.target.value)
                  setSavedConnection(undefined)
                  resetBrowse()
                }}
                className="min-w-80"
              />
            </KnowledgeField>
            <KnowledgeField label="SVN 认证方式">
              <select
                aria-label="SVN 认证方式"
                className="h-9 rounded border px-2"
                value={authentication}
                disabled={submit.isPending}
                onChange={(event) => {
                  setAuthentication(event.target.value)
                  setSavedConnection(undefined)
                  setPassword("")
                  resetBrowse()
                }}
              >
                <option value="anonymous">无需认证</option>
                <option value="account">配置用户名密码</option>
              </select>
            </KnowledgeField>
            {authentication === "account" && (
              <>
                <KnowledgeField label="SVN 用户名">
                  <Input
                    aria-label="SVN 用户名"
                    autoComplete="username"
                    value={username}
                    disabled={submit.isPending}
                    maxLength={256}
                    required
                    onChange={(event) => {
                      setUsername(event.target.value)
                      setSavedConnection(undefined)
                      resetBrowse()
                    }}
                  />
                </KnowledgeField>
                <KnowledgeField label="SVN 密码">
                  <Input
                    aria-label="SVN 密码"
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    disabled={submit.isPending}
                    maxLength={4096}
                    required={!reuseSaved}
                    placeholder={
                      reuseSaved ? "已保存；留空复用，输入新密码可更换" : ""
                    }
                    onChange={(event) => {
                      setPassword(event.target.value)
                      resetBrowse()
                    }}
                  />
                </KnowledgeField>
              </>
            )}
            <KnowledgeField label="SVN 版本（留空为最新）">
              <Input
                aria-label="SVN 版本"
                disabled={submit.isPending}
                type="number"
                min="1"
                step="1"
                value={revision}
                onChange={(e) => {
                  setRevision(e.target.value)
                  resetBrowse()
                }}
              />
            </KnowledgeField>
            <Button
              type="submit"
              disabled={
                !url.trim() ||
                submit.isPending ||
                !snapshot.data?.enabled ||
                (authentication === "account" &&
                  (!username.trim() || (!password && !reuseSaved)))
              }
            >
              {authentication === "account" && !reuseSaved
                ? "保存连接并浏览"
                : "浏览目录"}
            </Button>
          </form>
          {authentication === "account" && reuseSaved && (
            <p role="status" className="text-sm text-muted-foreground">
              账号凭据已保存，再次浏览无需重复填写密码。
            </p>
          )}
          {isLoopback(url) && (
            <p role="alert" className="text-sm">
              此地址指向执行容器自身。访问宿主机
              SVN，请填写容器可访问的实际地址。系统按填写地址直接连接，不自动替换地址。
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            支持 http://、https://、svn://
            仓库地址。账号密码加密保存到凭据中心，不会提供给
            Agent。企业自签证书需由部署人员配置受信任的 CA。
          </p>
          {browse.data && (
            <p role="status">
              目录浏览：{states[browse.data.state] ?? browse.data.state}
              {browse.data.error_code &&
                ` · ${authentication === "anonymous" && browse.data.error_code === "CODE_SVN_AUTH_FAILED" ? "该仓库需要账号认证，请选择配置用户名和密码。" : (errors[browse.data.error_code] ?? browse.data.error_code)}`}
            </p>
          )}
          {browse.data?.result_expired && (
            <p role="status">目录预览已过期，请重新浏览。</p>
          )}
          {ready && (
            <>
              <p>
                已固定 SVN r{browse.data!.result.revision}
                ，后续新提交不会改变本次检出内容。
              </p>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  aria-label="检出整个仓库"
                  checked={selected.includes("")}
                  onChange={(e) => setSelected(e.target.checked ? [""] : [])}
                />
                检出整个仓库
              </label>
              <DirectoryChoices
                directories={browse.data!.result.directories ?? []}
                files={browse.data!.result.files ?? []}
                selected={selected}
                onChange={setSelected}
              />
              <form
                className="flex flex-wrap items-end gap-3"
                onSubmit={(e) => {
                  e.preventDefault()
                  submit.mutate("checkout")
                }}
              >
                <KnowledgeField label="目标子目录">
                  <Input
                    aria-label="目标子目录"
                    value={folder}
                    onChange={(e) => setFolder(e.target.value)}
                  />
                </KnowledgeField>
                <Button
                  type="submit"
                  disabled={
                    submit.isPending ||
                    !selected.length ||
                    !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(folder)
                  }
                >
                  检出所选内容
                </Button>
              </form>
              <p className="text-sm text-muted-foreground">
                所选文件及目录中的完整内容将被检出。目标位于部署配置的检出根目录下；已有目录不会覆盖。
              </p>
            </>
          )}
        </>
      )}
      {notice && <p role="status">{notice}</p>}
      {Boolean(snapshot.data?.jobs.length) && (
        <ul className="space-y-2" aria-label="SVN 检出任务">
          {snapshot
            .data!.jobs.filter((job) => job.operation_kind === "checkout")
            .map((job) => (
              <li key={job.id} className="rounded border p-3 text-sm">
                <span>
                  {states[job.state] ?? job.state}
                  {job.result.operative_revision !== undefined
                    ? ` · SVN r${job.result.operative_revision}`
                    : ""}
                </span>
                {job.result.relative_dir && (
                  <p className="break-all">
                    检出目录：{job.result.relative_dir}
                  </p>
                )}
                {job.error_code && (
                  <p role="alert">
                    {errors[job.error_code] ?? `检出未完成：${job.error_code}`}
                  </p>
                )}
              </li>
            ))}
        </ul>
      )}
    </section>
  )
}

export function DirectoryChoices({
  directories,
  files,
  selected,
  onChange,
}: {
  directories: string[]
  files: string[]
  selected: string[]
  onChange: (value: string[]) => void
}) {
  const [expanded, setExpanded] = useState<string[]>([])
  const fileChildren = useMemo(() => {
    const result = new Map<string, string[]>()
    for (const path of files) {
      const parent = path.includes("/")
        ? path.slice(0, path.lastIndexOf("/"))
        : ""
      const siblings = result.get(parent) ?? []
      siblings.push(path)
      result.set(parent, siblings)
    }
    return result
  }, [files])
  const children = useMemo(() => {
    const result = new Map<string, string[]>()
    for (const path of directories) {
      const parent = path.includes("/")
        ? path.slice(0, path.lastIndexOf("/"))
        : ""
      result.set(parent, [...(result.get(parent) ?? []), path])
    }
    return result
  }, [directories])
  function rows(parent: string): React.ReactNode {
    return (
      <ul className="space-y-1 pl-4">
        {(children.get(parent) ?? []).map((path) => {
          const inherited = selected.some(
            (value) => value === "" || path.startsWith(value + "/")
          )
          return (
            <li key={path}>
              <div className="grid grid-cols-[1rem_minmax(0,1fr)] items-start gap-2 text-sm">
                {children.has(path) || fileChildren.has(path) ? (
                  <button
                    type="button"
                    className="flex h-5 w-4 items-center justify-center"
                    aria-label={`展开 ${path}`}
                    aria-expanded={expanded.includes(path)}
                    onClick={() =>
                      setExpanded(
                        expanded.includes(path)
                          ? expanded.filter((p) => p !== path)
                          : [...expanded, path]
                      )
                    }
                  >
                    {expanded.includes(path) ? "−" : "+"}
                  </button>
                ) : (
                  <span aria-hidden="true" className="h-5 w-4" />
                )}
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    className="size-4 shrink-0"
                    aria-label={`选择 ${path}`}
                    disabled={inherited}
                    checked={inherited || selected.includes(path)}
                    onChange={(e) =>
                      onChange(
                        e.target.checked
                          ? [
                              ...selected.filter(
                                (p) => !p.startsWith(path + "/")
                              ),
                              path,
                            ]
                          : selected.filter((p) => p !== path)
                      )
                    }
                  />
                  <Folder
                    aria-hidden="true"
                    className="size-4 shrink-0 text-muted-foreground"
                  />
                  <span className="min-w-0 break-all">
                    {path.split("/").at(-1)}
                  </span>
                </label>
              </div>
              {expanded.includes(path) && rows(path)}
            </li>
          )
        })}
        {(fileChildren.get(parent) ?? []).map((path) => (
          <li
            key={path}
            title={path}
            className="grid grid-cols-[1rem_minmax(0,1fr)] items-start gap-2 text-sm"
          >
            <span aria-hidden="true" className="h-5 w-4" />
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                className="size-4 shrink-0"
                aria-label={`选择 ${path}`}
                checked={selected.some(
                  (value) =>
                    value === "" ||
                    value === path ||
                    path.startsWith(value + "/")
                )}
                disabled={selected.some(
                  (value) => value === "" || path.startsWith(value + "/")
                )}
                onChange={(e) =>
                  onChange(
                    e.target.checked
                      ? [...selected, path]
                      : selected.filter((value) => value !== path)
                  )
                }
              />
              <File
                aria-hidden="true"
                className="size-4 shrink-0 text-muted-foreground"
              />
              <span className="break-all">{path.split("/").at(-1)}</span>
            </label>
          </li>
        ))}
      </ul>
    )
  }
  return (
    <div
      className="max-h-96 overflow-auto rounded border p-3"
      aria-label="SVN 目录多选"
    >
      {rows("")}
    </div>
  )
}
