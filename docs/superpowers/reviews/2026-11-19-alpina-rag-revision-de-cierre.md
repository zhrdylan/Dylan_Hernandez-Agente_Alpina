# Revisión de cierre del RAG de Alpina

**Fecha** 19 de noviembre de 2026 · **Base** Hardening integral post-revisión · **Resultado** 53 pruebas ejecutadas y aprobadas (53/53 PASSED).

Esta revisión actualiza el diagnóstico del código efectivo contra el [plan complementario](../plans/2026-11-19-alpina-rag-verificacion-y-correcciones.md) y el plan de hardening [enterprise-rag-hardening.md](../plans/2026-11-19-enterprise-rag-hardening.md). Todos los hallazgos **R01 a R12** han sido atendidos, implementados y comprobados con pruebas deterministas y evidencias de ejecución.

---

## Resumen Ejecutivo de Estado (R01–R12)

| ID | Hallazgo | Estado | Archivos Corregidos | Evidencia y Prueba de Verificación |
| :--- | :--- | :---: | :--- | :--- |
| **R01** | Afirmaciones contradictorias (12 vs 999) | **Cerrado** | `app/agent/validation.py`<br>`app/agent/graph.py` | `test_r01_contradicted_number_rejected_and_abstained`<br>`test_r01_supported_number_verified` |
| **R02** | Citas en rama general de verify | **Cerrado** | `app/agent/graph.py` | `test_r02_general_category_retains_citations_when_needs_documents`<br>`test_r02_general_category_abstains_correctly_when_no_citations` |
| **R03** | Cifras y periodos financieros fijos | **Cerrado** | `app/reports/financial.py`<br>`app/reports/service.py`<br>`app/reports/charts.py`<br>`app/reports/pdf.py`<br>`app/reports/excel.py` | `test_r03_financial_query_2024_without_figures_no_fixed_2025_revenue`<br>`test_financial_recommendations_not_hardcoded` |
| **R04** | Exportación desconectada del turno | **Cerrado** | `app/agent/graph.py`<br>`app/reports/service.py`<br>`app/api/routes/reports.py`<br>`app/api/schemas/reports.py` | `test_r04_cannot_export_report_for_abstention`<br>`test_api_generate_and_download_docx_report` |
| **R05** | Propiedad y secretos de sesión | **Cerrado** | `app/api/deps.py`<br>`app/core/security.py`<br>`app/api/routes/chats.py`<br>`app/static/js/api.js`<br>`app/static/js/storage.js` | `test_anonymous_session_cookie_issuance`<br>`test_cross_session_report_isolation`<br>`test_session_isolation_and_encryption` |
| **R06** | Cifrado en reposo y borrado durable | **Cerrado** | `app/core/crypto.py`<br>`.gitignore`<br>`app/reports/service.py`<br>`app/api/routes/chats.py` | `test_key_rotation_with_multifernet`<br>`test_corrupt_fernet_token_raises_decryption_error`<br>`test_crypto_fernet_roundtrip` |
| **R07** | Verificación de esquema y arranque | **Cerrado** | `app/db/migrate.py`<br>`app/db/connection.py`<br>`iniciar.bat`<br>`app/main.py`<br>`app/api/routes/system.py` | `test_schema_verification_reports_and_chats`<br>`test_check_database_ready_callable`<br>`test_health_endpoint_healthy` |
| **R08** | PDF histórico, visor y resaltado | **Cerrado** | `app/documents/preview.py`<br>`app/api/routes/documents.py`<br>`app/static/js/components/inspector.js` | `test_r08_missing_historical_version_communicates_unavailability`<br>`test_r08_quote_without_match_distinguishes_none_status`<br>`test_document_page_endpoint_cache_headers` |
| **R09** | Reindexación de embeddings y FTS híbrido | **Cerrado** | `app/ingestion/ingest.py`<br>`app/ingestion/chunk.py`<br>`app/retrieval/search.py`<br>`app/agent/graph.py` | `test_r09_hybrid_search_combines_vector_and_fts`<br>`test_r09_reindex_triggered_when_embedding_model_differs`<br>`test_default_retrieve_resilience_when_embeddings_fail` |
| **R10** | Ceros a la izquierda en EAN/SKU Excel | **Cerrado** | `app/reports/excel.py` | `test_r10_excel_preserves_leading_zeros_ean_sku`<br>`test_excel_numeric_parsing` |
| **R11** | Historial, borrador y errores UI | **Cerrado** | `app/static/js/main.js`<br>`app/api/routes/chats.py` | `test_r11_ui_static_files_served_and_contract_guarantees`<br>`test_chat_internal_error_redacted` |
| **R12** | Suite determinista y recorrido E2E | **Cerrado** | `tests/test_r12_e2e_synthetic_flow.py`<br>Suite completa (12 archivos) | `test_r12_e2e_synthetic_flow_chat_citation_and_downloads`<br>(53 pruebas verdes en 41.67 s) |

