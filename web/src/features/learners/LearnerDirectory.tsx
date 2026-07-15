import { FormEvent, useCallback, useEffect, useState } from 'react'
import { apiJson, type LearnerDetail, type LearnerPage, type ProfileOptions, type ProfileUpdateBody, type ProfileUpdateResult } from '../../api/client'

type Filters = {
  q: string
  learning_status: 'all' | 'current' | 'not_current'
  class_code: string
  course: string
  pic: string
  business_unit: string
  job_role: string
}

const initialFilters: Filters = { q:'', learning_status:'all', class_code:'', course:'', pic:'', business_unit:'', job_role:'' }

function display(value: string | number | boolean | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

export function LearnerDirectory({ csrfToken, onProfileSaved }: { csrfToken: string; onProfileSaved: () => void }) {
  const [draft, setDraft] = useState<Filters>(initialFilters)
  const [filters, setFilters] = useState<Filters>(initialFilters)
  const [page, setPage] = useState(1)
  const [results, setResults] = useState<LearnerPage | null>(null)
  const [detail, setDetail] = useState<LearnerDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async (nextPage: number, activeFilters: Filters) => {
    setLoading(true); setError('')
    const params = new URLSearchParams({ page:String(nextPage), page_size:'20', learning_status:activeFilters.learning_status })
    Object.entries(activeFilters).forEach(([key, value]) => { if (key !== 'learning_status' && value) params.set(key, value) })
    try { setResults(await apiJson<LearnerPage>(`/api/learners?${params}`)) }
    catch (error) { setError(error instanceof Error ? error.message : 'Could not load learners') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { void load(page, filters) }, [filters, load, page])

  function search(event: FormEvent) {
    event.preventDefault()
    setPage(1)
    setFilters({...draft})
  }

  async function openDetail(employeeId: number) {
    setLoading(true); setError('')
    try { setDetail(await apiJson<LearnerDetail>(`/api/learners/${employeeId}`)) }
    catch (error) { setError(error instanceof Error ? error.message : 'Could not load learner') }
    finally { setLoading(false) }
  }

  async function profileSaved(employeeId: number) {
    const updated = await apiJson<LearnerDetail>(`/api/learners/${employeeId}`)
    setDetail(updated)
    setNotice('Profile saved.')
    onProfileSaved()
  }

  if (detail) return <LearnerDetailView detail={detail} csrfToken={csrfToken} notice={notice} onBack={() => { setDetail(null); setNotice('') }} onProfileSaved={profileSaved} />

  return <section>
    <div className="section-heading"><div><p className="eyebrow">HR workspace</p><h2>Learners</h2></div></div>
    <form className="filters" onSubmit={search}>
      <label className="search-field">Search by employee code or name<input value={draft.q} onChange={event => setDraft({...draft,q:event.target.value})} /></label>
      <label>Learning status<select value={draft.learning_status} onChange={event => setDraft({...draft,learning_status:event.target.value as Filters['learning_status']})}><option value="all">All</option><option value="current">Currently learning</option><option value="not_current">Not currently learning</option></select></label>
      <button type="submit">Search</button>
      <details><summary>More filters</summary><div className="filter-grid">
        {(['class_code','course','pic','business_unit','job_role'] as const).map(key => <label key={key}>{key.replaceAll('_',' ')}<input value={draft[key]} onChange={event => setDraft({...draft,[key]:event.target.value})} /></label>)}
      </div></details>
    </form>
    {error && <p role="alert">{error}</p>}
    {loading && <p aria-live="polite">Loading learners…</p>}
    {!loading && results?.items.length === 0 && <div className="empty-state"><h3>No learners found</h3><p>Try a broader search or clear one of the filters.</p></div>}
    {!loading && results && results.items.length > 0 && <>
      <p className="result-count">{results.total} result{results.total === 1 ? '' : 's'}</p>
      <div className="table-wrap"><table><thead><tr><th>Learner</th><th>Status</th><th>Class / course</th><th>Organization</th><th>Attendance</th></tr></thead><tbody>
        {results.items.map(item => <tr key={item.employee_id}><td><button className="link-button" onClick={() => void openDetail(item.employee_id)}>{item.full_name}<small>{item.emp_code}</small></button></td><td>{item.enrollment_status === 'active' ? 'Currently learning' : 'Not currently learning'}</td><td>{display(item.class_code)}<small>{display(item.course_name)}</small></td><td>{display(item.business_unit_name)}<small>{display(item.job_role_name)}</small></td><td>{item.attendance_ratio == null ? '—' : `${Math.round(item.attendance_ratio * 100)}%`}</td></tr>)}
      </tbody></table></div>
      <div className="pagination"><button disabled={page <= 1} onClick={() => setPage(value => value - 1)}>Previous</button><span>Page {page}</span><button disabled={page * results.page_size >= results.total} onClick={() => setPage(value => value + 1)}>Next</button></div>
    </>}
  </section>
}

function LearnerDetailView({detail,csrfToken,notice,onBack,onProfileSaved}:{detail:LearnerDetail;csrfToken:string;notice:string;onBack:()=>void;onProfileSaved:(employeeId:number)=>Promise<void>}) {
  const learner = detail.learner
  const [editing, setEditing] = useState(false)
  const [options, setOptions] = useState<ProfileOptions | null>(null)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)

  async function editProfile() {
    setEditing(true); setFormError('')
    try { setOptions(await apiJson<ProfileOptions>('/api/learners/profile-options')) }
    catch (error) { setFormError(error instanceof Error ? error.message : 'Could not load profile options') }
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setFormError('')
    const form = new FormData(event.currentTarget)
    const body: ProfileUpdateBody = {
      emp_code: learner.emp_code,
      full_name: String(form.get('full_name') ?? ''),
      employment_status: String(form.get('employment_status')) as ProfileUpdateBody['employment_status'],
      business_unit_id: Number(form.get('business_unit_id')),
      job_role_id: Number(form.get('job_role_id')),
      organization_valid_from: String(form.get('organization_valid_from')),
      expected_org_valid_from: learner.current_org_valid_from ?? null,
    }
    try {
      await apiJson<ProfileUpdateResult>(`/api/learners/${learner.employee_id}/profile`, {
        method:'PATCH',
        headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},
        body:JSON.stringify(body),
      })
      await onProfileSaved(learner.employee_id)
      setEditing(false)
    } catch (error) { setFormError(error instanceof Error ? error.message : 'Could not save profile') }
    finally { setSaving(false) }
  }

  return <section><button className="back-button" onClick={onBack}>← Back to learners</button>
    {notice && <p className="success-notice" role="status">{notice}</p>}
    <div className="section-heading"><div><p className="eyebrow">{learner.emp_code}</p><h2>{learner.full_name}</h2></div><div className="heading-actions"><span className="badge">{learner.lifecycle.replaceAll('_',' ')}</span><button onClick={() => void editProfile()}>Edit profile</button></div></div>
    <div className="detail-grid"><article><span>Current class</span><strong>{display(learner.active_class_code)}</strong></article><article><span>Course</span><strong>{display(learner.active_course_name ?? learner.latest_course_name)}</strong></article><article><span>Entrance level</span><strong>{display(learner.entrance_level)}</strong></article><article><span>Business unit</span><strong>{display(learner.business_unit_name)}</strong></article></div>
    {editing && <section className="profile-editor"><h3>Edit profile</h3>{formError && <p role="alert">{formError}</p>}{!options && !formError ? <p aria-live="polite">Loading profile options…</p> : options && <form onSubmit={saveProfile}>
      <label>Employee code<input value={learner.emp_code} disabled /></label>
      <label>Full name<input name="full_name" defaultValue={learner.full_name} required /></label>
      <label>Employment status<select name="employment_status" defaultValue={learner.employment_status}><option value="active">Active</option><option value="inactive">Inactive</option><option value="unknown">Unknown</option></select></label>
      <label>Business unit<select name="business_unit_id" defaultValue={String(learner.business_unit_id ?? '')} required><option value="" disabled>Select business unit</option>{options.business_units.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}</select></label>
      <label>Role<select name="job_role_id" defaultValue={String(learner.job_role_id ?? '')} required><option value="" disabled>Select role</option>{options.job_roles.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}</select></label>
      <label>Organization effective date<input name="organization_valid_from" type="date" defaultValue={learner.current_org_valid_from ?? new Date().toISOString().slice(0,10)} required /></label>
      <div className="form-actions"><button type="submit" disabled={saving}>{saving?'Saving…':'Save profile'}</button><button type="button" className="secondary" onClick={() => { setEditing(false); setFormError('') }}>Cancel</button></div>
    </form>}</section>}
    <h3>Course history</h3>
    {detail.course_history.length === 0 ? <p>No course history.</p> : <div className="table-wrap"><table><thead><tr><th>Started</th><th>Class</th><th>Course</th><th>Status</th><th>Attendance</th><th>Final level</th><th>Passed</th></tr></thead><tbody>{detail.course_history.map((row,index) => <tr key={`${row.start_date}-${row.class_code}-${index}`}><td>{row.start_date}</td><td>{row.class_code}</td><td>{row.course_name}</td><td>{row.status}</td><td>{row.attendance_ratio == null ? '—' : `${Math.round(row.attendance_ratio*100)}%`}</td><td>{display(row.final_level)}</td><td>{display(row.passed)}</td></tr>)}</tbody></table></div>}
    <h3>Change history</h3>
    {detail.audit_summary.length === 0 ? <p>No recorded changes.</p> : <ul className="timeline">{detail.audit_summary.map((row,index) => <li key={`${row.created_at}-${index}`}><strong>{row.action}</strong><span>{row.actor_username} · {new Date(row.created_at).toLocaleString()}</span></li>)}</ul>}
  </section>
}
