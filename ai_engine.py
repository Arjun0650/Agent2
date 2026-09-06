
import os
import time
from pathlib import Path
from typing import Optional

from PIL import Image
from pydantic import BaseModel
from google import genai


# ============================================
# CONFIGURATION
# ============================================

MODEL_NAME = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)


# ============================================
# PAYMENT SCHEMA
# ============================================

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

    needs_review: bool = False

    review_reason: Optional[str] = None


# ============================================
# RESULT SCHEMA
# ============================================

class ExtractionResult(BaseModel):

    success: bool

    payment: Optional[
        PaymentTransaction
    ] = None

    error: Optional[str] = None

    quota_error: bool = False


# ============================================
# QUOTA DETECTION
# ============================================

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


# ============================================
# CLIENT
# ============================================

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


# ============================================
# EXTRACTION PROMPT
# ============================================

PAYMENT_PROMPT = """
You are processing a payment screenshot for
Gopal Chavan Guniting Work (GCGW).

Extract ONLY information that is actually
visible or strongly supported by the screenshot.

Return these fields:

- amount
- paid_to
- payment_date
- payment_time
- transaction_id
- payment_mode
- payment_app
- purpose
- project
- category
- confidence
- needs_review
- review_reason

STRICT FINANCIAL SAFETY RULES:

1. Never invent a transaction ID.
2. Never invent a recipient/payee.
3. Never invent an amount.
4. Never invent a date or time.
5. Never guess a project merely because a
   payment looks construction-related.
6. Never guess an expense category unless the
   screenshot provides enough evidence.
7. If project is not visible or supported,
   return project = null.
8. If category is uncertain,
   return category = null.
9. If purpose is not shown or supported,
   return purpose = null.
10. If important information is uncertain,
    set needs_review = true and explain why.
11. payment_date should use YYYY-MM-DD when
    the screenshot provides a reliable date.
12. confidence should be from 0 to 100.
13. For UPI screenshots, preserve the visible
    UPI/reference/transaction identifier exactly.
14. Do not treat decorative text, balances,
    cashback, rewards, or advertisements as
    the payment amount.
15. Accuracy is more important than completing
    every field.

This system must never fabricate financial data.
"""


# ============================================
# ANALYZE ONE SCREENSHOT
# ============================================

def analyze_payment_screenshot(
    image_path,
    max_attempts=3
):

    image_path = Path(
        image_path
    )

    if not image_path.exists():

        return ExtractionResult(
            success=False,
            error=(
                "Screenshot file does not exist."
            )
        )

    try:

        image = Image.open(
            image_path
        )

        # Force-load image while file is open.
        image.load()

    except Exception as e:

        return ExtractionResult(
            success=False,
            error=(
                "Invalid image: "
                + str(e)
            )
        )

    try:

        client = get_client()

    except Exception as e:

        return ExtractionResult(
            success=False,
            error=str(e)
        )

    last_error = None

    for attempt in range(
        1,
        max_attempts + 1
    ):

        try:

            response = (
                client.models.generate_content(
                    model=MODEL_NAME,

                    contents=[
                        PAYMENT_PROMPT,
                        image
                    ],

                    config={
                        "response_mime_type":
                            "application/json",

                        "response_schema":
                            PaymentTransaction
                    }
                )
            )

            payment = None

            # Preferred structured result
            if getattr(
                response,
                "parsed",
                None
            ) is not None:

                parsed = response.parsed

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

            # Fallback JSON parsing
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

            if payment is None:

                raise RuntimeError(
                    "Gemini returned no "
                    "structured payment data."
                )

            return ExtractionResult(
                success=True,
                payment=payment
            )

        except Exception as e:

            last_error = str(e)

            if is_quota_error(e):

                return ExtractionResult(
                    success=False,
                    error=last_error,
                    quota_error=True
                )

            # Temporary service errors can
            # succeed after a short retry.
            if attempt < max_attempts:

                time.sleep(
                    attempt * 2
                )

    return ExtractionResult(
        success=False,
        error=(
            last_error or
            "Unknown Gemini extraction error."
        )
    )


# ============================================
# VALIDATE EXTRACTED PAYMENT
# ============================================

def validate_extracted_payment(
    payment
):

    if isinstance(payment, dict):

        payment = (
            PaymentTransaction
            .model_validate(
                payment
            )
        )

    problems = []

    if (
        payment.amount is None
        or payment.amount <= 0
    ):

        problems.append(
            "Amount is missing or invalid"
        )

    if not payment.paid_to:

        problems.append(
            "Payee is missing"
        )

    if not payment.payment_date:

        problems.append(
            "Payment date is missing"
        )

    if not payment.transaction_id:

        problems.append(
            "Transaction/reference ID is missing"
        )

    # GCGW safety policy:
    # Do not automatically approve without
    # confirmed project and category.

    if not payment.project:

        problems.append(
            "Project requires confirmation"
        )

    if not payment.category:

        problems.append(
            "Category requires confirmation"
        )

    if payment.needs_review:

        reason = (
            payment.review_reason
            or
            "AI requested manual review"
        )

        if reason not in problems:
            problems.append(reason)

    return {
        "valid":
            len(problems) == 0,

        "needs_review":
            len(problems) > 0,

        "problems":
            problems
    }


# ============================================
# PUBLIC WEB EXTRACTION FUNCTION
# ============================================

def extract_payment_for_web(
    image_path
):

    result = (
        analyze_payment_screenshot(
            image_path
        )
    )

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
