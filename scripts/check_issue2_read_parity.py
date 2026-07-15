"""Compare Issue #2 endpoint reads with the current Streamlit read model."""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.learner_reads import LearnerReadService
from db import create_pool
from frontend_queries import learner_directory_rows


FIELDS = (
    "employee_id", "emp_code", "full_name", "employment_status",
    "business_unit_name", "job_role_name", "class_code", "course_name",
    "course_code", "enrollment_status", "attendance_ratio", "entrance_level", "pic",
)


def comparable(value):
    return float(value) if isinstance(value, Decimal) else value


def main() -> None:
    database_url = os.getenv("APP_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("APP_DATABASE_URL is required")
    pool = create_pool(database_url, application_name="issue2_read_parity")
    try:
        legacy = learner_directory_rows(pool)
        service = LearnerReadService(pool)
        endpoint = []
        page = 1
        while True:
            response = service.search(
                q="", learning_status="all", class_code=None, course=None,
                pic=None, business_unit=None, job_role=None, page=page, page_size=100,
            )
            endpoint.extend(item.model_dump() for item in response.items)
            if len(endpoint) >= response.total:
                break
            page += 1

        if len(legacy) != len(endpoint):
            raise AssertionError(
                f"Legacy snapshot has {len(legacy)} rows but endpoint has {len(endpoint)}; "
                "the legacy 500-row cap may need a separately approved comparison strategy."
            )
        endpoint_by_id = {row["employee_id"]: row for row in endpoint}
        mismatches = []
        for old in legacy:
            new = endpoint_by_id.get(old["employee_id"])
            if new is None:
                mismatches.append({"employee_id": old["employee_id"], "field": "missing"})
                continue
            for field in FIELDS:
                if comparable(old[field]) != comparable(new[field]):
                    mismatches.append({"employee_id": old["employee_id"], "field": field})
        if mismatches:
            raise AssertionError(f"Read parity mismatches: {mismatches[:10]}")
        print(json.dumps({
            "status": "pass",
            "legacy_rows": len(legacy),
            "endpoint_rows": len(endpoint),
            "fields_compared": list(FIELDS),
        }, indent=2))
    finally:
        pool.closeall()


if __name__ == "__main__":
    main()
