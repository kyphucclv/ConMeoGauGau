"""Password hashing work factor and backward compatibility (no database)."""

from __future__ import annotations

import base64
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auth import hash_password, verify_password


def test_new_hashes_use_owasp_work_factor():
    stored = hash_password("s3cret-pass")
    algorithm, iterations, _, _ = stored.split("$", 3)
    assert algorithm == "pbkdf2_sha256"
    assert int(iterations) >= 600000
    assert verify_password("s3cret-pass", stored)
    assert not verify_password("wrong-pass", stored)


def test_legacy_150k_hashes_still_verify():
    # Simulate a hash written before the work-factor bump: the iteration
    # count is embedded in the stored value, so verification must succeed.
    iterations = 150000
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", b"old-password", salt, iterations)
    legacy = "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(derived).decode("ascii"),
    )
    assert verify_password("old-password", legacy)
    assert not verify_password("other-password", legacy)


def test_malformed_hashes_are_rejected_not_crashing():
    assert not verify_password("anything", "not-a-hash")
    assert not verify_password("anything", "md5$1$abc$def")
