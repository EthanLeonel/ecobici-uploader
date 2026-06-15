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
            "connect-src 'self' https://storage.googleapis.com"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# ── Tipos de archivo ──────────────────────────────────────────────────────────
VIAJES_RE     = re.compile(r"^viajes-\d{4}-(0[1-9]|1[0-2])\.csv$")
ESTACIONES_RE = re.compile(r"^estaciones-\d{4}-(0[1-9]|1[0-2])\.csv$")

VIAJES_COLS = {
    "Genero_Usuario", "Edad_Usuario", "Bici",
    "Ciclo_Estacion_Retiro", "Fecha_Retiro", "Hora_Retiro",
    "Ciclo_EstacionArribo", "Fecha_Arribo", "Hora_Arribo",
}

ESTACIONES_COLS = {
    "sistema", "num_cicloe", "calle_prin", "calle_secu",
    "colonia", "alcaldia", "latitud", "longitud", "sitio_de_e", "estatus",
}

# ── Config ────────────────────────────────────────────────────────────────────
BUCKET_NAME    = os.environ.get("GCS_BUCKET_NAME", "ecobici-raw-data")
SIGNED_URL_TTL = 15  # minutos


def detect_type(filename: str):
    """Devuelve (tipo, carpeta) según el prefijo del nombre, o (None, None) si no aplica."""
    if VIAJES_RE.match(filename):
        return "viajes", "viajes"
    if ESTACIONES_RE.match(filename):
        return "estaciones", "estaciones"
    return None, None


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
    Valida el nombre del archivo, detecta el tipo (viajes / estaciones) y
    devuelve una Signed URL de GCS para upload directo desde el browser.
    """
    filename = body.filename.strip()

    tipo, carpeta = detect_type(filename)
    if tipo is None:
        raise HTTPException(
            400,
            "El nombre debe ser viajes-YYYY-MM.csv o estaciones-YYYY-MM.csv "
            f"(ej. viajes-2026-01.csv). Se recibió: {filename}",
        )

    blob_path = f"{carpeta}/{filename}"

    try:
        credentials, _ = google.auth.default()
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)

        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        blob   = bucket.blob(blob_path)

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

    return {"signed_url": signed_url, "blob_path": blob_path, "tipo": tipo}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