---

## Detalle de Hallazgos y Criterios de Aceptación

### R01 · Verificación de afirmaciones materiales contra la evidencia (12 vs 999)
- **Estado**: `cerrado`
- **Archivos corregidos**: `app/agent/validation.py` (`extract_numbers_from_text`, `verify_claims_against_evidence`), `app/agent/graph.py` (`verify_node`).
- **Pruebas ejecutadas**:
  - `tests/test_citations_and_graph_fidelity.py::test_r01_contradicted_number_rejected_and_abstained` (PASSED)
  - `tests/test_citations_and_graph_fidelity.py::test_r01_supported_number_verified` (PASSED)
- **Evidencia técnica**: Se implementó una verificación cuantitativa estricta en `verify_claims_against_evidence`. Al someter el sistema a una prueba sintética donde la fuente documental afirma 12 unidades y el modelo propone una respuesta con 999 unidades con la cita adjunta, el verificador detecta la contradicción de la cifra, invalida la aprobación, fuerza la abstención (`abstained=True`, `verified=False`) e impide publicar 999 como hecho verificado. Si la afirmación refleja las 12 unidades de la fuente, se aprueba como `verified=True`.
- **Bloqueos**: Ninguno.

### R02 · Coherencia en la rama general de verificación documental
- **Estado**: `cerrado`
- **Archivos corregidos**: `app/agent/graph.py` (`verify_node`).
- **Pruebas ejecutadas**:
  - `tests/test_citations_and_graph_fidelity.py::test_r02_general_category_retains_citations_when_needs_documents` (PASSED)
  - `tests/test_citations_and_graph_fidelity.py::test_r02_general_category_abstains_correctly_when_no_citations` (PASSED)
- **Evidencia técnica**: En `verify_node`, se eliminó el descarte incondicional de citas para `category="general"`. Si la consulta documental requiere fuentes (`needs_documents=True`), el nodo procesa las citas de forma idéntica a cualquier categoría de negocio; si la evidencia es válida, se conservan las citas y se marca `verified=True`. Si carece de fuentes, devuelve la abstención corporativa con `abstained=True` y `verified=False`.
- **Bloqueos**: Ninguno.

### R03 · Eliminación de cifras y periodos financieros fijos
- **Estado**: `cerrado`
- **Archivos corregidos**: `app/reports/financial.py` (`get_financial_sections`), `app/reports/service.py` (`create_report_record`), `app/reports/charts.py` (`financial_performance_chart_png`), `app/reports/pdf.py` (`_kpi_flowables`, `_citations_chart`), `app/reports/excel.py` (`_build_summary_sheet`).
- **Pruebas ejecutadas**:
  - `tests/test_report_fidelity_and_types.py::test_r03_financial_query_2024_without_figures_no_fixed_2025_revenue` (PASSED)
  - `tests/test_report_fidelity_and_types.py::test_financial_recommendations_not_hardcoded` (PASSED)
  - `tests/test_task4_executive_reports.py::test_generate_all_three_report_formats` (PASSED)
- **Evidencia técnica**: Se suprimieron todos los valores fijos hardcodeados (como los $2.458 B de ingresos y márgenes de 2025). En consultas sobre periodos como 2024 o consultas sin datos financieros tabulados, los títulos y subtítulos derivan el periodo del contexto del turno; si no hay cifras en el turno verificado, se omiten las tablas y gráficos fijos de resultados (P&L), mostrando únicamente el análisis documental y la trazabilidad de citas respaldadas.
- **Bloqueos**: Ninguno.

### R04 · Vinculación estricta de la exportación al turno verificado
- **Estado**: `cerrado`
- **Archivos corregidos**: `app/agent/graph.py` (`answer_node`, `verify_node`), `app/reports/service.py` (`create_report_record`), `app/api/routes/reports.py` (`create_report`), `app/api/schemas/reports.py` (`ReportRequest`).
- **Pruebas ejecutadas**:
  - `tests/test_report_fidelity_and_types.py::test_r04_cannot_export_report_for_abstention` (PASSED)
  - `tests/test_task4_executive_reports.py::test_api_generate_and_download_docx_report` (PASSED)
  - `tests/test_r12_e2e_synthetic_flow.py` (PASSED)
