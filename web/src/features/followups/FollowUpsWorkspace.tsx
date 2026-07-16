import { FormEvent, useEffect, useState } from 'react'
import { apiJson, type OperationalIssuePage, type QualityIssuePage } from '../../api/client'
import './followups.css'

type Props = { csrfToken: string; role: 'admin'|'editor' }
type Mode = 'operational'|'logged'|'actions'

export function FollowUpsWorkspace({csrfToken, role}: Props) {
  const [mode,setMode]=useState<Mode>('operational')
  const [operational,setOperational]=useState<OperationalIssuePage|null>(null)
  const [logged,setLogged]=useState<QualityIssuePage|null>(null)
  const [severity,setSeverity]=useState('all')
  const [workflow,setWorkflow]=useState('')
  const [status,setStatus]=useState('open')
  const [page,setPage]=useState(1)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')

  async function load() {
    setError('')
    try {
      if (mode==='logged') {
        setLogged(await apiJson<QualityIssuePage>(`/api/follow-ups/quality-issues?status=${status}&page=${page}&page_size=20`))
      } else if (mode==='operational') {
        const params=new URLSearchParams({severity,page:String(page),page_size:'20'})
        if(workflow) params.set('workflow',workflow)
        setOperational(await apiJson<OperationalIssuePage>(`/api/follow-ups/operational?${params}`))
      }
    } catch (e) { setError(e instanceof Error?e.message:'Unable to load follow-ups') }
  }
  useEffect(()=>{ void load() },[mode,severity,workflow,status,page])

  async function post(url:string, body:unknown) {
    setError('');setNotice('')
    try {
      await apiJson(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:JSON.stringify(body)})
      setNotice('Follow-up action saved.')
      await load()
    } catch(e){setError(e instanceof Error?e.message:'Action failed')}
  }
  function changeMode(next:Mode){setMode(next);setPage(1);setNotice('')}
  const current=mode==='logged'?logged:operational

  return <section>
    <div className="section-heading"><div><p className="eyebrow">Operations</p><h2>Follow-ups</h2><p>Review derived conditions separately from the durable quality-issue ledger.</p></div></div>
    <div className="workspace-tabs">
      <button className={mode==='operational'?'active':''} onClick={()=>changeMode('operational')}>To check</button>
      <button className={mode==='logged'?'active':''} onClick={()=>changeMode('logged')}>Logged issues</button>
      {role==='admin'&&<button className={mode==='actions'?'active':''} onClick={()=>changeMode('actions')}>Approved actions</button>}
    </div>
    {error&&<p role="alert">{error}</p>}{notice&&<p className="success-notice">{notice}</p>}
    {mode==='operational'&&<>
      <div className="filters followup-filters">
        <label>Severity<select value={severity} onChange={e=>{setSeverity(e.target.value);setPage(1)}}><option value="all">All</option><option value="high">High</option><option value="warning">Warning</option></select></label>
        <label>Workflow<select value={workflow} onChange={e=>{setWorkflow(e.target.value);setPage(1)}}><option value="">All</option><option>Learners</option><option>Attendance</option><option>Schedule</option></select></label>
      </div>
      <IssueTable rows={operational?.items??[]} />
    </>}
    {mode==='logged'&&<>
      <div className="filters followup-filters"><label>Status<select value={status} onChange={e=>{setStatus(e.target.value);setPage(1)}}><option value="open">Open</option><option value="resolved">Resolved</option><option value="ignored">Ignored</option><option value="all">All</option></select></label></div>
      <div className="table-wrap" tabIndex={0}><table><thead><tr><th>Issue</th><th>Source</th><th>Status</th><th>Resolution</th></tr></thead><tbody>{logged?.items.map(item=><tr key={item.issue_id}><td><strong>{item.issue_code}</strong><small>{item.entity_type} {item.entity_key}</small><details><summary>Original details</summary><pre>{JSON.stringify(item.details,null,2)}</pre></details></td><td>{item.source_sheet||'—'}<small>{item.source_row_number?`Row ${item.source_row_number}`:'No source row'}</small></td><td><span className="badge">{item.status}</span></td><td>{item.status==='open'?<ResolveIssue issueId={item.issue_id} post={post}/>:<><span>{item.resolution_note}</span><small>{item.resolved_by_username}</small></>}</td></tr>)}</tbody></table></div>
    </>}
    {mode==='actions'&&role==='admin'&&<ApprovedActions post={post}/>}
    {mode!=='actions'&&current&&<div className="pagination"><span>Page {current.page} · {current.total} item(s)</span><button className="secondary" disabled={page===1} onClick={()=>setPage(v=>v-1)}>Previous</button><button className="secondary" disabled={page*current.page_size>=current.total} onClick={()=>setPage(v=>v+1)}>Next</button></div>}
  </section>
}

