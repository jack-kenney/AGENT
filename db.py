import sqlite3
import os
from datetime import date, datetime
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "metcom.db")

# Maps user-facing keys to DB column names
FIELD_MAP = {
    "height":   "height_cm",
    "weight":   "weight_kg",
    "goal":     "goal_weight_kg",
    "calories": "target_calories",
    "protein":  "target_protein_g",
    "carbs":    "target_carbs_g",
    "fat":      "target_fat_g",
}


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                discord_id       TEXT PRIMARY KEY,
                display_name     TEXT NOT NULL,
                height_cm        REAL,
                weight_kg        REAL,
                goal_weight_kg   REAL,
                target_calories  INTEGER,
                target_protein_g INTEGER,
                target_carbs_g   INTEGER,
                target_fat_g     INTEGER,
                updated_at       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS food_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id   TEXT NOT NULL,
                logged_at    TEXT NOT NULL,
                description  TEXT NOT NULL,
                calories     REAL NOT NULL,
                protein_g    REAL NOT NULL,
                carbs_g      REAL NOT NULL,
                fat_g        REAL NOT NULL
            );
        """)


def get_profile(discord_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM profiles WHERE discord_id = ?", (discord_id,)
        ).fetchone()
        return dict(row) if row else None


def upsert_profile(discord_id: str, display_name: str, **fields) -> None:
    """Insert or partially update a profile. Only keys present in fields are written."""
    allowed = set(FIELD_MAP.values())
    fields = {k: v for k, v in fields.items() if k in allowed}
    fields["display_name"] = display_name
    fields["updated_at"] = datetime.now().isoformat()

    with _conn() as conn:
        existing = conn.execute(
            "SELECT discord_id FROM profiles WHERE discord_id = ?", (discord_id,)
        ).fetchone()

        if existing:
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE profiles SET {set_clause} WHERE discord_id = ?",
                (*fields.values(), discord_id),
            )
        else:
            fields["discord_id"] = discord_id
            cols = ", ".join(fields.keys())
            placeholders = ", ".join("?" * len(fields))
            conn.execute(
                f"INSERT INTO profiles ({cols}) VALUES ({placeholders})",
                list(fields.values()),
            )


def log_food(
    discord_id: str,
    description: str,
    calories: float,
    protein_g: float,
    carbs_g: float,
    fat_g: float,
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO food_log (discord_id, logged_at, description, calories, protein_g, carbs_g, fat_g) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (discord_id, datetime.now().isoformat(), description, calories, protein_g, carbs_g, fat_g),
        )
        return cur.lastrowid


def get_daily_log(discord_id: str, day: date | None = None) -> list[dict]:
    if day is None:
        day = date.today()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM food_log WHERE discord_id = ? AND date(logged_at) = ? ORDER BY logged_at",
            (discord_id, day.isoformat()),
        ).fetchall()
        return [dict(r) for r in rows]


def get_daily_totals(discord_id: str, day: date | None = None) -> dict:
    if day is None:
        day = date.today()
    with _conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(calories), 0)   AS calories, "
            "       COALESCE(SUM(protein_g), 0)  AS protein_g, "
            "       COALESCE(SUM(carbs_g), 0)    AS carbs_g, "
            "       COALESCE(SUM(fat_g), 0)      AS fat_g, "
            "       COUNT(*) AS entries "
            "FROM food_log WHERE discord_id = ? AND date(logged_at) = ?",
            (discord_id, day.isoformat()),
        ).fetchone()
        return dict(row)


def clear_daily_log(discord_id: str, day: date | None = None) -> int:
    if day is None:
        day = date.today()
    with _conn() as conn:
        result = conn.execute(
            "DELETE FROM food_log WHERE discord_id = ? AND date(logged_at) = ?",
            (discord_id, day.isoformat()),
        )
        return result.rowcount
