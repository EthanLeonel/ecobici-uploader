# Ecobici CDMX — Cargador de Datos

Interfaz web para subir datasets mensuales de Ecobici CDMX a Google Cloud Storage.  
Stack: **FastAPI · Docker · Cloud Run · Artifact Registry · Cloud Build · GCS**

---

## Arquitectura

```
Usuario → Cloud Run (FastAPI) → Cloud Storage  gs://BUCKET/raw/YYYY-MM.csv
                ↑
         Artifact Registry (imagen Docker)
                ↑
          Cloud Build (CI/CD automático)
```

---

## Requisitos previos

| Herramienta | Versión mínima |
|---|---|
| Python | 3.11 |
| gcloud CLI | última |
| Docker | 24+ |
| gh CLI | 2+ |

---

## Configuración local (desarrollo)

```bash
# 1. Clonar el repo
git clone https://github.com/<usuario>/ecobici-uploader.git
cd ecobici-uploader

# 2. Copiar variables de entorno y editarlas
cp .env.example .env
# → Edita GCS_BUCKET_NAME con el nombre de TU bucket

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Autenticarse con GCP (ADC)
gcloud auth application-default login

# 5. Ejecutar localmente
uvicorn main:app --reload --port 8080
# Abre http://localhost:8080
```

---

## Variables de entorno

| Variable | Descripción | Default |
|---|---|---|
| `GCS_BUCKET_NAME` | Nombre del bucket de GCS | `ecobici-raw-data` |
| `GCS_FOLDER` | Carpeta dentro del bucket | `raw` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Ruta al JSON de credenciales (solo local) | — |

Cada compañero debe configurar **su propio** `GCS_BUCKET_NAME` o usar el bucket centralizado del equipo.

---

## Primer deploy a Cloud Run

```bash
chmod +x deploy.sh
bash deploy.sh <PROJECT_ID> [REGION] [BUCKET_NAME]

# Ejemplo
bash deploy.sh ml-nube us-central1 ecobici-raw-data
```

El script:
1. Habilita las APIs necesarias
2. Crea el repositorio en Artifact Registry
3. Crea el bucket de GCS
4. Asigna permisos a Cloud Build
5. Construye la imagen y la sube
6. Despliega el servicio en Cloud Run

---

## CI/CD automático con Cloud Build

Conecta tu repositorio de GitHub a Cloud Build para que cada push a `main` dispare un build y re-deploy automático:

1. En la consola de GCP → **Cloud Build → Triggers → Crear trigger**
2. Conecta el repositorio de GitHub
3. Rama: `^main$`
4. Archivo de configuración: `cloudbuild.yaml`
5. Agrega las substituciones si cambias defaults:
   - `_BUCKET` → nombre de tu bucket
   - `_REGION` → región de Cloud Run

---

## Validaciones del uploader

El sistema valida antes de subir a GCS:

- El archivo debe ser `.csv`
- El nombre debe seguir el formato **`YYYY-MM.csv`** (ej. `2026-01.csv`)
- Debe contener las siguientes columnas:

| Columna |
|---|
| `Genero_Usuario` |
| `Edad_Usuario` |
| `Bici` |
| `Ciclo_Estacion_Retiro` |
| `Fecha_Retiro` |
| `Hora_Retiro` |
| `Ciclo_EstacionArribo` |
| `Fecha_Arribo` |
| `Hora_Arribo` |

- El archivo no puede estar vacío ni tener solo encabezados

---

## Fuente de datos

Los datasets se obtienen del portal oficial de Ecobici CDMX:  
**https://ecobici.cdmx.gob.mx/datos-abiertos/**
