import { FormEvent, useEffect, useState } from 'react'
import { apiJson, type AttendanceCourseRuns, type AttendanceRoster, type AttendanceRosterBody, type AttendanceRosterResult, type AttendanceSessionBody, type AttendanceSessionResult, type AttendanceSessionUnits } from '../../api/client'
import './attendance.css'

type Status = 'Present' | 'Absent' | ''

function localDateTimeValue() {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

export function AttendanceWorkspace({csrfToken,onSaved}:{csrfToken:string;onSaved:()=>void}) {
  const [runs, setRuns] = useState<AttendanceCourseRuns['items']>([])
  const [selectedRunId, setSelectedRunId] = useState('')
  const [units, setUnits] = useState<AttendanceSessionUnits['items']>([])
  const [selectedUnitId, setSelectedUnitId] = useState('')
  const [roster, setRoster] = useState<AttendanceRoster | null>(null)
  const [statuses, setStatuses] = useState<Record<number,Status>>({})
  const [creating, setCreating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    apiJson<AttendanceCourseRuns>('/api/attendance/course-runs').then(response => setRuns(response.items)).catch(showError)
  }, [])

  function showError(value: unknown) {
    setError(value instanceof Error ? value.message : 'Attendance request failed')
  }

  async function loadRoster(courseRunId: number, sessionUnitId: number) {
    const response = await apiJson<AttendanceRoster>(`/api/course-runs/${courseRunId}/session-units/${sessionUnitId}/roster`)
    setRoster(response)
    setStatuses(Object.fromEntries(response.rows.map(row => [row.run_enrollment_id, row.effective_status ?? ''])))
  }

  async function loadUnits(courseRunId: number, preferredUnitId?: number) {
    const response = await apiJson<AttendanceSessionUnits>(`/api/course-runs/${courseRunId}/session-units`)
    setUnits(response.items)
    if (preferredUnitId) {
      setSelectedUnitId(String(preferredUnitId))
      await loadRoster(courseRunId, preferredUnitId)
    }
  }

  async function selectRun(value: string) {
    setSelectedRunId(value); setSelectedUnitId(''); setRoster(null); setCreating(false); setNotice(''); setError('')
    if (value) try { await loadUnits(Number(value)) } catch (error) { showError(error) }
    else setUnits([])
  }

  async function selectUnit(value: string) {
    setSelectedUnitId(value); setRoster(null); setNotice(''); setError('')
    if (value && selectedRunId) try { await loadRoster(Number(selectedRunId), Number(value)) } catch (error) { showError(error) }
  }

  async function createSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError(''); setNotice('')
    const form = new FormData(event.currentTarget)
    const run = runs.find(item => item.course_run_id === Number(selectedRunId))
    const body: AttendanceSessionBody = {
      starts_at: new Date(String(form.get('starts_at'))).toISOString(),
      duration_minutes: Number(form.get('duration_minutes')),
      confirmed_sequence_in_run: run?.next_sequence_in_run ?? 0,
    }
    try {
      const result = await apiJson<AttendanceSessionResult>(`/api/course-runs/${selectedRunId}/attendance-sessions`, {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:JSON.stringify(body)})
      setCreating(false)
      await loadUnits(Number(selectedRunId), result.session_unit_id)
    } catch (error) { showError(error) }
    finally { setSaving(false) }
  }

  async function saveRoster() {
    if (!roster || Object.values(statuses).some(status => !status)) return
    setSaving(true); setError(''); setNotice('')
    const body: AttendanceRosterBody = {
      roster_token: roster.roster_token,
      records: roster.rows.map(row => ({run_enrollment_id:row.run_enrollment_id,effective_status:statuses[row.run_enrollment_id] as 'Present'|'Absent'})),
    }
    try {
      await apiJson<AttendanceRosterResult>(`/api/course-runs/${roster.course_run_id}/session-units/${roster.session_unit_id}/roster`, {method:'PUT',headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:JSON.stringify(body)})
      await Promise.all([loadRoster(roster.course_run_id, roster.session_unit_id), loadUnits(roster.course_run_id)])
      setNotice('Attendance saved.')
      onSaved()
    } catch (error) { showError(error) }
    finally { setSaving(false) }
  }

  const selectedRun = runs.find(item => item.course_run_id === Number(selectedRunId))
  const present = Object.values(statuses).filter(status => status === 'Present').length
  const absent = Object.values(statuses).filter(status => status === 'Absent').length
  const missing = Object.values(statuses).filter(status => !status).length

  return <section><div className="section-heading"><div><p className="eyebrow">Attendance workspace</p><h2>Attendance</h2></div></div>
    {notice && <p className="success-notice" role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
    <div className="attendance-selectors">
      <label>Class and course<select value={selectedRunId} onChange={event => void selectRun(event.target.value)}><option value="">Select class and course</option>{runs.map(run => <option key={run.course_run_id} value={run.course_run_id}>{run.class_code} · {run.course_name} · Run {run.run_number}</option>)}</select></label>
      <label>Session<select value={selectedUnitId} onChange={event => void selectUnit(event.target.value)} disabled={!selectedRunId}><option value="">Select session</option>{units.map(unit => <option key={unit.session_unit_id} value={unit.session_unit_id}>Session {unit.sequence_in_run} · {new Date(unit.starts_at).toLocaleString()} · {unit.meeting_status}</option>)}</select></label>
      <button type="button" onClick={() => setCreating(true)} disabled={!selectedRunId}>Create session</button>
    </div>
    {selectedRunId && units.length === 0 && !creating && <p className="notice">This class has no attendance sessions yet.</p>}
    {creating && selectedRun && <form className="attendance-create" onSubmit={createSession}><h3>Create session</h3><div className="confirmation-summary"><strong>Next credited session</strong><span>{selectedRun.class_code} · {selectedRun.course_name}</span><span>Session {selectedRun.next_sequence_in_run}</span></div><label>Session start<input name="starts_at" type="datetime-local" defaultValue={localDateTimeValue()} required /></label><label>Duration minutes<input name="duration_minutes" type="number" min="1" max="1440" defaultValue="60" required /></label><div className="form-actions"><button disabled={saving}>{saving?'Creating…':'Confirm session'}</button><button type="button" className="secondary" onClick={() => setCreating(false)}>Cancel</button></div></form>}
    {roster && <section className="attendance-roster"><div className="attendance-summary"><div><span>Session</span><strong>{roster.sequence_in_run}</strong></div><div><span>Status</span><strong>{roster.meeting_status === 'completed'?'Completed':'Planned'}</strong></div><div><span>Learners</span><strong>{roster.rows.length}</strong></div></div><div className="attendance-counts"><strong>{present} present</strong><strong>{absent} absent</strong>{missing>0 && <strong>{missing} needs entry</strong>}</div><div className="table-wrap"><table><thead><tr><th>Learner</th><th>Joined at session</th><th>Attendance</th></tr></thead><tbody>{roster.rows.map(row => <tr key={row.run_enrollment_id}><td>{row.full_name}<small>{row.emp_code}</small></td><td>{row.start_session_number}</td><td><label className="sr-only" htmlFor={`attendance-${row.run_enrollment_id}`}>Attendance for {row.emp_code}</label><select id={`attendance-${row.run_enrollment_id}`} value={statuses[row.run_enrollment_id]??''} onChange={event => setStatuses(current => ({...current,[row.run_enrollment_id]:event.target.value as Status}))}><option value="">Select attendance</option><option value="Present">Present</option><option value="Absent">Absent</option></select></td></tr>)}</tbody></table></div><div className="form-actions"><button type="button" onClick={() => void saveRoster()} disabled={saving || missing>0 || roster.rows.length===0}>{saving?'Saving…':'Save attendance'}</button></div></section>}
  </section>
}
