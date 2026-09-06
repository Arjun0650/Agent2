# GCGW Payment Management Agent

AI-powered payment management system for
Gopal Chavan Guniting Work.

## Features

- Payment screenshot upload
- Gemini payment extraction
- Duplicate detection
- Needs Review workflow
- Approved payment Excel storage
- Expense summaries
- Project/category tracking
- Pending AI handling
- Payment question interface

## Environment Variables

GOOGLE_API_KEY
GEMINI_MODEL

Do NOT commit your API key.

## Start locally

pip install -r requirements.txt

uvicorn app:app --host 0.0.0.0 --port 8000
