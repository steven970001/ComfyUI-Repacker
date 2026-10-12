@echo off
cd /d "%~dp0"
echo ============================================================
echo   ComfyUI Workflow Packer
echo ============================================================
echo.

rem Find a Python interpreter to run this script itself. This is a
rem different concern from which ComfyUI install gets packed (that's
rem auto-detected from the workflow JSON's location at runtime) - this
rem just needs *any* working Python 3 to launch pack_workflow.py.
set "PYEXE="

if exist "%~dp0python_embeded\python.exe" set "PYEXE=%~dp0python_embeded\python.exe"

if not defined PYEXE if exist "C:\ComfyUI_windows_portable\python_embeded\python.exe" (
    set "PYEXE=C:\ComfyUI_windows_portable\python_embeded\python.exe"
)

if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)

if not defined PYEXE (
    echo [Error] Could not find a Python interpreter.
    echo   Checked: %~dp0python_embeded\python.exe
    echo            C:\ComfyUI_windows_portable\python_embeded\python.exe
    echo            "python" on PATH
    echo   Install Python 3, or run: pack_workflow.py --source "D:\Your\ComfyUI_windows_portable"
    pause
    exit /b 1
)

"%PYEXE%" pack_workflow.py %*

echo.
pause
