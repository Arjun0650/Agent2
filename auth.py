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

DB_FILE = DATA_DIR / "users.db"


def normalize_email(value):
    return str(value or "").strip().lower()


def clean_name(value):
    return " ".join(
        str(value or "").strip().split()
    )


def valid_email(email):
    return bool(
        re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            email
        )
    )


def initialize_database():

    with sqlite3.connect(DB_FILE) as conn:

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        conn.commit()


initialize_database()


def hash_password(
    password,
    salt_hex=None
):

    password = str(password or "")

    if salt_hex:
        salt = bytes.fromhex(
            salt_hex
        )
    else:
        salt = secrets.token_bytes(
            16
        )

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        200_000
    )

    return {
        "hash": digest.hex(),
        "salt": salt.hex()
    }


def public_user(row):

    if not row:
        return None

    return {
        "id": row["id"],
        "full_name":
            row["full_name"],
        "email":
            row["email"]
    }


def environment_admin():

    email = normalize_email(
        os.environ.get(
            "GCGW_ADMIN_EMAIL"
        )
    )

    password = str(
        os.environ.get(
            "GCGW_ADMIN_PASSWORD",
            ""
        )
    )

    full_name = clean_name(
        os.environ.get(
            "GCGW_ADMIN_NAME",
            "GCGW Admin"
        )
    )

    if not email or not password:
        return None

    return {
        "id": "gcgw-admin",
        "full_name":
            full_name or "GCGW Admin",
        "email":
            email,
        "password":
            password
    }


def register_user(
    full_name,
    email,
    password
):

    full_name = clean_name(
        full_name
    )

    email = normalize_email(
        email
    )

    password = str(
        password or ""
    )


    if not full_name:

        return {
            "success": False,
            "error":
                "Full name is required."
        }


    if not valid_email(email):

        return {
            "success": False,
            "error":
                "Enter a valid email address."
        }


    if len(password) < 8:

        return {
            "success": False,
            "error":
                "Password must contain at least 8 characters."
        }


    admin = environment_admin()

    if (
        admin
        and
        hmac.compare_digest(
            email,
            admin["email"]
        )
    ):

        return {
            "success": False,
            "error":
                "This email is already registered."
        }


    password_data = (
        hash_password(
            password
        )
    )


    try:

        with sqlite3.connect(
            DB_FILE
        ) as conn:

            conn.row_factory = sqlite3.Row

            cursor = conn.execute(
                """
                INSERT INTO users
                (
                    full_name,
                    email,
                    password_hash,
                    salt,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    full_name,
                    email,
                    password_data[
                        "hash"
                    ],
                    password_data[
                        "salt"
                    ],
                    datetime.now()
                    .isoformat(
                        timespec="seconds"
                    )
                )
            )

            conn.commit()

            row = conn.execute(
                """
                SELECT
                    id,
                    full_name,
                    email
                FROM users
                WHERE id = ?
                """,
                (
                    cursor.lastrowid,
                )
            ).fetchone()


        return {
            "success": True,
            "user":
                public_user(row)
        }


    except sqlite3.IntegrityError:

        return {
            "success": False,
            "error":
                "An account with this email already exists."
        }


def authenticate_user(
    email,
    password
):

    email = normalize_email(
        email
    )

    password = str(
        password or ""
    )


    admin = environment_admin()

    if (
        admin
        and
        hmac.compare_digest(
            email,
            admin["email"]
        )
        and
        hmac.compare_digest(
            password,
            admin["password"]
        )
    ):

        return {
            "success": True,
            "user": {
                "id":
                    admin["id"],
                "full_name":
                    admin[
                        "full_name"
                    ],
                "email":
                    admin["email"]
            }
        }


    with sqlite3.connect(
        DB_FILE
    ) as conn:

        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE lower(email) = lower(?)
            LIMIT 1
            """,
            (
                email,
            )
        ).fetchone()


    if not row:

        return {
            "success": False,
            "error":
                "Invalid email or password."
        }


    password_data = (
        hash_password(
            password,
            row["salt"]
        )
    )


    if not hmac.compare_digest(
        password_data["hash"],
        row["password_hash"]
    ):

        return {
            "success": False,
            "error":
                "Invalid email or password."
        }


    return {
        "success": True,
        "user":
            public_user(row)
    }


def get_user_by_id(
    user_id
):

    admin = environment_admin()

    if (
        admin
        and
        str(user_id)
        ==
        str(admin["id"])
    ):

        return {
            "id":
                admin["id"],
            "full_name":
                admin[
                    "full_name"
                ],
            "email":
                admin["email"]
        }


    try:

        numeric_id = int(
            user_id
        )

    except (
        TypeError,
        ValueError
    ):

        return None


    with sqlite3.connect(
        DB_FILE
    ) as conn:

        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT
                id,
                full_name,
                email
            FROM users
            WHERE id = ?
            LIMIT 1
            """,
            (
                numeric_id,
            )
        ).fetchone()


    return public_user(row)
