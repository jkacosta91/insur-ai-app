# INSUR AI App

Plataforma multi-agente para analisis inmobiliario basado en documentos PDF.

Frontend en Streamlit, backend en FastAPI, modelos ML en Python y orquestacion con n8n.

---

## Concepto del Sistema

El sistema implementa una arquitectura hibrida con orquestacion multi-agente donde:

- Un agente **Data Scientist** evalua riesgo, scoring y senales cuantitativas.
- Un agente **Financiero** analiza viabilidad y fortalezas/debilidades.
- Un agente **de Mercado** estudia posicionamiento y tendencias.
- Un **orquestador n8n** consolida decisiones estructuradas.
- Se genera un **PRD ejecutivo descargable en PDF**.

El valor del sistema depende de la consistencia estructurada del JSON devuelto por n8n hacia el frontend.

---

## Arquitectura General

![Arquitectura](docs/images/worflow%20n8n.jpeg)

Flujos soportados:

### Modo A (operacion recomendada)
Frontend -> n8n -> Frontend

### Modo B (pipeline ML completo)
Frontend/n8n -> FastAPI `/ml/full` -> n8n -> Frontend

---

## Demo Visual

### Subida de Documento
![Upload](docs/images/intefaz%201.jpeg)

### Orquestacion Multi-Agente
![Orquestador](docs/images/intefaz%209.jpeg)

### Dashboard de KPIs
![KPIs](docs/images/intefaz%208.jpeg)

### Matriz de Riesgo
![Riesgo](docs/images/intefaz%205.jpeg)

### Decisiones Prioritarias
![Decisiones](docs/images/intefaz%206.jpeg)

---

## Arquitectura Operativa

### Modo A (Frontend -> n8n)

1. `frontend/app.py` extrae texto local del PDF.
2. Envia contexto al webhook `N8N_WEBHOOK_URL`.
3. n8n ejecuta agentes en paralelo.
4. Devuelve JSON estructurado.
5. El frontend adapta el payload y renderiza:
- Resumen Ejecutivo
- KPIs y graficos
- Panel por agente
- Matriz de riesgo
- PRD descargable

### Modo B (Pipeline ML Python)

1. FastAPI normaliza documento.
2. Ejecuta modelos ML (riesgo, forecast, scoring).
3. Ejecuta motor de decisiones.
4. Devuelve resultado completo con trazabilidad.

---

## Stack Tecnico

- Frontend: Streamlit + Plotly
- Backend API: FastAPI + Uvicorn
- Orquestacion: n8n
- ML: scikit-learn + joblib
- PDF: ReportLab
- Procesamiento PDF: pypdf, pdfplumber, pypdfium2
- Persistencia: SQLite (`data/app_runs.db`)

---

## Estructura del Repositorio

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

---

## Variables de Entorno Clave

### Frontend / n8n

- `N8N_WEBHOOK_URL`
- `N8N_STRICT_DECISIONS`
- `N8N_WEBHOOK_PATH`
- `N8N_OPENAI_MODEL`

### Backend

- `OPENAI_API_KEY`
- `OPENAI_PRD_MODEL`
- `OPENAI_EXTRACT_MODEL`
- `OPENAI_OCR_MODEL`
- `ML_PREDICT_API_TOKEN`
- `MIN_EXTRACT_CHARS`

---

## Instalacion Local (sin Docker)

### Crear entorno e instalar dependencias

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Levantar backend

```powershell
uvicorn backend.main:app --reload --port 8000
```

### Levantar frontend

```powershell
python -m streamlit run frontend/app.py
```

Frontend disponible en:

`http://localhost:8501`

---

## Docker

```bash
docker compose up -d
```

Servicios por defecto:

- Frontend -> `http://localhost:8501`
- n8n -> `http://localhost:5678`

---

## Modelos ML

### Generar datasets

```powershell
python data/generate_dataset.py --domain all
```

### Entrenar modelos

```powershell
python data/train.py --domain all
```

Artefactos generados en `artifacts/`.

---

## Generacion PRD

Puede generarse mediante:

- n8n (si devuelve `prd_text`)
- Backend `/generate-prd`
- Fallback local en frontend

Archivos clave:

- `backend/services/prd_generator.py`
- `backend/services/prd_pdf.py`
- `frontend/app.py`

---

## Contrato Recomendado n8n -> Frontend

La respuesta debe incluir:

- `report_type`
- `informe_ejecutivo`
- `commercial.output.kpis`
- `commercial.output.series`
- `data_scientist`
- `analista_financiero`
- `analista_mercado`

Si faltan metricas numericas estructuradas, el frontend mostrara KPIs en cero.

---

## Persistencia y Trazabilidad

- Base SQLite -> `data/app_runs.db`
- PDFs -> `uploads/`
- Historial via `run_store`

---

## Seguridad

- No subir `.env`
- No exponer claves reales
- Usar tokens para endpoints sensibles
- Rotar credenciales si fueron expuestas

---

## Documentacion Adicional

- `docs/n8n_end_to_end.md`
- `workflows_n8n/README.md`
- `workflows_n8n/insur_multiagente_blueprint.md`
- `frontend/README.md`

---

## Documentos de Prueba

El sistema fue probado con los siguientes documentos:

- [PDF Ventas](docs/samples/OPERACIONES.pdf)
- [PDF Clientes](docs/samples/CLIENTES.pdf)

### Ejemplo de PRD generado

- [PRD Ejecutivo - Clientes](docs/samples/PRD_Informe_Masivo_Clientes_Sector_Inmobiliario_2026.pdf)
- [PRD Ejecutivo - Ventas](docs/samples/PRD_Informe_Masivo_Ventas_Sector_Inmobiliario_2026.pdf)
