import { useRef, useState, type ReactNode } from "react"
import { Dialog } from "@base-ui/react/dialog"
import { XIcon } from "lucide-react"

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
import {
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { cn } from "@/lib/utils"

type FormDialogProps = {
  title: string
  description?: ReactNode
  children: ReactNode
  onClose: () => void
  pending: boolean
  dirty?: boolean
  wide?: boolean
  asSheet?: boolean
}

export function FormDialog({
  title,
  description,
  children,
  onClose,
  pending,
  dirty = false,
  wide,
  asSheet,
}: FormDialogProps) {
  const [touched, setTouched] = useState(false)
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const continueButton = useRef<HTMLButtonElement>(null)

  return (
    <Dialog.Root
      open
      disablePointerDismissal={!asSheet}
      onOpenChange={(open, details) => {
        if (open) return
        if (pending || (!asSheet && (touched || dirty))) {
          details.cancel()
          if (!pending) setConfirmDiscard(true)
          return
        }
        onClose()
      }}
    >
      {asSheet ? (
        <SheetContent className="overflow-y-auto">
          <SheetHeader>
            <SheetTitle>{title}</SheetTitle>
            {description && <SheetDescription>{description}</SheetDescription>}
          </SheetHeader>
          <div className="px-4 pb-4">{children}</div>
        </SheetContent>
      ) : (
        <Dialog.Portal>
          <Dialog.Backdrop
            data-slot="form-dialog-backdrop"
            className="fixed inset-0 z-50 bg-black/35 supports-backdrop-filter:backdrop-blur-xs"
          />
          <Dialog.Popup
            data-slot="form-dialog"
            onChangeCapture={() => setTouched(true)}
            className={cn(
              "fixed top-1/2 left-1/2 z-50 flex max-h-[calc(100dvh-1.5rem)] w-[calc(100%-1.5rem)] max-w-2xl -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-xl border bg-popover text-sm text-popover-foreground shadow-xl outline-none",
              wide && "max-w-4xl"
            )}
          >
            <header className="shrink-0 border-b px-4 py-4 pr-14 sm:px-6 sm:pr-14">
              <Dialog.Title className="text-lg font-semibold">
                {title}
              </Dialog.Title>
              {description && (
                <Dialog.Description className="mt-1 text-muted-foreground">
                  {description}
                </Dialog.Description>
              )}
            </header>
            <div className="min-h-0 overflow-y-auto overscroll-contain p-4 sm:p-6">
              {children}
            </div>
            <Dialog.Close
              disabled={pending}
              render={
                <Button
                  variant="ghost"
                  size="icon"
                  className="absolute top-3 right-3"
                />
              }
              aria-label="关闭"
            >
              <XIcon />
            </Dialog.Close>
          </Dialog.Popup>
        </Dialog.Portal>
      )}
      {confirmDiscard && (
        <AlertDialog
          open
          onOpenChange={(open) => {
            if (!open) setConfirmDiscard(false)
          }}
        >
          <AlertDialogContent initialFocus={continueButton}>
            <AlertDialogHeader>
              <AlertDialogTitle>放弃本次填写？</AlertDialogTitle>
              <AlertDialogDescription>
                关闭后，已填写的内容将丢失。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel ref={continueButton}>
                继续填写
              </AlertDialogCancel>
              <AlertDialogAction variant="destructive" onClick={onClose}>
                放弃填写
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </Dialog.Root>
  )
}

export function FormDialogCancel({
  disabled,
  children = "取消",
}: {
  disabled?: boolean
  children?: ReactNode
}) {
  return (
    <Dialog.Close
      disabled={disabled}
      render={<Button type="button" variant="outline" />}
    >
      {children}
    </Dialog.Close>
  )
}
