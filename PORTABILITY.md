# Guía de Portabilidad, Requisitos y Despliegue en Cualquier Equipo

Este documento describe la arquitectura de portabilidad, los requisitos mínimos y el procedimiento exacto para desempaquetar, configurar y ejecutar el **Agente RAG Corporativo de Alpina** (`alpina-rag-agent`) en cualquier computador (Windows, Linux o macOS), garantizando un despliegue sin fricciones en 1 solo clic.

---

## 1. Resumen de Portabilidad y Diseño "Zero-Footprint"

El proyecto fue diseñado bajo una filosofía de **cero dependencias pesadas locales**:
- **Sin Docker ni contenedores**: No es necesario tener Docker Desktop instalado ni configurado.
- **Sin PostgreSQL local**: La base de datos vectorial reside en la nube de **Supabase** (PostgreSQL 15+ con la extensión `pgvector` activada y los índices de distancia coseno ya creados).
- **Embeddings ya calculados y almacenados**: Los documentos oficiales de Alpina (estados financieros 2024-2025, catálogo de productos y resoluciones colombianas 810 de 2021 y 2492 de 2022) ya fueron tokenizados y embebidos con **Cohere Multilingual v3 (1.024 dimensiones)** y residen en Supabase. El nuevo equipo **no requiere recalcular ni reingestar** nada para funcionar.
- **Sin Git obligatorio**: Si recibes el paquete comprimido `.zip`, no requieres tener Git instalado.
- **Almacenamiento Híbrido Resiliente**: Cuenta con integración directa a **Cloudflare R2** para servir documentos y reportes, con degradación elegante (*graceful fallback*) a almacenamiento local en disco (`data/reports/` y `data/cache/`) en caso de no contar con conexión a R2.

---

## 2. Requisitos Previos del Sistema

| Requisito | Detalle |
| :--- | :--- |
| **Sistema Operativo** | Windows 10/11 (recomendado para 1 clic), Linux (Ubuntu/Debian/Fedora/etc.) o macOS |
| **Intérprete Python** | Versiones **3.12, 3.13 o 3.14** |
| **Opción PATH en Windows** | ⚠️ **Crucial**: Al instalar Python, marcar la casilla `[X] Add python.exe to PATH` en la primera pantalla del instalador |
| **Conexión a Internet** | Requerida en el primer inicio para descargar dependencias de `requirements.txt` y comunicarse con las APIs en la nube (Groq, Cohere, Supabase, Cloudflare R2) |
| **Navegador Web** | Google Chrome, Microsoft Edge, Brave, Firefox o Safari |

---

## 3. Despliegue Rápido en Windows (1 Solo Clic)

El proyecto incluye el asistente de automatización por lotes:
```text
iniciar.bat
```

### ¿Qué realiza `iniciar.bat` internamente?
1. **Fijación de Directorio**: Asegura que la ruta de ejecución sea siempre la carpeta del proyecto, sin importar desde dónde se abra.
2. **Detección y Auto-Reparación de Entorno Virtual (`.venv`)**:
   - Comprueba si existe una carpeta `.venv` funcional.
   - Si detecta que el entorno fue copiado de otra máquina o ruta absoluta diferente (lo que rompería los scripts de Python), **lo limpia y lo recrea automáticamente**.
3. **Búsqueda Inteligente de Python**:
   - Prueba `py -3`, `python`, `py` y examina las rutas de instalación estándar de Windows en `%LOCALAPPDATA%`, `%ProgramFiles%` y `C:\Python*`.
   - Si Python no está instalado, muestra instrucciones claras con el enlace oficial de descarga.
4. **Instalación Automática de Dependencias**:
   - Ejecuta `pip install -r requirements.txt` de manera transparente y segura.
5. **Comprobación de Variables de Entorno (`.env`)**:
   - Verifica la existencia de `.env`. Si no existe, genera una copia automática a partir de `.env.example`.
