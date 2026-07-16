import type { components } from './schema'

type Schemas = components['schemas']

export type Auth = Schemas['AuthResponse']
export type DashboardData = Schemas['DashboardResponse']
export type LearnerPage = Schemas['LearnerPage']
export type LearnerDetail = Schemas['LearnerDetail']
export type ProfileOptions = Schemas['ProfileOptions']
export type ProfileUpdateBody = Schemas['ProfileUpdateBody']
export type ProfileUpdateResult = Schemas['ProfileUpdateResult']
export type LearnerStartOptions = Schemas['LearnerStartOptions']
export type LearnerStartBody = Schemas['LearnerStartBody']
export type LearnerStartResult = Schemas['LearnerStartResult']
export type LearnerTransferOptions = Schemas['LearnerTransferOptions']
export type LearnerTransferBody = Schemas['LearnerTransferBody']
export type LearnerTransferResult = Schemas['LearnerTransferResult']
export type AttendanceCourseRuns = Schemas['AttendanceCourseRuns']
export type AttendanceSessionUnits = Schemas['AttendanceSessionUnits']
export type AttendanceSessionBody = Schemas['AttendanceSessionBody']
export type AttendanceSessionResult = Schemas['AttendanceSessionResult']
export type AttendanceRoster = Schemas['AttendanceRoster']
export type AttendanceRosterBody = Schemas['AttendanceRosterBody']
export type AttendanceRosterResult = Schemas['AttendanceRosterResult']
export type MakeupOptions = Schemas['MakeupOptions']
export type MakeupCreditBody = Schemas['MakeupCreditBody']
export type MakeupCreditResult = Schemas['MakeupCreditResult']
export type EvaluationPendingList = Schemas['EvaluationPendingList']
export type FinalResultDetail = Schemas['FinalResultDetail']
export type FinalResultBody = Schemas['FinalResultBody']
export type FinalResultResult = Schemas['FinalResultResult']
export type EligibilityOverrideBody = Schemas['EligibilityOverrideBody']
export type EligibilityOverrideResult = Schemas['EligibilityOverrideResult']
export type CompletionActionBody = Schemas['CompletionActionBody']
export type CompletionActionResult = Schemas['CompletionActionResult']
export type MonthlyReviewResponse = Schemas['MonthlyReviewResponse']
export type MonthlyActionSummaryBody = Schemas['MonthlyActionSummaryBody']
export type MonthlyActionSummaryResult = Schemas['MonthlyActionSummaryResult']
export type OperationalIssuePage = Schemas['OperationalIssuePage']
export type QualityIssuePage = Schemas['QualityIssuePage']
export type RemediationResult = Schemas['RemediationResult']
export type AdministrationOptions = Schemas['AdministrationOptions']
export type ClassPage = Schemas['ClassPage']
export type CourseRunPage = Schemas['CourseRunPage']
export type SchedulePage = Schemas['SchedulePage']
export type AdministrationCommandResult = Schemas['AdministrationCommandResult']
export type ReportCatalog = Schemas['ReportCatalog']
export type ReportPage = Schemas['ReportPage']
export type AuditEventPage = Schemas['AuditEventPage']

type ErrorEnvelope = { message?: string }

export async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    let message = 'Request failed'
    try {
      message = ((await response.json()) as ErrorEnvelope).message || message
    } catch {
      // Non-JSON proxy errors still get a safe client message.
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}
