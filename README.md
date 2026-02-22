# INSUR AI App

Plataforma de analisis inmobiliario basada en PDF, con frontend en Streamlit, backend en FastAPI, modelos ML en Python y orquestacion n8n.

## 1. Vision del proyecto

El sistema permite:

1. Subir documentos PDF inmobiliarios.
2. Extraer e interpretar informacion estructurada.
3. Ejecutar modelos de riesgo/comportamiento/forecast y modelos inmobiliarios.
4. Generar decisiones accionables y resumen ejecutivo.
5. Construir un PRD descargable en PDF.

## 2. Arquitectura operativa

El proyecto soporta dos modos de trabajo.

### Modo A (recomendado para operacion diaria): Frontend -> n8n

1. `frontend/app.py` extrae texto del PDF de forma local.
2. Envia el contexto al webhook n8n (`N8N_WEBHOOK_URL`).
3. n8n orquesta agentes y devuelve salida consolidada.
4. El frontend adapta el payload y renderiza KPIs, paneles y PRD.

### Modo B (pipeline Python completo): Frontend/n8n -> FastAPI `/ml/full`

1. FastAPI normaliza documento.
2. Ejecuta inferencias ML (segun tipo de documento).
3. Ejecuta motor de decisiones (`decision_engine`).
4. Devuelve resultado completo con trazabilidad.

## 3. Stack tecnico

- Frontend: Streamlit + Plotly.
- Backend API: FastAPI + Uvicorn.
- Orquestacion: n8n.
- ML tabular: scikit-learn + joblib.
- Procesamiento PDF: pypdf, pdfplumber, pypdfium2 (OCR opcional con OpenAI).
- Persistencia: SQLite (`data/app_runs.db`).

## 4. Estructura del repositorio

```text
backend/
  main.py
  schemas.py
  models/
  services/
frontend/
  app.py
data/
  generate_dataset.py
  train.py
  raw/
artifacts/
docs/
workflows_n8n/
docker-compose.yml
requirements.txt
```

## 5. Requisitos

- Python 3.12+
- pip
- (Opcional) Docker + Docker Compose
- Claves API segun flujo (OpenAI / n8n)

## 6. Instalacion local (sin Docker)

### 6.1 Crear entorno e instalar dependencias

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 6.2 Configurar `.env`

Ejemplo minimo:

```env
N8N_WEBHOOK_URL=https://TU_N8N/webhook/insur-multiagente
N8N_STRICT_DECISIONS=true
OPENAI_API_KEY=TU_API_KEY
```

### 6.3 Levantar backend (terminal 1)

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn backend.main:app --reload --port 8000
```

Nota: si ejecutas `uvicorn main:app` fallara porque el modulo correcto es `backend.main`.

### 6.4 Levantar frontend (terminal 2)

```powershell
.\.venv\Scripts\Activate.ps1
python -m streamlit run frontend/app.py
```

Frontend disponible en `http://localhost:8501`.

## 7. Levantar con Docker Compose

```bash
docker compose up -d
```

Servicios por defecto:

- Frontend: `http://localhost:8501`
- n8n: `http://localhost:5678`

Importante: el `docker-compose.yml` actual levanta frontend + n8n. El backend FastAPI se ejecuta aparte si necesitas `/ml/full` o endpoints API.

## 8. Variables de entorno importantes

### Frontend / n8n

- `N8N_WEBHOOK_URL`: webhook de analisis multi-agente.
- `N8N_STRICT_DECISIONS`: valida contrato estricto de salida n8n.
- `N8N_WEBHOOK_PATH`: path para compose local (default `insur-multiagente`).
- `N8N_OPENAI_MODEL`: modelo OpenAI usado por n8n.

### Backend

- `OPENAI_API_KEY`: requerido para PRD con OpenAI y OCR OpenAI.
- `OPENAI_EXTRACT_MODEL`: modelo para extraccion semantica.
- `OPENAI_OCR_MODEL`: modelo para OCR.
- `OPENAI_OCR_MAX_PAGES`: limite de paginas OCR.
- `OPENAI_PRD_MODEL`: modelo para generacion PRD.
- `MIN_EXTRACT_CHARS`: minimo de texto para permitir analisis.
- `ML_PREDICT_API_TOKEN`: token del endpoint `/ml/predict`.

## 9. Endpoints principales (FastAPI)

