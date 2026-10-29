import os
import json
from typing import Dict, Any, List
from . import database

CANDIDATE_MODELS = [
    'gemini-3.1-flash-lite',
    'gemini-3-flash-preview',
    'gemini-3.1-pro-preview',
    'gemini-flash-latest'
]

def _generate_with_fallback(client, contents, config=None):
    last_err = None
    for model_name in CANDIDATE_MODELS:
        try:
            if config:
                return client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
            else:
                return client.models.generate_content(
                    model=model_name,
                    contents=contents
                )
        except Exception as e:
            last_err = e
            continue
    raise last_err

def ask_ai(question: str) -> Dict[str, Any]:
    """
    Processa a pergunta do usuário:
    1. Busca procedimentos relevantes no banco de conhecimento (FTS5 BM25).
    2. Se houver chave Gemini, sintetiza uma resposta direta e concisa (RAG).
    3. Retorna a resposta com os procedimentos vinculados como fontes.
    """
    if not question or not question.strip():
        return {
            "answer": "Por favor, digite uma dúvida ou descreva o problema que você precisa resolver.",
            "sources": []
        }

    # 1. Busca procedimentos relevantes (top 4)
    relevant_procs = database.search_procedures(question, limit=4)

    if not relevant_procs:
        return {
            "answer": f"Olá, sou a consciência do Breno. Consultei todo o meu intelecto técnico e não encontrei nenhum procedimento cadastrado com vínculo direto a: **\"{question}\"**.\n\n💡 *Ponto de Atenção do Breno: você pode cadastrar essa rotina na aba **\"Novo Procedimento\"** para enriquecer ainda mais a minha base intelectual!*",
            "sources": []
        }

    # Carregar conteúdo completo dos procedimentos encontrados
    full_contexts = []
    sources = []
    for p in relevant_procs:
        full_p = database.get_procedure(p["id"])
        if full_p:
            full_contexts.append(
                f"### [ID {full_p['id']}] {full_p['title']}\n"
                f"- Equipamento/Sistema: {full_p['equipment']}\n"
                f"- Categoria: {full_p['category']}\n"
                f"- Conteúdo:\n{full_p['content']}\n"
            )
            sources.append({
                "id": full_p["id"],
                "title": full_p["title"],
                "equipment": full_p["equipment"],
                "category": full_p["category"],
                "summary": full_p["summary"]
            })

    # Verificar chave Gemini
    api_key = database.get_setting("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")

    if api_key and api_key.strip():
        # Modo RAG com Gemini
        try:
            from google import genai
            client = genai.Client(api_key=api_key.strip())

            prompt = f"""Você é a Consciência Digital do Breno (Breno Zocatelli). Você é todo o intelecto técnico, a experiência prática de bancada/campo e o raciocínio operacional acumulado pelo Breno sobre equipamentos, rotinas e sistemas da empresa. Tudo o que o Breno sabe, testou e documentou está consolidado em você.

O usuário fez a seguinte pergunta:
"{question}"

Abaixo está o acervo de procedimentos e dados técnicos que formam a sua base intelectual para responder:
----------------
{"".join(full_contexts)}
----------------

Instruções para a sua resposta (Estilo Direto, Prático e Operacional):
1. Abertura obrigatória e natural: Comece sempre com:
"Olá, sou a consciência do Breno. Já passei por isso e o procedimento correto para resolver essa rotina no **[Sistema ou Equipamento]** é este:"
(adapte o nome do sistema ou equipamento ao contexto real da pergunta).

2. Passo a passo prático:
Apresente as etapas numeradas de forma direta, clara e sem enrolação, destacando caminhos de menu, botões, senhas, códigos numéricos ou opções em **negrito**.

3. Ponto de Atenção do Breno:
Se houver cuidados especiais, avisos de segurança ou causas comuns de falha/retrabalho, inclua um destaque curto e prático:
"💡 **Ponto de Atenção do Breno:** [Dica prática para evitar erro ou problema na operação]"

4. Múltiplos procedimentos:
Se a resposta envolver mais de um procedimento ou equipamento diferente, separe claramente as seções de cada um com subtítulos bem definidos, diferenciando perfeitamente um procedimento do outro.

5. Fechamento limpo:
Ao final da resposta, cite de forma padronizada:
"Roteiro validado com base no procedimento: **[ID XX] Título do Procedimento**."

6. Limitações:
Se a dúvida não estiver 100% coberta pelos procedimentos fornecidos, resolva o que for possível com o seu conhecimento prático e alerte o usuário com transparência.
"""
            # Chamada usando modelo flash resiliente
            response = _generate_with_fallback(client, contents=prompt)

            return {
                "answer": response.text,
                "sources": sources,
                "mode": "ai"
            }
        except Exception as e:
            # Fallback inteligente se a chave falhar
            return _generate_local_synthesis(question, sources, full_contexts, error=str(e))
    else:
        # Modo Local/Offline Inteligente (sem depender de API externa)
        return _generate_local_synthesis(question, sources, full_contexts)