function IssueTable({rows}:{rows:OperationalIssuePage['items']}) {
  if(!rows.length) return <p className="empty-state">No operational follow-ups match these filters.</p>
  return <div className="table-wrap" tabIndex={0}><table><thead><tr><th>Priority</th><th>Follow-up</th><th>Workflow</th><th>Context</th></tr></thead><tbody>{rows.map(item=><tr key={`${item.issue_code}-${item.entity_type}-${item.entity_key}`}><td><span className={`badge ${item.severity}`}>{item.severity}</span></td><td><strong>{item.title}</strong><small>{item.issue_code}</small></td><td>{item.workflow}</td><td><details><summary>{item.entity_type} {item.entity_key}</summary><pre>{JSON.stringify(item.details,null,2)}</pre></details></td></tr>)}</tbody></table></div>
}

function ResolveIssue({issueId,post}:{issueId:number;post:(url:string,body:unknown)=>Promise<void>}) {
  async function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();const data=new FormData(e.currentTarget);await post(`/api/follow-ups/quality-issues/${issueId}/resolution`,{status:data.get('status'),note:data.get('note')})}
  return <form className="inline-resolution" onSubmit={submit}><label>Resolution<select name="status"><option value="resolved">Resolved</option><option value="ignored">Ignored</option></select></label><label>Resolution note<input name="note" required maxLength={2000}/></label><button>Save resolution</button></form>
}

function ApprovedActions({post}:{post:(url:string,body:unknown)=>Promise<void>}) {
  function form(url:string, extra:(data:FormData)=>object=()=>({})){return async(e:FormEvent<HTMLFormElement>)=>{e.preventDefault();const data=new FormData(e.currentTarget);await post(url,{...extra(data),reason:data.get('reason'),confirmed:true})}}
  return <div className="action-grid">
    <ActionForm title="Backfill unknown organization" submit={form('/api/follow-ups/actions/unknown-organization')} />
    <ActionForm title="Backfill unknown entrance placement" submit={form('/api/follow-ups/actions/unknown-placement')} />
    <ActionForm title="Approve legacy attendance exception" submit={form('/api/follow-ups/actions/legacy-attendance-exception',d=>({session_unit_id:Number(d.get('entity_id'))}))} entityLabel="Session unit ID" />
    <ActionForm title="Cancel duplicate schedule occurrence" submit={form('/api/follow-ups/actions/schedule-conflict',d=>({meeting_id:Number(d.get('entity_id'))}))} entityLabel="Duplicate meeting ID" />
  </div>
}

function ActionForm({title,submit,entityLabel}:{title:string;submit:(e:FormEvent<HTMLFormElement>)=>void;entityLabel?:string}) {
  return <form className="action-card" onSubmit={submit}><h3>{title}</h3>{entityLabel&&<label>{entityLabel}<input name="entity_id" type="number" min="1" required/></label>}<label>Approval reason<input name="reason" required maxLength={2000}/></label><label className="confirm"><input type="checkbox" required/>I confirm this owner-approved action</label><button>Apply approved action</button></form>
}
