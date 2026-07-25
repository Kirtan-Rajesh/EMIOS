@echo off
set PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
title EMIOS Launcher
cls
echo =======================================================================
echo              EMIOS - Enterprise Migration Intelligence Operating System
echo =======================================================================
echo.

:: 1. Detect Container Engine (Docker vs Podman)
set ENGINE=NONE
set COMPOSE_CMD=none

where docker >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set ENGINE=DOCKER
    set COMPOSE_CMD=docker compose
    goto engine_detected
)

where podman >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set ENGINE=PODMAN
    set COMPOSE_CMD=podman compose
    goto engine_detected
)

:engine_detected
echo [1/4] Checking Container Engine status...
if "%ENGINE%"=="DOCKER" (
    echo [INFO] Docker detected in PATH.
    tasklist /FI "IMAGENAME eq Docker Desktop.exe" 2>NUL | find /I /N "Docker Desktop.exe" >NUL
    if %ERRORLEVEL% EQU 0 (
        echo [INFO] Docker Desktop is already running.
    ) else (
        echo [INFO] Attempting to start Docker Desktop...
        if exist "C:\Program Files\Docker\Docker\Docker Desktop.exe" (
            start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
            echo [INFO] Docker Desktop launched. Please wait a few moments for it to fully initialize.
            timeout /t 10 /nobreak >nul
        ) else (
            echo [WARNING] Docker Desktop executable not found at default path.
        )
    )
    goto start_containers
)

if "%ENGINE%"=="PODMAN" (
    echo [INFO] Podman detected in PATH.
    echo [INFO] Checking if Podman machine exists...
    podman machine list 2>NUL | findstr /i "podman-machine-default" >NUL
    if %ERRORLEVEL% NEQ 0 (
        echo [INFO] Podman default machine does not exist. Initializing...
        podman machine init
    )
    echo [INFO] Starting Podman machine...
    podman machine start 2>NUL
    
    echo [INFO] Waiting for Podman API socket to be fully ready...
    set attempt=1
    goto podman_check
)

:podman_check
podman ps >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [OK] Podman API socket is ready.
    goto start_containers
)
if %attempt% GEQ 8 (
    echo [WARNING] Podman socket did not respond in time. Proceeding anyway...
    goto start_containers
)
set /a attempt=%attempt%+1
echo [INFO] Waiting for Podman daemon... (Attempt %attempt%/8)
timeout /t 3 /nobreak >nul
goto podman_check


:: If no engine detected
echo [WARNING] No container engine (Docker or Podman) was found in your system PATH.
echo           If they are not installed, EMIOS will boot in Zero-Configuration Fallback Mode.
goto container_done

:start_containers
echo.
:: 2. Start Compose services
echo [2/4] Initializing database containers via %COMPOSE_CMD%...
%COMPOSE_CMD% up -d 2>NUL
if %ERRORLEVEL% EQU 0 (
    echo [OK] Database containers started successfully [Neo4j and Qdrant].
) else (
    echo [WARNING] Could not start containers using %COMPOSE_CMD%. 
    echo           Please make sure your container service - Docker or Podman - is active.
    echo           EMIOS will automatically use local In-Memory Fallback Mode.
)

:container_done
echo.

:: 3. Launch Default Browser
echo [3/4] Opening Web Interface...
timeout /t 3 /nobreak >nul
start http://localhost:8000
echo.

:: 4. Start backend application
echo [4/4] Starting FastAPI Backend...
echo.
if not exist "venv\Scripts\python.exe" goto venv_missing

:start_backend
venv\Scripts\python.exe backend/main.py
goto end

:venv_missing
echo [INFO] Virtual environment 'venv' not found. Creating it automatically...
python -m venv venv
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to create virtual environment. Please ensure Python is installed and in your PATH.
    pause
    goto end
)
echo [INFO] Virtual environment created. Installing backend dependencies...
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r backend/requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    goto end
)
echo [OK] Dependencies installed successfully.
goto start_backend

:end