6. **Detección Preventiva de Conflictos de Puerto**:
   - Evalúa si el puerto `8000` está ocupado por otro proceso y emite una advertencia oportuna.
7. **Lanzamiento del Servidor y Apertura del Navegador**:
   - Inicia el servidor web Uvicorn (`app.main:app`).
   - Tras 5 segundos (para permitir que la aplicación complete la inicialización y el *pool* de base de datos), abre automáticamente tu navegador web predeterminado en `http://127.0.0.1:8000`.

---

## 4. Despliegue Manual (Linux / macOS / PowerShell)

Si prefieres ejecutar el proyecto mediante terminal o estás en un sistema basado en Unix:

```bash
# 1. Descomprimir el archivo ZIP y entrar a la carpeta
cd Dylan_Hernandez-Agente_Alpina

# 2. Crear el entorno virtual con Python 3.12 a 3.14
python3 -m venv .venv

# 3. Activar el entorno virtual
# En Linux / macOS:
source .venv/bin/activate
# En Windows PowerShell:
# .\.venv\Scripts\Activate.ps1
# En Windows CMD:
# .venv\Scripts\activate.bat

# 4. Instalar las dependencias exactas
pip install -r requirements.txt

# 5. Crear .env en la primera instalación y completar los valores del entorno
cp .env.example .env

# 5b. Verificar y aplicar migraciones de esquema
python -m app.db.migrate

# 6. Iniciar el servidor FastAPI con Uvicorn
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Abre en tu navegador: **`http://127.0.0.1:8000`**.

---

## 5. Configuración de Variables de Entorno (`.env`)

Usa `.env.example` para crear tu configuración local. Completa `.env` con credenciales de tu entorno antes de arrancar el servicio.

```env
# Configuración del Servidor
APP_ENV=development
APP_HOST=127.0.0.1
APP_PORT=8000

# Base de Datos Supabase (PostgreSQL 15 con extensión pgvector)
# Utiliza connection pooling (Session pooler) compatible con redes corporativas y TLS obligatorio
DATABASE_URL=postgresql://alpina_app.<ref>:<password>@<host>:5432/postgres?sslmode=require
MIGRATION_DATABASE_URL=
CHAT_ENCRYPTION_KEY=

# Groq Cloud (Inferencia de ultra-baja latencia para LLMs)
GROQ_API_KEY=gsk_...
GROQ_MODEL_ANSWER=openai/gpt-oss-120b      # Modelo principal para síntesis y generación
GROQ_MODEL_ROUTER=openai/gpt-oss-20b       # Modelo rápido para enrutamiento semántico
GROQ_MODEL_FALLBACK=qwen/qwen3.8-27b       # Modelo de respaldo ante contingencias

# Cohere (Generación de embeddings vectoriales de 1.024 dimensiones)
COHERE_API_KEY=...
COHERE_EMBED_MODEL=embed-multilingual-v3.0
COHERE_EMBED_DIM=1024

# Cloudflare R2 Object Storage (Almacenamiento de documentos PDF y reportes generados)
# Si se deja vacío, el sistema opera con almacenamiento local en la carpeta data/
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=agent-alpina
R2_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com
```

---

## 6. Pruebas de Verificación y Flujo de Aceptación

Una vez levantado el servidor, puedes validar el funcionamiento del sistema con estas acciones:

### 1. Comprobación de Endpoints (CLI o Navegador)
- **Estado de Salud**:
  ```bash
  curl http://127.0.0.1:8000/health
  ```
  *Respuesta*: `{"status":"ok","environment":"development","agent_ready":true}`.
- **Catálogo de Productos**:
  ```bash
  curl "http://127.0.0.1:8000/api/products?limit=5"
  ```
- **Documentación Interactiva (Swagger UI)**:
  Navega a `http://127.0.0.1:8000/docs`.

