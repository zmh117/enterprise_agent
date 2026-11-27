import { useRef, useState } from "react"
import {
  useMutation,
  useQueryClient,
  type QueryKey,
} from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"

export function ArchiveAction({
  name,
  archive,
  queryKey,
}: {
  name: string
  archive: () => Promise<unknown>
  queryKey: QueryKey
}) {
  return (
    <ConfirmListAction
      label="归档"
      name={name}
      action={archive}
      queryKey={queryKey}
      description="归档后仅可查看，可在列表中筛选「已归档」查找。"
    />
  )
}

export function ConfirmListAction({
  label,
  name,
  action,
  queryKey,
  description,
}: {
  label: string
  name: string
  action: () => Promise<unknown>
  queryKey: QueryKey
  description: string
}) {
  const [open, setOpen] = useState(false)
  const cancel = useRef<HTMLButtonElement>(null)
  const client = useQueryClient()
  const mutation = useMutation({
    mutationFn: action,
    onSuccess: () => {
      setOpen(false)
      return client.invalidateQueries({ queryKey })
    },
  })
  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => {
          mutation.reset()
          setOpen(true)
        }}
      >
        {label}
      </Button>
      <AlertDialog
        open={open}
        onOpenChange={(next) => {
          if (!mutation.isPending) setOpen(next)
        }}
      >
        <AlertDialogContent initialFocus={cancel}>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {label}「{name}」？
            </AlertDialogTitle>
            <AlertDialogDescription>{description}</AlertDialogDescription>
          </AlertDialogHeader>
          {mutation.error && (
            <p role="alert" className="text-sm text-destructive">
              {mutation.error.message}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel ref={cancel} disabled={mutation.isPending}>
              取消
            </AlertDialogCancel>
            <AlertDialogAction
              variant={label === "启用" ? "default" : "destructive"}
              disabled={mutation.isPending}
              onClick={() => mutation.mutate()}
            >
              确认{label}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
