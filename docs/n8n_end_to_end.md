# Configuracion n8n End-to-End (INSUR AI)

Este documento deja n8n como orquestador principal del analisis.
El frontend envia `pdf_text` a n8n y n8n responde el informe multi-agente.

## 1) Prerrequisitos

- Docker + Docker Compose
- OpenAI API key valida
- Frontend del proyecto

## 2) Variables de entorno (.env)

Asegura estas variables:

```env
N8N_WEBHOOK_URL=http://localhost:5678/webhook/insur-multiagente
N8N_STRICT_DECISIONS=true
N8N_OPENAI_MODEL=gpt-4.1
OPENAI_API_KEY=***
```

Si usas n8n Cloud, cambia `N8N_WEBHOOK_URL` por:

`<https://TU-ESPACIO.app.n8n.cloud/webhook/insur-multiagente>`

## 3) Levantar stack completo

```bash
docker compose up -d
```

Servicios:

- Frontend: <http://localhost:8501>
- n8n: <http://localhost:5678>

## 4) Crear workflow en n8n (nombres exactos)

Crea un workflow nuevo con estos nodos:

1. `Entrada — Webhook` (Webhook)
2. `Preparar contexto` (Code)
3. `Agente Orquestador — Clasificar y extraer` (HTTP Request)
4. `Parsear respuesta del Orquestador` (Code)
5. `Agente Data Scientist` (HTTP Request)
6. `Parsear Data Scientist` (Code)
7. `Agente Analista Financiero` (HTTP Request)
8. `Parsear Analista Financiero` (Code)
9. `Agente Analista de Mercado` (HTTP Request)
10. `Parsear Analista Mercado` (Code)
11. `Consolidar resultados de los 3 agentes` (Code)
12. `Agente Orquestador — Informe Ejecutivo` (HTTP Request)
13. `Construir respuesta final` (Code)
14. `Responder al frontend` (Respond to Webhook)

Conexiones:

- 1 -> 2 -> 3 -> 4
- 4 -> 5 -> 6
- 4 -> 7 -> 8
- 4 -> 9 -> 10
- 6, 8 y 10 -> 11
- 11 -> 12 -> 13 -> 14

## 5) Configuracion por nodo

### 5.1 Entrada — Webhook

- Method: `POST`
- Path: `insur-multiagente`
- Response mode: `Using 'Respond to Webhook' node`

### 5.2 Preparar contexto (Code)

```javascript
const b = $json || {};
const settings = b.settings || {};
const extraction = b.extraction || {};
const detected = b.detected || {};

return [{
  json: {
    session_id: `INS-${Date.now().toString(36).toUpperCase()}`,
    filename: b.filename || 'documento.pdf',
    document_id: b.document_id || null,
    pdf_text: (b.pdf_text || '').slice(0, 12000),
    extraction,
    detected,
    settings: {
      horizon_days: Number(settings.horizon_days || 90),
      macro_pressure: Number(settings.macro_pressure || 1.0),
      demand_pressure: Number(settings.demand_pressure || 1.0),
    },
    source: b.source || 'frontend',
  }
}];
```

### 5.3 HTTP Request (OpenAI) para todos los agentes

Para `Agente Orquestador — Clasificar y extraer`, `Agente Data Scientist`, `Agente Analista Financiero`, `Agente Analista de Mercado` y `Agente Orquestador — Informe Ejecutivo`:

- Method: `POST`
- URL: `https://api.openai.com/v1/chat/completions`
- Send headers: `Authorization: Bearer {{$env.OPENAI_API_KEY}}`, `content-type: application/json`
- Content type body: JSON

#### Body base

```json
{
  "model": "={{ $env.N8N_OPENAI_MODEL || 'gpt-4.1' }}",
  "temperature": 0,
  "max_completion_tokens": 2200,
  "messages": [
    { "role": "system", "content": "..." },
    { "role": "user", "content": "..." }
  ]
}
```

### 5.4 Prompt de clasificacion (Orquestador inicial)

System:

- "Eres un orquestador inmobiliario. Devuelve SOLO JSON valido. No markdown."

User:

```text
Analiza este texto de PDF y devuelve JSON con:
- tipo_documento (promotora|agencia|inversion|cartera|mercado|viabilidad|duediligence|businessplan|tasacion|rentabilidad|suelo|notasimple)
- confianza_tipo (0-1)
- zona_geografica
- ccaa
- datos_extraidos: { precio_m2, num_unidades, coste_construccion_m2, plazo_meses, roi_declarado_pct }

Texto PDF:
{{ $json.pdf_text }}
```

### 5.5 Parsear respuesta del Orquestador (Code)

```javascript
const raw = $json.choices?.[0]?.message?.content || '';
const m = raw.match(/\{[\s\S]*\}/);
if (!m) throw new Error('Orquestador no devolvio JSON');
const parsed = JSON.parse(m[0]);
return [{ json: { ...$items('Preparar contexto', 0, 0)[0].json, ...parsed } }];
```

### 5.6 Prompts de agentes especializados