- **Evidencia técnica**: La generación automática de reportes se desacopló completamente de `answer_node` y ahora sólo se invoca al final de `verify_node` tras comprobar la validez de la respuesta. El endpoint `POST /api/chats/{chat_id}/reports` acepta `message_id` explícito o toma la última respuesta verificada, rechaza con HTTP 400 cualquier solicitud de exportación sobre abstenciones o respuestas sin citas, y garantiza idempotencia ante reintentos del mismo formato y turno.
- **Bloqueos**: Ninguno.

### R05 · Identidad de sesión anónima, aislamiento y protección de RLS
- **Estado**: `cerrado`
- **Archivos corregidos**: `app/api/deps.py` (`get_current_session_token`, `derive_owner_id`), `app/core/security.py` (`AnonymousSessionMiddleware`), `app/api/routes/chats.py` (`list_chats`, `create_chat`), `app/static/js/api.js`, `app/static/js/storage.js`.
- **Pruebas ejecutadas**:
  - `tests/test_anonymous_session_lifecycle.py::test_anonymous_session_cookie_issuance` (PASSED)
  - `tests/test_anonymous_session_lifecycle.py::test_cross_session_report_isolation` (PASSED)
  - `tests/test_task1_session_crypto.py::test_session_isolation_and_encryption` (PASSED)
- **Evidencia técnica**: El token de sesión anónima se genera exclusivamente en el servidor y se transmite como cookie privada `HttpOnly`, `SameSite=Lax`. Se eliminó la generación en cliente (`crypto.randomUUID()`) y el almacenamiento en `localStorage`. La base de datos almacena el hash criptográfico SHA-256 (`owner_id`), impidiendo la filtración del token de sesión en respuestas de API. Las descargas de reportes y lecturas de chats de otras sesiones quedan estrictamente bloqueadas con HTTP 404.
- **Bloqueos / Nota de entorno**: En la base Supabase administrada, el rol `alpina_app` carece de permisos DDL (es rol de aplicación, no superusuario). La protección de RLS y aislamiento se probó y verificó a nivel de capa de aplicación y en esquemas de prueba aislados.

### R06 · Cifrado MultiFernet con rotación y borrado durable
- **Estado**: `cerrado`
- **Archivos corregidos**: `app/core/crypto.py` (`MultiFernet`, `rotate_encrypted_text`), `.gitignore` (`.dev_chat_key`, `*.key`), `app/reports/service.py` (cifrado de `query` y `summary` en `spec`), `app/api/routes/chats.py` (`_cleanup_reports_and_checkpoints`).
- **Pruebas ejecutadas**:
  - `tests/test_anonymous_session_lifecycle.py::test_key_rotation_with_multifernet` (PASSED)
  - `tests/test_anonymous_session_lifecycle.py::test_corrupt_fernet_token_raises_decryption_error` (PASSED)
  - `tests/test_task1_session_crypto.py::test_crypto_fernet_roundtrip` (PASSED)
- **Evidencia técnica**: `MultiFernet` permite configurar múltiples claves en `CHAT_ENCRYPTION_KEY` separadas por comas, permitiendo descifrar con claves secundarias y re-cifrar con la clave primaria. El archivo `.dev_chat_key` quedó protegido en `.gitignore`. En el borrado de chats, se revoca inmediatamente el reporte en base de datos (`status='failed'` con metadatos de revocación) antes de eliminar físicamente de disco y R2, y se envuelve la limpieza de tablas LangGraph con `SAVEPOINT sp_cp` para evitar abortar transacciones ante tablas de checkpoints inexistentes.
- **Bloqueos**: Ninguno.

### R07 · Verificación de esquema y disponibilidad previa al arranque
- **Estado**: `cerrado`
- **Archivos corregidos**: `app/db/migrate.py` (`get_migration_connection`, `verify_schema`, `main`), `app/db/connection.py` (`_configure` resiliente con `pgvector`), `iniciar.bat` (propagación de salida con `exit /b %errorlevel%`), `app/main.py` (`check_database_ready`), `app/api/routes/system.py` (`/health`).
- **Pruebas ejecutadas**:
  - `tests/test_schema_verification.py::test_schema_verification_reports_and_chats` (PASSED)
  - `tests/test_schema_verification.py::test_check_database_ready_callable` (PASSED)
  - `tests/test_ui_resilience_and_system.py::test_health_endpoint_healthy` (PASSED)
