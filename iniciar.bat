@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Agente Alpina RAG - Servidor Local

:: Asegurar que el directorio de trabajo sea siempre la carpeta donde esta este archivo .bat
cd /d "%~dp0"

echo ========================================================================
echo                 AGENTE RAG DE ALPINA - INICIO AUTOMATICO
echo ========================================================================
echo.

set "VENV_DIR=%~dp0.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_ACTIVATE=%VENV_DIR%\Scripts\activate.bat"
:: Mantener este rango sincronizado con requires-python en pyproject.toml.
set "ALPINA_PYTHON_CHECK=import sys; sys.exit(0 if (3, 12) <= sys.version_info[:2] < (3, 15) else 1)"

:: -------------------------------------------------------------------------
:: 1. Verificar si ya existe un entorno virtual valido y funcional
:: -------------------------------------------------------------------------
if not exist "%VENV_PY%" goto check_system_python

"%VENV_PY%" -c "import sys" >nul 2>&1
if %errorlevel% neq 0 (
    echo [AVISO] Se detecto un entorno virtual danado o copiado de otra ruta.
    echo [INFO] Limpiando entorno anterior para recrearlo limpiamente...
    rmdir /s /q "%VENV_DIR%" >nul 2>&1
    goto check_system_python
)

"%VENV_PY%" -c "%ALPINA_PYTHON_CHECK%" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] El entorno .venv usa una version de Python incompatible:
    "%VENV_PY%" --version
    echo Este proyecto admite Python 3.12, 3.13 y 3.14.
    echo Renombra la carpeta .venv y vuelve a ejecutar iniciar.bat.
    pause
    exit /b 1
)

echo [OK] Entorno virtual existente detectado y funcional:
"%VENV_PY%" --version
goto activate_venv

:: -------------------------------------------------------------------------
:: 2. Buscar Python en el sistema y crear entorno virtual (.venv)
:: -------------------------------------------------------------------------
:check_system_python
if exist "%VENV_DIR%" (
    echo [AVISO] Se detecto una carpeta .venv incompleta. Limpiando...
    rmdir /s /q "%VENV_DIR%" >nul 2>&1
)

echo [INFO] Buscando interprete de Python en el sistema...
set "SYS_PYTHON="

:: Probar 'py -3' (Python Launcher estandar de Windows)
py -3 -c "%ALPINA_PYTHON_CHECK%" >nul 2>&1
if %errorlevel% equ 0 (
    set "SYS_PYTHON=py -3"
    goto python_found
)

:: Probar 'python' en PATH
python -c "%ALPINA_PYTHON_CHECK%" >nul 2>&1
if %errorlevel% equ 0 (
    set "SYS_PYTHON=python"
    goto python_found
)

:: Probar 'py' generico
py -c "%ALPINA_PYTHON_CHECK%" >nul 2>&1
if %errorlevel% equ 0 (
    set "SYS_PYTHON=py"
    goto python_found
)

:: Probar versiones concretas si el lanzador selecciona otra version por defecto.
for %%V in (3.14 3.13 3.12) do (
    py -%%V -c "%ALPINA_PYTHON_CHECK%" >nul 2>&1
    if !errorlevel! equ 0 (
        set "SYS_PYTHON=py -%%V"
        goto python_found
    )
)

:: Buscar en rutas de instalacion comunes de Windows
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%ProgramFiles%\Python314\python.exe"
    "%ProgramFiles%\Python313\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "C:\Python314\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
) do (
    if exist %%P (
        %%P -c "%ALPINA_PYTHON_CHECK%" >nul 2>&1
        if !errorlevel! equ 0 (
            set "SYS_PYTHON="%%~P""
            goto python_found
        )
    )
)

:: Si no se encontro ningun Python
echo.
echo ========================================================================
echo  [ERROR] No se encontro Python 3.12, 3.13 o 3.14 en tu computador.
echo ========================================================================
echo  Este proyecto requiere Python para poder ejecutarse.
echo.
echo  Pasos para solucionarlo:
echo   1. Descarga Python 3.12, 3.13 o 3.14 desde:
echo      https://www.python.org/downloads/
echo   2. AL INSTALAR: En la primera ventana del instalador, marca la casilla:
echo      [X] "Add python.exe to PATH"
echo      antes de hacer clic en "Install Now".
echo   3. Vuelve a hacer doble clic en iniciar.bat.
echo ========================================================================
echo.
pause
exit /b 1

:python_found
echo [OK] Interprete detectado:
!SYS_PYTHON! --version