### 2. Consultas Clave en la Interfaz Web (`http://127.0.0.1:8000`)
1. **Catálogo y Sellos Nutricionales**:
   - *"¿Qué productos de Alpina no tienen sellos de advertencia frontal?"*
   - *"Dime el precio, ingredientes y tabla nutricional del Alpinito de Fresa."*
2. **Normativa Oficial Colombiana**:
   - *"¿Cuáles son los límites de sodio de la Resolución 810 de 2021 frente a la Resolución 2492 de 2022?"*
   - *(Haz clic en las "Fuentes Oficiales Citadas" para comprobar el visor de PDFs con resaltado exacto).*
3. **Resultados Financieros y Generación de Reportes (Tool Calling)**:
   - *"Genérame un reporte financiero en Excel con los resultados de Alpina 2025."*
   - *"Crea un informe ejecutivo en PDF de la Resolución 810."*
   - *(Comprueba la generación y descarga automática de los reportes en el Dossier Ejecutivo).*

---

## 7. Preguntas Frecuentes y Solución de Problemas (Troubleshooting)

### P1: Hago doble clic en `iniciar.bat` y la ventana se cierra de inmediato.
- **Causa**: Python no está instalado o no se agregó a la variable de entorno `PATH`.
- **Solución**: Descarga Python 3.12 o 3.13 desde [python.org](https://www.python.org/downloads/). En la primera pantalla del instalador, activa la casilla **"Add python.exe to PATH"** antes de presionar "Install Now".

### P2: Aviso: *"El puerto 8000 parece estar ocupado por otra aplicación"*.
- **Solución**:
  - Abre una consola y ejecuta `netstat -ano | findstr :8000` para ver qué proceso lo ocupa.
  - O edita el archivo `.env` cambiando `APP_PORT=8001` y ejecuta el servidor en el nuevo puerto.

### P3: Windows SmartScreen muestra *"Windows protegió su PC"* al ejecutar `iniciar.bat`.
- **Causa**: Filtro de seguridad de Windows para archivos `.bat` descargados de internet.
- **Solución**: Haz clic en **"Más información"** y luego en el botón **"Ejecutar de todas formas"**.

### P4: Error al descargar paquetes con `pip` (*SSL error* o *timeout*).
- **Causa**: Restricciones de firewall o proxy en redes corporativas/institucionales.
- **Solución**: Asegúrate de contar con salida a internet sin proxy restrictivo para el dominio `pypi.org`.

### P5: ¿Cómo detener el servidor completamente?
- En la ventana negra de la consola donde se está ejecutando el agente, presiona **`Ctrl + C`** y luego confirma con **`S`** (o simplemente cierra la ventana de la consola).

---

## 8. Contenido Limpio del Paquete Portable

El paquete comprimido `.zip` contiene **únicamente el código fuente esencial, archivos de configuración, interfaz web y utilidades de arranque**, habiéndose purgado todos los archivos prescindibles o de gran tamaño:
- ❌ **Excluido**: Carpeta `.venv/` (~270 MB, se genera limpia en destino con `iniciar.bat`).
- ❌ **Excluido**: Carpetas `__pycache__/` y archivos `.pyc` (bytecode de Python compilado).
- ❌ **Excluido**: Archivos temporales generados en pruebas locales (`data/reports/*`, `data/cache/*`).
- ❌ **Excluido**: Directorio `.git/` y cachés de pruebas (`.pytest_cache`).
- ✅ **Incluido**: Código fuente completo modular en `app/`.
- ✅ **Incluido**: Interfaz web completa en `app/static/` (CSS, JS, iconos, visor de evidencias).
- ✅ **Incluido**: Script de automatización universal `iniciar.bat`.
- ✅ **Incluido**: Archivos de especificación de dependencias (`requirements.txt`, `pyproject.toml`).
- ✅ **Plantilla de configuración** en `.env.example`. Cada instalación configura su propio `.env` local.
- ✅ **Incluido**: Documentación técnica (`README.md`, `PORTABILITY.md`, `LEEME.txt`).
