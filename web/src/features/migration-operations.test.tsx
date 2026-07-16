import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { FollowUpsWorkspace } from './followups/FollowUpsWorkspace'
import { AdministrationWorkspace } from './administration/AdministrationWorkspace'
import { ReportsWorkspace } from './reports/ReportsWorkspace'

afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals()})
const response=(body:unknown)=>new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}})

test('admin invokes each approved follow-up action family through its dedicated endpoint',async()=>{
  const posts:string[]=[]
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=String(input)
    if(url.startsWith('/api/follow-ups/operational')) return response({items:[],page:1,page_size:20,total:0})
    if(init?.method==='POST'){posts.push(url);return response({entity_type:'test',entity_id:null,values:{}})}
    throw new Error(`Unexpected fetch: ${url}`)
  }))
  render(<FollowUpsWorkspace csrfToken="csrf" role="admin"/>)
  fireEvent.click(await screen.findByRole('button',{name:'Approved actions'}))
  for(const heading of ['Backfill unknown organization','Backfill unknown entrance placement']){
    const form=screen.getByRole('heading',{name:heading}).closest('form')!
    fireEvent.change(within(form).getByLabelText('Approval reason'),{target:{value:'Owner approved action'}})
    fireEvent.click(within(form).getByLabelText(/I confirm/))
    fireEvent.click(within(form).getByRole('button',{name:'Apply approved action'}))
    await waitFor(()=>expect(posts.length).toBeGreaterThan(0))
  }
  for(const [heading,label] of [['Approve legacy attendance exception','Session unit ID'],['Cancel duplicate schedule occurrence','Duplicate meeting ID']]){
    const form=screen.getByRole('heading',{name:heading}).closest('form')!
    fireEvent.change(within(form).getByLabelText(label),{target:{value:'41'}})
    fireEvent.change(within(form).getByLabelText('Approval reason'),{target:{value:'Owner approved action'}})
    fireEvent.click(within(form).getByLabelText(/I confirm/))
    fireEvent.click(within(form).getByRole('button',{name:'Apply approved action'}))
    await waitFor(()=>expect(posts.length).toBeGreaterThan(2))
  }
  expect(posts).toEqual(['/api/follow-ups/actions/unknown-organization','/api/follow-ups/actions/unknown-placement','/api/follow-ups/actions/legacy-attendance-exception','/api/follow-ups/actions/schedule-conflict'])
})

test('editor resolves a logged issue from the durable ledger',async()=>{
  let resolved=false
  const fetchMock=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=String(input)
    if(url.startsWith('/api/follow-ups/operational')) return response({items:[],page:1,page_size:20,total:0})
    if(url.startsWith('/api/follow-ups/quality-issues')){
      if(init?.method==='POST'){resolved=true;expect(JSON.parse(String(init.body))).toEqual({status:'resolved',note:'Verified source'});return response({entity_type:'data_quality_issue',entity_id:9,values:{status:'resolved'}})}
      return response({items:resolved?[]:[{issue_id:9,issue_code:'source_gap',entity_type:'employee',entity_key:'4',source_sheet:'STUDENTS',source_row_number:8,details:{original:'kept'},status:'open',created_at:'2026-07-01T00:00:00Z',resolved_at:null,resolved_by_username:null,resolution_note:null}],page:1,page_size:20,total:resolved?0:1})
    }
    throw new Error(`Unexpected fetch: ${url}`)
  });vi.stubGlobal('fetch',fetchMock)
  render(<FollowUpsWorkspace csrfToken="csrf" role="editor"/>)
  fireEvent.click(await screen.findByRole('button',{name:'Logged issues'}))
  fireEvent.change(await screen.findByLabelText('Resolution note'),{target:{value:'Verified source'}})
  fireEvent.click(screen.getByRole('button',{name:'Save resolution'}))
  await waitFor(()=>expect(resolved).toBe(true))
})

