import sqlite3
import time

DB_FILE = "pepstein.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scores (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            points INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_games (
            chat_id INTEGER PRIMARY KEY,
            original_answer TEXT,
            redacted_answer TEXT,
            keywords TEXT,
            active INTEGER DEFAULT 1,
            asked_at REAL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def add_points(user_id, username, points):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO scores (user_id, username, points)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            points = points + excluded.points
    """, (user_id, username, points))
    conn.commit()
    conn.close()


def get_leaderboard(limit=10):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT username, points FROM scores
        ORDER BY points DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_user_score(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT points FROM scores WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0


def set_active_game(chat_id, original, redacted, keywords):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    keyword_str = "|".join(keywords)
    cursor.execute("""
        INSERT OR REPLACE INTO active_games
        (chat_id, original_answer, redacted_answer, keywords, active, asked_at)
        VALUES (?, ?, ?, ?, 1, ?)
    """, (chat_id, original, redacted, keyword_str, time.time()))
    conn.commit()
    conn.close()


def get_active_game(chat_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT original_answer, redacted_answer, keywords, asked_at
        FROM active_games
        WHERE chat_id = ? AND active = 1
    """, (chat_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "original": row[0],
            "redacted": row[1],
            "keywords": row[2].split("|") if row[2] else [],
            "asked_at": row[3] if row[3] else 0,
        }
    return None


def clear_active_game(chat_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE active_games SET active = 0 WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()


def reset_leaderboard():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM scores")
    conn.commit()
    conn.close()
