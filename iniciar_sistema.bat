@echo off
title DocuBrain - Base de Procedimentos Operacionais
cd /d "%~dp0"
echo ======================================================
echo    DOCUBRAIN - BASE DE PROCEDIMENTOS OPERACIONAIS
echo ======================================================
echo.
echo Iniciando servidor local na porta 8000...
echo Acesse no navegador: http://localhost:8000
echo.
echo Pressione CTRL+C para encerrar o servidor.
echo ------------------------------------------------------
echo.

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