echo [INFO] Creando entorno virtual (.venv)...
echo       (Esto solo se realiza en el primer inicio. Por favor espera)...
!SYS_PYTHON! -m venv "%VENV_DIR%"
if %errorlevel% neq 0 (
    echo.
    echo ========================================================================
    echo  [ERROR] No se pudo crear el entorno virtual en "%VENV_DIR%".
    echo ========================================================================
    echo  Verifica que tengas permisos de escritura y espacio en disco.
    echo ========================================================================
    echo.
    pause
    exit /b 1
)
echo [OK] Entorno virtual (.venv) creado exitosamente.

:: -------------------------------------------------------------------------
:: 3. Activar entorno virtual
:: -------------------------------------------------------------------------
:activate_venv
if exist "%VENV_ACTIVATE%" (
    call "%VENV_ACTIVATE%"
)

:: -------------------------------------------------------------------------
:: 4. Descargar e instalar requerimientos (requirements.txt)
:: -------------------------------------------------------------------------
if not exist "%~dp0requirements.txt" (
    echo [ADVERTENCIA] No se encontro el archivo requirements.txt. Omitiendo instalacion.
    goto check_env
)

echo.
echo ------------------------------------------------------------------------
echo  Verificando e instalando requerimientos desde requirements.txt...
echo  (Si es la primera vez, se descargaran los paquetes necesarios)...
echo ------------------------------------------------------------------------
echo.

"%VENV_PY%" -m pip install -r "%~dp0requirements.txt" --disable-pip-version-check --no-warn-script-location
if %errorlevel% neq 0 (
    echo.
    echo ========================================================================
    echo  [ERROR] Ocurrio un problema al descargar o instalar los requerimientos.
    echo ========================================================================
    echo  Por favor verifica tu conexion a internet e intenta nuevamente.
    echo ========================================================================
    echo.
    pause
    exit /b 1
)
echo.
echo [OK] Todos los requerimientos estan descargados y listos.

:: -------------------------------------------------------------------------
:: 5. Verificar archivo de variables de entorno (.env)
:: -------------------------------------------------------------------------
:check_env
if not exist "%~dp0.env" (
    if exist "%~dp0.env.example" (
        echo [INFO] Creando archivo .env a partir de .env.example...
        copy /y "%~dp0.env.example" "%~dp0.env" >nul
        echo [OK] Archivo .env generado correctamente.
    ) else (
        echo [ADVERTENCIA] No se encontro el archivo .env ni .env.example.
    )
) else (
    echo [OK] Archivo de configuracion .env detectado.
)

:: -------------------------------------------------------------------------
:: 6. Verificar si el puerto 8000 esta ocupado
:: -------------------------------------------------------------------------
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo [AVISO] El puerto 8000 parece estar ocupado por otra aplicacion.
    echo         Si el servidor no inicia, cierra el proceso que este usando el puerto 8000.
)

:: -------------------------------------------------------------------------
:: 6b. Verificar y aplicar migraciones de esquema de base de datos
:: -------------------------------------------------------------------------
echo.
echo [INFO] Verificando esquema y migraciones de base de datos...
"%VENV_PY%" -m app.db.migrate
if %errorlevel% neq 0 (
    echo [ERROR CRITICO] Fallaron las migraciones de base de datos.
    echo                 El servidor no puede iniciar con un esquema inconsistente.
    exit /b %errorlevel%
)

:: -------------------------------------------------------------------------
:: 7. Iniciar el servidor FastAPI y abrir el navegador web
:: -------------------------------------------------------------------------
echo.
echo ========================================================================
echo  INICIANDO SERVIDOR WEB - AGENTE ALPINA RAG
echo ========================================================================
echo  - Interfaz Web       : http://127.0.0.1:8000
echo  - Documentacion API  : http://127.0.0.1:8000/docs
echo.
echo  Tu navegador se abrira automaticamente en breves segundos.
echo  Para detener el servidor, presiona Ctrl + C en esta ventana.
echo ========================================================================
echo.

:: Abrir navegador en segundo plano despues de dar tiempo al servidor para levantar
start /b "" cmd /c "ping 127.0.0.1 -n 5 >nul & start http://127.0.0.1:8000"

:: Ejecutar servidor con uvicorn
"%VENV_PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

if %errorlevel% neq 0 (
    echo.
    echo [AVISO] El servidor se ha detenido con codigo de salida %errorlevel%.
) else (
    echo.
    echo [INFO] Servidor detenido correctamente.
)

echo.
echo Presiona cualquier tecla para cerrar esta ventana...
pause >nul
