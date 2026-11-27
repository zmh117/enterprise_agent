import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import { expect, it, vi } from "vitest"
import { ArchiveAction } from "./archive-action"

it("默认聚焦取消，归档被拒绝时保留确认框，成功后刷新列表", async () => {
  const client = new QueryClient()
  const refresh = vi.spyOn(client, "invalidateQueries")
  const archive = vi
    .fn()
    .mockRejectedValueOnce(new Error("仍有活动引用"))
    .mockResolvedValueOnce({})
  render(
    <QueryClientProvider client={client}>
      <ArchiveAction
        name="合成应用"
        archive={archive}
        queryKey={["applications"]}
      />
    </QueryClientProvider>
  )
  const open = () =>
    fireEvent.click(screen.getByRole("button", { name: "归档" }))
  open()
  const cancel = await screen.findByRole("button", { name: "取消" })
  await waitFor(() => expect(cancel).toHaveFocus())
  fireEvent.click(cancel)
  expect(archive).not.toHaveBeenCalled()
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull())
  open()
  const dialog = within(await screen.findByRole("alertdialog"))
  fireEvent.click(dialog.getByRole("button", { name: "确认归档" }))
  expect(await dialog.findByRole("alert")).toHaveTextContent("仍有活动引用")
  expect(refresh).not.toHaveBeenCalled()
  fireEvent.click(dialog.getByRole("button", { name: "确认归档" }))
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull())
  expect(refresh).toHaveBeenCalledWith({ queryKey: ["applications"] })
})
