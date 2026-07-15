import { FormEvent, useEffect, useState } from 'react'

type User = { user_id:number; username:string; full_name:string; role:string }
type Auth = { user:User; csrf_token:string }

async function json(response: Response): Promise<Auth> {
  if (!response.ok) throw new Error((await response.json()).message || 'Request failed')
  return response.json()
}

export function App() {
  const [auth, setAuth] = useState<Auth|null>(null)
  const [checking, setChecking] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => { fetch('/api/auth/me').then(json).then(setAuth).catch(() => setAuth(null)).finally(() => setChecking(false)) }, [])

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError('')
    const data = new FormData(event.currentTarget)
    try {
      setAuth(await json(await fetch('/api/auth/login', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:data.get('username'),password:data.get('password')})})))
    } catch (e) { setError(e instanceof Error ? e.message : 'Sign in failed') }
  }
  async function logout() {
    if (!auth) return
    const response = await fetch('/api/auth/logout', {method:'POST',headers:{'X-CSRF-Token':auth.csrf_token}})
    if (response.ok) setAuth(null)
  }

  if (checking) return <main aria-live="polite">Checking session…</main>
  if (!auth) return <main><section className="card"><h1>English Class</h1><p>Sign in to continue.</p><form onSubmit={login}><label>Username<input name="username" autoComplete="username" required /></label><label>Password<input name="password" type="password" autoComplete="current-password" required /></label>{error && <p role="alert">{error}</p>}<button>Sign in</button></form></section></main>
  return <main><section className="card"><p>Signed in as</p><h1>{auth.user.full_name}</h1><p>Role: {auth.user.role}</p><div data-testid="protected-content">Protected workspace</div><button onClick={logout}>Sign out</button></section></main>
}
