import { useState } from 'react'
import { AuthGate } from './components/AuthGate'
import { Dashboard } from './components/Dashboard'

function App() {
  const [userEmail, setUserEmail] = useState<string | null>(null)

  if (!userEmail) {
    return <AuthGate onLogin={setUserEmail} />
  }

  return <Dashboard userEmail={userEmail} onLogout={() => setUserEmail(null)} />
}

export default App