- Cada agente recibe el JSON del orquestador inicial.
- Cada agente devuelve SOLO JSON con su bloque:
  - Data Scientist -> `data_scientist`
  - Analista Financiero -> `analista_financiero`
  - Analista Mercado -> `analista_mercado`

Ejemplo User (Data Scientist):

```text
Devuelve SOLO JSON con clave data_scientist.
Incluye: score_riesgo, score_rentabilidad, score_absorcion, score_global,
desviacion_precio_pct, benchmark_precio_zona, ventas_proyectadas_3m,
ventas_proyectadas_6m, ventas_proyectadas_12m, roi_estimado_pct,
variacion_yoy_zona_pct, alertas_cuantitativas[], conclusiones[].

Input:
{{ JSON.stringify($json) }}
```

### 5.7 Parsear agentes (Code)

Usa el mismo parser para cada uno y envuelve en su clave:

```javascript
const raw = $json.choices?.[0]?.message?.content || '';
const m = raw.match(/\{[\s\S]*\}/);
if (!m) throw new Error('Agente no devolvio JSON');
const parsed = JSON.parse(m[0]);
return [{ json: parsed }];
```

### 5.8 Consolidar resultados de los 3 agentes (Code)

```javascript
const ctx = $items('Parsear respuesta del Orquestador', 0, 0)[0].json;
const ds = $items('Parsear Data Scientist', 0, 0)[0].json.data_scientist;
const af = $items('Parsear Analista Financiero', 0, 0)[0].json.analista_financiero;
const am = $items('Parsear Analista Mercado', 0, 0)[0].json.analista_mercado;

return [{ json: { ...ctx, data_scientist: ds, analista_financiero: af, analista_mercado: am } }];
```

### 5.9 Prompt orquestador final (Informe Ejecutivo)

System:

- "Eres director de inversiones inmobiliarias. Devuelve SOLO JSON valido en espanol."

User:

```text
Consolida los tres analisis y devuelve SOLO JSON con clave informe_ejecutivo.
Campos obligatorios:
- score_oportunidad_global (0-100)
- recomendacion_global (INVERTIR|INVERTIR CON CAUTELA|REVISAR|NO INVERTIR)
- resumen_ejecutivo
- decisiones[] con: urgencia(CRITICA|ALTA|MEDIA|BAJA), titulo, descripcion, impacto, confianza
- matriz_riesgo: riesgo_precio, riesgo_absorcion, riesgo_financiero, riesgo_mercado (BAJO|MEDIO|ALTO|CRITICO)
- proximos_pasos[]

Input consolidado:
{{ JSON.stringify($json) }}
```

### 5.10 Construir respuesta final (Code)

```javascript
const base = $items('Consolidar resultados de los 3 agentes', 0, 0)[0].json;
const raw = $json.choices?.[0]?.message?.content || '';
const m = raw.match(/\{[\s\S]*\}/);
if (!m) throw new Error('Informe ejecutivo no devolvio JSON');
const inf = JSON.parse(m[0]).informe_ejecutivo;

if (!inf || !Array.isArray(inf.decisiones)) {
  throw new Error('Contrato invalido: informe_ejecutivo.decisiones');
}

return [{
  json: {
    status: 'success',
    session_id: base.session_id,
    filename: base.filename,
    tipo_documento: base.tipo_documento,
    confianza_tipo: base.confianza_tipo,
    zona_geografica: base.zona_geografica,
    ccaa: base.ccaa,
    datos_extraidos: base.datos_extraidos || {},
    data_scientist: base.data_scientist || {},
    analista_financiero: base.analista_financiero || {},
    analista_mercado: base.analista_mercado || {},
    informe_ejecutivo: inf,
  }
}];
```

### 5.11 Responder al frontend

- Node: `Respond to Webhook`
- Respond with: JSON
- Response body: `={{ $json }}`
- Status code: `200`

## 6) Contrato obligatorio para frontend

Si `N8N_STRICT_DECISIONS=true`, el frontend exige:

- `informe_ejecutivo.score_oportunidad_global`
- `informe_ejecutivo.recomendacion_global`
- `informe_ejecutivo.resumen_ejecutivo`
- `informe_ejecutivo.decisiones[]` con `urgencia` y `titulo`

## 7) Prueba end-to-end

1. Activar workflow en n8n.
2. Abrir frontend (`<http://localhost:8501>`).
3. Sidebar:
   - Orquestacion: `n8n webhook`
   - URL webhook: local o cloud segun tu despliegue
4. Subir PDF y ejecutar analisis.
5. En resultados debe aparecer badge: `Decisiones: N8N`.

## 8) Troubleshooting rapido

- Error `n8n no devolvio informe_ejecutivo`:
  - El prompt final no devolvio JSON estricto.
- Error `Webhook 404`:
  - Workflow no activado o path incorrecto.
- Error OpenAI 401/429:
  - API key invalida o cuota agotada.
- Decisiones vacias:
  - Revisa que `informe_ejecutivo.decisiones` sea array con objetos validos.
