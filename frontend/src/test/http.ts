export function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })
  )
}

export function jsonErrorResponse(status: number, detail: unknown) {
  return jsonResponse({ detail }, status)
}
