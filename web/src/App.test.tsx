import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { App } from './App'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

test('never renders protected content before session revalidation', async () => {
  let finish!: (value: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { finish = resolve })))
  render(<App />)
  expect(screen.queryByTestId('protected-content')).toBeNull()
  finish(new Response('{}', {status:401,headers:{'Content-Type':'application/json'}}))
  expect(await screen.findByText('Sign in to continue.')).toBeTruthy()
})

test('revalidates an existing session and signs out with csrf', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({user:{user_id:3,username:'viewer',full_name:'Viewer',role:'viewer'},csrf_token:'csrf'}),{status:200,headers:{'Content-Type':'application/json'}}))
    .mockResolvedValueOnce(new Response(null,{status:204}))
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  expect(await screen.findByTestId('protected-content')).toBeTruthy()
  fireEvent.click(screen.getByText('Sign out'))
  await waitFor(() => expect(screen.getByText('Sign in to continue.')).toBeTruthy())
  expect(fetchMock).toHaveBeenLastCalledWith('/api/auth/logout',{method:'POST',headers:{'X-CSRF-Token':'csrf'}})
})
