# Frontend Dashboard (n8n-only)

## Ejecutar

```bash
pip install -r requirements.txt
python -m streamlit run frontend/app.py
```

## Configuracion

En `.env`:

```bash
N8N_WEBHOOK_URL=https://tu-n8n/webhook/insur-multiagente
N8N_STRICT_DECISIONS=true
```

## Funcionalidades

- Carga de PDF.
- Extraccion local de texto para contexto.
- Pipeline de analisis via webhook n8n.
- Resumen ejecutivo + decisiones estrategicas.
- PRD con solicitud a n8n y fallback local.
- Exportacion JSON/CSV/PDF.
