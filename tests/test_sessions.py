from db import create_pool
from session_store import SessionStore


def test_session_is_opaque_revocable_and_expires(database_url, seed_ids, conn):
    pool = create_pool(database_url, application_name="pytest_session")
    store = SessionStore(pool)
    try:
        issued = store.create(seed_ids["viewer"])
        assert len(issued.token) >= 43
        assert store.authenticate(issued.token).user.username == "pytest_viewer"
        assert store.csrf_matches(store.authenticate(issued.token), issued.csrf_token)

        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT token_hash FROM app_sessions WHERE user_id = %s ORDER BY app_session_id DESC LIMIT 1", (seed_ids["viewer"],))
                assert cur.fetchone()[0] != issued.token

        store.revoke(issued.token)
        assert store.authenticate(issued.token) is None

        expired = store.create(seed_ids["viewer"])
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE app_sessions SET last_seen_at = NOW() - INTERVAL '61 minutes' WHERE token_hash = %s", (store._digest(expired.token),))
        assert store.authenticate(expired.token) is None
    finally:
        pool.closeall()


def test_session_limit_revokes_oldest(database_url, seed_ids):
    pool = create_pool(database_url, application_name="pytest_session_limit")
    store = SessionStore(pool, max_sessions=2)
    try:
        first = store.create(seed_ids["editor"])
        store.create(seed_ids["editor"])
        store.create(seed_ids["editor"])
        assert store.authenticate(first.token) is None
    finally:
        pool.closeall()
