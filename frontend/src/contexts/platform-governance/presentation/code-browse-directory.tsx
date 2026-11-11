import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { z } from "zod"
import { apiRequest } from "@/shared/api/api-client"
import { createRequestKey } from "@/lib/request-key"
import { Button } from "@/components/ui/button"
import { codeOperationSchema } from "../application/code-checkout-query"
import { KnowledgeError } from "./knowledge-resource-ui"
import { DirectoryChoices } from "./code-directory-choices"
import { codeCheckoutErrors } from "./code-checkout-errors"

type Props = {
  resourceId: string
  browseId: string
  path: string
  revision: number
  selected: string[]
  onChange: (paths: string[]) => void
}

export function CodeBrowseDirectory(props: Props) {
  const { resourceId, browseId, path, revision, selected, onChange } = props
  const [requestKey, setRequestKey] = useState(createRequestKey)
  const submission = useQuery({
    queryKey: ["code-directory-submit", resourceId, browseId, path, requestKey],
    retry: false,
    staleTime: Infinity,
    queryFn: async () =>
      z
        .object({ id: z.string() })
        .parse(
          await apiRequest(
            `/api/platform/knowledge/code/resources/${encodeURIComponent(resourceId)}/browse-children`,
            {
              method: "POST",
              body: { browse_job_id: browseId, path, request_key: requestKey },
            }
          )
        ),
  })
  const operation = useQuery({
    queryKey: ["code-directory-result", submission.data?.id],
    enabled: Boolean(submission.data),
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchInterval: (query) =>
      query.state.status === "error" ||
      ["succeeded", "failed", "interrupted", "cancelled"].includes(
        query.state.data?.state ?? ""
      )
        ? false
        : 1000,
    queryFn: async () =>
      codeOperationSchema.parse(
        await apiRequest(
          `/api/platform/knowledge/code/operations/${encodeURIComponent(submission.data!.id)}`
        )
      ),
  })
  const data = operation.data
  const terminalError =
    data?.error_code ||
    (data?.result_expired ? "CODE_RESULT_EXPIRED" : undefined)
  const invalid =
    data?.state === "succeeded" &&
    (data.result.revision !== revision || data.result.directory_path !== path)
  const failed =
    submission.isError ||
    operation.isError ||
    terminalError ||
    invalid ||
    (data && ["failed", "interrupted", "cancelled"].includes(data.state))
  if (failed)
    return (
      <div className="pl-4 text-sm" role="alert">
        <KnowledgeError error={submission.error || operation.error} />
        <p>
          {terminalError
            ? (codeCheckoutErrors[terminalError] ?? "子目录加载失败，请重试。")
            : "子目录加载失败，请重试或重新浏览仓库。"}
        </p>
        <Button
          type="button"
          variant="outline"
          onClick={() => setRequestKey(createRequestKey())}
          aria-label={`重试加载 ${path}`}
        >
          重试加载
        </Button>
      </div>
    )
  if (data?.state !== "succeeded")
    return (
      <p role="status" className="pl-4 text-sm">
        正在加载 {path}…
      </p>
    )
  if (!data.result.directories?.length && !data.result.files?.length)
    return <p className="pl-4 text-sm text-muted-foreground">此目录为空。</p>
  return (
    <DirectoryChoices
      parentPath={path}
      directories={data.result.directories ?? []}
      files={data.result.files ?? []}
      selected={selected}
      onChange={onChange}
      renderDirectory={(child) => (
        <CodeBrowseDirectory {...props} key={child} path={child} />
      )}
    />
  )
}
