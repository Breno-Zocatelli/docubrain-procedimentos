# Script de Inicialização - DocuBrain Base de Conhecimento
Set-Location $PSScriptRoot

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "   DOCUBRAIN - BASE DE PROCEDIMENTOS OPERACIONAIS" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Iniciando servidor local..." -ForegroundColor Green
Write-Host "URL no Navegador: http://localhost:8000" -ForegroundColor Yellow
Write-Host ""
Write-Host "Pressione Ctrl+C para finalizar o servidor." -ForegroundColor Gray
Write-Host ""

& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
