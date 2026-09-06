import os
import json
from pathlib import Path
from datetime import date, datetime

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from openpyxl import load_workbook

from ai_engine import extract_payment_for_web
from payment_engine import (
    process_extracted_payment,
    add_pending_ai,
    approve_review_payment
)


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR = BASE_DIR / "data"

WORKBOOK_FILE = DATA_DIR / "GCGW_Payment_Management.xlsx"
PENDING_FILE = DATA_DIR / "pending_ai_queue.json"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="GCGW Payment Management Agent",
    description=(
        "Payment and expenditure management "
        "for Gopal Chavan Guniting Work."
    ),
    version="1.1.0"
)

app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static"
)


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def safe_amount(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_date(value):

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if not value:
        return None

    text = str(value).strip()

    for fmt in (
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y/%m/%d"
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass

    return None


def load_gcgw_workbook():

    if not WORKBOOK_FILE.exists():
        raise FileNotFoundError(
            f"GCGW workbook is unavailable: {WORKBOOK_FILE}"
        )

    return load_workbook(
        WORKBOOK_FILE,
        data_only=False
    )


# ============================================================
# APPROVED PAYMENTS
# ============================================================

def get_approved_payments():

    workbook = load_gcgw_workbook()

    sheet = workbook["All Payments"]

    records = []

    for row in range(2, sheet.max_row + 1):

        internal_id = sheet.cell(row, 1).value

        if not internal_id:
            continue

        status = clean_text(
            sheet.cell(row, 14).value
        )

        if status.lower() != "approved":
            continue

        payment_date = normalize_date(
            sheet.cell(row, 2).value
        )

        records.append({
            "id": clean_text(internal_id),

            "date": (
                payment_date.isoformat()
                if payment_date
                else clean_text(
                    sheet.cell(row, 2).value
                )
            ),

            "time": clean_text(
                sheet.cell(row, 3).value
            ),

            "amount": safe_amount(
                sheet.cell(row, 4).value
            ),

            "paid_to": clean_text(
                sheet.cell(row, 5).value
            ),

            "project": clean_text(
                sheet.cell(row, 6).value
            ),

            "category": clean_text(
                sheet.cell(row, 7).value
            ),

            "purpose": clean_text(
                sheet.cell(row, 8).value
            ),

            "payment_mode": clean_text(
                sheet.cell(row, 9).value
            ),

            "payment_app": clean_text(
                sheet.cell(row, 10).value
            ),

            "reference_no": clean_text(
                sheet.cell(row, 11).value
            ),

            "screenshot": clean_text(
                sheet.cell(row, 12).value
            ),

            "confidence": safe_amount(
                sheet.cell(row, 13).value
            ),

            "status": status
        })

    workbook.close()

    return records


# ============================================================
# NEEDS REVIEW
# ============================================================

def get_review_payments():

    workbook = load_gcgw_workbook()

    sheet = workbook["Needs Review"]

    records = []

    for row in range(2, sheet.max_row + 1):

        transaction_id = sheet.cell(
            row,
            1
        ).value

        if not transaction_id:
            continue

        decision = clean_text(
            sheet.cell(row, 8).value
        )

        if decision.lower() in {
            "approved",
            "rejected",
            "deleted"
        }:
            continue

        records.append({
            "row": row,

            "transaction_id":
                clean_text(transaction_id),

            "date":
                clean_text(
                    sheet.cell(row, 2).value
                ),

            "amount":
                safe_amount(
                    sheet.cell(row, 3).value
                ),

            "paid_to":
                clean_text(
                    sheet.cell(row, 4).value
                ),

            "project":
                clean_text(
                    sheet.cell(row, 5).value
                ),

            "category":
                clean_text(
                    sheet.cell(row, 6).value
                ),

            "reason":
                clean_text(
                    sheet.cell(row, 7).value
                ),

            "decision":
                decision or "Pending",

            "screenshot":
                clean_text(
                    sheet.cell(row, 9).value
                ),

            "time":
                clean_text(
                    sheet.cell(row, 10).value
                ),

            "payment_mode":
                clean_text(
                    sheet.cell(row, 11).value
                ),

            "payment_app":
                clean_text(
                    sheet.cell(row, 12).value
                ),

            "purpose":
                clean_text(
                    sheet.cell(row, 13).value
                ),

            "confidence":
                safe_amount(
                    sheet.cell(row, 14).value
                )
        })

    workbook.close()

    return records


# ============================================================
# PENDING AI
# ============================================================

def get_pending_ai():

    if not PENDING_FILE.exists():
        return []

    try:

        data = json.loads(
            PENDING_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(data, list):
            return data

    except Exception:
        pass

    return []


# ============================================================
# ACCOUNTING SUMMARY
# ============================================================

def accounting_summary():

    payments = get_approved_payments()
    review = get_review_payments()
    pending = get_pending_ai()

    today = date.today()

    total = 0.0
    today_total = 0.0
    month_total = 0.0

    project_totals = {}
    category_totals = {}

    for payment in payments:

        amount = payment["amount"]

        total += amount

        payment_date = normalize_date(
            payment["date"]
        )

        if payment_date:

            if payment_date == today:
                today_total += amount

            if (
                payment_date.year == today.year
                and
                payment_date.month == today.month
            ):
                month_total += amount

        project = (
            payment["project"]
            or "Unassigned"
        )

        category = (
            payment["category"]
            or "Other"
        )

        project_totals[project] = (
            project_totals.get(project, 0)
            + amount
        )

        category_totals[category] = (
            category_totals.get(category, 0)
            + amount
        )

    return {
        "total_expenditure":
            round(total, 2),

        "this_month":
            round(month_total, 2),

        "today":
            round(today_total, 2),

        "approved_payments":
            len(payments),

        "needs_review":
            len(review),

        "pending_ai":
            len(pending),

        "project_totals":
            project_totals,

        "category_totals":
            category_totals
    }


# ============================================================
# HOME
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse
)
def home():

    index_file = (
        TEMPLATES_DIR /
        "index.html"
    )

    return index_file.read_text(
        encoding="utf-8"
    )


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    workbook_ready = (
        WORKBOOK_FILE.exists()
    )

    return {
        "status":
            (
                "healthy"
                if workbook_ready
                else "degraded"
            ),

        "application":
            "GCGW Payment Management Agent",

        "workbook":
            workbook_ready,

        "version":
            "1.1.0"
    }


# ============================================================
# SUMMARY
# ============================================================

@app.get("/api/summary")
def summary():

    try:
        return accounting_summary()

    except Exception as e:

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


# ============================================================
# PAYMENT HISTORY
# ============================================================

@app.get("/api/payments")
def payment_history():

    try:

        payments = (
            get_approved_payments()
        )

        payments.reverse()

        return {
            "success": True,
            "count": len(payments),
            "payments": payments
        }

    except Exception as e:

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


# ============================================================
# REVIEW QUEUE
# ============================================================

@app.get("/api/review")
def review_queue():

    try:

        payments = (
            get_review_payments()
        )

        return {
            "success": True,
            "count": len(payments),
            "payments": payments
        }

    except Exception as e:

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


# ============================================================
# APPROVE REVIEW PAYMENT
# ============================================================

@app.post(
    "/api/review/{review_row}/approve"
)
async def approve_review(
    review_row: int,
    payload: dict
):

    try:

        result = (
            approve_review_payment(
                review_row,
                payload
            )
        )

        if not result.get("success"):

            return JSONResponse(
                status_code=400,
                content=result
            )

        return result

    except Exception as e:

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "status": "FAILED",
                "error": str(e)
            }
        )


