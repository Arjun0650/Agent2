import os
import re
import hmac
import sqlite3
import hashlib
import secrets
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SQLITE_FILE = DATA_DIR / "users.db"

DATABASE_URL = (
    os.environ.get("DATABASE_URL")
    or os.environ.get("POSTGRES_URL")
    or ""
).strip()

def normalize_email(value):
    return str(value or "").strip().lower()

def clean_name(value):
    return " ".join(str(value or "").strip().split())

def valid_email(email):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))

def using_postgres():
    return DATABASE_URL.lower().startswith(("postgres://", "postgresql://"))

def hash_password(password, salt_hex=None):
    password = str(password or "")
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        200_000
    )
    return {"hash": digest.hex(), "salt": salt.hex()}

def public_user(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "full_name": row["full_name"],
        "email": row["email"]
    }

def get_postgres_connection():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL is configured but psycopg is not installed. "
            "Add 'psycopg[binary]' to requirements.txt."
        ) from exc

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row
    )

def get_sqlite_connection():
    conn = sqlite3.connect(SQLITE_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database():
    if using_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS users (
                        id BIGSERIAL PRIMARY KEY,
                        full_name TEXT NOT NULL,
                        email TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        salt TEXT NOT NULL,
                        created_at TIMESTAMP NOT NULL
                    )
                    '''
                )
            conn.commit()
    else:
        with get_sqlite_connection() as conn:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                '''
            )
            conn.commit()

initialize_database()

def register_user(full_name, email, password):
    full_name = clean_name(full_name)
    email = normalize_email(email)
    password = str(password or "")

    if not full_name:
        return {"success": False, "error": "Full name is required."}

    if not valid_email(email):
        return {"success": False, "error": "Enter a valid email address."}

    if len(password) < 8:
        return {
            "success": False,
            "error": "Password must contain at least 8 characters."
        }

    password_data = hash_password(password)

    try:
        if using_postgres():
            with get_postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        '''
                        INSERT INTO users
                        (
                            full_name,
                            email,
                            password_hash,
                            salt,
                            created_at
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id, full_name, email
                        ''',
                        (
                            full_name,
                            email,
                            password_data["hash"],
                            password_data["salt"],
                            datetime.now()
                        )
                    )
                    row = cur.fetchone()
                conn.commit()
        else:
            with get_sqlite_connection() as conn:
                cursor = conn.execute(
                    '''
                    INSERT INTO users
                    (
                        full_name,
                        email,
                        password_hash,
                        salt,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ''',
                    (
                        full_name,
                        email,
                        password_data["hash"],
                        password_data["salt"],
                        datetime.now().isoformat(timespec="seconds")
                    )
                )
                conn.commit()

                row = conn.execute(
                    '''
                    SELECT id, full_name, email
                    FROM users
                    WHERE id = ?
                    ''',
                    (cursor.lastrowid,)
                ).fetchone()

        return {"success": True, "user": public_user(row)}

    except Exception as exc:
        message = str(exc).lower()

        if (
            "unique" in message
            or "duplicate" in message
            or "already exists" in message
        ):
            return {
                "success": False,
                "error": "An account with this email already exists."
            }

        return {
            "success": False,
            "error": "Could not create account. Please try again."
        }

def authenticate_user(email, password):
    email = normalize_email(email)
    password = str(password or "")

    if not email or not password:
        return {
            "success": False,
            "error": "Email and password are required."
        }

    if using_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    SELECT *
                    FROM users
                    WHERE LOWER(email) = LOWER(%s)
                    LIMIT 1
                    ''',
                    (email,)
                )
                row = cur.fetchone()
    else:
        with get_sqlite_connection() as conn:
            row = conn.execute(
                '''
                SELECT *
                FROM users
                WHERE LOWER(email) = LOWER(?)
                LIMIT 1
                ''',
                (email,)
            ).fetchone()

    if not row:
        return {
            "success": False,
            "error": "Invalid email or password."
        }

    password_data = hash_password(password, row["salt"])

    if not hmac.compare_digest(
        password_data["hash"],
        row["password_hash"]
    ):
        return {
            "success": False,
            "error": "Invalid email or password."
        }

    return {
        "success": True,
        "user": public_user(row)
    }

def get_user_by_id(user_id):
    try:
        numeric_id = int(user_id)
    except (TypeError, ValueError):
        return None

    if using_postgres():
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    SELECT id, full_name, email
                    FROM users
                    WHERE id = %s
                    LIMIT 1
                    ''',
                    (numeric_id,)
                )
                row = cur.fetchone()
    else:
        with get_sqlite_connection() as conn:
            row = conn.execute(
                '''
                SELECT id, full_name, email
                FROM users
                WHERE id = ?
                LIMIT 1
                ''',
                (numeric_id,)
            ).fetchone()

    return public_user(row)
