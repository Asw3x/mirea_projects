import sqlite3
import threading
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "bot_data.db")
_lock = threading.Lock()


@contextmanager
def _get_conn():
    """Yield a sqlite3 connection. Uses a simple lock to be thread-safe."""
    with _lock:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        try:
            yield conn
        finally:
            conn.close()


class ConnectionWrapper:
    """Compatibility wrapper exposing get_connection().

    The connection returned by get_connection() provides a .cursor() which
    returns a cursor-like wrapper. That wrapper translates MySQL-style %s
    placeholders into SQLite ? placeholders at execution time, so existing
    SQL strings in the codebase can remain unchanged.
    """

    def get_connection(self):
        class CursorWrapper:
            def __init__(self, cur, conn):
                self._cur = cur
                self._conn = conn

            def execute(self, sql, params=None):
                if params is None:
                    params = ()
                new_sql = sql.replace('%s', '?')
                return self._cur.execute(new_sql, params)

            def executemany(self, sql, seq_of_params):
                new_sql = sql.replace('%s', '?')
                return self._cur.executemany(new_sql, seq_of_params)

            def fetchone(self):
                return self._cur.fetchone()

            def fetchall(self):
                return self._cur.fetchall()

            def __getattr__(self, item):
                return getattr(self._cur, item)

        class Conn:
            def __init__(self, conn):
                self._conn = conn

            def cursor(self):
                cur = self._conn.cursor()
                return CursorWrapper(cur, self._conn)

            def commit(self):
                return self._conn.commit()

            def close(self):
                try:
                    try:
                        self._conn.commit()
                    except Exception:
                        pass
                    self._conn.close()
                except Exception:
                    pass

        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return Conn(conn)


# Public objects
connection_pool = ConnectionWrapper()
db = connection_pool  # compatibility alias


def init_db():
    """Create necessary tables if they do not exist.

    Note: schema intentionally omits any premium/limit columns per project
    requirements (browsing always allowed).
    """
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS Users (
                PersonID INTEGER PRIMARY KEY,
                UserName TEXT,
                Age INTEGER,
                Gender TEXT,
                Looking TEXT,
                City TEXT,
                Bio TEXT,
                Photo TEXT,
                IsActive INTEGER DEFAULT 0,
                Consent INTEGER DEFAULT 0,
                Language TEXT
            )
            """
        )

        # Ensure Consent column exists for older DBs: add if missing
        cur.execute("PRAGMA table_info(Users)")
        cols = [r[1] for r in cur.fetchall()]
        if 'Consent' not in cols:
            try:
                cur.execute("ALTER TABLE Users ADD COLUMN Consent INTEGER DEFAULT 0")
            except Exception:
                # Some SQLite versions may not support ALTER in all contexts; ignore if fails
                pass

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS Likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                LikeUserID INTEGER,
                LikedUserID INTEGER,
                MesToPerson TEXT,
                MessageText TEXT,
                UNIQUE(LikeUserID, LikedUserID)
            )
            """
        )

        # Ensure MessageText column exists in older databases
        cur.execute("PRAGMA table_info(Likes)")
        like_cols = [r[1] for r in cur.fetchall()]
        if 'MessageText' not in like_cols:
            try:
                cur.execute("ALTER TABLE Likes ADD COLUMN MessageText TEXT")
            except Exception:
                pass

        # Migrate legacy rows where actual messages were stored in MesToPerson
        cur.execute(
            """
            UPDATE Likes
            SET MessageText = CASE
                    WHEN MessageText IS NULL OR MessageText = ''
                        THEN MesToPerson
                        ELSE MessageText
                END,
                MesToPerson = '__LIKE__'
            WHERE MesToPerson NOT LIKE '__%'
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS Reports (
                UserID INTEGER PRIMARY KEY,
                AdultREP INTEGER DEFAULT 0,
                DrugREP INTEGER DEFAULT 0,
                SaleREP INTEGER DEFAULT 0,
                OtherREP INTEGER DEFAULT 0
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS banned (
                PersonID INTEGER PRIMARY KEY
            )
            """
        )

        conn.commit()


if __name__ == "__main__":
    init_db()
    print("Initialized DB at", DB_PATH)
