"""Modal deployment for the FastAPI backend.

One-time setup:
    pip install modal
    modal setup                          # authenticate
    modal secret create cv-tailor-secrets \
        SUPABASE_URL=... SUPABASE_ANON_KEY=... \
        OPENAI_API_KEY=... CORS_ORIGINS=https://<your-vercel-app>.vercel.app

Deploy:
    modal deploy modal_app.py            # prints the public URL

Local dev (no Modal needed):
    uvicorn app.main:app --reload
"""

import modal

image = (
    modal.Image.debian_slim(python_version="3.12")
    # WeasyPrint (cover-letter PDF) + LibreOffice (CV DOCX→PDF)
    .apt_install(
        "libpango-1.0-0", "libpangocairo-1.0-0", "libgdk-pixbuf-2.0-0",
        "libffi-dev", "shared-mime-info",
        "libreoffice-writer", "fonts-liberation", "fonts-dejavu-core",
    )
    .pip_install_from_requirements("requirements.txt")
    .add_local_python_source("app")
)

app = modal.App("cv-tailor-api")


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("cv-tailor-secrets")],
    # Analyses run as in-process background tasks; keep the container alive
    # long enough for the pipeline to finish after the response returns.
    scaledown_window=300,
    timeout=600,
)
@modal.asgi_app()
def api():
    from app.main import app as fastapi_app
    return fastapi_app
