import { useLayoutEffect, useRef } from "react"
import { useLocation, useSearchParams } from "react-router-dom"

export function useListNavigation() {
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  // Multiple debounced fields can finish before the router commits the next location.
  const latestParams = useRef(params)
  useLayoutEffect(() => {
    latestParams.current = params
  }, [params])
  const rawPage = Number(params.get("page"))
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1
  const trail: string[] = location.state?.pageTrail ?? []

  function update(
    values: Record<string, string>,
    pageTrail: string[] = [],
    replace = true
  ) {
    const next = new URLSearchParams(latestParams.current)
    for (const [name, value] of Object.entries(values)) {
      if (value) next.set(name, value)
      else next.delete(name)
    }
    latestParams.current = next
    setParams(next, { replace, state: { ...location.state, pageTrail } })
  }

  return {
    params,
    page,
    detailState: {
      discoveryOrigin: location.state?.discoveryOrigin,
      listSearch: location.search,
      pageTrail: trail,
    },
    filter: (values: Record<string, string>) =>
      update({ after: "", page: "", ...values }),
    numberedPage: (value: number, key = "page") =>
      update({ [key]: value > 1 ? String(value) : "" }, [], false),
    next: (after: string) =>
      update(
        { after, page: String(page + 1) },
        [...trail, params.get("after") ?? ""],
        false
      ),
    previous: () =>
      update(
        {
          after: trail.at(-1) ?? "",
          page: trail.length && page > 2 ? String(page - 1) : "",
        },
        trail.slice(0, -1),
        false
      ),
    previousLabel: !trail.length && page > 2 ? "返回首页" : "上一页",
  }
}

export function useListReturn(pathname: string) {
  const { state } = useLocation()
  return {
    to: { pathname, search: state?.listSearch ?? "" },
    state: {
      discoveryOrigin: state?.discoveryOrigin,
      pageTrail: state?.pageTrail ?? [],
    },
  }
}

export const LIST_PAGE_SIZE = 20

export function catalogPage<T>(rows: T[], requested: number) {
  const pages = Math.max(1, Math.ceil(rows.length / LIST_PAGE_SIZE))
  const page = Math.min(requested, pages)
  const start = (page - 1) * LIST_PAGE_SIZE
  return {
    rows: rows.slice(start, start + LIST_PAGE_SIZE),
    page,
    pages,
    total: rows.length,
  }
}

export function matchesListSearch(
  search: string,
  ...values: (string | null | undefined)[]
) {
  const term = search.trim().toLowerCase()
  return !term || values.some((value) => value?.toLowerCase().includes(term))
}

export function useDiscoveryReturn() {
  const origin = useLocation().state?.discoveryOrigin
  return {
    to: {
      pathname: "/users/dingtalk-discovery",
      search: origin?.listSearch ?? "",
    },
    state: { pageTrail: origin?.pageTrail ?? [] },
  }
}
