import asyncio
import csv
import io
import os
import re

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from google.cloud import storage

app = FastAPI(title="Ecobici Uploader")
templates = Jinja2Templates(directory="templates")

BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "ecobici-raw-data")
GCS_FOLDER = os.environ.get("GCS_FOLDER", "raw")

REQUIRED_COLUMNS = {
    "Genero_Usuario",
    "Edad_Usuario",
    "Bici",
    "Ciclo_Estacion_Retiro",
    "Fecha_Retiro",
    "Hora_Retiro",
    "Ciclo_EstacionArribo",
    "Fecha_Arribo",
    "Hora_Arribo",
}

FILENAME_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])\.csv$")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html", {"request": request, "bucket": BUCKET_NAME}
    )


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
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

    # 3. Leer primeros bytes para validar encabezados sin cargar todo en memoria
    header_chunk = await file.read(16_384)  # 16 KB es suficiente para el header

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

    # 4. Volver al inicio y subir a GCS en thread para no bloquear el event loop
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
