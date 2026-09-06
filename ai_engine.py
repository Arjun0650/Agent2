import os
import json
import re
from pathlib import Path
from typing import Optional

from PIL import Image
from pydantic import BaseModel, Field
from google import genai
from google.genai import types


# ============================================================
# CONFIGURATION
# ============================================================

MODEL_NAME = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)

# Maximum time Gemini is allowed to take.
# After this, the request fails instead of hanging.
GEMINI_TIMEOUT_MS = 15000

# Resize large screenshots before sending.
MAX_IMAGE_SIDE = 1400


# ============================================================
# PAYMENT SCHEMA
# ============================================================

class PaymentTransaction(BaseModel):

    amount: Optional[float] = None

    paid_to: Optional[str] = None

    payment_date: Optional[str] = None

    payment_time: Optional[str] = None

    transaction_id: Optional[str] = None

    payment_mode: Optional[str] = None

    payment_app: Optional[str] = None

    purpose: Optional[str] = None

    project: Optional[str] = None

    category: Optional[str] = None

    confidence: Optional[float] = Field(
        default=None,
        ge=0,
        le=100
    )

    needs_review: bool = True

    review_reason: Optional[str] = None


# ============================================================
# EXTRACTION RESULT
# ============================================================

class ExtractionResult(BaseModel):

    success: bool

    payment: Optional[PaymentTransaction] = None

    error: Optional[str] = None

    quota_error: bool = False


# ============================================================
# CLEANING HELPERS
# ============================================================

def clean_optional_text(value):

    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    if text.lower() in {
        "null",
        "none",
        "unknown",
        "not visible",
        "not available",
        "n/a"
    }:
        return None

    return text


def normalize_amount(value):

    if value is None:
        return None

    if isinstance(
        value,
        (int, float)
    ):

        amount = float(value)

        return (
            amount
            if amount > 0
            else None
        )

    text = str(value)

    text = (
        text
        .replace("₹", "")
        .replace(",", "")
        .strip()
    )

    match = re.search(
        r"\d+(?:\.\d+)?",
        text
    )

    if not match:
        return None

    try:

        amount = float(
            match.group()
        )

        return (
            amount
            if amount > 0
            else None
        )

    except ValueError:

        return None


def normalize_confidence(value):

    if value is None:
        return None

    try:

        confidence = float(value)

        return max(
            0,
            min(
                100,
                confidence
            )
        )

    except (
        TypeError,
        ValueError
    ):

        return None


# ============================================================
# ERROR HELPERS
# ============================================================

def is_quota_error(error):

    text = str(error).lower()

    quota_terms = [
        "429",
        "resource_exhausted",
        "resource exhausted",
        "quota",
        "rate limit",
        "rate_limit",
        "too many requests"
    ]

    return any(
        term in text
        for term in quota_terms
    )


# ============================================================
# GEMINI CLIENT
# ============================================================

def get_client():

    api_key = os.environ.get(
        "GOOGLE_API_KEY"
    )

    if not api_key:

        raise RuntimeError(
            "GOOGLE_API_KEY is not configured."
        )

    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=GEMINI_TIMEOUT_MS
        )
    )


# ============================================================
# FAST PAYMENT PROMPT
# ============================================================

PAYMENT_PROMPT = """
Read this payment screenshot for GCGW.

Extract only information that is actually visible.

Return:

amount
paid_to
payment_date
payment_time
transaction_id
payment_mode
payment_app
purpose
project
category
confidence
needs_review
review_reason

Rules:

- Never invent financial information.
- Missing information must be null.
- Partial extraction is SUCCESS.
- Do not fail because project, category or purpose are missing.
- Do not guess project.
- Do not guess category.
- Do not guess purpose.
- Preserve transaction / UTR / reference IDs exactly.
- amount must be the transferred payment amount.
- Do not mistake balances, cashback or rewards for the amount.
- Prefer payment_date in YYYY-MM-DD format.
- confidence must be from 0 to 100.
- If anything important needs human confirmation,
  set needs_review=true.

The payment will be manually reviewed before approval.

Focus mainly on:
amount,
paid_to,
payment_date,
transaction_id,
payment_app,
payment_mode.

Be fast and accurate.
"""


