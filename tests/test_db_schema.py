from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.db.schema_sync import sync_schema


def _create_legacy_users_table(db_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE users (
                    id VARCHAR(64) PRIMARY KEY,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO users (id, created_at) VALUES "
                "('550e8400-e29b-41d4-a716-446655440000', '2024-01-01 00:00:00')"
            )
        )
    engine.dispose()


def test_sync_schema_adds_missing_user_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _create_legacy_users_table(db_path)

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    sync_schema(engine)

    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("users")}
    assert {"id", "created_at", "name", "email"}.issubset(columns)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT name, email FROM users WHERE id = :id"),
            {"id": "550e8400-e29b-41d4-a716-446655440000"},
        ).one()
        assert row.name.startswith("Legacy User ")
        assert row.email == "550e8400-e29b-41d4-a716-446655440000@legacy.local"

    indexes = inspector.get_indexes("users")
    assert any(idx.get("unique") and "email" in idx["column_names"] for idx in indexes)

    engine.dispose()


def test_sync_schema_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _create_legacy_users_table(db_path)

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    sync_schema(engine)
    sync_schema(engine)

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
        row = conn.execute(
            text("SELECT name, email FROM users WHERE id = :id"),
            {"id": "550e8400-e29b-41d4-a716-446655440000"},
        ).one()

    assert count == 1
    assert row.name.startswith("Legacy User ")
    assert row.email == "550e8400-e29b-41d4-a716-446655440000@legacy.local"
    engine.dispose()
