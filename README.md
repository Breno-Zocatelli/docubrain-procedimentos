# DocuBrain - Base de Procedimentos Operacionais

Sistema local inteligente para anotação, gerenciamento e consulta semântica de procedimentos operacionais de equipamentos (impressoras, servidores, etc.) e sistemas (ERP DataBit, TopPonto, etc.).

## 🚀 Como Iniciar o Sistema

Basta dar duplo clique no script executável dentro da pasta do projeto:
- **`iniciar_sistema.bat`** (ou executar `.\iniciar_sistema.ps1` no terminal).

Em seguida, abra seu navegador em:
👉 **`http://localhost:8000`**

---

## 💡 Como Funciona a Busca Inteligente

1. **Aba "Perguntar / Buscar":**
   - Você digita qualquer dúvida em linguagem natural (ex: *"Como reseto o fusor da Ricoh no erro SC542?"* ou *"Qual o procedimento para emitir saída de toner?"*).
   - O motor de busca vetorial/BM25 encontra os procedimentos mais relevantes mesmo que você não lembre o título exato.
   - O sistema extrai os passos rápidos e apresenta os cartões correspondentes para você abrir o roteiro completo.

2. **Modo Assistente IA (Opcional):**
   - Se desejar que o assistente converse e sintetize respostas fluidas diretamente, você pode colar uma chave gratuita do Google Gemini na aba **Configurações** (gerada em [aistudio.google.com](https://aistudio.google.com)).
   - Sem a chave, o sistema continua funcionando perfeitamente em **Modo Local 100% Offline**.

3. **Armazenamento Seguro e Dual:**
   - As anotações ficam no banco rápido SQLite `data/knowledge.db`.
   - Simultaneamente, cada procedimento é salvo como arquivo Markdown legível em:
     `C:\Users\sistema_03\.gemini\antigravity\scratch\base-conhecimento\data\procedimentos\<Categoria>\<Equipamento>_<Titulo>.md`
   - O diretório `C:\Users\sistema_03\.gemini` está na lista de exclusão do antivírus da máquina.

---

## 📁 Estrutura do Projeto

```
base-conhecimento/
├── app/
│   ├── ai_service.py     # Lógica RAG e síntese inteligente
│   ├── database.py       # SQLite com FTS5, BM25 e exportação Markdown
│   ├── main.py           # API FastAPI e rotas web
│   └── templates/
│       └── index.html    # Interface web moderna e responsiva
├── data/
│   ├── knowledge.db      # Banco de dados local
│   └── procedimentos/    # Arquivos .md organizados por categorias
├── .venv/                # Ambiente virtual Python isolado
├── iniciar_sistema.bat   # Inicializador Windows
├── iniciar_sistema.ps1   # Inicializador PowerShell
└── README.md
```
