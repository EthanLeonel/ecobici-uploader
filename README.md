# Ecobici CDMX — Cargador de Datasets Mensuales

Interfaz web para subir datasets mensuales de Ecobici CDMX a Google Cloud Storage.  
Stack: **FastAPI · Docker · Cloud Run · Artifact Registry · Cloud Build · GCS**

---

## Arquitectura

```
Usuario → Cloud Run (FastAPI)
            ├─ Valida nombre y detecta tipo (viajes / estaciones)
            └─ Devuelve Signed URL (15 min)

Usuario → GCS directo (PUT con Signed URL)
            ├─ gs://BUCKET/viajes/viajes-YYYY-MM.csv
            └─ gs://BUCKET/estaciones/estaciones-YYYY-MM.csv
```

> El archivo **nunca pasa por Cloud Run**. El servidor solo genera la URL firmada (~50 bytes de payload), lo que permite archivos de cualquier tamaño sin límite de infraestructura.

---

## Tipos de archivo soportados

| Tipo | Formato de nombre | Carpeta en GCS | Columnas requeridas |
|---|---|---|---|
| **Viajes** | `viajes-YYYY-MM.csv` | `viajes/` | `Genero_Usuario, Edad_Usuario, Bici, Ciclo_Estacion_Retiro, Fecha_Retiro, Hora_Retiro, Ciclo_EstacionArribo, Fecha_Arribo, Hora_Arribo` |
| **Estaciones** | `estaciones-YYYY-MM.csv` | `estaciones/` | `sistema, num_cicloe, calle_prin, calle_secu, colonia, alcaldia, latitud, longitud, sitio_de_e, estatus` |

Ejemplos válidos: `viajes-2026-01.csv`, `estaciones-2026-03.csv`

---

## Clonar y ejecutar localmente

```bash
# 1. Clonar
git clone https://github.com/EthanLeonel/ecobici-uploader.git
cd ecobici-uploader

# 2. Variables de entorno
cp .env.example .env
# → Edita GCS_BUCKET_NAME con el nombre de tu bucket

# 3. Dependencias
pip install -r requirements.txt

# 4. Autenticarse con GCP
gcloud auth application-default login

# 5. Ejecutar
uvicorn main:app --reload --port 8080
# Abre http://localhost:8080
```

---

## Variables de entorno

| Variable | Descripción | Default |
|---|---|---|
| `GCS_BUCKET_NAME` | Nombre del bucket de GCS | `ecobici-raw-data` |

> **Para tus compañeros:** cada quien configura su propio `GCS_BUCKET_NAME` en `.env`, o todos apuntan al bucket centralizado del equipo.

---

## Primer deploy a Cloud Run

```bash
chmod +x deploy.sh
bash deploy.sh <PROJECT_ID> [REGION] [BUCKET_NAME]

# Ejemplo
bash deploy.sh ml-nube us-central1 ecobici-cdmx-datos
```

El script:
1. Habilita APIs (Cloud Run, GCS, Artifact Registry, Cloud Build)
2. Crea el repositorio en Artifact Registry
3. Crea el bucket y las carpetas `viajes/` y `estaciones/`
4. Asigna permisos a Cloud Build y al service account de Cloud Run
5. Construye la imagen Docker y la sube
6. Despliega el servicio en Cloud Run

---

## CI/CD con Cloud Build

Cada push a `main` dispara build + redeploy automático:

1. **Cloud Build → Triggers → Crear trigger**
2. Conecta el repositorio de GitHub
3. Rama: `^main$`
4. Archivo de configuración: `cloudbuild.yaml`
5. Sustituciones opcionales:
   - `_BUCKET` → nombre de tu bucket
   - `_REGION` → región de Cloud Run

---

## Validaciones

Antes de cualquier petición al servidor, el **cliente** valida:

- Extensión `.csv`
- Formato de nombre correcto (`viajes-YYYY-MM.csv` o `estaciones-YYYY-MM.csv`)
- Archivo no vacío y menor a 300 MB
- Columnas requeridas (lee los primeros 8 KB con FileReader)

El **servidor** re-valida el nombre antes de generar la URL firmada (defensa en profundidad).

---

## Seguridad implementada

| # | Componente | Qué protege |
|---|---|---|
| 1 | Rate limiting 10 req/min por IP | DoS, abuso de API |
| 2 | X-Content-Type-Options: nosniff | MIME sniffing |
| 3 | X-Frame-Options: DENY | Clickjacking |
| 4 | Content-Security-Policy | XSS |
| 5 | Strict-Transport-Security | MITM / downgrade HTTP |
| 6 | Referrer-Policy | Filtración de URLs internas |
| 7 | Permissions-Policy | Acceso a cámara/micrófono/GPS |
| 8 | Validación de nombre (cliente + servidor) | Path traversal, archivos maliciosos |
| 9 | Validación de columnas en cliente | Schema inválido |
| 10 | Signed URLs con TTL 15 min | Acceso no autorizado a GCS |
| 11 | CORS restrictivo en bucket | Peticiones desde dominios ajenos |
| 12 | Ocultamiento de rutas internas | Information disclosure |
| 13 | Límite de tamaño 300 MB | DoS por archivos enormes |

---

## Fuente de datos

Los datasets se obtienen del portal oficial de Ecobici CDMX:  
**https://ecobici.cdmx.gob.mx/datos-abiertos/**
