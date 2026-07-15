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
    .mockResolvedValueOnce(new Response(JSON.stringify({summary:{active_employees:1,active_learners:0,open_course_runs:0,operational_issues:0,high_issues:0,open_quality_issues:0},hr_home:null}),{status:200,headers:{'Content-Type':'application/json'}}))
    .mockResolvedValueOnce(new Response(null,{status:204}))
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  expect(await screen.findByTestId('protected-content')).toBeTruthy()
  fireEvent.click(screen.getByText('Sign out'))
  await waitFor(() => expect(screen.getByText('Sign in to continue.')).toBeTruthy())
  expect(fetchMock).toHaveBeenLastCalledWith('/api/auth/logout',{method:'POST',headers:{'X-CSRF-Token':'csrf'}})
})

test('admin navigates from HR home through learner search and detail', async () => {
  const jsonResponse = (body: unknown) => new Response(JSON.stringify(body), {status:200,headers:{'Content-Type':'application/json'}})
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url === '/api/auth/me') return jsonResponse({user:{user_id:1,username:'admin',full_name:'HR Admin',role:'admin'},csrf_token:'csrf'})
    if (url === '/api/dashboard') return jsonResponse({summary:{active_employees:12,active_learners:4,open_course_runs:2,operational_issues:1,high_issues:0,open_quality_issues:1},hr_home:{active_people:12,current_learners:4,open_classes:2,review_items:1,urgent_items:0,follow_ups:1}})
    if (url.startsWith('/api/learners?')) return jsonResponse({items:[{employee_id:41,emp_code:'E041',full_name:'Directory Alpha',employment_status:'active',business_unit_name:'People',job_role_name:'Specialist',class_code:'A1',course_name:'Pytest Course',course_code:'PT',enrollment_status:'active',attendance_ratio:0.75,entrance_level:'Entrance',pic:'Team'}],page:1,page_size:20,total:1,sort:'full_name_asc_emp_code_asc'})
    if (url === '/api/learners/41') return jsonResponse({learner:{employee_id:41,emp_code:'E041',full_name:'Directory Alpha',employment_status:'active',business_unit_id:1,business_unit_name:'People',job_role_id:1,job_role_name:'Specialist',placement_id:1,entrance_level_id:1,entrance_level:'Entrance',active_enrollment_id:51,active_course_run_id:2,active_cohort_id:3,active_class_code:'A1',active_course_name:'Pytest Course',active_membership_id:4,membership_cohort_id:3,membership_class_code:'A1',latest_enrollment_status:'active',latest_class_code:'A1',latest_course_name:'Pytest Course',membership_count:1,lifecycle:'active'},course_history:[{start_date:'2026-08-01',class_code:'A1',course_name:'Pytest Course',status:'active',start_session_number:1,attendance_ratio:0.75,final_level:null,passed:null}],audit_summary:[{created_at:'2026-08-01T00:00:00Z',actor_username:'admin',action:'learner.onboard'}]})
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<App />)
  expect(await screen.findByText('HR home')).toBeTruthy()
  expect(screen.getByText('12')).toBeTruthy()
  fireEvent.click(screen.getByRole('button',{name:'Learners'}))
  fireEvent.change(await screen.findByLabelText('Search by employee code or name'), {target:{value:'Directory'}})
  fireEvent.click(screen.getByRole('button',{name:'Search'}))
  fireEvent.click(await screen.findByRole('button',{name:/Directory Alpha/}))
  expect(await screen.findByRole('heading',{name:'Directory Alpha'})).toBeTruthy()
  expect(screen.getByText('Course history')).toBeTruthy()
  expect(screen.getAllByText('Pytest Course').length).toBeGreaterThan(0)
  expect(screen.getByText('learner.onboard')).toBeTruthy()
})
