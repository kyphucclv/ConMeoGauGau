import { FormEvent, useEffect, useState } from 'react'
import { apiJson, type CompletionActionBody, type CompletionActionResult, type EligibilityOverrideBody, type EligibilityOverrideResult, type EvaluationPendingList, type FinalResultBody, type FinalResultDetail, type FinalResultResult } from '../../api/client'
import './evaluation.css'

export function EvaluationWorkspace({csrfToken,role,onSaved}:{csrfToken:string;role:'admin'|'editor';onSaved:()=>void}) {
  const [items,setItems] = useState<EvaluationPendingList['items']>([])
  const [selectedId,setSelectedId] = useState('')
  const [detail,setDetail] = useState<FinalResultDetail|null>(null)
  const [saving,setSaving] = useState(false)
  const [notice,setNotice] = useState('')
  const [error,setError] = useState('')

  useEffect(() => { void loadItems() }, [])

  function showError(value:unknown) {
    setError(value instanceof Error?value.message:'Final-result request failed')
  }

  async function loadItems() {
    const response = await apiJson<EvaluationPendingList>('/api/evaluations/pending')
    setItems(response.items)
  }

  async function loadDetail(id:number) {
    setDetail(await apiJson<FinalResultDetail>(`/api/run-enrollments/${id}/final-result`))
  }

  async function selectEnrollment(value:string) {
    setSelectedId(value);setDetail(null);setNotice('');setError('')
    if (value) try { await loadDetail(Number(value)) } catch (error) { showError(error) }
  }

  async function refresh() {
    await Promise.all([loadItems(),loadDetail(Number(selectedId))])
    onSaved()
  }

  async function saveResult(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();setSaving(true);setNotice('');setError('')
    const form = new FormData(event.currentTarget)
    const body:FinalResultBody = {
      final_level_id:Number(form.get('final_level_id')),
      passed:form.get('passed')==='on',
      next_course_id:form.get('next_course_id')?Number(form.get('next_course_id')):null,
      teacher_notes:String(form.get('teacher_notes')||'').trim()||null,
      correction_reason:detail?.latest_result?String(form.get('correction_reason')||'').trim()||null:null,
    }
    try {
      const result=await apiJson<FinalResultResult>(`/api/run-enrollments/${selectedId}/final-result`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:JSON.stringify(body)})
      await refresh();setNotice(`Final result saved as version ${result.version_number}.`)
    } catch(error){showError(error)} finally{setSaving(false)}
  }

  async function saveOverride(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();setSaving(true);setNotice('');setError('')
    const form=new FormData(event.currentTarget)
    const body:EligibilityOverrideBody={eligible:form.get('eligible')==='true',reason:String(form.get('reason')||'').trim()}
    try {
      await apiJson<EligibilityOverrideResult>(`/api/run-enrollments/${selectedId}/exam-eligibility-override`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:JSON.stringify(body)})
      await refresh();setNotice('Eligibility override saved.')
    } catch(error){showError(error)} finally{setSaving(false)}
  }

  async function applyCompletion(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();setSaving(true);setNotice('');setError('')
    const form=new FormData(event.currentTarget)
    const action=String(form.get('action')) as CompletionActionBody['action']
    const body:CompletionActionBody={action,reason:action==='reject'?String(form.get('reason')||'').trim()||null:null}
    try {
      const result=await apiJson<CompletionActionResult>(`/api/run-enrollments/${selectedId}/completion-confirmation`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:JSON.stringify(body)})
      await refresh();setNotice(result.completion_status==='suggested'?'Completion suggested.':result.completion_status==='confirmed'?'Completion confirmed.':'Completion rejected.')
    } catch(error){showError(error)} finally{setSaving(false)}
  }

  return <section><div className="section-heading"><div><p className="eyebrow">Final-result workspace</p><h2>Final results</h2></div></div>
    {notice&&<p className="success-notice" role="status">{notice}</p>}{error&&<p role="alert">{error}</p>}
    <div className="evaluation-picker"><label>Learner and course<select value={selectedId} onChange={event=>void selectEnrollment(event.target.value)}><option value="">Select learner and course</option>{items.map(item=><option key={item.run_enrollment_id} value={item.run_enrollment_id}>{item.full_name} · {item.class_code} · {item.course_code} · Run {item.run_number}</option>)}</select></label></div>
    {detail&&<><div className="evaluation-summary"><article><span>Attendance</span><strong>{Math.round(detail.eligibility.attendance_ratio*100)}% attendance</strong><small>{detail.eligibility.present_units} / {detail.eligibility.applicable_units} units</small></article><article><span>Exam eligibility</span><strong>{detail.eligibility.effective_exam_eligible?'Eligible':'Not eligible'}</strong><small>{detail.eligibility.exam_eligibility_override?'Admin override':'Attendance rule'}</small></article><article><span>Result version</span><strong>{detail.latest_result?.version_number??'Not recorded'}</strong><small>{detail.latest_result?.passed===true?'Passed':detail.latest_result?.passed===false?'Not passed':'Pending'}</small></article><article><span>Completion</span><strong>{detail.completion?.status??'Not suggested'}</strong><small>{detail.enrollment.enrollment_status}</small></article></div>
      <div className="evaluation-actions"><form onSubmit={saveResult}><h3>Record or correct final result</h3><label>Final level<select name="final_level_id" defaultValue={detail.latest_result?.final_level_id??''} required><option value="">Select final level</option>{detail.options.levels.map(level=><option key={level.level_id} value={level.level_id}>{level.level_name}</option>)}</select></label><label className="check-label"><input name="passed" type="checkbox" defaultChecked={detail.latest_result?.passed??false}/>Passed</label><label>Next course<select name="next_course_id" defaultValue={detail.latest_result?.next_course_id??''}><option value="">No next course</option>{detail.options.courses.map(course=><option key={course.course_id} value={course.course_id}>{course.course_code} · {course.course_name}</option>)}</select></label><label>Teacher notes<textarea name="teacher_notes" defaultValue={detail.latest_result?.teacher_notes??''}/></label>{detail.latest_result&&<label>Correction reason<input name="correction_reason" required /></label>}<div className="form-actions"><button disabled={saving}>{saving?'Saving…':'Save final result'}</button></div></form>
        {role==='admin'&&<form onSubmit={saveOverride}><h3>Exam eligibility exception</h3><label>Eligibility decision<select name="eligible" defaultValue={String(detail.eligibility.effective_exam_eligible)}><option value="true">Eligible</option><option value="false">Not eligible</option></select></label><label>Override reason<input name="reason" required /></label><div className="form-actions"><button disabled={saving}>Save eligibility override</button></div></form>}
        <form onSubmit={applyCompletion}><h3>Course completion</h3><label>Completion action<select name="action" defaultValue="suggest"><option value="suggest">Suggest</option>{role==='admin'&&<><option value="confirm">Confirm</option><option value="reject">Reject</option></>}</select></label><label>Rejection reason<input name="reason" /></label><div className="form-actions"><button disabled={saving}>Apply completion action</button></div></form>
      </div>
      <section className="evaluation-history"><h3>Version history</h3>{detail.history.length===0?<p className="notice">No final result has been recorded.</p>:<div className="table-wrap"><table><thead><tr><th>Version</th><th>Result</th><th>Eligibility</th><th>Actor</th><th>Reason</th></tr></thead><tbody>{detail.history.map(item=><tr key={item.evaluation_version_id}><td>{item.version_number}</td><td>{item.final_level_name??'—'} · {item.passed?'Passed':'Not passed'}</td><td>{item.exam_eligible?'Eligible':'Not eligible'}{item.exam_eligibility_override?' · override':''}</td><td>{item.created_by_username??'System'}</td><td>{item.correction_reason??'—'}</td></tr>)}</tbody></table></div>}</section>
    </>}
  </section>
}
