import { useMemo, useState } from "react"
import { File, Folder } from "lucide-react"

export function DirectoryChoices({
  directories,
  files,
  selected,
  onChange,
  parentPath = "",
  renderDirectory,
}: {
  directories: string[]
  files: string[]
  selected: string[]
  onChange: (value: string[]) => void
  parentPath?: string
  renderDirectory?: (path: string) => React.ReactNode
}) {
  const [expanded, setExpanded] = useState<string[]>([])
  const [visited, setVisited] = useState<string[]>([])
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
                {renderDirectory ||
                children.has(path) ||
                fileChildren.has(path) ? (
                  <button
                    type="button"
                    className="flex h-5 w-4 items-center justify-center"
                    aria-label={`展开 ${path}`}
                    aria-expanded={expanded.includes(path)}
                    onClick={() => {
                      setVisited((prior) =>
                        prior.includes(path) ? prior : [...prior, path]
                      )
                      setExpanded(
                        expanded.includes(path)
                          ? expanded.filter((p) => p !== path)
                          : [...expanded, path]
                      )
                    }}
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
              {renderDirectory
                ? visited.includes(path) && (
                    <div hidden={!expanded.includes(path)}>
                      {renderDirectory(path)}
                    </div>
                  )
                : expanded.includes(path) && rows(path)}
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
  if (parentPath) return rows(parentPath)
  return (
    <div
      className="max-h-96 overflow-auto rounded border p-3"
      aria-label="SVN 目录多选"
    >
      {rows("")}
    </div>
  )
}