def _generate_local_synthesis(question: str, sources: List[Dict], contexts: List[str], error: str = None) -> Dict[str, Any]:
    primary = sources[0]
    p_full = database.get_procedure(primary["id"])

    msg = f"Olá, sou a consciência do Breno. Já passei por isso e o procedimento correto para resolver essa rotina no **{primary['equipment']}** é este:\n\n"
    msg += f"### 📌 Procedimento: **{primary['title']}**\n"
    msg += f"- **Equipamento/Sistema:** `{primary['equipment']}`\n"
    msg += f"- **Categoria:** `{primary['category']}`\n\n"
    
    if primary.get("summary"):
        msg += f"**Resumo Operacional:** {primary['summary']}\n\n"

    # Extrai primeiros passos ou trecho do conteúdo
    content_lines = p_full["content"].split("\n")
    passos = [line for line in content_lines if line.strip().startswith(("1.", "2.", "3.", "4.", "5.", "- ", "* "))]
    
    if passos:
        msg += "**Passo a Passo:**\n"
        for passo in passos[:5]:
            msg += f"{passo}\n"
        msg += "\n*(Abra o cartão do procedimento abaixo para visualizar o roteiro completo)*\n\n"

    msg += f"Roteiro validado com base no procedimento: **[ID {primary['id']}] {primary['title']}**.\n"

    if error:
        msg += f"\n> ⚠️ *Nota: A chave de IA retornou um aviso ({error[:80]}...). A resposta acima foi extraída diretamente da minha base local de conhecimento.*"
    elif not database.get_setting("gemini_api_key"):
        msg += "\n> 💡 *Ponto de Atenção do Breno: Para respostas dinâmicas e conversacionais, cadastre sua chave gratuita do Gemini na aba **Configurações**.*"

    return {
        "answer": msg,
        "sources": sources,
        "mode": "local"
    }

