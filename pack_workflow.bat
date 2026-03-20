@echo off
cd /d "%~dp0"
echo ============================================================
echo   ComfyUI Workflow Packer
echo ============================================================
echo.

C:\ComfyUI_windows_portable\python_embeded\python.exe pack_workflow.py %*

echo.
pause
