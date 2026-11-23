import { TableRow, TableCell } from "@/components/ui/table"
import {
  useEffect,
  useEffectEvent,
  useRef,
  useState,
  type ReactNode,
} from "react"
import {
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  RefreshCwIcon,
  SearchIcon,
  XIcon,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

export function ListPage({
  title,
  actions,
  children,
}: {
  title: string
  actions?: ReactNode
  children: ReactNode
}) {
  useEffect(() => {
    const previous = document.title
    document.title = `${title} · Agent 应用平台`
    return () => {
      document.title = previous
    }
  }, [title])
  return (
    <div className="mx-auto grid w-full max-w-[1500px] min-w-0 gap-5 px-4 py-6 sm:px-6 lg:gap-6 lg:px-8 lg:py-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      </header>
      {children}
    </div>
  )
}

export function RefreshList({
  refresh,
  busy,
}: {
  refresh: () => void
  busy: boolean
}) {
  return (
    <Button
      variant="outline"
      size="icon"
      aria-label="刷新"
      title="刷新"
      disabled={busy}
      onClick={refresh}
    >
      <RefreshCwIcon
        aria-hidden="true"
        className={busy ? "animate-spin" : ""}
      />
    </Button>
  )
}

export function ListSearch({
  label,
  placeholder,
  value,
  onCommit,
}: {
  label: string
  placeholder: string
  value: string
  onCommit: (value: string) => void
}) {
  const [draft, setDraft] = useState(value)
  const [previous, setPrevious] = useState(value)
  const [composing, setComposing] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  if (previous !== value) {
    setPrevious(value)
    setDraft(value)
  }
  const commitLatest = useEffectEvent(onCommit)
  useEffect(() => {
    if (composing || draft.trim() === value) return
    const timer = window.setTimeout(() => commitLatest(draft.trim()), 300)
    return () => window.clearTimeout(timer)
  }, [composing, draft, value])
  return (
    <form
      role="search"
      className="relative w-full sm:w-80"
      onSubmit={(e) => {
        e.preventDefault()
        if (!composing && draft.trim() !== value) onCommit(draft.trim())
      }}
    >
      <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        ref={input}
        className="bg-background pr-9 pl-9"
        aria-label={label}
        placeholder={placeholder}
        maxLength={200}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onCompositionStart={() => setComposing(true)}
        onCompositionEnd={() => setComposing(false)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.nativeEvent.isComposing || composing))
            e.preventDefault()
        }}
      />
      {draft && (
        <button
          type="button"
          aria-label={`清除${label}`}
          className="absolute inset-y-0 right-0 px-3 text-muted-foreground hover:text-foreground"
          onClick={() => {
            setDraft("")
            onCommit("")
            input.current?.focus()
          }}
        >
          <XIcon className="size-3.5" />
        </button>
      )}
    </form>
  )
}

export function ListStatusFilter({
  value,
  onChange,
  archived = false,
}: {
  value: string
  onChange: (value: string) => void
  archived?: boolean
}) {
  return (
    <select
      aria-label="状态"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-8 rounded-lg border border-input bg-background px-2 text-sm shadow-xs focus-visible:outline-ring"
    >
      <option value="">全部状态</option>
      <option value="enabled">已启用</option>
      <option value="disabled">已停用</option>
      {archived && <option value="archived">已归档</option>}
    </select>
  )
}

export function ListStatus({
  status,
}: {
  status: "enabled" | "disabled" | "archived"
}) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium">
      <span
        aria-hidden="true"
        className={`size-1.5 rounded-full ${status === "enabled" ? "bg-emerald-600" : "bg-muted-foreground/60"}`}
      />
      {{ enabled: "已启用", disabled: "已停用", archived: "已归档" }[status]}
    </span>
  )
}

export function ListEmpty({
  title,
  clear,
}: {
  title: string
  clear?: () => void
}) {
  return (
    <div
      role="status"
      className="grid justify-items-center gap-2 py-14 text-sm text-muted-foreground"
    >
      <p>{title}</p>
      {clear && (
        <Button variant="link" onClick={clear}>
          清除筛选
        </Button>
      )}
    </div>
  )
}

export function ListPager({
  count,
  page,
  previous,
  next,
  previousLabel = "上一页",
  pages,
}: {
  count: string
  page: number
  previous: () => void
  next?: () => void
  previousLabel?: string
  pages?: number
}) {
  return (
    <nav
      aria-label="列表分页"
      className="flex flex-wrap items-center justify-between gap-2 border-t px-3 py-2.5 text-xs text-muted-foreground sm:px-4"
    >
      <span>{count}</span>
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={previousLabel}
          title={previousLabel}
          disabled={page <= 1}
          onClick={previous}
        >
          <ChevronLeftIcon />
        </Button>
        <span className="tabular-nums">
          第 {page} 页{pages !== undefined && ` / 共 ${Math.max(1, pages)} 页`}
        </span>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="下一页"
          title="下一页"
          disabled={!next}
          onClick={next}
        >
          <ChevronRightIcon />
        </Button>
      </div>
    </nav>
  )
}

export function ListResults({ children }: { children: ReactNode }) {
  return (
    <div className="min-w-0 overflow-hidden rounded-xl border bg-card [&_td]:py-3 max-sm:[&_td]:px-1.5 [&_td:first-child]:pl-4 [&_th]:text-xs [&_th]:text-muted-foreground max-sm:[&_th]:px-1.5 [&_th:first-child]:pl-4 [&_thead]:bg-muted/45">
      {children}
    </div>
  )
}

export function CatalogPager({
  result,
  onPage,
}: {
  result: { page: number; pages: number; total: number }
  onPage: (page: number) => void
}) {
  return (
    <ListPager
      count={`共 ${result.total} 条`}
      page={result.page}
      pages={result.pages}
      previous={() => onPage(result.page - 1)}
      next={
        result.page < result.pages ? () => onPage(result.page + 1) : undefined
      }
    />
  )
}

export function ExpandableListRow({
  name,
  meta,
  cells,
  columns,
  children,
}: {
  name: string
  meta?: string
  cells: ReactNode
  columns: number
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <TableRow>
        <TableCell>
          <button
            type="button"
            aria-expanded={open}
            className="flex max-w-[min(35vw,15rem)] items-center gap-1.5 text-left font-medium hover:underline"
            onClick={() => setOpen(!open)}
          >
            <ChevronDownIcon
              aria-hidden="true"
              className={`size-3.5 shrink-0 text-muted-foreground ${open ? "" : "-rotate-90"}`}
            />
            <span className="truncate">{name}</span>
          </button>
          {meta && (
            <span className="block max-w-[min(35vw,15rem)] truncate pl-5 text-xs text-muted-foreground">
              {meta}
            </span>
          )}
        </TableCell>
        {cells}
      </TableRow>
      {open && (
        <TableRow className="hover:bg-transparent">
          <TableCell
            colSpan={columns}
            className="bg-muted/20 whitespace-normal"
          >
            {children}
          </TableCell>
        </TableRow>
      )}
    </>
  )
}
