"""SQLite storage: classes, students and per-user dialog state (survives restarts / PC shutdowns)."""
import json
import secrets
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS classes (
    code TEXT PRIMARY KEY, template TEXT, title TEXT, expected INTEGER, tariff INTEGER,
    source TEXT, fields TEXT, class_photos TEXT, common TEXT, status TEXT, admin_id INTEGER, created REAL, crm TEXT);
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT, class_code TEXT, user_id INTEGER, name TEXT, pages TEXT,
    cover TEXT, portrait TEXT, quote TEXT, grp TEXT, status TEXT, preview TEXT, updated REAL, crops TEXT,
    UNIQUE(class_code, user_id));
CREATE TABLE IF NOT EXISTS state (user_id INTEGER PRIMARY KEY, step TEXT, data TEXT);
"""
JSON_COLS = {"source", "fields", "class_photos", "common", "pages", "grp", "crops", "crm"}
MIGRATIONS = ["ALTER TABLE students ADD COLUMN crops TEXT",
              "ALTER TABLE classes ADD COLUMN crm TEXT"]     # {order, progress, link, built}: the CRM Lumi order
CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def _dump(row):
    return {k: (json.dumps(v, ensure_ascii=False) if k in JSON_COLS else v) for k, v in row.items()}


def _load(cursor, row):
    d = {col[0]: row[i] for i, col in enumerate(cursor.description)}
    for k in JSON_COLS & d.keys():
        d[k] = json.loads(d[k]) if d[k] is not None else None
    return d


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = _load
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)
            for sql in MIGRATIONS:             # databases created by older versions
                try:
                    self.db.execute(sql)
                except sqlite3.OperationalError:
                    pass
            self.db.commit()

    def _exec(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    # ---- classes ----
    def create_class(self, **fields):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        row = _dump(dict(fields, code=code, status=fields.get("status", "collecting"), created=time.time()))
        cols = ", ".join(row)
        self._exec(f"INSERT INTO classes ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
        return code

    def get_class(self, code):
        return self._exec("SELECT * FROM classes WHERE code = ?", (code,)).fetchone()

    def update_class(self, code, **fields):
        row = _dump(fields)
        self._exec(f"UPDATE classes SET {', '.join(f'{k} = ?' for k in row)} WHERE code = ?", (*row.values(), code))

    def list_classes(self):
        return self._exec("SELECT * FROM classes ORDER BY created DESC").fetchall()

    # ---- students ----
    def student(self, class_code, user_id):
        return self._exec("SELECT * FROM students WHERE class_code = ? AND user_id = ?", (class_code, user_id)).fetchone()

    def student_by_id(self, sid):
        return self._exec("SELECT * FROM students WHERE id = ?", (sid,)).fetchone()

    def join(self, class_code, user_id):
        st = self.student(class_code, user_id)
        if st is None:
            self._exec("INSERT INTO students (class_code, user_id, status, updated) VALUES (?, ?, 'filling', ?)",
                       (class_code, user_id, time.time()))
            st = self.student(class_code, user_id)
        return st

    def update_student(self, sid, **fields):
        row = _dump(dict(fields, updated=time.time()))
        self._exec(f"UPDATE students SET {', '.join(f'{k} = ?' for k in row)} WHERE id = ?", (*row.values(), sid))

    def students(self, class_code, statuses=None):
        rows = self._exec("SELECT * FROM students WHERE class_code = ? ORDER BY id", (class_code,)).fetchall()
        return [r for r in rows if statuses is None or r["status"] in statuses]

    def latest_student(self, user_id):
        return self._exec("SELECT * FROM students WHERE user_id = ? ORDER BY updated DESC LIMIT 1", (user_id,)).fetchone()

    # ---- dialog state ----
    def get_state(self, user_id):
        row = self._exec("SELECT * FROM state WHERE user_id = ?", (user_id,)).fetchone()
        return (row["step"], json.loads(row["data"] or "{}")) if row else (None, {})

    def set_state(self, user_id, step, data=None):
        self._exec("INSERT OR REPLACE INTO state (user_id, step, data) VALUES (?, ?, ?)",
                   (user_id, step, json.dumps(data or {}, ensure_ascii=False)))
