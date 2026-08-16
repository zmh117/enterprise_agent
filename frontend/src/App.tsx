import { RouterProvider } from "react-router-dom"

import { AppErrorBoundary } from "@/app/errors/app-error-boundary"
import { appRouter } from "@/app/router/app-router"

export function App() {
  return (
    <AppErrorBoundary>
      <RouterProvider router={appRouter} />
    </AppErrorBoundary>
  )
}

export default App
