import { FormEvent, useEffect, useState } from 'react'
import { apiJson, type Auth } from './api/client'
import { Dashboard } from './features/dashboard/Dashboard'
import { LearnerDirectory } from './features/learners/LearnerDirectory'

type View = 'home' | 'learners'

export function App() {
  const [auth, setAuth] = useState<Auth|null>(null)
  const [checking, setChecking] = useState(true)
  const [error, setError] = useState('')
  const [view, setView] = useState<View>('home')
  const [dashboardRefreshToken, setDashboardRefreshToken] = useState(0)
  useEffect(() => { apiJson<Auth>('/api/auth/me').then(setAuth).catch(() => setAuth(null)).finally(() => setChecking(false)) }, [])

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError('')
    const data = new FormData(event.currentTarget)
    try {
      setAuth(await apiJson<Auth>('/api/auth/login', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:data.get('username'),password:data.get('password')})}))
    } catch (error) { setError(error instanceof Error ? error.message : 'Sign in failed') }
  }
  async function logout() {
    if (!auth) return
    const response = await fetch('/api/auth/logout', {method:'POST',headers:{'X-CSRF-Token':auth.csrf_token}})
    if (response.ok) { setAuth(null); setView('home') }
  }

  if (checking) return <main className="centered" aria-live="polite">Checking session…</main>
  if (!auth) return <main className="centered"><section className="login-card"><h1>English Class</h1><p>Sign in to continue.</p><form onSubmit={login}><label>Username<input name="username" autoComplete="username" required /></label><label>Password<input name="password" type="password" autoComplete="current-password" required /></label>{error && <p role="alert">{error}</p>}<button>Sign in</button></form></section></main>

  const canAccessHr = auth.user.role === 'admin' || auth.user.role === 'editor'
  return <div className="app-shell" data-testid="protected-content">
    <header><div><span className="brand-mark">EC</span><strong>English Class</strong></div><div className="user-menu"><span>{auth.user.full_name}<small>{auth.user.role}</small></span><button className="secondary" onClick={logout}>Sign out</button></div></header>
    <div className="app-body"><nav aria-label="Main navigation"><button className={view==='home'?'active':''} onClick={() => setView('home')}>Home</button>{canAccessHr && <button className={view==='learners'?'active':''} onClick={() => setView('learners')}>Learners</button>}</nav>
      <main className="workspace">{view === 'learners' && canAccessHr
        ? <LearnerDirectory csrfToken={auth.csrf_token} onProfileSaved={() => setDashboardRefreshToken(value => value + 1)} />
        : <Dashboard canAccessHr={canAccessHr} refreshToken={dashboardRefreshToken} />}</main>
    </div>
  </div>
}
