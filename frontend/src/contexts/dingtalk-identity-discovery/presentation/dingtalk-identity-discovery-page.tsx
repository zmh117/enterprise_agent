import { useState, type FormEvent } from "react"
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  SearchIcon,
  UserSearchIcon,
} from "lucide-react"
import { Link } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useDingTalkIdentityCandidates } from "@/contexts/dingtalk-identity-discovery/application/dingtalk-identity-candidate-queries"
import type {
  ConversationScope,
  DingTalkIdentityCandidate,
} from "@/contexts/dingtalk-identity-discovery/domain/dingtalk-identity-candidate"
import { formatDate } from "@/contexts/users/presentation/format-date"
import { RequestError } from "@/contexts/users/presentation/user-ui"

const PAGE_SIZE = 25

export function DingTalkIdentityDiscoveryPage() {
  const [draftSearch, setDraftSearch] = useState("")
  const [search, setSearch] = useState("")
  const [scope, setScope] = useState<"all" | ConversationScope>("all")
  const [cursor, setCursor] = useState("")
  const [cursorHistory, setCursorHistory] = useState<string[]>([])
  const query = useDingTalkIdentityCandidates({
    search,
    conversationScope: scope,
    cursor,
    limit: PAGE_SIZE,
  })

  const resetPagination = () => {
    setCursor("")
    setCursorHistory([])
  }
  const submitSearch = (event: FormEvent) => {
    event.preventDefault()
    resetPagination()
    setSearch(draftSearch.trim())
  }
  const nextPage = () => {
    if (!query.data?.next_cursor) return
    setCursorHistory((value) => [...value, cursor])
    setCursor(query.data.next_cursor)
  }
  const previousPage = () => {
    const previous = cursorHistory.at(-1)
    if (previous === undefined) return
    setCursor(previous)
    setCursorHistory((value) => value.slice(0, -1))
  }

  return (
    <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-indigo-700">
            <UserSearchIcon className="size-4" aria-hidden="true" />
            DINGTALK IDENTITY DISCOVERY
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">
            未绑定钉钉用户
          </h1>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-muted-foreground">
            展示最近 30
            天内给机器人发送过消息、但尚未完成系统身份绑定的私聊和群聊用户。
            完成绑定或恢复后，用户会立即从列表消失。
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
        >
          <RefreshCwIcon
            className={query.isFetching ? "animate-spin" : ""}
            aria-hidden="true"
          />
          刷新
        </Button>
      </header>

      <Card className="shadow-none">
        <CardContent>
          <form
            onSubmit={submitSearch}
            className="flex flex-col gap-2 lg:flex-row"
            role="search"
          >
            <div className="relative flex-1">
              <SearchIcon
                className="pointer-events-none absolute top-2 left-2.5 size-4 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                aria-label="搜索未绑定钉钉用户"
                className="pl-8"
                value={draftSearch}
                onChange={(event) => setDraftSearch(event.target.value)}
                placeholder="钉钉用户名、用户 ID、群 ID、机器人或连接器"
              />
            </div>
            <select
              aria-label="会话类型"
              className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              value={scope}
              onChange={(event) => {
                setScope(event.target.value as "all" | ConversationScope)
                resetPagination()
              }}
            >
              <option value="all">全部会话</option>
              <option value="direct">仅私聊</option>
              <option value="group">仅群聊</option>
              <option value="both">私聊和群聊均出现</option>
            </select>
            <Button type="submit" variant="outline">
              搜索
            </Button>
          </form>
        </CardContent>
      </Card>

      {query.isLoading ? (
        <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-muted-foreground">
          <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
          正在加载待绑定用户…
        </div>
      ) : null}
      {query.isError ? <RequestError error={query.error} /> : null}
      {query.data ? (
        <Card className="shadow-none">
          <CardContent className="px-0">
            {query.data.candidates.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-4">钉钉用户</TableHead>
                    <TableHead>最近消息</TableHead>
                    <TableHead>时间</TableHead>
                    <TableHead>会话 / 群 ID</TableHead>
                    <TableHead>所属机器人</TableHead>
                    <TableHead className="pr-4 text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {query.data.candidates.map((candidate) => (
                    <CandidateRow key={candidate.id} candidate={candidate} />
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="px-4 py-16 text-center text-sm text-muted-foreground">
                当前没有待绑定的钉钉用户。
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}

      {query.data ? (
        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!cursorHistory.length}
            onClick={previousPage}
          >
            <ChevronLeftIcon aria-hidden="true" />
            上一页
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!query.data.has_more}
            onClick={nextPage}
          >
            下一页
            <ChevronRightIcon aria-hidden="true" />
          </Button>
        </div>
      ) : null}
    </div>
  )
}

