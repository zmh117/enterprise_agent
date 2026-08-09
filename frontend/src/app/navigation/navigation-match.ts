export type NavigationTarget = { href: string }

export function resolveActiveNavigationHref(
  pathname: string,
  items: NavigationTarget[]
) {
  return (
    items
      .filter(
        (item) =>
          pathname === item.href || pathname.startsWith(`${item.href}/`)
      )
      .sort((left, right) => right.href.length - left.href.length)[0]?.href ?? ""
  )
}
