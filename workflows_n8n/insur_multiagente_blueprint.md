# Blueprint - Workflow n8n Multi-Agente

Este blueprint corresponde al flujo visual usado en el proyecto.

## Grafo

1. Entrada - Webhook
2. Preparar contexto
3. Agente Orquestador - Clasificar y extraer
4. Parsear respuesta del Orquestador
5. Agente Data Scientist
6. Parsear Data Scientist
7. Agente Analista Financiero
8. Parsear Analista Financiero
9. Agente Analista de Mercado
10. Parsear Analista Mercado
11. Consolidar resultados de los 3 agentes
12. Agente Orquestador - Informe Ejecutivo
13. Construir respuesta final
14. Responder al frontend

## Referencia completa

- `docs/n8n_end_to_end.md`

## Contrato de salida obligatorio

- `workflows_n8n/insur_multiagente_response_example.json`
