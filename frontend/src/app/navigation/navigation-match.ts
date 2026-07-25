import type { NavigationItem } from "@/mocks/dashboard"

export function resolveActiveNavigationHref(
  pathname: string,
  items: NavigationItem[]
) {
  return (
    items
      .filter((item) => {
        if (!item.href) return false
        if (item.href === "/") return pathname === "/"
        return pathname === item.href || pathname.startsWith(`${item.href}/`)
      })
      .sort(
        (left, right) => (right.href?.length ?? 0) - (left.href?.length ?? 0)
      )[0]?.href ?? ""
  )
}
