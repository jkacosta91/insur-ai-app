# n8n Workflows - INSUR AI

Workflows de automatizacion para INSUR AI.

## Incluidos

| Archivo | Trigger | Uso |
|---|---|---|
| `supplier_pdf_webhook.json` | HTTP POST con PDF | Pipeline proveedores via n8n |
| `supplier_email_imap.json` | Email con PDF adjunto | Pipeline proveedores por correo |
| `insur_multiagente_blueprint.md` | Documentacion | Mapa de nodos del flujo multi-agente |
| `insur_multiagente_response_example.json` | Contrato JSON | Ejemplo de respuesta valida para frontend |

## Multi-agente inmobiliario (nuevo)

La configuracion completa paso a paso esta en:

- `docs/n8n_end_to_end.md`

Ese documento cubre:

- Levantar n8n con Docker
- Configurar variables y credenciales
- Crear workflow `insur-multiagente` nodo por nodo
- Contrato de salida obligatorio para frontend
- Troubleshooting

## Variables recomendadas en n8n

- `OPENAI_API_KEY=...`
- `N8N_OPENAI_MODEL=gpt-4.1`

## URL n8n local

- Editor: `http://localhost:5678`
- Webhook esperado por frontend: `http://localhost:5678/webhook/insur-multiagente`
