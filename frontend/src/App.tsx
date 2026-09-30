import { useEffect, useState } from 'react'
import { AuthGate } from './components/AuthGate'
import { Dashboard } from './components/Dashboard'
import { getSession, signOut } from './lib/api'

function App() {
  const [user, setUser] = useState<{ email: string; name?: string } | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    // restore an existing approved session (cookie) on reload
    getSession().then((s) => {
      if (s) setUser({ email: s.email, name: s.name || undefined })
      setChecking(false)
    })
    const onUnauthorized = () => setUser(null)
    window.addEventListener('tcc:unauthorized', onUnauthorized)
    return () => window.removeEventListener('tcc:unauthorized', onUnauthorized)
  }, [])

  if (checking) {
    return <div className="min-h-screen bg-obsidian-bg" />
  }

  if (!user) {
    return <AuthGate onLogin={(email, name) => setUser({ email, name })} />
  }

  return (
    <Dashboard
      userEmail={user.email}
      userName={user.name}
      onLogout={() => { signOut(); setUser(null) }}
    />
  )
}

export default App
