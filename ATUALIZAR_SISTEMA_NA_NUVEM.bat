@echo off
title Atualizar DocuBrain na VPS (Hostinger)
color 0B
cd /d "%~dp0"

echo ======================================================================
echo       ATUALIZAR DOCUBRAIN NA NUVEM - PROCEDIMENTOS.MNSERVICE.NET.BR
echo ======================================================================
echo.
echo 1. Enviando alteracoes locais para o GitHub...
git add .
git commit -m "feat: automatic update via sync script"
git push origin main

echo.
echo 2. Disparando atualizacao remota na VPS (Hostinger)...
powershell -Command "try { $res = Invoke-RestMethod -Uri 'https://procedimentos.mnservice.net.br/api/system/update?token=mn_docubrain_auto_sync_token_2026' -Method Post -TimeoutSec 15; Write-Host 'SUCESSO: ' $res.message -ForegroundColor Green } catch { Write-Host 'AVISO: Nao foi possivel acionar o endpoint remoto diretamente (aguarde o pull ou acione manualmente).' -ForegroundColor Yellow }"

echo.
echo ======================================================================
echo  ATUALIZACAO CONCLUIDA!
echo ======================================================================
echo Acesse: https://procedimentos.mnservice.net.br
echo.
timeout /t 5 >nul
