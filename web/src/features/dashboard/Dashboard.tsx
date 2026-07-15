import { useEffect, useState } from 'react'
import { apiJson, type DashboardData } from '../../api/client'

const summaryLabels: Record<string, string> = {
  active_employees: 'Active employees',
  active_learners: 'Active learners',
  open_course_runs: 'Open course runs',
  operational_issues: 'Review items',
  high_issues: 'Urgent items',
  open_quality_issues: 'Open follow-ups',
}

const hrLabels: Record<string, string> = {
  active_people: 'Active people',
  current_learners: 'Current learners',
  open_classes: 'Open classes',
  review_items: 'Review items',
  urgent_items: 'Urgent items',
  follow_ups: 'Follow-ups',
}

function Metrics({ values, labels }: { values: Record<string, number>; labels: Record<string, string> }) {
  return <div className="metrics">{Object.entries(values).map(([key, value]) => (
    <article className="metric" key={key}><span>{labels[key] ?? key}</span><strong>{value}</strong></article>
  ))}</div>
}

export function Dashboard({ canAccessHr }: { canAccessHr: boolean }) {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    apiJson<DashboardData>('/api/dashboard').then(setData).catch(error => setError(error.message))
  }, [])

  if (error) return <p role="alert">{error}</p>
  if (!data) return <p aria-live="polite">Loading dashboard…</p>
  return <section>
    <div className="section-heading"><div><p className="eyebrow">Overview</p><h2>{canAccessHr ? 'HR home' : 'Workspace summary'}</h2></div></div>
    {data.hr_home ? <Metrics values={data.hr_home} labels={hrLabels} /> : <Metrics values={data.summary} labels={summaryLabels} />}
    {!canAccessHr && <p className="notice">HR learner data is restricted. Your approved reporting access remains unchanged during the side-by-side migration.</p>}
  </section>
}
