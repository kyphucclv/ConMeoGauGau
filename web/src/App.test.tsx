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

test('admin navigates, edits a profile, and refetches only affected reads', async () => {
  const jsonResponse = (body: unknown) => new Response(JSON.stringify(body), {status:200,headers:{'Content-Type':'application/json'}})
  let saved = false
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url === '/api/auth/me') return jsonResponse({user:{user_id:1,username:'admin',full_name:'HR Admin',role:'admin'},csrf_token:'csrf'})
    if (url === '/api/dashboard') return jsonResponse({summary:{active_employees:12,active_learners:4,open_course_runs:2,operational_issues:1,high_issues:0,open_quality_issues:1},hr_home:{active_people:12,current_learners:4,open_classes:2,review_items:1,urgent_items:0,follow_ups:1}})
    if (url.startsWith('/api/learners?')) return jsonResponse({items:[{employee_id:41,emp_code:'E041',full_name:'Directory Alpha',employment_status:'active',business_unit_name:'People',job_role_name:'Specialist',class_code:'A1',course_name:'Pytest Course',course_code:'PT',enrollment_status:'active',attendance_ratio:0.75,entrance_level:'Entrance',pic:'Team'}],page:1,page_size:20,total:1,sort:'full_name_asc_emp_code_asc'})
    if (url === '/api/learners/profile-options') return jsonResponse({business_units:[{id:1,name:'People'}],job_roles:[{id:1,name:'Specialist'}]})
    if (url === '/api/learners/41/profile') {
      expect(init).toMatchObject({method:'PATCH',headers:{'Content-Type':'application/json','X-CSRF-Token':'csrf'}})
      saved = true
      return jsonResponse({employee_id:41,org_history_action:'unchanged'})
    }
    if (url === '/api/learners/41') return jsonResponse({learner:{employee_id:41,emp_code:'E041',full_name:saved?'Directory Updated':'Directory Alpha',employment_status:'active',business_unit_id:1,business_unit_name:'People',job_role_id:1,job_role_name:'Specialist',current_org_valid_from:'2026-08-01',placement_id:1,entrance_level_id:1,entrance_level:'Entrance',active_enrollment_id:51,active_course_run_id:2,active_cohort_id:3,active_class_code:'A1',active_course_name:'Pytest Course',active_membership_id:4,membership_cohort_id:3,membership_class_code:'A1',latest_enrollment_status:'active',latest_class_code:'A1',latest_course_name:'Pytest Course',membership_count:1,lifecycle:'active'},course_history:[{start_date:'2026-08-01',class_code:'A1',course_name:'Pytest Course',status:'active',start_session_number:1,attendance_ratio:0.75,final_level:null,passed:null}],audit_summary:saved?[{created_at:'2026-08-02T00:00:00Z',actor_username:'admin',action:'employee.upsert'}]:[{created_at:'2026-08-01T00:00:00Z',actor_username:'admin',action:'learner.onboard'}]})
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
  const directoryCallsBeforeSave = fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/learners?')).length
  fireEvent.click(screen.getByRole('button',{name:'Edit profile'}))
  fireEvent.change(await screen.findByLabelText('Full name'), {target:{value:'Directory Updated'}})
  fireEvent.click(screen.getByRole('button',{name:'Save profile'}))
  expect(await screen.findByRole('heading',{name:'Directory Updated'})).toBeTruthy()
  expect(screen.getByText('Profile saved.')).toBeTruthy()
  expect(screen.getByText('employee.upsert')).toBeTruthy()
  fireEvent.click(screen.getByRole('button',{name:'Home'}))
  expect(await screen.findByText('HR home')).toBeTruthy()
  expect(fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/learners?'))).toHaveLength(directoryCallsBeforeSave)
  expect(fetchMock.mock.calls.filter(([url]) => String(url) === '/api/learners/41')).toHaveLength(2)
  await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url) === '/api/dashboard')).toHaveLength(2))
})

