import { LoaderCircleIcon } from "lucide-react"
import { Link } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  ListPage,
  ExpandableListRow,
  ListSearch,
  ListResults,
  ListEmpty,
  ListPager,
  RefreshList,
} from "@/shared/presentation/list-page"
import { useListNavigation } from "@/shared/presentation/list-navigation"
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
  const list = useListNavigation()
  const search = list.params.get("q") ?? ""
  const rawScope = list.params.get("scope")
  const scope = ["direct", "group", "both"].includes(rawScope ?? "")
    ? (rawScope as ConversationScope)
    : "all"
  const query = useDingTalkIdentityCandidates({
    search,
    conversationScope: scope,
    cursor: list.params.get("after") ?? "",
    limit: PAGE_SIZE,
  })
  const filtered = Boolean(search || scope !== "all")
  const clear = () => list.filter({ q: "", scope: "" })
  return (
    <ListPage
      title="未绑定钉钉用户"
      actions={
        <RefreshList
          refresh={() => void query.refetch()}
          busy={query.isFetching}
        />
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <ListSearch
          label="搜索未绑定钉钉用户"
          placeholder="搜索用户名、用户 ID、群或机器人"
          value={search}
          onCommit={(q) => list.filter({ q })}
        />
        <select
          aria-label="会话类型"
          className="h-8 rounded-lg border bg-background px-2 text-sm"
          value={scope}
          onChange={(e) =>
            list.filter({
              scope: e.target.value === "all" ? "" : e.target.value,
            })
          }
        >
          <option value="all">全部会话</option>
          <option value="direct">仅私聊</option>
          <option value="group">仅群聊</option>
          <option value="both">私聊和群聊均出现</option>
        </select>
        {filtered && (
          <Button variant="ghost" size="sm" onClick={clear}>
            重置
          </Button>
        )}
        <span className="ml-auto text-xs text-muted-foreground">
          最近 30 天
        </span>
      </div>
      {query.isLoading ? (
        <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-muted-foreground">
          <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
          正在加载待绑定用户…
        </div>
      ) : null}
      {query.isError ? <RequestError error={query.error} /> : null}
      {query.data ? (
        <ListResults>
          {query.data.candidates.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-4">钉钉用户</TableHead>
                  <TableHead>会话</TableHead>
                  <TableHead className="hidden sm:table-cell">
                    最近活动
                  </TableHead>
                  <TableHead className="hidden md:table-cell">
                    所属机器人
                  </TableHead>
                  <TableHead className="pr-4 text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {query.data.candidates.map((candidate) => (
                  <CandidateRow
                    key={candidate.id}
                    candidate={candidate}
                    origin={list.detailState}
                  />
                ))}
              </TableBody>
            </Table>
          ) : (
            <ListEmpty
              title={
                filtered ? "没有符合条件的用户" : "当前没有待绑定的钉钉用户。"
              }
              clear={filtered ? clear : undefined}
            />
          )}
          <ListPager
            count={`本页 ${query.data.candidates.length} 人`}
            page={list.page}
            previous={list.previous}
            previousLabel={list.previousLabel}
            next={
              query.data.has_more && query.data.next_cursor
                ? () => list.next(query.data.next_cursor!)
                : undefined
            }
          />
        </ListResults>
      ) : null}
    </ListPage>
  )
}

function CandidateRow({
  candidate,
  origin,
}: {
  candidate: DingTalkIdentityCandidate
  origin: ReturnType<typeof useListNavigation>["detailState"]
}) {
  const latest = candidate.latest_message
  const historical = candidate.historical_identity
  const actionHref =
    candidate.identity_state === "restore_required" && historical
      ? `/users/${encodeURIComponent(historical.user_id)}?candidate=${encodeURIComponent(candidate.id)}`
      : `/users?candidate=${encodeURIComponent(candidate.id)}`

  const scopeLabel = { direct: "私聊", group: "群聊", both: "私聊 + 群聊" }[
    candidate.conversation_scope
  ]
  const lastSeen = formatDate(latest?.occurred_at || candidate.last_seen_at)
  return (
    <ExpandableListRow
      columns={5}
      name={candidate.display_name || "未提供钉钉用户名"}
      meta={candidate.external_subject_id}
      cells={
        <>
          <TableCell>
            <Badge variant="outline">{scopeLabel}</Badge>
          </TableCell>
          <TableCell className="hidden sm:table-cell">{lastSeen}</TableCell>
          <TableCell className="hidden md:table-cell">
            {candidate.robot_codes.join("、") || "—"}
          </TableCell>
          <TableCell className="pr-4 text-right">
            <Link
              className={buttonVariants({ variant: "outline", size: "sm" })}
              to={actionHref}
              state={{ discoveryOrigin: origin }}
            >
              {candidate.identity_state === "restore_required"
                ? "前往原人员恢复"
                : "去绑定"}
            </Link>
          </TableCell>
        </>
      }
    >
      <div className="grid gap-3 p-2 text-sm">
        <div>
          <p className="font-medium">
            {candidate.enterprise_name || "企业名称不可用"}
          </p>
          <p className="text-xs break-all text-muted-foreground">
            Corp ID {candidate.corp_id} ·{" "}
            {candidate.connector_names.join("、") || "连接器名称不可用"}
          </p>
        </div>
        <p className="md:hidden">
          机器人 {candidate.robot_codes.join("、") || "—"}
        </p>
        <p className="sm:hidden">最近活动 {lastSeen}</p>
        {candidate.group_ids.length > 0 && (
          <p className="break-all">
            群 ID{" "}
            {candidate.group_ids.map((id) => (
              <span key={id} className="mr-2 font-mono">
                {id}
              </span>
            ))}
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          {candidate.observation_count} 条观测
        </p>
        {latest && (
          <div>
            <p className="font-medium">最近消息</p>
            <p className="break-words whitespace-pre-wrap">
              {messageSummary(latest)}
            </p>
            {latest.text_truncated && <small>消息已截断</small>}
          </div>
        )}
        {candidate.messages.length > 0 && (
          <details>
            <summary className="cursor-pointer text-sm">
              查看最近消息（{candidate.messages.length}）
            </summary>
            <ul className="mt-2 space-y-2">
              {candidate.messages.map((message) => (
                <li className="rounded-lg border p-2" key={message.id}>
                  <p className="break-words whitespace-pre-wrap">
                    {messageSummary(message)}
                  </p>
                  <small className="text-muted-foreground">
                    {formatDate(message.occurred_at)} ·{" "}
                    {message.conversation_type === "group" ? "群聊" : "私聊"}
                  </small>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </ExpandableListRow>
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
