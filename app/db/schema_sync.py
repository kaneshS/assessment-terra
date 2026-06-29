"""Lightweight SQLite schema sync for dev databases.

SQLAlchemy ``create_all()`` does not alter existing tables. This module adds
missing columns and indexes so older local ``*.db`` files keep working.
"""

from sqlalchemy import Engine, inspect, text

# Columns added after initial schema; table -> {column: SQL type for ALTER TABLE}
_SQLITE_USER_MIGRATIONS: dict[str, dict[str, str]] = {
    "users": {
        "name": "VARCHAR(255)",
        "email": "VARCHAR(255)",
    },
}


def sync_schema(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    with engine.begin() as conn:
        _sync_users_table(conn, inspector, "users" in table_names)
        if "users" in table_names:
            _ensure_users_email_unique_index(conn, inspector)


def _sync_users_table(conn, inspector, table_exists: bool) -> None:
    if not table_exists:
        return

    columns = {col["name"] for col in inspector.get_columns("users")}
    pending = _SQLITE_USER_MIGRATIONS["users"]
    added_any = False

    for column_name, column_type in pending.items():
        if column_name not in columns:
            conn.execute(
                text(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}")
            )
            added_any = True

    if added_any or "name" in columns or "email" in columns:
        conn.execute(
            text(
                "UPDATE users SET name = 'Legacy User ' || substr(id, 1, 8) "
                "WHERE name IS NULL OR name = ''"
            )
        )
        conn.execute(
            text(
                "UPDATE users SET email = id || '@legacy.local' "
                "WHERE email IS NULL OR email = ''"
            )
        )


def _ensure_users_email_unique_index(conn, inspector) -> None:
    has_unique_email_index = any(
        idx.get("unique") and "email" in idx.get("column_names", [])
        for idx in inspector.get_indexes("users")
    )
    if not has_unique_email_index:
        conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)")
        )