test('editor confirms authoritative destination details before starting a learner', async () => {
  const jsonResponse = (body: unknown) => new Response(JSON.stringify(body), {status:200,headers:{'Content-Type':'application/json'}})
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url === '/api/auth/me') return jsonResponse({user:{user_id:2,username:'editor',full_name:'HR Editor',role:'editor'},csrf_token:'start-csrf'})
    if (url === '/api/dashboard') return jsonResponse({summary:{active_employees:1,active_learners:0,open_course_runs:1,operational_issues:0,high_issues:0,open_quality_issues:0},hr_home:{active_people:1,current_learners:0,open_classes:1,review_items:0,urgent_items:0,follow_ups:0}})
    if (url.startsWith('/api/learners?')) return jsonResponse({items:[],page:1,page_size:20,total:0,sort:'full_name_asc_emp_code_asc'})
    if (url === '/api/learners/start-options') return jsonResponse({business_units:[{id:1,name:'People'}],job_roles:[{id:2,name:'Specialist'}],entrance_levels:[{id:3,name:'Entrance'}],course_runs:[{course_run_id:4,cohort_id:5,class_code:'EL101',course_code:'ENG1',course_name:'English One',run_number:1,run_status:'active',start_date:'2026-08-01',capacity:10,active_learners:7,proposed_start_session_number:3}]})
    if (url === '/api/learners/start') {
      expect(init).toMatchObject({method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':'start-csrf'}})
      expect(JSON.parse(String(init?.body))).toMatchObject({emp_code:'E-NEW',expected_employee_id:null,course_run_id:4,confirmed_start_session_number:3,capacity_override_reason:null})
      return jsonResponse({run_enrollment_id:8,employee_id:9,lifecycle:'first_time',placement_action:'created',membership_action:'created'})
    }
    if (url === '/api/learners/9') return jsonResponse({learner:{employee_id:9,emp_code:'E-NEW',full_name:'New Learner',employment_status:'active',business_unit_id:1,business_unit_name:'People',job_role_id:2,job_role_name:'Specialist',current_org_valid_from:'2026-08-03',placement_id:6,entrance_level_id:3,entrance_level:'Entrance',active_enrollment_id:8,active_course_run_id:4,active_cohort_id:5,active_class_code:'EL101',active_course_name:'English One',active_membership_id:7,membership_cohort_id:5,membership_class_code:'EL101',latest_enrollment_status:'active',latest_class_code:'EL101',latest_course_name:'English One',membership_count:1,lifecycle:'active'},course_history:[{start_date:'2026-08-01',class_code:'EL101',course_name:'English One',status:'active',start_session_number:3,attendance_ratio:null,final_level:null,passed:null}],audit_summary:[{created_at:'2026-08-03T00:00:00Z',actor_username:'editor',action:'learner.onboard'}]})
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<App />)
  fireEvent.click(await screen.findByRole('button',{name:'Learners'}))
  fireEvent.click(await screen.findByRole('button',{name:'Start learner'}))
  fireEvent.change(await screen.findByLabelText('Employee code'), {target:{value:'E-NEW'}})
  fireEvent.change(screen.getByLabelText('Full name'), {target:{value:'New Learner'}})
  fireEvent.change(screen.getByLabelText('Business unit'), {target:{value:'1'}})
  fireEvent.change(screen.getByLabelText('Role'), {target:{value:'2'}})
  fireEvent.change(screen.getByLabelText('Entrance level'), {target:{value:'3'}})
  fireEvent.change(screen.getByLabelText('Destination'), {target:{value:'4'}})
  expect(screen.getByText('First applicable session: 3')).toBeTruthy()
  expect(screen.getByText('Projected class size: 8 / 10')).toBeTruthy()
  fireEvent.click(screen.getByRole('button',{name:'Confirm start'}))

  expect(await screen.findByRole('heading',{name:'New Learner'})).toBeTruthy()
  expect(screen.getByText('Learning started.')).toBeTruthy()
  expect(screen.getByText('learner.onboard')).toBeTruthy()
})

