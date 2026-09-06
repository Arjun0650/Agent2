import os
from pathlib import Path
from typing import Optional

from PIL import Image
from pydantic import BaseModel
from google import genai


# ============================================================
# CONFIGURATION
# ============================================================

MODEL_NAME = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)

# We only want quick basic extraction.
# Project/category/purpose can be completed manually.
MAX_IMAGE_SIZE = 1280


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

    confidence: Optional[float] = None

    needs_review: bool = True

    review_reason: Optional[str] = None


# ============================================================
# RESULT SCHEMA
# ============================================================

class ExtractionResult(BaseModel):

    success: bool

    payment: Optional[PaymentTransaction] = None

    error: Optional[str] = None

    quota_error: bool = False


# ============================================================
# QUOTA DETECTION
# ============================================================

def is_quota_error(error):

    text = str(error).lower()

    quota_terms = [
        "429",
        "resource_exhausted",
        "resource exhausted",
        "quota",
        "rate limit",
        "rate_limit"
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
        api_key=api_key
    )


# ============================================================
# FAST EXTRACTION PROMPT
# ============================================================

PAYMENT_PROMPT = """
Read this payment screenshot.

This is for Gopal Chavan Guniting Work (GCGW).

Extract the BASIC payment information visible in the screenshot.

Priority fields:

1. amount
2. paid_to
3. payment_date
4. payment_time
5. transaction_id
6. payment_mode
7. payment_app

Optional fields:

8. purpose
9. project
10. category

Rules:

- Never invent financial information.
- If a value is not visible, return null.
- Preserve transaction/reference/UPI IDs exactly.
- payment_date should preferably be YYYY-MM-DD.
- amount must be the actual transferred/paid amount.
- Do not use account balance, cashback, reward or advertisement amounts.
- paid_to should be the visible recipient/merchant/person name.
- payment_app may be Google Pay, PhonePe, Paytm, bank app, etc.
- payment_mode may be UPI, bank transfer, IMPS, NEFT, etc.
- Do NOT waste time trying to determine project or category.
- If project is not clearly visible, return null.
- If category is not clearly visible, return null.
- If purpose is not clearly visible, return null.
- confidence should be 0 to 100.

IMPORTANT:

This payment will be manually reviewed before approval.

Therefore partial extraction is acceptable.

Set:

needs_review = true

Use review_reason to briefly mention which important fields
still require manual confirmation.
"""


# ============================================================
# PREPARE IMAGE FOR FAST PROCESSING
# ============================================================

def prepare_image(image_path):

    image = Image.open(
        image_path
    )

    image.load()

    # Convert unsupported modes to RGB
    if image.mode not in (
        "RGB",
        "L"
    ):
        image = image.convert(
            "RGB"
        )

    # Resize large screenshots.
    # Payment text remains readable while reducing processing time.
    width, height = image.size

    largest_side = max(
        width,
        height
    )

    if largest_side > MAX_IMAGE_SIZE:

        scale = (
            MAX_IMAGE_SIZE
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
# CHECK WHETHER AI EXTRACTED ANY USEFUL DATA
# ============================================================

def has_useful_payment_data(payment):

    if payment is None:
        return False

    useful_fields = [
        payment.amount,
        payment.paid_to,
        payment.payment_date,
        payment.transaction_id,
        payment.payment_app,
        payment.payment_mode
    ]

    return any(
        value not in (
            None,
            ""
        )
        for value in useful_fields
    )


# ============================================================
# ANALYZE PAYMENT SCREENSHOT
# ============================================================

def analyze_payment_screenshot(
    image_path
):

    image_path = Path(
        image_path
    )

    # --------------------------------------------------------
    # FILE CHECK
    # --------------------------------------------------------

    if not image_path.exists():

        return ExtractionResult(
            success=False,
            error="Screenshot file does not exist."
        )

    # --------------------------------------------------------
    # PREPARE SMALLER IMAGE
    # --------------------------------------------------------

    try:

        image = prepare_image(
            image_path
        )

    except Exception as e:

        return ExtractionResult(
            success=False,
            error=(
                "Invalid image: "
                + str(e)
            )
        )

    # --------------------------------------------------------
    # CLIENT
    # --------------------------------------------------------

    try:

        client = get_client()

    except Exception as e:

        return ExtractionResult(
            success=False,
            error=str(e)
        )

    # --------------------------------------------------------
    # ONE AI ATTEMPT ONLY
    # --------------------------------------------------------

    try:

        response = client.models.generate_content(
            model=MODEL_NAME,

            contents=[
                PAYMENT_PROMPT,
                image
            ],

            config={
                "response_mime_type":
                    "application/json",

                "response_schema":
                    PaymentTransaction,

                "temperature":
                    0
            }
        )

        payment = None

        # ----------------------------------------------------
        # STRUCTURED RESULT
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
        # JSON TEXT FALLBACK
        # ----------------------------------------------------

        elif getattr(
            response,
            "text",
            None
        ):

            payment = (
                PaymentTransaction
                .model_validate_json(
                    response.text
                )
            )

        # ----------------------------------------------------
        # NOTHING RETURNED
        # ----------------------------------------------------

        if payment is None:

            return ExtractionResult(
                success=False,
                error=(
                    "Gemini returned no "
                    "payment information."
                )
            )

        # ----------------------------------------------------
        # CHECK USEFUL DATA
        # ----------------------------------------------------

        if not has_useful_payment_data(
            payment
        ):

            return ExtractionResult(
                success=False,
                error=(
                    "AI could not detect any "
                    "useful payment information."
                )
            )

        # ----------------------------------------------------
        # ALWAYS SEND TO MANUAL REVIEW
        # ----------------------------------------------------

        payment.needs_review = True

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
            payment=payment
        )

    # --------------------------------------------------------
    # AI ERROR
    # --------------------------------------------------------

    except Exception as e:

        error_text = str(e)

        return ExtractionResult(
            success=False,
            error=error_text,
            quota_error=is_quota_error(
                error_text
            )
        )


# ============================================================
# VALIDATE EXTRACTED PAYMENT
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
    # BASIC PAYMENT FIELDS
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
    # GCGW ACCOUNTING FIELDS
    # --------------------------------------------------------

    if not payment.project:

        problems.append(
            "Project requires confirmation"
        )

    if not payment.category:

        problems.append(
            "Category requires confirmation"
        )

    # --------------------------------------------------------
    # ALWAYS MANUAL REVIEW
    # --------------------------------------------------------

    if payment.review_reason:

        if (
            payment.review_reason
            not in problems
        ):

            problems.append(
                payment.review_reason
            )

    return {

        # We intentionally do NOT auto-approve
        # screenshot payments.

        "valid": True,

        "needs_review": True,

        "problems": problems
    }


# ============================================================
# PUBLIC FUNCTION USED BY APP.PY
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
    # TOTAL AI FAILURE
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
    # PARTIAL / COMPLETE AI EXTRACTION
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

        "error":
            None
    }
