import sqlite3
import hashlib
import hmac
import secrets
from pathlib import Path
from datetime import datetime, timezone


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)

USERS_DB = (
    DATA_DIR /
    "users.db"
)


# ============================================================
# PASSWORD SETTINGS
# ============================================================

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 64

PBKDF2_ITERATIONS = 310000


# ============================================================
# DATABASE
# ============================================================

def get_connection():

    connection = sqlite3.connect(
        USERS_DB
    )

    connection.row_factory = (
        sqlite3.Row
    )

    return connection


def init_user_database():

    connection = (
        get_connection()
    )

    cursor = (
        connection.cursor()
    )

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


init_user_database()


# ============================================================
# EMAIL
# ============================================================

def clean_email(email):

    if not email:
        return ""

    return (
        str(email)
        .strip()
        .lower()
    )


# ============================================================
# PASSWORD VALIDATION
# ============================================================

def validate_password(password):

    password = str(
        password or ""
    )

    if not password:

        return {
            "success": False,
            "error": (
                "Password is required."
            )
        }


    if len(password) < MIN_PASSWORD_LENGTH:

        return {
            "success": False,
            "error": (
                "Password must contain "
                "at least 8 characters."
            )
        }


    if len(password) > MAX_PASSWORD_LENGTH:

        return {
            "success": False,
            "error": (
                "Password must be "
                "64 characters or fewer."
            )
        }


    return {
        "success": True
    }


# ============================================================
# PASSWORD HASHING
# ============================================================

def hash_password(password):

    password = str(
        password
    )

    salt = secrets.token_hex(
        16
    )


    password_hash = (
        hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(
                "utf-8"
            ),
            salt.encode(
                "utf-8"
            ),
            PBKDF2_ITERATIONS
        )
        .hex()
    )


    return (
        f"pbkdf2_sha256$"
        f"{PBKDF2_ITERATIONS}$"
        f"{salt}$"
        f"{password_hash}"
    )


# ============================================================
# VERIFY PASSWORD
# ============================================================

def verify_password(
    plain_password,
    stored_hash
):

    try:

        parts = str(
            stored_hash
        ).split("$")


        if len(parts) != 4:
            return False


        algorithm = parts[0]

        iterations = int(
            parts[1]
        )

        salt = parts[2]

        expected_hash = (
            parts[3]
        )


        if algorithm != "pbkdf2_sha256":
            return False


        calculated_hash = (
            hashlib.pbkdf2_hmac(
                "sha256",
                str(
                    plain_password
                ).encode(
                    "utf-8"
                ),
                salt.encode(
                    "utf-8"
                ),
                iterations
            )
            .hex()
        )


        return hmac.compare_digest(
            calculated_hash,
            expected_hash
        )


    except Exception:

        return False


# ============================================================
# GET USER BY EMAIL
# ============================================================

def get_user_by_email(email):

    email = clean_email(
        email
    )


    if not email:
        return None


    connection = (
        get_connection()
    )

    cursor = (
        connection.cursor()
    )


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
        (
            email,
        )
    )


    row = (
        cursor.fetchone()
    )

    connection.close()


    if not row:
        return None


    return dict(
        row
    )


# ============================================================
# GET USER BY ID
# ============================================================

def get_user_by_id(user_id):

    if not user_id:
        return None


    connection = (
        get_connection()
    )

    cursor = (
        connection.cursor()
    )


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
        (
            user_id,
        )
    )


    row = (
        cursor.fetchone()
    )

    connection.close()


    if not row:
        return None


    return dict(
        row
    )


# ============================================================
# REGISTER USER
# ============================================================

def register_user(
    full_name,
    email,
    password
):

    full_name = (
        str(
            full_name or ""
        )
        .strip()
    )


    email = clean_email(
        email
    )


    password = str(
        password or ""
    )


    # --------------------------------------------------------
    # NAME
    # --------------------------------------------------------

    if len(full_name) < 2:

        return {
            "success": False,
            "error": (
                "Please enter your full name."
            )
        }


    # --------------------------------------------------------
    # EMAIL
    # --------------------------------------------------------

    if not email:

        return {
            "success": False,
            "error": (
                "Email address is required."
            )
        }


    if (
        "@" not in email
        or
        "." not in email
    ):

        return {
            "success": False,
            "error": (
                "Please enter a valid "
                "email address."
            )
        }


    # --------------------------------------------------------
    # PASSWORD
    # --------------------------------------------------------

    password_check = (
        validate_password(
            password
        )
    )


    if not password_check.get(
        "success"
    ):

        return (
            password_check
        )


    # --------------------------------------------------------
    # EXISTING ACCOUNT
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
    # CREATE PASSWORD HASH
    # --------------------------------------------------------

    try:

        password_hash = (
            hash_password(
                password
            )
        )

    except Exception:

        return {
            "success": False,
            "error": (
                "Could not create your account. "
                "Please try again."
            )
        }


    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    created_at = (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )


    # --------------------------------------------------------
    # INSERT USER
    # --------------------------------------------------------

    connection = (
        get_connection()
    )

    cursor = (
        connection.cursor()
    )


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


        user_id = (
            cursor.lastrowid
        )


    except sqlite3.IntegrityError:

        connection.close()

        return {
            "success": False,
            "error": (
                "An account already exists "
                "with this email address."
            )
        }


    except Exception:

        connection.close()

        return {
            "success": False,
            "error": (
                "Could not create your account. "
                "Please try again."
            )
        }


    connection.close()


    return {

        "success": True,

        "user": {

            "id":
                user_id,

            "full_name":
                full_name,

            "email":
                email
        }
    }


# ============================================================
# LOGIN
# ============================================================

def authenticate_user(
    email,
    password
):

    email = clean_email(
        email
    )


    password = str(
        password or ""
    )


    if not email or not password:

        return {
            "success": False,
            "error": (
                "Please enter your "
                "email and password."
            )
        }


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
                "This account is "
                "currently inactive."
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

            "id":
                user["id"],

            "full_name":
                user["full_name"],

            "email":
                user["email"]
        }
    }
