import { PlatformShell } from "@/app/shell/platform-shell"
import { DashboardPage } from "@/contexts/overview/presentation/dashboard-page"

export function App() {
  return (
    <PlatformShell>
      <DashboardPage />
    </PlatformShell>
  )
}

export default App
