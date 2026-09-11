import os
import sqlite3
from pathlib import Path
from datetime import datetime

from passlib.context import CryptContext


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

DATA_DIR.mkdir(parents=True, exist_ok=True)

USERS_DB = DATA_DIR / "users.db"


# ============================================================
# PASSWORD HASHING
# ============================================================

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)


# ============================================================
# DATABASE
# ============================================================

def get_connection():
    connection = sqlite3.connect(
        USERS_DB
    )

    connection.row_factory = sqlite3.Row

    return connection


def init_user_database():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            full_name TEXT NOT NULL,

            email TEXT NOT NULL UNIQUE,

            password_hash TEXT NOT NULL,

            created_at TEXT NOT NULL,

            is_active INTEGER NOT NULL DEFAULT 1

        )
        """
    )

    connection.commit()

    connection.close()


# Create DB/table when application starts
init_user_database()


# ============================================================
# HELPERS
# ============================================================

def clean_email(email):

    if not email:
        return ""

    return str(email).strip().lower()


def hash_password(password):

    return pwd_context.hash(
        password
    )


def verify_password(
    plain_password,
    password_hash
):

    try:

        return pwd_context.verify(
            plain_password,
            password_hash
        )

    except Exception:

        return False


# ============================================================
# GET USER
# ============================================================

def get_user_by_email(email):

    email = clean_email(email)

    if not email:
        return None

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            id,
            full_name,
            email,
            password_hash,
            created_at,
            is_active
        FROM users
        WHERE email = ?
        """,
        (email,)
    )

    row = cursor.fetchone()

    connection.close()

    if not row:
        return None

    return dict(row)


def get_user_by_id(user_id):

    if not user_id:
        return None

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            id,
            full_name,
            email,
            created_at,
            is_active
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    )

    row = cursor.fetchone()

    connection.close()

    if not row:
        return None

    return dict(row)


# ============================================================
# REGISTER USER
# ============================================================

def register_user(
    full_name,
    email,
    password
):

    full_name = (
        str(full_name or "")
        .strip()
    )

    email = clean_email(email)

    password = str(
        password or ""
    )


    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    if len(full_name) < 2:

        return {
            "success": False,
            "error": "Please enter your full name."
        }


    if not email:

        return {
            "success": False,
            "error": "Email is required."
        }


    if "@" not in email or "." not in email:

        return {
            "success": False,
            "error": "Please enter a valid email address."
        }


    if len(password) < 8:

        return {
            "success": False,
            "error": (
                "Password must contain at least "
                "8 characters."
            )
        }


    # --------------------------------------------------------
    # CHECK EXISTING ACCOUNT
    # --------------------------------------------------------

    existing_user = (
        get_user_by_email(
            email
        )
    )


    if existing_user:

        return {
            "success": False,
            "error": (
                "An account already exists "
                "with this email address."
            )
        }


    # --------------------------------------------------------
    # HASH PASSWORD
    # --------------------------------------------------------

    password_hash = (
        hash_password(
            password
        )
    )


    created_at = (
        datetime.utcnow()
        .isoformat()
    )


    # --------------------------------------------------------
    # INSERT USER
    # --------------------------------------------------------

    connection = get_connection()

    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            INSERT INTO users (
                full_name,
                email,
                password_hash,
                created_at,
                is_active
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                full_name,
                email,
                password_hash,
                created_at,
                1
            )
        )

        connection.commit()

        user_id = cursor.lastrowid


    except sqlite3.IntegrityError:

        connection.close()

        return {
            "success": False,
            "error": (
                "An account already exists "
                "with this email address."
            )
        }


    except Exception as error:

        connection.close()

        return {
            "success": False,
            "error": str(error)
        }


    connection.close()


    return {
        "success": True,
        "user": {
            "id": user_id,
            "full_name": full_name,
            "email": email
        }
    }


# ============================================================
# AUTHENTICATE USER
# ============================================================

def authenticate_user(
    email,
    password
):

    email = clean_email(email)

    user = (
        get_user_by_email(
            email
        )
    )


    if not user:

        return {
            "success": False,
            "error": (
                "Invalid email or password."
            )
        }


    if not user.get(
        "is_active"
    ):

        return {
            "success": False,
            "error": (
                "This account is currently inactive."
            )
        }


    password_valid = (
        verify_password(
            password,
            user.get(
                "password_hash",
                ""
            )
        )
    )


    if not password_valid:

        return {
            "success": False,
            "error": (
                "Invalid email or password."
            )
        }


    return {
        "success": True,
        "user": {
            "id": user["id"],
            "full_name": user["full_name"],
            "email": user["email"]
        }
    }