function CandidateRow({ candidate }: { candidate: DingTalkIdentityCandidate }) {
  const latest = candidate.latest_message
  const historical = candidate.historical_identity
  const actionHref =
    candidate.identity_state === "restore_required" && historical
      ? `/users/${encodeURIComponent(historical.user_id)}?candidate=${encodeURIComponent(candidate.id)}`
      : `/users?candidate=${encodeURIComponent(candidate.id)}`

  return (
    <TableRow>
      <TableCell className="max-w-60 pl-4 align-top">
        <div className="font-medium">
          {candidate.display_name || "未提供钉钉用户名"}
        </div>
        <div className="mt-1 font-mono text-xs break-all text-muted-foreground">
          {candidate.external_subject_id}
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          <Badge variant="outline">
            {candidate.conversation_scope === "direct"
              ? "私聊"
              : candidate.conversation_scope === "group"
                ? "群聊"
                : "私聊 + 群聊"}
          </Badge>
          <Badge variant="secondary">
            {candidate.observation_count} 条观测
          </Badge>
          {candidate.identity_state === "restore_required" ? (
            <Badge variant="outline">需恢复历史身份</Badge>
          ) : null}
        </div>
      </TableCell>
      <TableCell className="max-w-96 align-top">
        <div className="text-sm break-words whitespace-pre-wrap">
          {messageSummary(latest)}
        </div>
        {latest?.text_truncated ? (
          <span className="text-xs text-muted-foreground">消息已截断</span>
        ) : null}
        <details className="mt-2 text-xs">
          <summary className="cursor-pointer text-indigo-700">
            查看最近消息（{candidate.messages.length}）
          </summary>
          <div className="mt-2 space-y-2">
            {candidate.messages.map((message) => (
              <div key={message.id} className="rounded-md border p-2">
                <div className="break-words whitespace-pre-wrap">
                  {messageSummary(message)}
                </div>
                <div className="mt-1 text-muted-foreground">
                  {formatDate(message.occurred_at)} ·{" "}
                  {message.conversation_type === "group" ? "群聊" : "私聊"}
                </div>
              </div>
            ))}
          </div>
        </details>
      </TableCell>
      <TableCell className="align-top whitespace-nowrap text-muted-foreground">
        {formatDate(latest?.occurred_at || candidate.last_seen_at)}
      </TableCell>
      <TableCell className="max-w-64 align-top">
        {candidate.group_ids.length ? (
          candidate.group_ids.map((id) => (
            <div key={id} className="font-mono text-xs break-all">
              {id}
            </div>
          ))
        ) : (
          <span className="text-sm text-muted-foreground">私聊，无群 ID</span>
        )}
      </TableCell>
      <TableCell className="max-w-60 align-top">
        <div className="text-sm">
          {candidate.robot_codes.join("、") || "未提供机器人标识"}
        </div>
        <div className="mt-1 text-xs text-muted-foreground">
          {candidate.connector_names.join("、") || "连接器名称不可用"}
        </div>
      </TableCell>
      <TableCell className="pr-4 text-right align-top">
        <Link
          className={buttonVariants({ variant: "outline", size: "sm" })}
          to={actionHref}
        >
          {candidate.identity_state === "restore_required"
            ? "前往原人员恢复"
            : "去绑定"}
        </Link>
      </TableCell>
    </TableRow>
  )
}

function messageSummary(message: DingTalkIdentityCandidate["latest_message"]) {
  if (!message) return "没有可展示的消息摘要"
  if (message.safe_text) return message.safe_text
  if (message.attachment_name) {
    return `附件：${message.attachment_name}（${message.attachment_type || "文件"}）`
  }
  return `消息类型：${message.message_kind}`
}
