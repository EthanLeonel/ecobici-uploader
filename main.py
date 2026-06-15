import asyncio
import csv
import os
import re

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from google.cloud import storage
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

# ── Security headers middleware ───────────────────────────────────────────────
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
            "connect-src 'self'"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# ── Config ────────────────────────────────────────────────────────────────────
BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "ecobici-raw-data")
GCS_FOLDER = os.environ.get("GCS_FOLDER", "raw")
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE_MB", "300")) * 1024 * 1024

REQUIRED_COLUMNS = {
    "Genero_Usuario", "Edad_Usuario", "Bici",
    "Ciclo_Estacion_Retiro", "Fecha_Retiro", "Hora_Retiro",
    "Ciclo_EstacionArribo", "Fecha_Arribo", "Hora_Arribo",
}

FILENAME_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])\.csv$")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"bucket": BUCKET_NAME},
    )


@app.post("/upload")
@limiter.limit("10/minute")
async def upload(request: Request, file: UploadFile = File(...)):
    # 1. Extensión
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos .csv")

    # 2. Formato YYYY-MM.csv
    if not FILENAME_RE.match(file.filename):
        raise HTTPException(
            status_code=400,
            detail=(
                f"El nombre debe tener el formato YYYY-MM.csv "
                f"(ej. 2026-01.csv). Se recibió: {file.filename}"
            ),
        )

    # 3. Tamaño máximo (via Content-Length header)
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"El archivo excede el límite permitido de {MAX_FILE_SIZE // (1024*1024)} MB.",
        )

    # 4. Leer primeros bytes para validar encabezados sin cargar todo en memoria
    header_chunk = await file.read(16_384)

    if not header_chunk:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")

    try:
        try:
            sample = header_chunk.decode("utf-8")
        except UnicodeDecodeError:
            sample = header_chunk.decode("latin-1")

        lines = sample.splitlines()
        if not lines:
            raise HTTPException(status_code=400, detail="El CSV no tiene contenido.")

        header = next(csv.reader([lines[0]]))
        actual = {c.strip() for c in header}
        missing = REQUIRED_COLUMNS - actual
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Columnas faltantes: {', '.join(sorted(missing))}",
            )

        if len(lines) < 2 or not lines[1].strip():
            raise HTTPException(
                status_code=400,
                detail="El archivo CSV no contiene datos (solo encabezados).",
            )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Error al leer el CSV: {exc}")

    # 5. Volver al inicio y subir a GCS en thread para no bloquear el event loop
    await file.seek(0)
    blob_path = f"{GCS_FOLDER}/{file.filename}" if GCS_FOLDER else file.filename

    try:
        def _upload():
            client = storage.Client()
            bucket = client.bucket(BUCKET_NAME)
            blob = bucket.blob(blob_path)
            blob.upload_from_file(file.file, content_type="text/csv")

        await asyncio.to_thread(_upload)

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error al subir a GCS: {exc}")

    return {
        "success": True,
        "message": f"Se ha cargado exitosamente el archivo {file.filename}",
        "destino": f"gs://{BUCKET_NAME}/{blob_path}",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
