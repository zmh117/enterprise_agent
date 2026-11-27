import { Button } from "@/components/ui/button"

type McpToolOption = {
  identifier: string
  server_code?: string
  display_name_zh?: string
  ariaLabel?: string
  description: string
  read_only: boolean
  confirmation_policy: string
  resource_kind?: string
  required?: boolean
}

export function McpToolGroups({
  tools,
  selected,
  onChange,
}: {
  tools: McpToolOption[]
  selected: Iterable<string>
  onChange: (identifiers: string[]) => void
}) {
  const selection = new Set(selected)
  const groups = new Map<string, McpToolOption[]>()
  for (const tool of tools) {
    const server = tool.server_code ?? "未标明服务"
    const group = groups.get(server)
    if (group) group.push(tool)
    else groups.set(server, [tool])
  }

  function setChecked(items: McpToolOption[], checked: boolean) {
    const next = new Set(selection)
    for (const tool of items) {
      if (tool.required) continue
      if (checked) next.add(tool.identifier)
      else next.delete(tool.identifier)
    }
    onChange([...next])
  }

  const services = [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))
  return (
    <div className="space-y-4">
      {services.map(([server, items]) => {
        const count = items.filter((tool) =>
          selection.has(tool.identifier)
        ).length
        const allSelected = count === items.length
        const action = allSelected ? "取消全选" : "全选"
        return (
          <fieldset
            key={server}
            className="min-w-0 overflow-hidden rounded-lg border"
          >
            <legend className="sr-only">{server}</legend>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 bg-muted/50 px-3 py-1.5">
              <span
                aria-hidden="true"
                className="min-w-0 font-mono text-sm font-semibold break-all"
              >
                {server}
              </span>
              <span className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">
                已选 {count}/{items.length}
              </span>
              {items[0].server_code && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="ml-auto"
                  aria-label={`${action} ${server}`}
                  disabled={items.every((tool) => tool.required)}
                  onClick={() => setChecked(items, !allSelected)}
                >
                  {action}
                </Button>
              )}
            </div>
            <div className="grid md:grid-cols-2">
              {items.map((tool) => (
                <label
                  key={tool.identifier}
                  className="flex min-h-12 min-w-0 cursor-pointer items-start gap-3 border-t bg-background px-3 py-2.5 hover:bg-muted/40 has-disabled:cursor-default"
                >
                  <input
                    type="checkbox"
                    className="mt-1 size-4 shrink-0 accent-primary"
                    aria-label={tool.ariaLabel ?? tool.identifier}
                    checked={selection.has(tool.identifier)}
                    disabled={tool.required}
                    onChange={(event) =>
                      setChecked([tool], event.target.checked)
                    }
                  />
                  <span className="min-w-0 space-y-1">
                    <span className="block text-sm font-medium">
                      {tool.display_name_zh && (
                        <>
                          <span>{tool.display_name_zh}</span>{" "}
                        </>
                      )}
                      <span className="font-mono text-xs break-all">
                        {tool.identifier}
                      </span>
                    </span>
                    {tool.description.trim() && (
                      <span className="block text-xs leading-5 text-muted-foreground">
                        {tool.description}
                      </span>
                    )}
                    <span className="block text-xs text-muted-foreground">
                      <span
                        className={
                          tool.read_only
                            ? undefined
                            : "font-medium text-foreground"
                        }
                      >
                        {tool.read_only ? "只读" : "写入"}
                      </span>
                      {tool.confirmation_policy === "external_action_card_v1" &&
                        " · 每次需原用户确认卡片"}
                      {tool.resource_kind &&
                        ` · 解析 ${tool.resource_kind} Resource`}
                      {tool.required && (
                        <span className="text-primary">
                          {" "}
                          · 当前任务文件功能必选
                        </span>
                      )}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
        )
      })}
    </div>
  )
}