test('editor creates an atomic class journey and a two-unit meeting',async()=>{
  const writes:{url:string;body:any}[]=[]
  const options={proposed_class_code:'EL900',courses:[{id:1,label:'ENG · English'}],employees:[],cohorts:[{id:2,label:'EL100 · Alpha'}],course_runs:[{id:3,label:'EL100 · ENG · run 1'}],pic_labels:['People Team']}
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=String(input)
    if(init?.method){writes.push({url,body:JSON.parse(String(init.body))});return response({entity_type:'test',entity_id:7,values:{}})}
    if(url==='/api/administration/options')return response(options)
    if(url.startsWith('/api/administration/classes'))return response({items:[],page:1,page_size:100,total:0})
    if(url.startsWith('/api/administration/course-runs'))return response({items:[],page:1,page_size:100,total:0})
    if(url.startsWith('/api/administration/schedule'))return response({items:[],page:1,page_size:100,total:0})
    throw new Error(`Unexpected fetch: ${url}`)
  }))
  render(<AdministrationWorkspace csrfToken="csrf"/>)
  const classForm=(await screen.findByRole('heading',{name:'Create class with first course'})).closest('form')!
  fireEvent.change(within(classForm).getByLabelText('Display name'),{target:{value:'New Class'}})
  fireEvent.change(within(classForm).getByLabelText('Course'),{target:{value:'1'}})
  fireEvent.change(within(classForm).getByLabelText('Start date'),{target:{value:'2026-09-01'}})
  fireEvent.change(classForm.querySelector('input[name="pic_label"]')!,{target:{value:'People Team'}})
  fireEvent.click(within(classForm).getByRole('button',{name:'Create class'}))
  await waitFor(()=>expect(writes[0].url).toBe('/api/administration/classes'))
  expect(writes[0].body).toMatchObject({class_code:'EL900',course_id:1,capacity:12,pic_label:'People Team'})
  fireEvent.click(screen.getByRole('button',{name:'Schedule'}))
  fireEvent.change(screen.getByLabelText('Class and course'),{target:{value:'3'}})
  fireEvent.change(screen.getByLabelText('Meeting start'),{target:{value:'2026-09-03T09:00'}})
  fireEvent.change(screen.getByLabelText('First session number'),{target:{value:'1'}})
  fireEvent.change(screen.getByLabelText('Sessions counted'),{target:{value:'2'}})
  fireEvent.click(screen.getByRole('button',{name:'Create meeting'}))
  await waitFor(()=>expect(writes).toHaveLength(2))
  expect(writes[1].url).toBe('/api/administration/course-runs/3/meetings')
  expect(writes[1].body).toMatchObject({first_sequence_in_run:1,unit_count:2,unit_type:'normal'})
})

test('viewer runs registered reports while only admin can open audit history',async()=>{
  const fetchMock=vi.fn(async(input:RequestInfo|URL)=>{
    const url=String(input)
    if(url==='/api/reports')return response({reports:[{key:'progress_summary',label:'Progress summary',columns:['emp_code','full_name'],metric_definitions:[]}]})
    if(url.startsWith('/api/reports/progress_summary'))return response({key:'progress_summary',label:'Progress summary',columns:['emp_code','full_name'],metric_definitions:[],items:[{emp_code:'E1',full_name:'Report Learner'}],page:1,page_size:50,total:1})
    if(url.startsWith('/api/audit-events'))return response({items:[{audit_event_id:1,actor_username:'admin',action:'employee.upsert',entity_type:'employee',entity_key:'1',details:{reason:'approved'},created_at:'2026-07-16T00:00:00Z'}],page:1,page_size:50,total:1})
    throw new Error(`Unexpected fetch: ${url}`)
  });vi.stubGlobal('fetch',fetchMock)
  const viewer=render(<ReportsWorkspace role="viewer"/>)
  expect(await screen.findByText('Report Learner')).toBeTruthy()
  expect(screen.queryByRole('button',{name:'Audit history'})).toBeNull()
  viewer.unmount()
  render(<ReportsWorkspace role="admin"/>)
  fireEvent.click(await screen.findByRole('button',{name:'Audit history'}))
  expect(await screen.findByText('employee.upsert')).toBeTruthy()
  expect(screen.getByText('admin')).toBeTruthy()
})
