import { useState } from 'react'
import { AuthGate } from './components/AuthGate'
import { Dashboard } from './components/Dashboard'

function App() {
  const [user, setUser] = useState<{ email: string; name?: string } | null>(null)

  if (!user) {
    return <AuthGate onLogin={(email, name) => setUser({ email, name })} />
  }

  return <Dashboard userEmail={user.email} userName={user.name} onLogout={() => setUser(null)} />
}

export default App