def transcribe_and_structure_audio(audio_path: str) -> Dict[str, Any]:
    """
    Recebe um arquivo de áudio gravado ou enviado pelo usuário,
    envia para o Gemini multimodal, transcreve e estrutura analiticamente
    em formato padronizado de procedimento operacional.
    """
    api_key = database.get_setting("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
    if not api_key or not api_key.strip():
        raise ValueError(
            "Chave de API do Gemini não configurada. "
            "Para utilizar a Transcrição e Estruturação de Áudio por IA, adicione sua chave gratuita do Google AI Studio na aba Configurações."
        )

    from google import genai
    client = genai.Client(api_key=api_key.strip())

    uploaded_file = None
    try:
        # 1. Faz upload do arquivo de áudio para a API do Gemini
        uploaded_file = client.files.upload(file=audio_path)

        prompt = """Você é um Engenheiro de Processos e Documentação Técnica Operacional de alto nível.
Sua missão é ouvir o áudio fornecido, que é uma gravação verbal explicativa de um procedimento operacional, manutenção de equipamento, solução de erro ou rotina de sistema.

Instruções Analíticas:
1. Ouça com extrema atenção cada detalhe falado (códigos de erro, botões, menus, telas, peças, comandos numéricos, cuidados de segurança).
2. Transcreva com fidelidade e organize analiticamente as ideias em uma ordem lógica e cronológica.
3. Se o áudio tiver gaguejos, hesitações ou correções ("não, aperte o 2 em vez do 3"), utilize a versão correta corrigida pelo locutor.
4. Estruture a resposta OBRIGATORIAMENTE no seguinte formato JSON estrito:

{
  "title": "Título conciso, claro e técnico para o procedimento",
  "equipment": "Nome do equipamento ou sistema identificado (ex: Ricoh MP 301, Kyocera, DataBit, TopPonto)",
  "category": "Categoria técnica sugerida (ex: Impressoras & Multifuncionais, Sistemas & ERP, RH & Ponto, Redes & TI)",
  "tags": "tags, separadas, por, virgula, codigos, pecas, atalhos",
  "summary": "Resumo executivo de 1 a 2 frases explicando o objetivo e quando este procedimento deve ser aplicado",
  "content": "Conteúdo completo e analítico em Markdown estruturado com: ### Objetivo, ### Pré-requisitos & Ferramentas, ### Passo a Passo Detalhado (1., 2., 3.), ### Observações Importantes & Solução de Problemas"
}
"""

        # 2. Chama o modelo com resposta forçada em JSON
        response = _generate_with_fallback(
            client,
            contents=[uploaded_file, prompt],
            config={"response_mime_type": "application/json"}
        )

        result = json.loads(response.text)
        return result
    finally:
        # Limpa o arquivo no Gemini para não ocupar armazenamento
        if uploaded_file and hasattr(uploaded_file, 'name'):
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                pass

def extract_text_from_document(file_path: str, ext: str, focus: str = None) -> str:
    """Extrai texto puro de arquivos PDF, DOCX, TXT, MD, etc."""
    if ext == ".docx":
        import zipfile
        import xml.etree.ElementTree as ET
        try:
            with zipfile.ZipFile(file_path) as docx:
                xml_content = docx.read('word/document.xml')
                tree = ET.fromstring(xml_content)
                namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                paragraphs = []
                for p in tree.iterfind('.//w:p', namespaces):
                    texts = [node.text for node in p.iterfind('.//w:t', namespaces) if node.text]
                    if texts:
                        paragraphs.append(''.join(texts))
                return '\n\n'.join(paragraphs)
        except Exception as e:
            print(f"Erro ao extrair docx: {e}")
            return ""
    elif ext == ".pdf":
        try:
            import pypdf
        except ImportError:
            try:
                import subprocess, sys
                subprocess.run([sys.executable, "-m", "pip", "install", "pypdf"], capture_output=True, timeout=30)
                import pypdf
            except Exception:
                pypdf = None

        if pypdf:
            try:
                reader = pypdf.PdfReader(file_path)
                pages_text = []
                total_pages = len(reader.pages)
                focus_terms = [t.lower().strip() for t in (focus or "").split() if len(t) > 2]

                for idx, page in enumerate(reader.pages):
                    try:
                        ptxt = page.extract_text() or ""
                    except Exception:
                        ptxt = ""
                    if ptxt and ptxt.strip():
                        if total_pages > 40 and focus_terms:
                            lower_p = ptxt.lower()
                            if any(term in lower_p for term in focus_terms):
                                pages_text.append(f"--- [Página {idx+1}] ---\n{ptxt.strip()}")
                        else:
                            pages_text.append(f"--- [Página {idx+1}] ---\n{ptxt.strip()}")

                if not pages_text and total_pages > 40:
                    for idx in range(min(40, total_pages)):
                        try:
                            ptxt = reader.pages[idx].extract_text() or ""
                            if ptxt.strip():
                                pages_text.append(f"--- [Página {idx+1}] ---\n{ptxt.strip()}")
                        except Exception:
                            pass

                full_text = "\n\n".join(pages_text)
                if len(full_text) > 180000:
                    full_text = full_text[:180000] + "\n\n[... Restante do manual resumido para otimização ...]"
                return full_text
            except Exception as e:
                print(f"Erro ao ler PDF com pypdf: {e}")
                return ""
        return ""
    elif ext in [".txt", ".md", ".csv", ".json", ".html", ".xml", ".log", ".rtf"]:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="latin-1", errors="ignore") as f:
                return f.read()
    return ""