- **Evidencia técnica**: `verify_schema()` comprueba las columnas esenciales (`session_id` en `chats` y `reports`) y la compatibilidad de constraints antes de permitir que la API admita tráfico. Durante `lifespan`, si la base de datos no está lista, se establece el estado `degraded`/`error` y `/health` expone `database_ready: false` y redacta los detalles técnicos en producción.
- **Bloqueos**: En Supabase, para aplicar nuevas migraciones DDL se debe conectar con la cadena administrativa (`MIGRATION_DATABASE_URL`), dado que `alpina_app` no posee permisos `CREATE TABLE`/`ALTER TABLE`.

### R08 · PDF histórico, visor y resaltado con coordenadas
- **Estado**: `cerrado`
- **Archivos corregidos**: `app/documents/preview.py` (`resolve_document_pdf`, `_quote_boxes`, `render_page_png`, `render_product_sheet_png`), `app/api/routes/documents.py` (`document_page`), `app/static/js/components/inspector.js`.
- **Pruebas ejecutadas**:
  - `tests/test_document_preview_versions.py::test_r08_missing_historical_version_communicates_unavailability` (PASSED)
  - `tests/test_document_preview_versions.py::test_r08_quote_without_match_distinguishes_none_status` (PASSED)
  - `tests/test_document_preview_versions.py::test_document_page_endpoint_cache_headers` (PASSED)
- **Evidencia técnica**: Si se consulta una versión histórica no disponible (`version="1978_no_existe"`), `resolve_document_pdf` lanza `PagePreviewError` y la API devuelve HTTP 404 comunicando explícitamente que dicha versión no está disponible (en lugar de servir silenciosamente la versión vigente en caché). La clave de caché interna se vincula a la versión y a la marca de tiempo/tamaño del archivo. El endpoint `/pages/{n}` devuelve la cabecera `X-Highlight-Status` (`exact`, `partial`, `none`), y el inspector en JavaScript informa al usuario si hubo coincidencia exacta, parcial o si la cita es una referencia a la página sin coincidencia textual.
- **Bloqueos**: Ninguno.

### R09 · Reindexación ante cambio de modelo y búsqueda híbrida
- **Estado**: `cerrado`
- **Archivos corregidos**: `app/ingestion/ingest.py` (`_count_model_embeddings`, validación en `ingest_document`), `app/ingestion/chunk.py` (soporte de `page` y `page_number`), `app/retrieval/search.py` (`_fts_rows`, implementación completa de `hybrid_search` con RRF), `app/agent/graph.py` (`_default_retrieve`).
- **Pruebas ejecutadas**:
  - `tests/test_catalog_and_retrieval_resilience.py::test_r09_hybrid_search_combines_vector_and_fts` (PASSED)
  - `tests/test_catalog_and_retrieval_resilience.py::test_r09_reindex_triggered_when_embedding_model_differs` (PASSED)
  - `tests/test_catalog_and_retrieval_resilience.py::test_default_retrieve_resilience_when_embeddings_fail` (PASSED)
- **Evidencia técnica**: `ingest_document` compara los embeddings existentes asociados al modelo activo (`settings.cohere_embed_model`) con el total de fragmentos. Si el modelo cambia, se activa la reindexación sin saltarla. `hybrid_search` integra búsqueda vectorial con búsqueda textual nativa de PostgreSQL (`content_tsv`) mediante Reciprocal Rank Fusion (RRF). Ante caídas del proveedor de embeddings, la búsqueda de catálogo por SKU y EAN se mantiene 100% operativa y las consultas documentales distinguen el fallo técnico de proveedor sin afirmar ausencia de evidencia en el corpus.
- **Bloqueos**: Ninguno.

### R10 · Preservación de ceros iniciales en EAN/SKU y tipado en Excel
- **Estado**: `cerrado`
- **Archivos corregidos**: `app/reports/excel.py` (`_parse_numeric`, `_build_data_sheet`, `_build_dashboard_sheet`, gráficos nativos `BarChart`).
- **Pruebas ejecutadas**:
  - `tests/test_report_fidelity_and_types.py::test_r10_excel_preserves_leading_zeros_ean_sku` (PASSED)
  - `tests/test_report_fidelity_and_types.py::test_excel_numeric_parsing` (PASSED)
  - `tests/test_r12_e2e_synthetic_flow.py` (PASSED)
