import { FormEvent, useEffect, useState } from 'react'
import { apiJson, type AuditEventPage, type ReportCatalog, type ReportPage } from '../../api/client'
import './reports.css'

type Props={role:'admin'|'editor'|'viewer'}
type Mode='reports'|'audit'

export function ReportsWorkspace({role}:Props){
  const [mode,setMode]=useState<Mode>('reports');const[catalog,setCatalog]=useState<ReportCatalog|null>(null)
  const[key,setKey]=useState('');const[report,setReport]=useState<ReportPage|null>(null);const[page,setPage]=useState(1)
  const[audit,setAudit]=useState<AuditEventPage|null>(null);const[error,setError]=useState('')
  useEffect(()=>{apiJson<ReportCatalog>('/api/reports').then(data=>{setCatalog(data);if(data.reports.length)setKey(data.reports[0].key)}).catch(e=>setError(e instanceof Error?e.message:'Unable to load reports'))},[])
  useEffect(()=>{if(!key||mode!=='reports')return;setError('');apiJson<ReportPage>(`/api/reports/${encodeURIComponent(key)}?page=${page}&page_size=50`).then(setReport).catch(e=>setError(e instanceof Error?e.message:'Unable to run report'))},[key,page,mode])
  async function filterAudit(e:FormEvent<HTMLFormElement>){e.preventDefault();const d=new FormData(e.currentTarget);const p=new URLSearchParams({page:'1',page_size:'50'});for(const name of['action','entity_type','actor_username']){const value=String(d.get(name)||'');if(value)p.set(name,value)}try{setAudit(await apiJson<AuditEventPage>(`/api/audit-events?${p}`))}catch(err){setError(err instanceof Error?err.message:'Unable to load audit history')}}
  function switchMode(next:Mode){setMode(next);setError('');if(next==='audit'&&!audit)void apiJson<AuditEventPage>('/api/audit-events?page_size=50').then(setAudit).catch(e=>setError(e instanceof Error?e.message:'Unable to load audit history'))}
  return <section><div className="section-heading"><div><p className="eyebrow">Insights</p><h2>Reports{mode==='audit'?' and audit':''}</h2><p>Only registered reports and approved fields are available.</p></div></div>
    {role==='admin'&&<div className="workspace-tabs"><button className={mode==='reports'?'active':''} onClick={()=>switchMode('reports')}>Reports</button><button className={mode==='audit'?'active':''} onClick={()=>switchMode('audit')}>Audit history</button></div>}
    {error&&<p role="alert">{error}</p>}
    {mode==='reports'?<><label className="report-picker">Registered report<select value={key} onChange={e=>{setKey(e.target.value);setPage(1)}}>{catalog?.reports.map(x=><option key={x.key} value={x.key}>{x.label}</option>)}</select></label>{report&&<ReportResult report={report}/>} {report&&<div className="pagination"><span>Page {report.page} · {report.total} row(s)</span><button className="secondary" disabled={page===1} onClick={()=>setPage(x=>x-1)}>Previous</button><button className="secondary" disabled={page*report.page_size>=report.total} onClick={()=>setPage(x=>x+1)}>Next</button></div>}</>:role==='admin'?<AuditHistory page={audit} submit={filterAudit}/>:null}
  </section>
}

function ReportResult({report}:{report:ReportPage}){return <><div className="metric-definitions">{report.metric_definitions.map(m=><article key={m.metric_key}><strong>{m.metric_name}</strong><p>{m.definition}</p>{m.denominator_definition&&<small>Denominator: {m.denominator_definition}</small>}</article>)}</div><div className="table-wrap"><table><thead><tr>{report.columns.map(c=><th key={c}>{c.replaceAll('_',' ')}</th>)}</tr></thead><tbody>{report.items.map((row,index)=><tr key={index}>{report.columns.map(c=><td key={c}>{display(row[c])}</td>)}</tr>)}</tbody></table></div>{!report.items.length&&<p className="empty-state">This report has no rows.</p>}</>}

function AuditHistory({page,submit}:{page:AuditEventPage|null;submit:(e:FormEvent<HTMLFormElement>)=>void}){return <><form className="filters audit-filters" onSubmit={submit}><label>Action<input name="action"/></label><label>Entity type<input name="entity_type"/></label><label>Actor username<input name="actor_username"/></label><button>Filter audit</button></form><div className="table-wrap"><table><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Entity</th><th>Approved details</th></tr></thead><tbody>{page?.items.map(x=><tr key={x.audit_event_id}><td>{new Date(x.created_at).toLocaleString()}</td><td>{x.actor_username}</td><td>{x.action}</td><td>{x.entity_type}<small>{x.entity_key}</small></td><td><details><summary>View details</summary><pre>{JSON.stringify(x.details,null,2)}</pre></details></td></tr>)}</tbody></table></div><p className="result-count">{page?.total??0} audit event(s)</p></>}

function display(value:unknown){if(value===null||value===undefined)return '—';if(typeof value==='object')return JSON.stringify(value);if(typeof value==='boolean')return value?'Yes':'No';return String(value)}