- `GET /health`
- `GET /ml/status`
- `POST /extract`
- `POST /normalize`
- `POST /ml/run`
- `POST /ml/behavior`
- `POST /ml/forecast`
- `POST /ml/full`
- `POST /ml/predict`
- `POST /decisions`
- `POST /generate-prd`
- `POST /generate-prd/pdf`
- `GET /runs`
- `GET /runs/{run_id}`
- `GET /documents/{document_id}`

## 10. Como hacer que n8n invoque modelos ML para decisiones

Para que las decisiones usen los modelos Python del proyecto:

1. Desde n8n, llama `POST http://TU_BACKEND/ml/full`.
2. Envia `full_text` y/o `extraction.full_text` con `horizon_days`.
3. Usa la respuesta completa de `/ml/full` como salida del workflow.

Payload minimo ejemplo:

```json
{
  "document_id": "doc-123",
  "full_text": "texto extraido del PDF",
  "extraction": {
    "full_text": "texto extraido del PDF",
    "char_count": 1800,
    "quality_status": "ok",
    "usable_for_analysis": true
  },
  "horizon_days": 90
}
```

Si usas `/ml/predict`, enviar header `x-api-key: <ML_PREDICT_API_TOKEN>`.

## 11. Contrato recomendado de salida n8n hacia frontend

Para paneles KPI completos (clientes y ventas), incluir:

- `status`
- `report_type` (`clientes` u `operaciones`)
- `informe_ejecutivo` (objeto con score, recomendacion, decisiones, matriz_riesgo)
- `commercial.output.kpis` con `kpi_mode` y metricas numericas
- `commercial.output.series` para graficos
- `data_scientist`, `analista_financiero`, `analista_mercado`

Si faltan metricas numericas, el frontend mostrara ceros en varios KPIs.

## 12. Dataset y entrenamiento de modelos

### 12.1 Generar datasets

```powershell
python data/generate_dataset.py --domain all
```

Genera tablas en `data/raw/` y `dataset_manifest.json`.

### 12.2 Entrenar modelos

```powershell
python data/train.py --domain all
```

Genera artefactos en `artifacts/`:

- `segmentation_model.joblib`
- `behavior_model.joblib`
- `forecast_model.joblib`
- `re_sale_price_model.joblib`
- `re_rent_model.joblib`
- `re_liquidity_model.joblib`
- `re_investment_score_model.joblib`
- `metrics.json`
- `model_diagnostics.json`

## 13. PRD (Product Requirements Document)

El PRD se puede generar por:

1. n8n (si tu workflow responde `prd_text` o equivalente), o
2. fallback local del frontend, o
3. backend `/generate-prd` y `/generate-prd/pdf`.

Archivo/fuentes clave:

- `backend/services/prd_generator.py`
- `backend/services/prd_pdf.py`
- `frontend/app.py` (boton `Generar PRD`)

## 14. Persistencia y trazabilidad

- Base de datos local: `data/app_runs.db`
- PDFs subidos: `uploads/`
- Historial de ejecuciones y PRD asociado via `run_store`.

## 15. Troubleshooting rapido

### Error: `N8N_WEBHOOK_URL no configurado`

- Configura `N8N_WEBHOOK_URL` en `.env`.
- Reinicia Streamlit.

### Error: `Could not import module "main"`

- Comando correcto:
  - `uvicorn backend.main:app --reload --port 8000`

### Error de conexion `ConnectionResetError(10054)` al analizar

- Verifica que n8n este activo y el workflow en estado `Active`.
- Revisa timeout/red y tamano de payload.

### KPIs en cero (clientes o ventas)

- El webhook no esta devolviendo metricas numericas suficientes.
- Incluye en respuesta los campos KPI recomendados en la seccion 11.

### Caracteres raros en UI (por ejemplo texto corrupto)

- Problema de codificacion UTF-8 en texto de entrada/salida.
- Forzar UTF-8 en nodos de n8n y en archivos de datos.

## 16. Seguridad

- No subir `.env` ni claves reales al repositorio.
- Rotar claves si fueron expuestas.
- Para integraciones externas, usar tokens (`ML_PREDICT_API_TOKEN`).

## 17. Documentacion adicional

- `docs/n8n_end_to_end.md`
- `workflows_n8n/README.md`
- `workflows_n8n/insur_multiagente_blueprint.md`
- `frontend/README.md`