# ============================================================
# PENDING AI
# ============================================================

@app.get("/api/pending-ai")
def pending_ai():

    payments = get_pending_ai()

    return {
        "success": True,
        "count": len(payments),
        "payments": payments
    }


# ============================================================
# DOWNLOAD UPDATED EXCEL
# ============================================================

@app.get("/api/download-excel")
def download_excel():

    try:

        if not WORKBOOK_FILE.exists():

            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error":
                        "GCGW Excel workbook was not found."
                }
            )

        timestamp = datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S"
        )

        download_name = (
            "GCGW_Payment_Management_"
            f"{timestamp}.xlsx"
        )

        return FileResponse(
            path=str(WORKBOOK_FILE),
            filename=download_name,
            media_type=(
                "application/vnd.openxmlformats-"
                "officedocument.spreadsheetml.sheet"
            )
        )

    except Exception as e:

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


# ============================================================
# SCREENSHOT UPLOAD
# ============================================================

@app.post("/api/upload")
async def upload_payment_screenshots(
    files: list[UploadFile] = File(...)
):

    allowed = {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp"
    }

    results = []

    approved = 0
    needs_review = 0
    pending_ai_count = 0
    duplicates = 0
    failed = 0

    for uploaded_file in files:

        original_name = (
            uploaded_file.filename
            or "payment"
        )

        safe_name = Path(
            original_name
        ).name

        extension = Path(
            safe_name
        ).suffix.lower()

        # -----------------------------------
        # VALIDATE FILE
        # -----------------------------------

        if extension not in allowed:

            results.append({
                "filename":
                    safe_name,

                "status":
                    "REJECTED",

                "error":
                    "Unsupported image format."
            })

            failed += 1
            continue

        # -----------------------------------
        # UNIQUE SCREENSHOT NAME
        # -----------------------------------

        destination = (
            UPLOAD_DIR /
            safe_name
        )

        counter = 1

        while destination.exists():

            destination = (
                UPLOAD_DIR /
                (
                    f"{Path(safe_name).stem}"
                    f"_{counter}"
                    f"{extension}"
                )
            )

            counter += 1

        # -----------------------------------
        # SAVE SCREENSHOT
        # -----------------------------------

        try:

            content = (
                await uploaded_file.read()
            )

            destination.write_bytes(
                content
            )

        except Exception as e:

            results.append({
                "filename":
                    safe_name,

                "status":
                    "FAILED",

                "error":
                    (
                        "Could not store screenshot: "
                        + str(e)
                    )
            })

            failed += 1
            continue

        stored_name = destination.name

        # -----------------------------------
        # AI EXTRACTION
        # -----------------------------------

        try:

            extraction = (
                extract_payment_for_web(
                    destination
                )
            )

        except Exception as e:

            extraction = {
                "success": False,
                "error": str(e),
                "quota_error": False
            }

        # -----------------------------------
        # AI FAILURE
        # -----------------------------------

        if not extraction.get("success"):

            error_text = (
                extraction.get("error")
                or
                "AI extraction failed."
            )

            pending_result = (
                add_pending_ai(
                    stored_name,
                    error_text
                )
            )

            results.append({
                "filename":
                    stored_name,

                "status":
                    "PENDING_AI",

                "quota_error":
                    extraction.get(
                        "quota_error",
                        False
                    ),

                "error":
                    error_text,

                "pending":
                    pending_result
            })

            pending_ai_count += 1
            continue

        # -----------------------------------
        # PAYMENT DATA
        # -----------------------------------

        payment = (
            extraction.get("payment")
            or {}
        )

        validation = (
            extraction.get("validation")
            or {}
        )

        # -----------------------------------
        # PROCESS PAYMENT
        # -----------------------------------

        try:

            decision = (
                process_extracted_payment(
                    payment=payment,
                    validation=validation,
                    screenshot_filename=
                        stored_name
                )
            )

        except Exception as e:

            results.append({
                "filename":
                    stored_name,

                "status":
                    "FAILED",

                "error":
                    (
                        "Payment processing failed: "
                        + str(e)
                    )
            })

            failed += 1
            continue

        status = (
            decision.get(
                "status",
                "FAILED"
            )
        )

        if status == "APPROVED":
            approved += 1

        elif status == "NEEDS_REVIEW":
            needs_review += 1

        elif status == "DUPLICATE":
            duplicates += 1

        else:
            failed += 1

        results.append({
            "filename":
                stored_name,

            "status":
                status,

            "payment":
                payment,

            "validation":
                validation,

            "decision":
                decision
        })

    return {
        "success": True,

        "uploaded":
            len(results),

        "approved":
            approved,

        "needs_review":
            needs_review,

        "pending_ai":
            pending_ai_count,

        "duplicates":
            duplicates,

        "failed":
            failed,

        "results":
            results
    }


