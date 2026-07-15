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

test('editor creates an attendance session and saves the complete roster once', async () => {
  const jsonResponse = (body: unknown) => new Response(JSON.stringify(body), {status:200,headers:{'Content-Type':'application/json'}})
  let created = false
  let saved = false
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url === '/api/auth/me') return jsonResponse({user:{user_id:2,username:'editor',full_name:'HR Editor',role:'editor'},csrf_token:'attendance-csrf'})
    if (url === '/api/dashboard') return jsonResponse({summary:{active_employees:2,active_learners:2,open_course_runs:1,operational_issues:0,high_issues:0,open_quality_issues:0},hr_home:{active_people:2,current_learners:2,open_classes:1,review_items:0,urgent_items:0,follow_ups:0}})
    if (url === '/api/attendance/course-runs') return jsonResponse({items:[{course_run_id:7,cohort_id:8,class_code:'A1',course_code:'ENG1',course_name:'English One',run_number:1,run_status:'active',next_sequence_in_run:1}]})
    if (url === '/api/course-runs/7/session-units') return jsonResponse({items:created?[{session_unit_id:11,meeting_id:10,sequence_in_run:1,starts_at:'2026-08-10T09:00:00Z',duration_minutes:60,meeting_status:saved?'completed':'planned'}]:[]})
    if (url === '/api/course-runs/7/attendance-sessions') {
      expect(init).toMatchObject({method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':'attendance-csrf'}})
      expect(JSON.parse(String(init?.body))).toMatchObject({duration_minutes:60,confirmed_sequence_in_run:1})
      created = true
      return jsonResponse({session_unit_id:11,meeting_id:10,sequence_in_run:1})
    }
    if (url === '/api/course-runs/7/session-units/11/roster' && init?.method === 'PUT') {
      expect(init.headers).toMatchObject({'Content-Type':'application/json','X-CSRF-Token':'attendance-csrf'})
      expect(JSON.parse(String(init.body))).toEqual({roster_token:'a'.repeat(64),records:[{run_enrollment_id:21,effective_status:'Present'},{run_enrollment_id:22,effective_status:'Absent'}]})
      saved = true
      return jsonResponse({session_unit_id:11,count:2,created_count:2,updated_count:0,unchanged_count:0})
    }
    if (url === '/api/course-runs/7/session-units/11/roster') return jsonResponse({course_run_id:7,session_unit_id:11,sequence_in_run:1,meeting_status:saved?'completed':'planned',starts_at:'2026-08-10T09:00:00Z',roster_token:saved?'b'.repeat(64):'a'.repeat(64),rows:[{run_enrollment_id:21,emp_code:'E021',full_name:'Attendance Alpha',start_session_number:1,effective_status:'Present',attendance_id:saved?31:null},{run_enrollment_id:22,emp_code:'E022',full_name:'Attendance Beta',start_session_number:1,effective_status:saved?'Absent':'Present',attendance_id:saved?32:null}]})
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<App />)
  fireEvent.click(await screen.findByRole('button',{name:'Attendance'}))
  fireEvent.change(await screen.findByLabelText('Class and course'),{target:{value:'7'}})
  fireEvent.click(screen.getByRole('button',{name:'Create session'}))
  fireEvent.change(await screen.findByLabelText('Session start'),{target:{value:'2026-08-10T09:00'}})
  fireEvent.click(screen.getByRole('button',{name:'Confirm session'}))

  expect(await screen.findByText('Attendance Alpha')).toBeTruthy()
  expect(screen.getByText('2 present')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Attendance for E022'),{target:{value:'Absent'}})
  expect(screen.getByText('1 absent')).toBeTruthy()
  fireEvent.click(screen.getByRole('button',{name:'Save attendance'}))

  expect(await screen.findByText('Attendance saved.')).toBeTruthy()
  expect(screen.getByText('Completed')).toBeTruthy()
  expect(fetchMock.mock.calls.filter(([url,init]) => String(url).endsWith('/roster') && init?.method === 'PUT')).toHaveLength(1)
})

test('editor records a linked make-up with a reason and zero denominator impact', async () => {
  const jsonResponse = (body: unknown) => new Response(JSON.stringify(body), {status:200,headers:{'Content-Type':'application/json'}})
  let credited = false
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url === '/api/auth/me') return jsonResponse({user:{user_id:2,username:'editor',full_name:'HR Editor',role:'editor'},csrf_token:'makeup-csrf'})
    if (url === '/api/dashboard') return jsonResponse({summary:{active_employees:1,active_learners:1,open_course_runs:1,operational_issues:0,high_issues:0,open_quality_issues:0},hr_home:{active_people:1,current_learners:1,open_classes:1,review_items:0,urgent_items:0,follow_ups:0}})
    if (url === '/api/attendance/course-runs') return jsonResponse({items:[]})
    if (url === '/api/attendance/makeup-options') return jsonResponse({items:credited?[]:[{attendance_id:31,course_run_id:7,emp_code:'E021',full_name:'Make-up Alpha',class_code:'A1',course_code:'ENG1',course_name:'English One',run_number:1,sequence_in_run:1,starts_at:'2026-08-03T09:00:00Z',eligible_units:[{session_unit_id:42,sequence_in_run:2,starts_at:'2026-08-10T09:00:00Z',meeting_status:'planned'}]}]})
    if (url === '/api/attendance/31/makeup-credit') {
      expect(init).toMatchObject({method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':'makeup-csrf'}})
      expect(JSON.parse(String(init?.body))).toEqual({makeup_session_unit_id:42,reason:'Approved medical recovery'})
      credited = true
      return jsonResponse({attendance_id:50,makeup_for_attendance_id:31,credited_status:'Present',denominator_units_added:0})
    }
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<App />)
  fireEvent.click(await screen.findByRole('button',{name:'Attendance'}))
  fireEvent.click(await screen.findByRole('button',{name:'Record make-up'}))
  fireEvent.change(await screen.findByLabelText('Original absence'),{target:{value:'31'}})
  fireEvent.change(screen.getByLabelText('Make-up session'),{target:{value:'42'}})
  fireEvent.change(screen.getByLabelText('Reason'),{target:{value:'Approved medical recovery'}})
  expect(screen.getByText('Original attendance remains Absent.')).toBeTruthy()
  expect(screen.getByText('Adds 0 denominator units.')).toBeTruthy()
  fireEvent.click(screen.getByRole('button',{name:'Confirm make-up credit'}))

  expect(await screen.findByText('Make-up attendance credited.')).toBeTruthy()
  expect(screen.getByText('No eligible absences currently have a make-up session available.')).toBeTruthy()
})

test('admin records a result, overrides eligibility, and confirms completion in one workspace', async () => {
  const jsonResponse = (body: unknown) => new Response(JSON.stringify(body), {status:200,headers:{'Content-Type':'application/json'}})
  let recorded = false
  let overridden = false
  let completion: null|'suggested'|'confirmed' = null
  const detail = () => ({enrollment:{run_enrollment_id:51,employee_id:41,emp_code:'E041',full_name:'Final Alpha',course_run_id:7,class_code:'A1',course_code:'ENG1',course_name:'English One',run_number:1,enrollment_status:completion==='confirmed'?'completed':'active'},eligibility:{applicable_units:4,present_units:2,attendance_ratio:.5,calculated_exam_eligible:false,effective_exam_eligible:overridden,exam_eligibility_override:overridden,exam_eligibility_override_reason:overridden?'Approved exception':null,latest_evaluation_version:recorded?(overridden?2:1):null},latest_result:recorded?{evaluation_version_id:overridden?72:71,version_number:overridden?2:1,final_level_id:3,final_level_name:'Level Two',passed:true,next_course_id:9,next_course_code:'ENG2',teacher_notes:'Ready',correction_reason:overridden?'Approved exception':null,created_by_username:'admin',created_at:'2026-08-20T09:00:00Z'}:null,history:recorded?[{evaluation_version_id:71,version_number:1,final_level_id:3,final_level_name:'Level Two',passed:true,next_course_id:9,next_course_code:'ENG2',teacher_notes:'Ready',correction_reason:null,created_by_username:'admin',created_at:'2026-08-20T09:00:00Z'}]:[],completion:completion?{suggested:true,status:completion,confirmed_by_username:completion==='confirmed'?'admin':null,confirmed_at:completion==='confirmed'?'2026-08-20T10:00:00Z':null}:null,options:{levels:[{level_id:3,level_name:'Level Two'}],courses:[{course_id:9,course_code:'ENG2',course_name:'English Two'}]}})
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url === '/api/auth/me') return jsonResponse({user:{user_id:1,username:'admin',full_name:'HR Admin',role:'admin'},csrf_token:'result-csrf'})
    if (url === '/api/dashboard') return jsonResponse({summary:{active_employees:1,active_learners:1,open_course_runs:1,operational_issues:0,high_issues:0,open_quality_issues:0},hr_home:{active_people:1,current_learners:1,open_classes:1,review_items:0,urgent_items:0,follow_ups:0}})
    if (url === '/api/evaluations/pending') return jsonResponse({items:[{run_enrollment_id:51,employee_id:41,emp_code:'E041',full_name:'Final Alpha',class_code:'A1',course_code:'ENG1',course_name:'English One',run_number:1,enrollment_status:'active',attendance_ratio:.5,effective_exam_eligible:overridden,latest_version_number:recorded?(overridden?2:1):null,passed:recorded?true:null,completion_status:completion}]})
    if (url === '/api/run-enrollments/51/final-result' && !init?.method) return jsonResponse(detail())
    if (url === '/api/run-enrollments/51/final-result' && init?.method === 'POST') {
      expect(init.headers).toMatchObject({'Content-Type':'application/json','X-CSRF-Token':'result-csrf'})
      expect(JSON.parse(String(init.body))).toEqual({final_level_id:3,passed:true,next_course_id:9,teacher_notes:'Ready',correction_reason:null})
      recorded = true
      return jsonResponse({evaluation_version_id:71,version_number:1,effective_exam_eligible:false,exam_eligibility_override:false})
    }
    if (url === '/api/run-enrollments/51/exam-eligibility-override') {
      expect(JSON.parse(String(init?.body))).toEqual({eligible:true,reason:'Approved exception'})
      overridden = true
      return jsonResponse({evaluation_version_id:72,version_number:2,effective_exam_eligible:true,previous_effective_exam_eligible:false})
    }
    if (url === '/api/run-enrollments/51/completion-confirmation') {
      const body = JSON.parse(String(init?.body))
      if (completion === null) {
        expect(body).toEqual({action:'suggest',reason:null}); completion = 'suggested'
      } else {
        expect(body).toEqual({action:'confirm',reason:null}); completion = 'confirmed'
      }
      return jsonResponse({action:body.action,suggested:true,completion_status:completion,enrollment_status:completion==='confirmed'?'completed':'active'})
    }
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<App />)
  fireEvent.click(await screen.findByRole('button',{name:'Final results'}))
  fireEvent.change(await screen.findByLabelText('Learner and course'),{target:{value:'51'}})
  expect(await screen.findByText('50% attendance')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Final level'),{target:{value:'3'}})
  fireEvent.click(screen.getByLabelText('Passed'))
  fireEvent.change(screen.getByLabelText('Next course'),{target:{value:'9'}})
  fireEvent.change(screen.getByLabelText('Teacher notes'),{target:{value:'Ready'}})
  fireEvent.click(screen.getByRole('button',{name:'Save final result'}))
  expect(await screen.findByText('Final result saved as version 1.')).toBeTruthy()

  fireEvent.change(screen.getByLabelText('Eligibility decision'),{target:{value:'true'}})
  fireEvent.change(screen.getByLabelText('Override reason'),{target:{value:'Approved exception'}})
  fireEvent.click(screen.getByRole('button',{name:'Save eligibility override'}))
  expect(await screen.findByText('Eligibility override saved.')).toBeTruthy()
  expect(screen.getByText('Admin override')).toBeTruthy()

  fireEvent.change(screen.getByLabelText('Completion action'),{target:{value:'suggest'}})
  fireEvent.click(screen.getByRole('button',{name:'Apply completion action'}))
  expect(await screen.findByText('Completion suggested.')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Completion action'),{target:{value:'confirm'}})
  fireEvent.click(screen.getByRole('button',{name:'Apply completion action'}))
  expect(await screen.findByText('Completion confirmed.')).toBeTruthy()
})
