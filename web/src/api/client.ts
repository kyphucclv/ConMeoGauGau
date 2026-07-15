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
