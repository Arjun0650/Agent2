import os
import time
import json
import re
from pathlib import Path
from typing import Optional

from PIL import Image
from pydantic import BaseModel, Field
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

    confidence: Optional[float] = Field(
        default=None,
        ge=0,
        le=100
    )

    needs_review: bool = True

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
# HELPERS
# ============================================

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

    if isinstance(value, (int, float)):

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

    except (TypeError, ValueError):
        return None


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
        "rate_limit",
        "too many requests"
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
You are the payment screenshot reading assistant
for Gopal Chavan Guniting Work (GCGW).

Your job is to read the screenshot and extract
AS MUCH REAL INFORMATION AS POSSIBLE.

IMPORTANT:

A payment DOES NOT need to have every field
available.

If you can identify only some fields, return
those fields and leave the remaining fields null.

For example:

If you can see:

Paid To: KEVIL
Amount: ₹2,000
Date: 02-09-2026
Transaction ID: HDFCF2CF52605882

but Project, Category and Purpose are not visible,
you MUST still return the information you found.

Do NOT fail the extraction merely because some
fields are missing.

Extract:

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


FINANCIAL SAFETY RULES:

1. Never invent an amount.

2. Never invent the recipient/payee.

3. Never invent a transaction/reference ID.

4. Never invent a date or time.

5. Never guess the project.

6. Never guess the category unless the screenshot
   itself provides strong evidence.

7. Never guess the purpose.

8. Missing information must be returned as null.

9. Missing project/category/purpose is NOT an AI
   processing failure.

10. A partially readable screenshot is considered
    successfully processed.

11. If any important field is missing or uncertain,
    set needs_review = true.

12. review_reason should clearly state which fields
    require human confirmation.

13. payment_date should preferably use YYYY-MM-DD.

14. confidence must be between 0 and 100.

15. For UPI payments, preserve the visible
    transaction/reference/UTR number exactly.

16. Do not confuse balances, rewards, cashback,
    advertisements or account balances with the
    payment amount.

17. Read Google Pay, PhonePe, Paytm, UPI and bank
    screenshots carefully.

18. The recipient may appear near labels such as:
    Paid to
    To
    Sent to
    Recipient
    Merchant
    Beneficiary

19. Transaction identifiers may appear as:
    UPI transaction ID
    UTR
    Transaction ID
    Reference ID
    Bank reference
    RRN

20. Return every field that is actually readable,
    even when other fields are unavailable.

21. Accuracy is more important than filling every
    field.

22. Do not fabricate financial information.

EXPECTED BEHAVIOR:

Readable payment + missing project/category
=
SUCCESSFUL EXTRACTION + NEEDS REVIEW

Readable payment + missing purpose
=
SUCCESSFUL EXTRACTION + NEEDS REVIEW

Readable amount/payee but missing transaction ID
=
SUCCESSFUL EXTRACTION + NEEDS REVIEW