# ============================================================
# PREPARE IMAGE
# ============================================================

def prepare_image(image_path):

    image_path = Path(
        image_path
    )

    if not image_path.exists():

        raise FileNotFoundError(
            "Screenshot file does not exist."
        )

    with Image.open(
        image_path
    ) as opened_image:

        opened_image.load()

        if opened_image.mode != "RGB":

            image = opened_image.convert(
                "RGB"
            )

        else:

            image = opened_image.copy()

    width, height = image.size

    largest_side = max(
        width,
        height
    )

    if largest_side > MAX_IMAGE_SIDE:

        scale = (
            MAX_IMAGE_SIDE
            / largest_side
        )

        new_width = max(
            1,
            int(width * scale)
        )

        new_height = max(
            1,
            int(height * scale)
        )

        image = image.resize(
            (
                new_width,
                new_height
            )
        )

    return image


# ============================================================
# CLEAN GEMINI RESULT
# ============================================================

def clean_payment(payment):

    if isinstance(
        payment,
        PaymentTransaction
    ):

        data = payment.model_dump()

    elif isinstance(
        payment,
        dict
    ):

        data = dict(payment)

    else:

        data = {}

    data["amount"] = normalize_amount(
        data.get("amount")
    )

    for field_name in [
        "paid_to",
        "payment_date",
        "payment_time",
        "transaction_id",
        "payment_mode",
        "payment_app",
        "purpose",
        "project",
        "category",
        "review_reason"
    ]:

        data[field_name] = (
            clean_optional_text(
                data.get(field_name)
            )
        )

    data["confidence"] = (
        normalize_confidence(
            data.get("confidence")
        )
    )

    data["needs_review"] = True

    return PaymentTransaction(
        **data
    )


# ============================================================
# CHECK IF GEMINI FOUND SOMETHING USEFUL
# ============================================================

def has_useful_data(payment):

    values = [
        payment.amount,
        payment.paid_to,
        payment.payment_date,
        payment.payment_time,
        payment.transaction_id,
        payment.payment_mode,
        payment.payment_app
    ]

    return any(
        value not in {
            None,
            ""
        }
        for value in values
    )


# ============================================================
# ANALYZE SCREENSHOT
# ============================================================

def analyze_payment_screenshot(
    image_path
):

    # --------------------------------------------------------
    # IMAGE
    # --------------------------------------------------------

    try:

        image = prepare_image(
            image_path
        )

    except Exception as error:

        return ExtractionResult(
            success=False,
            error=(
                "Image error: "
                + str(error)
            )
        )

    # --------------------------------------------------------
    # CLIENT
    # --------------------------------------------------------

    try:

        client = get_client()

    except Exception as error:

        return ExtractionResult(
            success=False,
            error=str(error)
        )

    # --------------------------------------------------------
    # EXACTLY ONE GEMINI REQUEST
    # --------------------------------------------------------

    try:

        response = (
            client.models.generate_content(
                model=MODEL_NAME,

                contents=[
                    PAYMENT_PROMPT,
                    image
                ],

                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=PaymentTransaction,
                    temperature=0
                )
            )
        )

        payment = None

        # ----------------------------------------------------
        # PARSED STRUCTURED RESPONSE
        # ----------------------------------------------------

        parsed = getattr(
            response,
            "parsed",
            None
        )

        if parsed is not None:

            if isinstance(
                parsed,
                PaymentTransaction
            ):

                payment = parsed

            else:

                payment = (
                    PaymentTransaction
                    .model_validate(
                        parsed
                    )
                )

        # ----------------------------------------------------
        # JSON FALLBACK
        # ----------------------------------------------------

        if payment is None:

            response_text = getattr(
                response,
                "text",
                None
            )

            if response_text:

                try:

                    payment = (
                        PaymentTransaction
                        .model_validate_json(
                            response_text
                        )
                    )

                except Exception:

                    raw_data = json.loads(
                        response_text
                    )

                    payment = (
                        PaymentTransaction
                        .model_validate(
                            raw_data
                        )
                    )

        if payment is None:

            return ExtractionResult(
                success=False,
                error=(
                    "Gemini returned no "
                    "payment information."
                )
            )

        payment = clean_payment(
            payment
        )

        # ----------------------------------------------------
        # IF GEMINI READ AT LEAST SOMETHING,
        # IT IS A SUCCESS
        # ----------------------------------------------------

        if not has_useful_data(
            payment
        ):

            return ExtractionResult(
                success=False,
                error=(
                    "Gemini could not detect "
                    "useful payment information."
                )
            )

        # ----------------------------------------------------
        # BUILD REVIEW REASON LOCALLY
        # ----------------------------------------------------

        missing = []

        if payment.amount is None:

            missing.append(
                "amount"
            )

        if not payment.paid_to:

            missing.append(
                "payee"
            )

        if not payment.payment_date:

            missing.append(
                "date"
            )

        if not payment.transaction_id:

            missing.append(
                "transaction ID"
            )

        if not payment.project:

            missing.append(
                "project"
            )

        if not payment.category:

            missing.append(
                "category"
            )

        if not payment.purpose:

            missing.append(
                "purpose"
            )

        payment.needs_review = True

        if missing:

            payment.review_reason = (
                "Manual confirmation required: "
                + ", ".join(missing)
            )

        else:

            payment.review_reason = (
                "Manual approval required."
            )

        return ExtractionResult(
            success=True,
            payment=payment,
            quota_error=False
        )

    # --------------------------------------------------------
    # GEMINI ERROR
    # --------------------------------------------------------

    except Exception as error:

        error_text = str(error)

        print(
            "[GEMINI ERROR]",
            error_text,
            flush=True
        )

        return ExtractionResult(
            success=False,
            error=error_text,
            quota_error=is_quota_error(
                error
            )
        )