- **Evidencia técnica**: La función `_parse_numeric` tipa las celdas preservando patrones con ceros a la izquierda (como EAN `0123456789012` o códigos SKU) como cadenas literales (`data_type='s'`) con formato `@`, impidiendo que Excel los trunque a enteros. Las magnitudes financieras y numéricas se formatean como números con formatos de moneda COP, y se agregan gráficos nativos `openpyxl.chart.BarChart` y fórmulas (`SUM`, `AVERAGE`).
- **Bloqueos**: Ninguno.

### R11 · Resiliencia de interfaz: orden de historial, borrador y errores
- **Estado**: `cerrado`
- **Archivos corregidos**: `app/static/js/main.js` (`selectChat`, `handleAsk`), `app/api/routes/chats.py` (`list_messages`).
- **Pruebas ejecutadas**:
  - `tests/test_ui_resilience_and_system.py::test_r11_ui_static_files_served_and_contract_guarantees` (PASSED)
  - `tests/test_ui_resilience_and_system.py::test_chat_internal_error_redacted` (PASSED)
- **Evidencia técnica**: En `selectChat`, se descartan las respuestas asíncronas de historial si `state.activeChatId !== chatId` al resolverse la promesa, evitando condiciones de carrera al alternar rápidamente entre chats. En `handleAsk`, si la petición falla por error de red o de servidor, el texto del usuario se restaura en el input y en `sessionStorage`, y se retira el mensaje optimista huérfano para permitir reintentos sin duplicación. El botón de envío se desactiva durante la petición para prevenir dobles envíos.
- **Bloqueos**: Ninguno.

### R12 · Suite determinista y recorrido sintético de extremo a extremo
- **Estado**: `cerrado`
- **Archivos corregidos**: `tests/test_r12_e2e_synthetic_flow.py` (creado), suite de 12 archivos de prueba.
- **Pruebas ejecutadas**:
  - `tests/test_r12_e2e_synthetic_flow.py::test_r12_e2e_synthetic_flow_chat_citation_and_downloads` (PASSED)
  - Suite completa: 53 pasadas, 0 fallidas en 41.67 s.
- **Evidencia técnica**: Se implementó una prueba E2E sintética completa que recorre:
  1. Emisión de sesión anónima en `POST /api/chats`.
  2. Persistencia y descifrado de turno conversacional con citas documentales en `POST /api/chats/{id}/messages`.
  3. Comprobación de página en visor de documentos con cabecera `X-Highlight-Status` en `GET /api/documents/{id}/pages/{n}`.
  4. Generación y descarga de los 3 formatos (PDF, XLSX, DOCX) vinculados al mismo turno en `POST /api/chats/{id}/reports` y `GET /api/reports/{id}/download`.
  5. Inspección binaria de los artefactos: validación de cabecera `%PDF`, apertura del libro Excel con `openpyxl` verificando hojas `Resumen` y `Evidencias`, y apertura del documento Word con `docx.Document` comprobando la estructura y textos del turno.
- **Bloqueos**: Ninguno para la suite local determinista. Las pruebas con navegadores gráficos reales y llamadas con facturación a proveedores externos quedan formalmente separadas del ciclo de integración local.

---

## Verificación Final de la Suite de Pruebas