Only genuine technical/API/image processing
failure should result in extraction failure.
"""


# ============================================
# CLEAN PAYMENT
# ============================================

def clean_payment(payment):

    if isinstance(
        payment,
        PaymentTransaction
    ):

        data = payment.model_dump()

    elif isinstance(payment, dict):

        data = dict(payment)

    else:

        data = {}


    data["amount"] = (
        normalize_amount(
            data.get("amount")
        )
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


    return PaymentTransaction(
        **data
    )


# ============================================
# ANALYZE ONE SCREENSHOT
# ============================================

def analyze_payment_screenshot(
    image_path,
    max_attempts=1
):

    image_path = Path(
        image_path
    )


    # ----------------------------------------
    # FILE CHECK
    # ----------------------------------------

    if not image_path.exists():

        return ExtractionResult(
            success=False,
            error=(
                "Screenshot file does not exist."
            )
        )


    # ----------------------------------------
    # IMAGE CHECK
    # ----------------------------------------

    try:

        with Image.open(
            image_path
        ) as opened_image:

            opened_image.load()

            # Convert to RGB for consistent
            # Gemini image processing.

            if opened_image.mode != "RGB":

                image = (
                    opened_image
                    .convert("RGB")
                )

            else:

                image = (
                    opened_image
                    .copy()
                )

    except Exception as e:

        return ExtractionResult(
            success=False,
            error=(
                "Invalid image: "
                + str(e)
            )
        )


    # ----------------------------------------
    # GEMINI CLIENT
    # ----------------------------------------

    try:

        client = get_client()

    except Exception as e:

        return ExtractionResult(
            success=False,
            error=str(e)
        )


    last_error = None


    # ----------------------------------------
    # GEMINI RETRIES
    # ----------------------------------------

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


            # =================================
            # STRUCTURED RESPONSE
            # =================================

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


            # =================================
            # JSON TEXT FALLBACK
            # =================================

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

                        raw_data = (
                            json.loads(
                                response_text
                            )
                        )

                        payment = (
                            PaymentTransaction
                            .model_validate(
                                raw_data
                            )
                        )


            # =================================
            # NOTHING RETURNED
            # =================================

            if payment is None:

                raise RuntimeError(
                    "Gemini returned no readable "
                    "payment information."
                )


            # =================================
            # CLEAN VALUES
            # =================================

            payment = clean_payment(
                payment
            )


            # =================================
            # IMPORTANT
            #
            # Partial extraction is SUCCESS.
            # =================================

            return ExtractionResult(
                success=True,
                payment=payment,
                quota_error=False
            )


        except Exception as e:

            last_error = str(e)


            # =================================
            # QUOTA / RATE LIMIT
            # =================================

            if is_quota_error(e):

                return ExtractionResult(
                    success=False,
                    error=last_error,
                    quota_error=True
                )


            # =================================
            # TEMPORARY ERROR RETRY
            # =================================

            if attempt < max_attempts:

                time.sleep(
                    attempt * 2
                )


    # ----------------------------------------
    # ALL ATTEMPTS FAILED
    # ----------------------------------------

    return ExtractionResult(
        success=False,
        error=(
            last_error
            or
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


    # ========================================
    # BASIC PAYMENT DATA
    # ========================================

    if (
        payment.amount is None
        or
        payment.amount <= 0
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
            "Transaction/reference ID "
            "requires confirmation"
        )


    # ========================================
    # GCGW ACCOUNTING DATA
    # ========================================

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
            "Purpose / remark can be "
            "confirmed manually"
        )


    # ========================================
    # GEMINI REVIEW REQUEST
    # ========================================

    if payment.needs_review:

        reason = clean_optional_text(
            payment.review_reason
        )

        if (
            reason
            and
            reason not in problems
        ):

            problems.append(
                reason
            )


    # ========================================
    # CONFIDENCE
    # ========================================

    if (
        payment.confidence is not None
        and
        payment.confidence < 70
    ):

        problems.append(
            "AI confidence is below 70%"
        )


    # Remove duplicate messages while
    # preserving order.

    unique_problems = []

    for problem in problems:

        if problem not in unique_problems:

            unique_problems.append(
                problem
            )


    return {

        # Automatically approve ONLY when
        # there is nothing requiring review.

        "valid":
            len(unique_problems) == 0,

        "needs_review":
            len(unique_problems) > 0,

        "problems":
            unique_problems,

        "partial_extraction":
            len(unique_problems) > 0
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


    # ========================================
    # REAL AI / TECHNICAL FAILURE
    # ========================================

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


    # ========================================
    # VALIDATE PARTIAL DATA
    # ========================================

    validation = (
        validate_extracted_payment(
            payment
        )
    )


    # ========================================
    # IMPORTANT:
    #
    # Even if fields are missing,
    # success remains TRUE.
    #
    # app.py/payment_engine.py can therefore
    # send the record to Needs Review.
    # ========================================

    return {

        "success": True,

        "payment":
            payment.model_dump(),

        "validation":
            validation,

        "quota_error":
            False,

        "partial_extraction":
            validation.get(
                "needs_review",
                False
            ),

        "error":
            None
    }