# ============================================================
# ACCOUNTING AGENT
# ============================================================

@app.post("/api/ask")
async def ask_agent(payload: dict):

    question = clean_text(
        payload.get("question")
    )

    if not question:

        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error":
                    "Question is required."
            }
        )

    q = question.lower()

    summary_data = (
        accounting_summary()
    )

    payments = (
        get_approved_payments()
    )

    answer = None

    # TOTAL EXPENDITURE

    if (
        "total expenditure" in q
        or "total spent" in q
        or "total spending" in q
    ):

        answer = (
            "Total approved expenditure is "
            f"₹{summary_data['total_expenditure']:,.2f}."
        )

    # MONTH

    elif (
        "this month" in q
        or "month expenditure" in q
    ):

        answer = (
            "Approved expenditure this month is "
            f"₹{summary_data['this_month']:,.2f}."
        )

    # TODAY

    elif (
        "today" in q
        and
        (
            "spend" in q
            or "expenditure" in q
            or "paid" in q
        )
    ):

        answer = (
            "Approved expenditure today is "
            f"₹{summary_data['today']:,.2f}."
        )

    # HIGHEST PROJECT

    elif (
        "highest" in q
        and
        "project" in q
    ):

        totals = (
            summary_data[
                "project_totals"
            ]
        )

        if totals:

            project = max(
                totals,
                key=totals.get
            )

            answer = (
                f"{project} currently has "
                "the highest approved expenditure "
                f"at ₹{totals[project]:,.2f}."
            )

        else:

            answer = (
                "There are no approved "
                "project expenses yet."
            )

    # PROJECT SEARCH

    if answer is None:

        for project, amount in (
            summary_data[
                "project_totals"
            ].items()
        ):

            if (
                project
                and
                project.lower() in q
            ):

                answer = (
                    f"Approved expenditure for "
                    f"{project} is "
                    f"₹{amount:,.2f}."
                )

                break

    # CATEGORY SEARCH

    if answer is None:

        for category, amount in (
            summary_data[
                "category_totals"
            ].items()
        ):

            if (
                category
                and
                category.lower() in q
            ):

                answer = (
                    f"Approved expenditure for "
                    f"{category} is "
                    f"₹{amount:,.2f}."
                )

                break

    # PAYEE SEARCH

    if answer is None:

        matching = []

        for payment in payments:

            payee = (
                payment["paid_to"]
                .lower()
            )

            if (
                payee
                and
                payee in q
            ):
                matching.append(
                    payment
                )

        if matching:

            amount = sum(
                item["amount"]
                for item in matching
            )

            answer = (
                f"There are {len(matching)} "
                "approved payment(s) matching "
                f"that payee, totaling "
                f"₹{amount:,.2f}."
            )

    # SAFE FALLBACK

    if answer is None:

        answer = (
            "I could not answer that safely "
            "from the current accounting rules. "
            "No financial data was guessed."
        )

    return {
        "success": True,
        "question": question,
        "answer": answer,
        "source": "GCGW Excel records"
    }


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    import uvicorn

    port = int(
        os.environ.get(
            "PORT",
            8000
        )
    )

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port
    )