# ============================================================
# VALIDATE PAYMENT
# ============================================================

def validate_extracted_payment(
    payment
):

    if isinstance(
        payment,
        dict
    ):

        payment = (
            PaymentTransaction
            .model_validate(
                payment
            )
        )

    problems = []

    # --------------------------------------------------------
    # PAYMENT DETAILS
    # --------------------------------------------------------

    if (
        payment.amount is None
        or payment.amount <= 0
    ):

        problems.append(
            "Amount requires confirmation"
        )

    if not payment.paid_to:

        problems.append(
            "Payee requires confirmation"
        )

    if not payment.payment_date:

        problems.append(
            "Payment date requires confirmation"
        )

    if not payment.transaction_id:

        problems.append(
            "Transaction/reference ID requires confirmation"
        )

    # --------------------------------------------------------
    # GCGW DETAILS
    # --------------------------------------------------------

    if not payment.project:

        problems.append(
            "Project requires confirmation"
        )

    if not payment.category:

        problems.append(
            "Category requires confirmation"
        )

    if not payment.purpose:

        problems.append(
            "Purpose / remark requires confirmation"
        )

    if (
        payment.confidence is not None
        and payment.confidence < 70
    ):

        problems.append(
            "AI confidence is below 70%"
        )

    # Remove duplicates

    unique_problems = []

    for problem in problems:

        if problem not in unique_problems:

            unique_problems.append(
                problem
            )

    # ========================================================
    # IMPORTANT:
    #
    # EVERY SCREENSHOT GOES TO NEEDS REVIEW.
    # IT SHOULD NOT WAIT FOR PERFECT AI DATA.
    # ========================================================

    return {
        "valid": True,
        "needs_review": True,
        "problems": unique_problems,
        "partial_extraction":
            len(unique_problems) > 0
    }


# ============================================================
# FUNCTION USED BY APP.PY
# ============================================================

def extract_payment_for_web(
    image_path
):

    result = (
        analyze_payment_screenshot(
            image_path
        )
    )

    # --------------------------------------------------------
    # TRUE TECHNICAL FAILURE
    # --------------------------------------------------------

    if not result.success:

        return {
            "success": False,
            "payment": None,
            "validation": None,
            "quota_error":
                result.quota_error,
            "error":
                result.error
        }

    # --------------------------------------------------------
    # GEMINI READ SOMETHING
    # --------------------------------------------------------

    payment = result.payment

    validation = (
        validate_extracted_payment(
            payment
        )
    )

    return {
        "success": True,

        "payment":
            payment.model_dump(),

        "validation":
            validation,

        "quota_error":
            False,

        "partial_extraction":
            True,

        "error":
            None
    }
