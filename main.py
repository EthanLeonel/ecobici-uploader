import datetime
import os
import re

import google.auth
import google.auth.transport.requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from google.cloud import storage
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

# ── Rate limiting ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Ecobici Uploader")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

templates = Jinja2Templates(directory="templates")


# ── Security headers ──────────────────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline' cdn.tailwindcss.com; "
            "connect-src 'self' https://storage.googleapis.com"  # permite XHR a GCS
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# ── Config ────────────────────────────────────────────────────────────────────
BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "ecobici-raw-data")
GCS_FOLDER = os.environ.get("GCS_FOLDER", "raw")
SIGNED_URL_TTL = 15  # minutos de validez para la URL firmada

FILENAME_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])\.csv$")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"bucket": BUCKET_NAME},
    )


class UploadUrlRequest(BaseModel):
    filename: str


@app.post("/get-upload-url")
@limiter.limit("10/minute")
async def get_upload_url(request: Request, body: UploadUrlRequest):
    """
    Valida el nombre del archivo y devuelve una Signed URL de GCS para que
    el browser suba el archivo directamente sin pasar por Cloud Run.
    Esto evita el límite de 32 MB del HTTP load balancer y permite archivos
    de cualquier tamaño.
    """
    filename = body.filename.strip()

    if not filename.lower().endswith(".csv"):
        raise HTTPException(400, "Solo se aceptan archivos .csv")

    if not FILENAME_RE.match(filename):
        raise HTTPException(
            400,
            f"El nombre debe tener el formato YYYY-MM.csv "
            f"(ej. 2026-01.csv). Se recibió: {filename}",
        )

    blob_path = f"{GCS_FOLDER}/{filename}" if GCS_FOLDER else filename

    try:
        # Usar las credenciales del service account de Cloud Run para firmar
        credentials, _ = google.auth.default()
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)

        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(blob_path)

        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=SIGNED_URL_TTL),
            method="PUT",
            content_type="text/csv",
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
        )
    except Exception as exc:
        raise HTTPException(500, f"Error al generar URL de carga: {exc}")

    return {"signed_url": signed_url, "blob_path": blob_path}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
