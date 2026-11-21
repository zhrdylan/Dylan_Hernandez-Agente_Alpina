Plan de Implementación: Alineación Integral para Despliegue en Vercel 

  │ For agentic workers: REQUIRED SUB-SKILL: Use autonomous-swe-team:subagent-driven-development (recommended) or autonomous-swe-team:executing-plans to implement this plan task-by-   
  │ task. Steps use checkbox (- [ ]) syntax for tracking.

  Goal: Adaptar la arquitectura del Agente RAG Alpina (FastAPI + LangGraph) para ejecutarse de forma nativa, segura y de alto rendimiento en el entorno serverless de Vercel.

  Architecture: Se creará un punto de entrada ASGI en api/index.py respaldado por reglas de reescritura en vercel.json con maxDuration adaptado a tareas de IA
  generativa. Se refactorizarán las rutas de almacenamiento efímero (app/config.py y app/documents/preview.py) para emplear /tmp en serverless sin alterar el
  funcionamiento en local. La persistencia definitiva de reportes se apoyará en Cloudflare R2 y el acceso a despliegues protegidos se auditará con vc curl.

  Tech Stack: FastAPI, LangGraph, Python 3.12, Supabase (pgvector + Transaction Pooler), Cloudflare R2, Vercel Serverless Functions (Fluid Compute).

  Spec: Arquitectura definida en README.md y directrices de despliegue en Vercel.

  ## Global Constraints

  • No alterar la lógica de negocio del agente, los prompts ni los algoritmos de validación en app/agent/.
  • Mantener compatibilidad absoluta con la ejecución local en Windows (iniciar.bat) mientras se habilita Vercel.
  • Respetar el límite de tamaño de bundle de Python en Vercel (500 MB) excluyendo librerías o datos prescindibles.
  • No deshabilitar Deployment Protection de Vercel durante las auditorías de despliegue.

  ## Review Focus

  1. Llamadas al visor de páginas PDF / PNG: Verificar que app/documents/preview.py renderice y guarde cachés en /tmp sin provocar errores de permisos.
  2. Respuesta de TrustedHostMiddleware: Confirmar que cualquier dominio .vercel.app sea aceptado sin devolver HTTP 400.
  3. Generación y descarga de Dossiers en PDF/Excel: Confirmar que los reportes generados se creen en /tmp/reports y se sincronicen correctamente con Cloudflare R2.    
  4. Respuesta del endpoint /health: Validar que check_database_ready() retorne status: ok en el arranque de la función serverless.
  5. Autenticación en entornos protegidos: Asegurar que vc curl permita consultar endpoints sin ser interceptado por la pantalla de login de Vercel.
  ──────
  ### Fase 1: Andamiaje y Configuración de Vercel

  #### Task 1: Crear el punto de entrada Serverless (api/index.py)

  Files:

  • Create: api/index.py

  Steps:

  [x] 1.1 Crear el directorio api/ en la raíz del proyecto.
  [x] 1.2 Crear el archivo api/index.py importando la instancia app de app/main.py:
    from app.main import app

  [x] 1.3 Verificar que el import no genere dependencias circulares.
  ──────
  #### Task 2: Configurar el enrutador y límites de función (vercel.json)

  Files:

  • Create: vercel.json

  Steps:

  [x] 2.1 Crear vercel.json en la raíz del proyecto.
  [x] 2.2 Configurar el esquema oficial de Vercel, la reescritura universal hacia api/index.py y una duración máxima (maxDuration: 60 o superior) para permitir la      
  orquestación de LangGraph y la renderización de PDFs:
    {
      "$schema": "https://openapi.vercel.sh/vercel.json",
      "version": 2,
      "rewrites": [
        {
          "source": "/(.*)",
          "destination": "/api/index.py"
        }
      ],
      "functions": {
        "api/index.py": {
          "maxDuration": 60
        }
      }
    }

  ──────
  #### Task 3: Optimización del empaquetado (.vercelignore)

  Files:

  • Create: .vercelignore

  Steps:

  [x] 3.1 Crear el archivo .vercelignore en la raíz del proyecto.
  [x] 3.2 Listar las carpetas locales de desarrollo, entornos virtuales y cachés que no deben subirse al bundle serverless:
    .venv
    __pycache__
    *.pyc
    .git
    .cache
    data/cache
    data/reports
    tests
    .pytest_cache
    iniciar.bat

  ──────
  ### Fase 2: Adaptación del Sistema de Archivos Serverless

  #### Task 4: Refactorizar directorios y arranque seguro en app/config.py

  Files:

  • Modify: app/config.py:7-13 y app/config.py:91-93

  Steps:

  [x] 4.1 En app/config.py, detectar si la aplicación se ejecuta bajo Vercel (bool(os.environ.get("VERCEL"))).
  [x] 4.2 Si está en Vercel, redirigir DATA_DIR, REPORTS_DIR y CACHE_DIR hacia Path(tempfile.gettempdir()).
  [x] 4.3 En ensure_project_dirs(), envolver la creación de directorios en un bloque try...except OSError: pass para garantizar que no lance excepciones si alguna      
  carpeta base es de solo lectura.
  ──────
  #### Task 5: Adaptar la caché de previsualizaciones en app/documents/preview.py

  Files:

  • Modify: app/documents/preview.py:25-26

  Steps:

  [x] 5.1 En app/documents/preview.py, sustituir las rutas estáticas de CACHE_DIR y DOCUMENT_CACHE_DIR:
    import os
    import tempfile

    _CACHE_BASE = Path(tempfile.gettempdir()) / "alpina_cache" if os.environ.get("VERCEL") else BASE_DIR / "data" / "cache"
    CACHE_DIR = _CACHE_BASE / "pages"
    DOCUMENT_CACHE_DIR = _CACHE_BASE / "documents"

  [x] 5.2 Comprobar que _write_cache pueda escribir libremente en la subcarpeta temporal en entornos serverless.
  ──────
  ### Fase 3: Base de Datos y Variables de Entorno

  #### Task 6: Validación de esquema y pool en Supabase

  Files:

  • Reference: app/db/migrate.py, app/db/connection.py

  Steps:

  [x] 6.1 Ejecutar localmente las migraciones pendientes con python -m app.db.migrate utilizando MIGRATION_DATABASE_URL.
  [x] 6.2 Verificar que el usuario alpina_app posea los permisos adecuados sobre las tablas de chats, mensajes, reportes y vectores sin violar RLS.
  [x] 6.3 Obtener la cadena de conexión con Transaction Pooling (puerto 6543) de Supabase para su uso en Vercel.
  ──────
  #### Task 7: Configuración de Variables en Vercel Dashboard

  Files:

  • Reference: .env.example

  Steps:

  [ ] 7.1 Cargar en Vercel (Project Settings → Environment Variables):
      • APP_ENV = production
      • TRUSTED_HOSTS = ["*"] (O ["*.vercel.app"])
      • DATABASE_URL = postgresql://alpina_app:...@...pooler.supabase.com:6543/postgres
      • CHAT_ENCRYPTION_KEY = <clave_fernet>
      • GROQ_API_KEY = gsk_...
      • COHERE_API_KEY = ...
      • Credenciales Cloudflare R2 (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET).
      • VERCEL_SUPPORT_LARGE_FUNCTIONS = 1 (Habilita el bundle extendido de hasta 5 GB para Python si fuera necesario).

  ──────
  ### Fase 4: Despliegue, Auditoría Protegida y Verificación

  #### Task 8: Despliegue de Preview y Enlace

  Steps:

  [ ] 8.1 Ejecutar vc para inicializar el proyecto y generar un despliegue de Preview.
  [ ] 8.2 Comprobar en los logs de construcción que Vercel detecte el runtime @vercel/python y finalice la instalación de requirements.txt exitosamente.
  ──────
  #### Task 9: Auditoría con access-protected-vercel-deployment

  Steps:

  [ ] 9.1 Verificar el estado del servicio en el despliegue protegido usando vc curl:
    vc curl https://<deployment-url>.vercel.app/health
  Confirmar que la respuesta retorne {"status": "ok"}.
  [ ] 9.2 Probar la creación de un chat mediante vc curl:
    vc curl https://<deployment-url>.vercel.app/api/chats -X POST -H "Content-Type: application/json" -d '{"title":"Prueba Vercel"}'

  [ ] 9.3 Si se realizan pruebas con herramientas de automatización de navegador (Playwright/agent-browser), adjuntar la cabecera OIDC:
    x-vercel-trusted-oidc-idp-token: <VERCEL_OIDC_TOKEN>

  [ ] 9.4 Si se observa un error TRUSTED_SOURCES_ENVIRONMENT_MISMATCH, acudir a Settings → Deployment Protection → Trusted Sources y habilitar la transición
  development → production.
  ──────
  #### Task 10: Promoción a Producción

  Steps:

  [ ] 10.1 Ejecutar vc --prod para desplegar la versión validada en el dominio principal de producción.
  [ ] 10.2 Validar desde el navegador la interfaz gráfica (app/static/index.html), el flujo de conversación con el agente y la apertura de citas en el Visor de
  Evidencias.