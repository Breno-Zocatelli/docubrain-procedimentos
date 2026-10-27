#!/bin/bash
# Script de Configuração Automática do DocuBrain no Servidor KVM Hostinger
# Subdomínio: procedimentos.mnservice.net.br

set -e

echo "=========================================================="
echo "   INSTALANDO DOCUBRAIN - PROCEDIMENTOS.MNSERVICE.NET.BR"
echo "=========================================================="

APP_DIR="/var/www/procedimentos"
DOMAIN="procedimentos.mnservice.net.br"

# 1. Atualizar pacotes e instalar dependências essenciais
echo "--> [1/5] Instalando Python3, venv e Nginx..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv nginx curl

# 2. Criar diretório da aplicação e ajustar permissões
echo "--> [2/5] Configurando pasta da aplicação em $APP_DIR..."
sudo mkdir -p $APP_DIR
sudo cp -r ./* $APP_DIR/
sudo chown -R www-data:www-data $APP_DIR
cd $APP_DIR

# 3. Criar ambiente virtual Python e instalar dependências
echo "--> [3/5] Criando ambiente virtual Python e instalando pacotes..."
sudo -u www-data python3 -m venv .venv
sudo -u www-data ./.venv/bin/pip install --upgrade pip
sudo -u www-data ./.venv/bin/pip install -r requirements.txt

# 4. Criar serviço systemd para rodar 24/7
echo "--> [4/5] Criando serviço systemd (procedimentos.service)..."
sudo bash -c "cat <<EOF > /etc/systemd/system/procedimentos.service
[Unit]
Description=DocuBrain Base de Procedimentos Operacionais
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
Environment=\"PATH=$APP_DIR/.venv/bin:/usr/bin:/bin\"

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload
sudo systemctl enable procedimentos.service
sudo systemctl restart procedimentos.service

# 5. Configurar Nginx para encaminhar o subdomínio
echo "--> [5/5] Configurando Nginx para $DOMAIN..."
sudo bash -c "cat <<EOF > /etc/nginx/sites-available/$DOMAIN
server {
    listen 80;
    server_name $DOMAIN;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \\\$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \\\$host;
        proxy_set_header X-Real-IP \\\$remote_addr;
        proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\\$scheme;
        proxy_cache_bypass \\\$http_upgrade;
    }
}
EOF"

sudo ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

echo ""
echo "=========================================================="
echo "  INSTALAÇÃO CONCLUÍDA COM SUCESSO!"
echo "  Serviço: sudo systemctl status procedimentos"
echo "  URL: http://$DOMAIN (ou https com Cloudflare ativado)"
echo "=========================================================="
