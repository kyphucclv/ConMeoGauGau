"""Export the deterministic FastAPI schema consumed by the React client."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.main import Settings, create_app


def main() -> None:
    destination = ROOT / "web" / "openapi.json"
    app = create_app(
        Settings(
            database_url="postgresql://schema-export.invalid/english_class",
            origin="http://schema-export.invalid",
            secure_cookie=False,
            serve_static=False,
        )
    )
    destination.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Exported {destination.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
