"""Exam eligibility, evaluation versioning, completion, and monthly summary commands.

Split verbatim from the original services.py; behavior unchanged.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

import psycopg2
import psycopg2.extras

from services.base import CommandError, CommandResult, _json_safe, _normalize_label, _required


class EvaluationCompletionCommands:
    def save_monthly_action_summary(self, review_month: date, *, highlights: str, risks: str, next_month_priorities: str) -> CommandResult:
        """Persist only an explicitly saved HR conclusion as an immutable version."""
        def op(cur):
            if review_month.day != 1:
                raise CommandError("invalid_input", "review month must be the first day of the month")
            self._advisory_lock(cur, f"monthly_review_action_summary:{review_month.isoformat()}")
            cur.execute("SELECT COALESCE(MAX(version_number),0)+1 FROM monthly_review_action_summary_versions WHERE review_month=%s", (review_month,))
            version_number = cur.fetchone()[0]
            cur.execute("""INSERT INTO monthly_review_action_summary_versions(
                           review_month,version_number,highlights,risks,next_month_priorities,created_by_user_id
                         ) VALUES(%s,%s,%s,%s,%s,%s) RETURNING monthly_review_action_summary_version_id""",
                        (review_month, version_number, highlights.strip(), risks.strip(), next_month_priorities.strip(), self.actor_user_id))
            entity_id = cur.fetchone()[0]
            self._audit(cur, "monthly_review.action_summary.save", "monthly_review_action_summary", entity_id,
                        {"review_month": review_month.isoformat(), "version_number": version_number})
            return CommandResult("monthly_review_action_summary", entity_id, {"review_month": review_month, "version_number": version_number})
        return self._run({"admin", "editor"}, op)

    def calculate_exam_eligibility(self, run_enrollment_id: int) -> CommandResult:
        def op(cur):
            values = self._eligibility_in_tx(cur, run_enrollment_id)
            return CommandResult("run_enrollment", run_enrollment_id, values)
        return self._run({"admin","editor","viewer"},op)

    def override_exam_eligibility(self, run_enrollment_id: int, eligible: bool, reason: str) -> CommandResult:
        def op(cur):
            _required(reason,"reason")
            cur.execute("""INSERT INTO evaluations(run_enrollment_id) VALUES(%s) ON CONFLICT(run_enrollment_id) DO UPDATE SET run_enrollment_id=EXCLUDED.run_enrollment_id RETURNING evaluation_id""",(run_enrollment_id,)); evaluation_id=cur.fetchone()[0]
            self._advisory_lock(cur, f"evaluation_version:{evaluation_id}")
            calc = self._eligibility_in_tx(cur, run_enrollment_id)
            version = self._next_evaluation_version(cur, evaluation_id)
            cur.execute("""INSERT INTO evaluation_versions(evaluation_id,version_number,exam_eligible,exam_eligibility_override,exam_eligibility_override_reason,created_by_user_id,correction_reason)
                         VALUES(%s,%s,%s,TRUE,%s,%s,%s) RETURNING evaluation_version_id""",(evaluation_id,version,eligible,reason,self.actor_user_id,"eligibility override" if version>1 else None))
            entity_id=cur.fetchone()[0]; self._audit(cur,"eligibility.override","evaluation_version",entity_id,{"previous":calc,"eligible":eligible,"reason":reason}); return CommandResult("evaluation_version",entity_id,{"exam_eligible":eligible,"previous":calc})
        return self._run({"admin"},op)

    def _eligibility_in_tx(self, cur, enrollment_id):
        cur.execute("""SELECT applicable_units,present_units,
                              COALESCE(attendance_ratio,0::numeric),calculated_exam_eligible
                       FROM v_run_enrollment_attendance WHERE run_enrollment_id=%s""", (enrollment_id,))
        attendance = cur.fetchone()
        if not attendance:
            raise CommandError("not_found", "enrollment not found")
        total, present, ratio, calculated = attendance
        cur.execute(
            """SELECT ev.exam_eligible,ev.exam_eligibility_override,
                      ev.exam_eligibility_override_reason,ev.version_number
               FROM evaluations e JOIN evaluation_versions ev ON ev.evaluation_id=e.evaluation_id
               WHERE e.run_enrollment_id=%s
               ORDER BY ev.version_number DESC LIMIT 1""",
            (enrollment_id,),
        )
        latest = cur.fetchone()
        has_override = bool(latest and latest[1])
        effective = bool(latest[0]) if has_override else calculated
        return {
            "applicable_units": total,
            "present_units": present,
            "attendance_ratio": ratio,
            "calculated_exam_eligible": bool(calculated),
            "effective_exam_eligible": effective,
            "exam_eligible": effective,
            "exam_eligibility_override": has_override,
            "exam_eligibility_override_reason": latest[2] if has_override else None,
            "latest_evaluation_version": latest[3] if latest else None,
        }

    def record_evaluation(self, run_enrollment_id: int, *, final_level_id=None, passed=None, next_course_id=None,
                          exam_eligible=None, teacher_notes=None, correction_reason=None) -> CommandResult:
        def op(cur):
            if exam_eligible is not None:
                raise CommandError(
                    "invalid_input",
                    "exam eligibility is calculated; use the authorized override action when needed",
                )
            cur.execute("INSERT INTO evaluations(run_enrollment_id) VALUES(%s) ON CONFLICT(run_enrollment_id) DO UPDATE SET run_enrollment_id=EXCLUDED.run_enrollment_id RETURNING evaluation_id",(run_enrollment_id,)); evaluation_id=cur.fetchone()[0]
            self._advisory_lock(cur, f"evaluation_version:{evaluation_id}")
            eligibility = self._eligibility_in_tx(cur, run_enrollment_id)
            version = self._next_evaluation_version(cur, evaluation_id)
            reason = _normalize_label(correction_reason)
            if version > 1 and not reason:
                raise CommandError("invalid_input", "correction reason is required for an updated final result")
            cur.execute(
                """SELECT exam_eligibility_override,exam_eligibility_override_reason
                   FROM evaluation_versions
                   WHERE evaluation_id=%s
                   ORDER BY version_number DESC LIMIT 1""",
                (evaluation_id,),
            )
            latest = cur.fetchone()
            carry_override = bool(latest and latest[0])
            override_reason = latest[1] if carry_override else None
            cur.execute("""INSERT INTO evaluation_versions(
                              evaluation_id,version_number,final_level_id,exam_eligible,
                              exam_eligibility_override,exam_eligibility_override_reason,
                              passed,next_course_id,teacher_notes,correction_reason,created_by_user_id
                           ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           RETURNING evaluation_version_id""",
                        (evaluation_id,version,final_level_id,eligibility["effective_exam_eligible"],
                         carry_override,override_reason,passed,next_course_id,teacher_notes,reason,self.actor_user_id))
            entity_id = cur.fetchone()[0]
            self._audit(
                cur,
                "evaluation.record" if version == 1 else "evaluation.correct",
                "evaluation_version",
                entity_id,
                {
                    "version_number": version,
                    "correction_reason": reason,
                    "calculated_exam_eligible": eligibility["calculated_exam_eligible"],
                    "effective_exam_eligible": eligibility["effective_exam_eligible"],
                    "exam_eligibility_override": carry_override,
                },
            )
            return CommandResult("evaluation_version", entity_id, {
                "version_number": version,
                "exam_eligible": eligibility["effective_exam_eligible"],
                "exam_eligibility_override": carry_override,
            })
        return self._run({"admin","editor"},op)

    def suggest_completion(self, run_enrollment_id: int) -> CommandResult:
        def op(cur):
            eligibility=self._eligibility_in_tx(cur,run_enrollment_id)
            cur.execute("""SELECT ev.passed,ev.next_course_id,ev.exam_eligible,ev.exam_eligibility_override
                         FROM evaluations e JOIN evaluation_versions ev ON ev.evaluation_id=e.evaluation_id
                         WHERE e.run_enrollment_id=%s ORDER BY ev.version_number DESC LIMIT 1""",(run_enrollment_id,)); evaluation=cur.fetchone()
            effective_eligible = bool(evaluation[2]) if evaluation and evaluation[2] is not None else eligibility["exam_eligible"]
            suggested=bool(evaluation and evaluation[0] is True and effective_eligible)
            cur.execute("""INSERT INTO course_completion_suggestions(run_enrollment_id,suggested,reason) VALUES(%s,%s,%s)
                         ON CONFLICT(run_enrollment_id) DO UPDATE SET suggested=EXCLUDED.suggested,reason=EXCLUDED.reason,status='suggested',confirmed_by_user_id=NULL,confirmed_at=NULL
                         RETURNING completion_suggestion_id""",(run_enrollment_id,suggested,psycopg2.extras.Json(_json_safe({"eligibility":eligibility,"effective_exam_eligible":effective_eligible,"evaluation_present":bool(evaluation)}))))
            entity_id=cur.fetchone()[0]; self._audit(cur,"completion.suggest","completion_suggestion",entity_id,{"suggested":suggested}); return CommandResult("completion_suggestion",entity_id,{"suggested":suggested,"reason":eligibility})
        return self._run({"admin","editor"},op)

    def confirm_completion(self, run_enrollment_id: int, confirmed: bool, reason: str | None = None) -> CommandResult:
        def op(cur):
            if not confirmed and not reason: raise CommandError("invalid_input","reason is required when rejecting completion")
            cur.execute("UPDATE course_completion_suggestions SET status=%s,confirmed_by_user_id=%s,confirmed_at=NOW() WHERE run_enrollment_id=%s RETURNING completion_suggestion_id",("confirmed" if confirmed else "rejected",self.actor_user_id,run_enrollment_id)); row=cur.fetchone()
            if not row: raise CommandError("invalid_state","completion must be suggested before confirmation")
            cur.execute("UPDATE run_enrollments SET status='completed' WHERE run_enrollment_id=%s AND %s",(run_enrollment_id,confirmed))
            self._audit(cur,"completion.confirm","completion_suggestion",row[0],{"confirmed":confirmed,"reason":reason}); return CommandResult("completion_suggestion",row[0],{"confirmed":confirmed})
        return self._run({"admin"},op)