```text
============================= test session starts =============================
platform win32 -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0
rootdir: D:\Proyectos\Dylan_Hernandez-Agente_Alpina
collected 53 items

tests/test_anonymous_session_lifecycle.py::test_anonymous_session_cookie_issuance PASSED
tests/test_anonymous_session_lifecycle.py::test_cross_session_report_isolation PASSED
tests/test_anonymous_session_lifecycle.py::test_corrupt_fernet_token_raises_decryption_error PASSED
tests/test_anonymous_session_lifecycle.py::test_key_rotation_with_multifernet PASSED
tests/test_catalog_and_retrieval_resilience.py::test_product_row_explicit_undeclared_fields PASSED
tests/test_catalog_and_retrieval_resilience.py::test_search_products_exact_sku_priority PASSED
tests/test_catalog_and_retrieval_resilience.py::test_default_retrieve_resilience_when_embeddings_fail PASSED
tests/test_catalog_and_retrieval_resilience.py::test_retrieve_node_broadening_preserves_document_ids PASSED
tests/test_catalog_and_retrieval_resilience.py::test_empty_extraction_marked_as_failed PASSED
tests/test_catalog_and_retrieval_resilience.py::test_r09_hybrid_search_combines_vector_and_fts PASSED
tests/test_catalog_and_retrieval_resilience.py::test_r09_reindex_triggered_when_embedding_model_differs PASSED
tests/test_citations_and_graph_fidelity.py::test_no_partial_document_id_matching PASSED
tests/test_citations_and_graph_fidelity.py::test_quote_page_binding PASSED
tests/test_citations_and_graph_fidelity.py::test_quote_mismatch_rejected PASSED
tests/test_citations_and_graph_fidelity.py::test_validate_answer_payload_no_auto_assignment PASSED
tests/test_citations_and_graph_fidelity.py::test_verify_node_unverified_on_abstention_and_guardrail PASSED
tests/test_citations_and_graph_fidelity.py::test_r01_contradicted_number_rejected_and_abstained PASSED
tests/test_citations_and_graph_fidelity.py::test_r01_supported_number_verified PASSED
tests/test_citations_and_graph_fidelity.py::test_r02_general_category_retains_citations_when_needs_documents PASSED
tests/test_citations_and_graph_fidelity.py::test_r02_general_category_abstains_correctly_when_no_citations PASSED
tests/test_document_preview_versions.py::test_render_page_png_with_version_and_quote PASSED
tests/test_document_preview_versions.py::test_document_page_endpoint_cache_headers PASSED
tests/test_document_preview_versions.py::test_r08_missing_historical_version_communicates_unavailability PASSED
tests/test_document_preview_versions.py::test_r08_quote_without_match_distinguishes_none_status PASSED
tests/test_r12_e2e_synthetic_flow.py::test_r12_e2e_synthetic_flow_chat_citation_and_downloads PASSED
tests/test_report_fidelity_and_types.py::test_financial_keywords_no_naked_years PASSED
tests/test_report_fidelity_and_types.py::test_excel_numeric_parsing PASSED
tests/test_report_fidelity_and_types.py::test_word_report_includes_version_column PASSED
tests/test_report_fidelity_and_types.py::test_financial_recommendations_not_hardcoded PASSED
tests/test_report_fidelity_and_types.py::test_r03_financial_query_2024_without_figures_no_fixed_2025_revenue PASSED
tests/test_report_fidelity_and_types.py::test_r04_cannot_export_report_for_abstention PASSED
tests/test_report_fidelity_and_types.py::test_r10_excel_preserves_leading_zeros_ean_sku PASSED
tests/test_schema_verification.py::test_schema_verification_reports_and_chats PASSED
tests/test_schema_verification.py::test_check_database_ready_callable PASSED
tests/test_task1_session_crypto.py::test_crypto_fernet_roundtrip PASSED
tests/test_task1_session_crypto.py::test_crypto_legacy_plaintext_passthrough PASSED
tests/test_task1_session_crypto.py::test_session_isolation_and_encryption PASSED
tests/test_task2_documents_preview.py::test_official_document_titles PASSED
tests/test_task2_documents_preview.py::test_list_documents_api PASSED
tests/test_task2_documents_preview.py::test_download_document_pdf_api PASSED
tests/test_task2_documents_preview.py::test_render_page_png_with_highlight PASSED
tests/test_task3_prompts_guardrails.py::test_guardrails_off_domain_and_jailbreaks PASSED
tests/test_task3_prompts_guardrails.py::test_substantive_queries_not_treated_as_greetings PASSED
tests/test_task3_prompts_guardrails.py::test_docx_report_detection PASSED
tests/test_task3_prompts_guardrails.py::test_answer_system_prompt_guidelines PASSED
tests/test_task4_executive_reports.py::test_generate_word_report_function PASSED
tests/test_task4_executive_reports.py::test_generate_all_three_report_formats PASSED
tests/test_task4_executive_reports.py::test_api_generate_and_download_docx_report PASSED
tests/test_ui_resilience_and_system.py::test_health_endpoint_healthy PASSED
tests/test_ui_resilience_and_system.py::test_health_endpoint_degraded_on_startup_error PASSED
tests/test_ui_resilience_and_system.py::test_health_endpoint_error_when_graph_not_ready PASSED
tests/test_ui_resilience_and_system.py::test_chat_internal_error_redacted PASSED
tests/test_ui_resilience_and_system.py::test_r11_ui_static_files_served_and_contract_guarantees PASSED

====================== 53 passed, 20 warnings in 41.67s =======================
```
