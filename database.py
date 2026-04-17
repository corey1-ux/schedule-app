import os
import sqlite3

DATABASE = os.environ.get("DATABASE_PATH", "ir_schedule.db")


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                username             TEXT    NOT NULL UNIQUE,
                password             TEXT    NOT NULL,
                role                 TEXT    NOT NULL DEFAULT 'user',
                force_password_change INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS skills (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL UNIQUE,
                priority   INTEGER NOT NULL DEFAULT 0,
                created_at TEXT    DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS staff (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL,
                fte        REAL    NOT NULL DEFAULT 1.0,
                created_at TEXT    DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS staff_skills (
                staff_id   INTEGER NOT NULL REFERENCES staff(id)  ON DELETE CASCADE,
                skill_id   INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                PRIMARY KEY (staff_id, skill_id)
            );
            CREATE TABLE IF NOT EXISTS schedules (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT    NOT NULL,
                description TEXT,
                start_time  TEXT    NOT NULL,
                end_time    TEXT    NOT NULL,
                created_by  INTEGER REFERENCES users(id),
                created_at  TEXT    DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS schedule_templates (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL UNIQUE,
                created_at TEXT    DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS template_needs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER NOT NULL REFERENCES schedule_templates(id) ON DELETE CASCADE,
                day_of_week TEXT    NOT NULL,
                skill_id    INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                quantity    INTEGER NOT NULL DEFAULT 1,
                UNIQUE (template_id, day_of_week, skill_id)
            );
            CREATE TABLE IF NOT EXISTS day_priority (
                day_of_week TEXT    PRIMARY KEY,
                priority    INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS generated_schedule (
                id           INTEGER PRIMARY KEY CHECK (id = 1),
                result_json  TEXT,
                month_start  TEXT,
                generated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS closed_dates (
                date TEXT PRIMARY KEY
            );
        """)

        # Migrations
        cols = [r[1] for r in conn.execute("PRAGMA table_info(skills)").fetchall()]
        if "priority" not in cols:
            conn.execute("ALTER TABLE skills ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")

        staff_cols = [r[1] for r in conn.execute("PRAGMA table_info(staff)").fetchall()]
        if "is_casual" not in staff_cols:
            conn.execute("ALTER TABLE staff ADD COLUMN is_casual INTEGER NOT NULL DEFAULT 0")

        user_cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "force_password_change" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN force_password_change INTEGER NOT NULL DEFAULT 0")

        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        if "generated_schedule" not in tables:
            conn.execute("""
                CREATE TABLE generated_schedule (
                    id           INTEGER PRIMARY KEY CHECK (id = 1),
                    result_json  TEXT,
                    month_start  TEXT,
                    generated_at TEXT DEFAULT (datetime('now'))
                )
            """)
        else:
            gs_cols = [r[1] for r in conn.execute("PRAGMA table_info(generated_schedule)").fetchall()]
            if "month_start" not in gs_cols:
                conn.execute("ALTER TABLE generated_schedule ADD COLUMN month_start TEXT")

        if "closed_dates" not in tables:
            conn.execute("CREATE TABLE closed_dates (date TEXT PRIMARY KEY)")

        # Seed admin
        from werkzeug.security import generate_password_hash
        admin_exists = conn.execute("SELECT id FROM users WHERE role='admin'").fetchone()
        if not admin_exists:
            admin_username = os.environ.get("ADMIN_USERNAME")
            admin_password = os.environ.get("ADMIN_PASSWORD")
            if not admin_username or not admin_password:
                raise RuntimeError(
                    "ADMIN_USERNAME and ADMIN_PASSWORD environment variables must both be set."
                )
            conn.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (admin_username, generate_password_hash(admin_password), "admin")
            )

        # Seed day priorities
        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
            conn.execute(
                "INSERT OR IGNORE INTO day_priority (day_of_week, priority) VALUES (?, 0)", (day,)
            )

        conn.commit()


def init_blocks_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS fte_tiers (
                fte              REAL    PRIMARY KEY,
                shifts_per_week  INTEGER NOT NULL,
                shifts_per_pp    INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS schedule_blocks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL,
                start_date TEXT    NOT NULL,
                end_date   TEXT    NOT NULL,
                status     TEXT    NOT NULL DEFAULT 'draft'
            );
            CREATE TABLE IF NOT EXISTS staff_requests (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                block_id INTEGER NOT NULL REFERENCES schedule_blocks(id) ON DELETE CASCADE,
                staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
                date     TEXT    NOT NULL,
                skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                UNIQUE (block_id, staff_id, date, skill_id)
            );
            CREATE TABLE IF NOT EXISTS staff_unavailability (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                block_id INTEGER NOT NULL REFERENCES schedule_blocks(id) ON DELETE CASCADE,
                staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
                date     TEXT    NOT NULL,
                UNIQUE (block_id, staff_id, date)
            );
            CREATE TABLE IF NOT EXISTS rotation_history (
                staff_id  INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
                skill_id  INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                last_date TEXT    NOT NULL,
                PRIMARY KEY (staff_id, skill_id)
            );
            CREATE TABLE IF NOT EXISTS skill_minimums (
                skill_id      INTEGER PRIMARY KEY REFERENCES skills(id) ON DELETE CASCADE,
                minimum_count INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS staff_block_config (
                block_id       INTEGER NOT NULL REFERENCES schedule_blocks(id) ON DELETE CASCADE,
                staff_id       INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
                fte_start_week TEXT    NOT NULL DEFAULT 'low',
                PRIMARY KEY (block_id, staff_id)
            );
            CREATE TABLE IF NOT EXISTS optimized_schedule (
                block_id     INTEGER PRIMARY KEY REFERENCES schedule_blocks(id) ON DELETE CASCADE,
                result_json  TEXT,
                optimized_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS block_publish_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                block_id     INTEGER NOT NULL REFERENCES schedule_blocks(id) ON DELETE CASCADE,
                version      INTEGER NOT NULL DEFAULT 1,
                published_at TEXT    NOT NULL DEFAULT (datetime('now')),
                changes_json TEXT
            );
            CREATE TABLE IF NOT EXISTS block_last_published (
                block_id      INTEGER PRIMARY KEY REFERENCES schedule_blocks(id) ON DELETE CASCADE,
                snapshot_json TEXT    NOT NULL,
                published_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );
        """)

        for fte, weekly, pp in [(0.5, 2, 4), (0.6, 3, 5), (0.75, 3, 6), (1.0, 4, 8)]:
            conn.execute(
                "INSERT OR IGNORE INTO fte_tiers (fte, shifts_per_week, shifts_per_pp) VALUES (?, ?, ?)",
                (fte, weekly, pp)
            )

        conn.commit()
