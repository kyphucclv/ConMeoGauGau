# English Class domain context

This glossary defines the shared business language for this repository and for
the English-training part of a ConCho2 integration. Field-level rules remain
canonical in `DATA_DICTIONARY.md`; entity grain and invariants remain canonical
in `TARGET_ARCHITECTURE.md`.

## Employee

A person known by the company. `emp_code` is the stable business identity;
names and email addresses are attributes, never identifiers.

_Avoid:_ learner record, student identity, user account. A learner is an
Employee participating in training, while an application user is an account
used to sign in and act.

## Organization assignment

One observed period in which an Employee belongs to a business unit and job
role. Changing organization closes the old period and creates a new one.

_Avoid:_ current BU copied everywhere. A Run Enrollment keeps a separate,
immutable organization snapshot for historical reporting.

## Cohort

A stable learning group identified by `class_code`. A Cohort can study several
Courses over time and can repeat a Course through another Course Run.

_Avoid:_ course, course delivery, meeting. A ConCho2 `Class` is not assumed to
be equivalent until its grain has been checked.

## Cohort membership

One continuous period in which an Employee belongs to one Cohort. A transfer
closes the source membership and creates and links the target membership.

_Avoid:_ enrollment. Membership answers "which stable group?"; Run Enrollment
answers "which delivery of which course?".

## PIC assignment

One period of ownership for a Cohort. The PIC may be an Employee or a
normalized team label; it does not have to be an application user.

_Avoid:_ teacher assignment, learner identity.

## Course

A reusable course definition with current defaults such as expected credited
units and attendance threshold. Those defaults are snapshotted into each new
Course Run.

_Avoid:_ Course Run, Cohort.

## Course Run

One numbered delivery of one Course to one Cohort. Repeating the same Course
creates a new Course Run rather than overwriting or reusing the earlier one.

_Avoid:_ `class_code + course_name` as an identifier, because the same Cohort
may repeat the same Course.

## Run Enrollment

One Employee's participation in one Course Run. It records the first
applicable session and immutable organization snapshots. An Employee may have
at most one active Run Enrollment across all runs.

_Avoid:_ Cohort Membership, current employee profile, Sessions before the
first applicable session counted as absences.

## Meeting

One scheduled or delivered gathering with a real start time, duration, and
status.

_Avoid:_ Session Unit. A two-hour Meeting can contain two credited Session
Units, and a credited sequence can have another occurrence for make-up work.

## Session Unit

One credited logical unit inside a Meeting. Its sequence controls enrollment
applicability and the attendance denominator.

_Avoid:_ Meeting duration, calendar event.

## Attendance fact

One Run Enrollment's effective Present or Absent result for one applicable
Session Unit. The event-time roster, not today's Cohort membership, determines
who belongs in the fact set.

_Avoid:_ a mutable current attendance total, a fact keyed only by employee and
meeting.

## Make-up credit

A later Present Attendance fact on a make-up Session Unit that links to one
original direct Absent fact. The original absence remains unchanged; the link
credits its logical sequence and adds no denominator unit.

_Avoid:_ changing the original absence to Present, adding a bonus attendance
unit, or deleting the link during correction.

## Placement

An initial or diagnostic assessment that places an Employee at a Level. It is
not the final result of a Course Run.

_Avoid:_ Evaluation.

## Evaluation

The identity of a Course Run result for one Run Enrollment. Its corrections
are stored as immutable Evaluation Versions.

_Avoid:_ editing the latest result row in place.

## Evaluation Version

One immutable version of the teacher's final level, pass result, next-course
decision, notes, eligibility override, and correction context. Version 2 and
later require a correction reason.

_Avoid:_ client-assigned version numbers, current level inferred from the
highest historical level.

## Exam eligibility

A derived result based on attendance over applicable, non-cancelled,
non-make-up units. An admin may override it only with actor, reason, previous
result, and time retained.

_Avoid:_ pass result. Passing and next-course eligibility are teacher
Evaluation decisions.

## Completion

A lifecycle decision that is first suggested and then explicitly confirmed or
rejected by an authorized user. It is not implied merely by recording an
Evaluation.

_Avoid:_ automatic irreversible completion.

## Audit event

An immutable record of who performed a named business action, when, against
which entity, and with safe before/after context. The server creates it inside
the same transaction as the business change.

_Avoid:_ accepting actor identity from the browser, best-effort asynchronous
audit for canonical English business changes.

## Data-quality issue

A durable, machine-coded record explaining why source data could not yet be
represented canonically. Resolution retains the original issue, action, actor,
and time.

_Avoid:_ warning-only logs or silently converting unknown values to null.

## Source-row outcome

The auditable result of processing one imported source row: represented in a
canonical entity, retained in staging, recorded as a Data-quality issue, or
ignored by an approved rule.

_Avoid:_ dropped source rows.
