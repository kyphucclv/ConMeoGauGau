import { FormEvent, useEffect, useState } from 'react'
import { apiJson, type MonthlyActionSummaryBody, type MonthlyActionSummaryResult, type MonthlyReviewResponse } from '../../api/client'
import './monthly-review.css'

const initialMonth = new Date().toISOString().slice(0,7)
const percent=(value:number|null|undefined)=>value==null?'No data':`${Math.round(value*100)}%`

export function MonthlyReviewWorkspace({csrfToken}:{csrfToken:string}){
  const [month,setMonth]=useState(initialMonth)
  const [data,setData]=useState<MonthlyReviewResponse|null>(null)
  const [mode,setMode]=useState<'overview'|'details'|'actions'>('overview')
  const [draft,setDraft]=useState({highlights:'',risks:'',next_month_priorities:''})
  const [notice,setNotice]=useState('')
  const [error,setError]=useState('')
  const [saving,setSaving]=useState(false)

  useEffect(()=>{void load(month)},[])
  async function load(value:string){
    setError('');setNotice('')
    try{
      const response=await apiJson<MonthlyReviewResponse>(`/api/monthly-review?month=${value}`)
      setData(response)
      const defaults=response.action_summary??response.proposed_action_summary
      setDraft({highlights:defaults.highlights,risks:defaults.risks,next_month_priorities:defaults.next_month_priorities})
    }catch(value){setError(value instanceof Error?value.message:'Monthly review could not be loaded')}
  }
  async function changeMonth(value:string){setMonth(value);setData(null);await load(value)}
  async function save(event:FormEvent<HTMLFormElement>){
    event.preventDefault();setSaving(true);setError('');setNotice('')
    const body:MonthlyActionSummaryBody={month,...draft}
    try{
      const result=await apiJson<MonthlyActionSummaryResult>('/api/monthly-review/action-summary',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:JSON.stringify(body)})
      await load(month);setNotice(`Action summary saved as version ${result.version_number}.`)
    }catch(value){setError(value instanceof Error?value.message:'Action summary could not be saved')}finally{setSaving(false)}
  }
  return <section>
    <div className="section-heading"><div><p className="eyebrow">Monthly operations</p><h2>Monthly review</h2></div><label>Review month<input type="month" value={month} onChange={event=>void changeMonth(event.target.value)}/></label></div>
    {notice&&<p className="success-notice" role="status">{notice}</p>}{error&&<p role="alert">{error}</p>}
    {data&&<><div className="review-modes" aria-label="Monthly review sections"><button className={mode==='overview'?'active secondary':'secondary'} onClick={()=>setMode('overview')}>Overview</button><button className={mode==='details'?'active secondary':'secondary'} onClick={()=>setMode('details')}>Detail tables</button><button className={mode==='actions'?'active secondary':'secondary'} onClick={()=>setMode('actions')}>Summary & export</button></div>
      <div className="monthly-summary"><article><strong>{data.summary.active} active participants</strong><span>{data.summary.repeated} repeated</span></article><article><strong>{data.summary.planned} / {data.summary.delivered} sessions</strong><span>{data.summary.variance>=0?'+':''}{data.summary.variance} variance</span></article><article><strong>{percent(data.summary.attendance_ratio)} attendance</strong><span>{data.summary.low_count} below threshold</span></article><article><strong>{data.summary.improved_count} / {data.summary.tested_count} improved</strong><span>{data.summary.new_course_count} new courses</span></article></div>
      {mode==='overview'&&<div className="review-overview"><ReviewTable title="Program status" rows={data.program}/><ReviewTable title="Course participation" rows={data.course_participation}/></div>}
      {mode==='details'&&<div className="review-details"><ReviewTable title="Program status" rows={data.program}/><ReviewTable title="Course participation" rows={data.course_participation}/><ReviewTable title="Class participation" rows={data.class_participation}/><ReviewTable title="Learner participation" rows={data.participation}/><ReviewTable title="Learning progress" rows={data.progress}/><ReviewTable title="Level distribution" rows={data.level_distribution}/><ReviewTable title="New courses" rows={data.new_courses}/></div>}
      {mode==='actions'&&<form className="monthly-actions" onSubmit={save}><div><h3>Action summary</h3><p>{data.action_summary?`Saved by ${data.action_summary.created_by_username} · version ${data.action_summary.version_number}`:'Server-proposed draft; save to make it an HR conclusion.'}</p></div><label>Highlights<textarea value={draft.highlights} onChange={event=>setDraft({...draft,highlights:event.target.value})}/></label><label>Risks<textarea value={draft.risks} onChange={event=>setDraft({...draft,risks:event.target.value})}/></label><label>Next-month priorities<textarea value={draft.next_month_priorities} onChange={event=>setDraft({...draft,next_month_priorities:event.target.value})}/></label><div className="form-actions"><button disabled={saving}>{saving?'Saving…':'Save action summary'}</button><a className="button-link" href={`/api/monthly-review/export?month=${month}`}>Download Excel review</a></div></form>}
    </>}
  </section>
}

function ReviewTable({title,rows}:{title:string;rows:Array<Record<string,unknown>>}){
  const headers=rows.length?Object.keys(rows[0]):[]
  return <section className="review-table"><h3>{title}</h3>{!rows.length?<p className="notice">No activity for this month.</p>:<div className="table-wrap" tabIndex={0}><table><thead><tr>{headers.map(header=><th key={header}>{header.replaceAll('_',' ')}</th>)}</tr></thead><tbody>{rows.map((row,index)=><tr key={index}>{headers.map(header=><td key={header}>{String(row[header]??'—')}</td>)}</tr>)}</tbody></table></div>}</section>
}