test('editor confirms target state and refetches the learner after transfer', async () => {
  const jsonResponse = (body: unknown) => new Response(JSON.stringify(body), {status:200,headers:{'Content-Type':'application/json'}})
  let transferred = false
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url === '/api/auth/me') return jsonResponse({user:{user_id:2,username:'editor',full_name:'HR Editor',role:'editor'},csrf_token:'transfer-csrf'})
    if (url === '/api/dashboard') return jsonResponse({summary:{active_employees:1,active_learners:1,open_course_runs:2,operational_issues:0,high_issues:0,open_quality_issues:0},hr_home:{active_people:1,current_learners:1,open_classes:2,review_items:0,urgent_items:0,follow_ups:0}})
    if (url.startsWith('/api/learners?')) return jsonResponse({items:[{employee_id:41,emp_code:'E041',full_name:'Transfer Learner',employment_status:'active',business_unit_name:'People',job_role_name:'Specialist',class_code:'A1',course_name:'English One',course_code:'ENG1',enrollment_status:'active',attendance_ratio:null,entrance_level:'Entrance',pic:'Team'}],page:1,page_size:20,total:1,sort:'full_name_asc_emp_code_asc'})
    if (url === '/api/learners/41') return jsonResponse({learner:{employee_id:41,emp_code:'E041',full_name:'Transfer Learner',employment_status:'active',business_unit_id:1,business_unit_name:'People',job_role_id:2,job_role_name:'Specialist',current_org_valid_from:'2026-08-01',placement_id:3,entrance_level_id:4,entrance_level:'Entrance',active_enrollment_id:transferred?61:51,active_course_run_id:transferred?7:6,active_cohort_id:transferred?9:8,active_class_code:transferred?'B1':'A1',active_course_name:transferred?'English Two':'English One',active_membership_id:transferred?71:70,membership_cohort_id:transferred?9:8,membership_class_code:transferred?'B1':'A1',latest_enrollment_status:'active',latest_class_code:transferred?'B1':'A1',latest_course_name:transferred?'English Two':'English One',membership_count:transferred?2:1,lifecycle:'active'},course_history:transferred?[{start_date:'2026-08-15',class_code:'B1',course_name:'English Two',status:'active',start_session_number:3,attendance_ratio:null,final_level:null,passed:null},{start_date:'2026-08-01',class_code:'A1',course_name:'English One',status:'transferred',start_session_number:1,attendance_ratio:0.8,final_level:null,passed:null}]:[{start_date:'2026-08-01',class_code:'A1',course_name:'English One',status:'active',start_session_number:1,attendance_ratio:0.8,final_level:null,passed:null}],audit_summary:[{created_at:'2026-08-15T00:00:00Z',actor_username:'editor',action:transferred?'learner.transfer':'learner.onboard'}]})
    if (url === '/api/run-enrollments/51/transfer-options') return jsonResponse({source:{run_enrollment_id:51,employee_id:41,emp_code:'E041',full_name:'Transfer Learner',course_run_id:6,cohort_id:8,class_code:'A1',course_code:'ENG1',course_name:'English One',start_session_number:1},destinations:[{course_run_id:7,cohort_id:9,class_code:'B1',course_code:'ENG2',course_name:'English Two',run_number:1,run_status:'active',start_date:'2026-08-10',capacity:10,active_learners:4,proposed_start_session_number:3}]})
    if (url === '/api/run-enrollments/51/transfer') {
      expect(init).toMatchObject({method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':'transfer-csrf'}})
      expect(JSON.parse(String(init?.body))).toMatchObject({target_course_run_id:7,confirmed_start_session_number:3,capacity_override_reason:null})
      transferred = true
      return jsonResponse({run_enrollment_id:61,from_enrollment_id:51,membership_id:71,start_session_number:3,capacity_override_applied:false})
    }
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<App />)
  fireEvent.click(await screen.findByRole('button',{name:'Learners'}))
  fireEvent.click(await screen.findByRole('button',{name:/Transfer Learner/}))
  fireEvent.click(await screen.findByRole('button',{name:'Transfer learner'}))
  fireEvent.change(await screen.findByLabelText('Target class and course'), {target:{value:'7'}})
  expect(screen.getByText('First applicable session: 3')).toBeTruthy()
  expect(screen.getByText('Projected class size: 5 / 10')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Transfer date'), {target:{value:'2026-08-15'}})
  fireEvent.click(screen.getByRole('button',{name:'Confirm transfer'}))

  expect(await screen.findByText('Learner transferred.')).toBeTruthy()
  expect(screen.getAllByText('B1').length).toBeGreaterThan(0)
  expect(screen.getByText('learner.transfer')).toBeTruthy()
  expect(screen.queryByRole('heading',{name:'Transfer learner'})).toBeNull()
  expect(fetchMock.mock.calls.filter(([url]) => String(url) === '/api/learners/41')).toHaveLength(2)
})