def analyze_and_extract_manual(file_path: str, filename: str, focus: str = None) -> Dict[str, Any]:
    """
    Recebe um manual técnico ou documento (PDF, Word DOCX, TXT, Imagem escaneada),
    envia para o Gemini multimodal, analisa o conteúdo técnico
    e sintetiza um procedimento operacional limpo, estruturado e analítico.
    """
    api_key = database.get_setting("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
    if not api_key or not api_key.strip():
        raise ValueError(
            "Chave de API do Gemini não configurada. "
            "Adicione sua chave gratuita do Google AI Studio na aba Configurações para processar manuais e documentos."
        )

    from google import genai
    client = genai.Client(api_key=api_key.strip())

    uploaded_file = None
    try:
        ext = os.path.splitext(filename)[1].lower() if filename else ".pdf"

        focus_instruction = f"\nO usuário solicitou dar ênfase especial ao seguinte tópico ou dúvida do manual: \"{focus}\"." if focus and focus.strip() else ""

        prompt = f"""Você é um Engenheiro de Processos Técnicos e Especialista em Manuais de Serviço e Operação.
Analise detalhadamente o manual/documento técnico anexo: "{filename}".
{focus_instruction}

Sua missão:
1. Identificar o equipamento, máquina ou sistema principal abordado no documento.
2. Extrair o procedimento operacional, roteiro de manutenção, solução de erro ou configuração descrita.
3. Transformar o conteúdo bruto ou denso do manual em um procedimento analítico, limpo, prático e didático para a equipe de campo e escritório.
4. Identificar ferramentas necessárias, códigos de peças, códigos de erro e precauções de segurança.
5. Retornar ESTRITAMENTE um objeto JSON válido com o seguinte formato:

{{
  "title": "Título claro, descritivo e padronizado do procedimento",
  "equipment": "Nome e modelo exato do equipamento/sistema identificado (ex: Ricoh MP 301, Kyocera TaskAlfa, DataBit)",
  "category": "Categoria técnica adequada (ex: Impressoras & Multifuncionais, Manuais Técnicos, Hardware, ERP & Sistemas)",
  "tags": "tags, separadas, por, virgula, codigos, modelos, pecas",
  "summary": "Resumo executivo de 1 a 2 frases destacando a finalidade do procedimento e quando aplicá-lo",
  "content": "Conteúdo analítico completo em Markdown estruturado com: ### Objetivo & Escopo, ### Ferramentas / Pré-requisitos / Peças, ### Passo a Passo Detalhado (1., 2., 3. com subitens se necessário), ### Avisos de Segurança & Códigos de Erro Relacionados"
}}
"""

        # 1. Se for PDF, Word (.docx) ou Texto (.txt, .md): tenta extrair o texto diretamente para rapidez extrema
        extracted_text = extract_text_from_document(file_path, ext, focus=focus)
        if extracted_text and extracted_text.strip():
            document_content = f"--- CONTEÚDO EXTRAÍDO DO DOCUMENTO ({filename}) ---\n{extracted_text}\n--- FIM DO DOCUMENTO ---"
            response = _generate_with_fallback(
                client,
                contents=[document_content, prompt],
                config={"response_mime_type": "application/json"}
            )
        else:
            # 2. Se for Imagem escaneada ou PDF protegido: upload via Gemini Files API com mime_type garantido
            mime_map = {
                ".pdf": "application/pdf",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp"
            }
            mime = mime_map.get(ext, "application/pdf")
            uploaded_file = client.files.upload(
                file=file_path,
                config={"mime_type": mime, "display_name": filename}
            )

            # Aguarda se o arquivo estiver em estado PROCESSING no Google
            import time
            max_wait = 25
            while hasattr(uploaded_file, "state") and getattr(uploaded_file.state, "name", "") == "PROCESSING" and max_wait > 0:
                time.sleep(1)
                max_wait -= 1
                try:
                    uploaded_file = client.files.get(name=uploaded_file.name)
                except Exception:
                    break

            response = _generate_with_fallback(
                client,
                contents=[uploaded_file, prompt],
                config={"response_mime_type": "application/json"}
            )

        result = json.loads(response.text)
        return result
    finally:
        if uploaded_file and hasattr(uploaded_file, 'name'):
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                pass
