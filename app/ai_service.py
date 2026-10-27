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
            "answer": f"Não encontrei nenhum procedimento cadastrado com vínculo direto a: **\"{question}\"**.\n\n💡 *Dica: você pode cadastrar essa anotação na aba **\"Novo Procedimento\"** para tê-la sempre à mão quando precisar novamente!*",
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

            prompt = f"""Você é o Assistente Especialista em Procedimentos Operacionais e Manutenção da empresa.
O usuário fez a seguinte pergunta:
"{question}"

Abaixo estão os procedimentos registrados na base de conhecimento da empresa relacionados a essa dúvida:
----------------
{"".join(full_contexts)}
----------------

Instruções para a resposta:
1. Responda diretamente à dúvida do usuário de forma clara, objetiva e prática.
2. Forneça o passo a passo exato conforme documentado nos procedimentos acima.
3. Se houver comandos específicos, códigos numéricos ou avisos de segurança/atenção, destaque-os com clareza.
4. Ao final, cite o título exato do procedimento de onde veio a informação.
5. Se a dúvida não estiver 100% coberta pelos procedimentos fornecidos, responda o que for possível e alerte o usuário.
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

    msg = f"Encontrei **{len(sources)}** procedimento(s) vinculado(s) à sua pergunta:\n\n"
    msg += f"### 📌 Principal Correspondência: **{primary['title']}**\n"
    msg += f"- **Equipamento/Sistema:** `{primary['equipment']}`\n"
    msg += f"- **Categoria:** `{primary['category']}`\n\n"
    
    if primary.get("summary"):
        msg += f"**Resumo:** {primary['summary']}\n\n"

    # Extrai primeiros passos ou trecho do conteúdo
    content_lines = p_full["content"].split("\n")
    passos = [line for line in content_lines if line.strip().startswith(("1.", "2.", "3.", "4.", "5.", "- ", "* "))]
    
    if passos:
        msg += "**Passos Rápidos:**\n"
        for passo in passos[:5]:
            msg += f"{passo}\n"
        msg += "\n*(Abra o cartão do procedimento abaixo para visualizar o roteiro completo)*\n"

    if error:
        msg += f"\n> ⚠️ *Nota: A chave de IA retornou um aviso ({error[:80]}...). A resposta acima foi extraída diretamente da base local.*"
    elif not database.get_setting("gemini_api_key"):
        msg += "\n> 💡 *Dica: Se quiser respostas conversacionais sintetizadas com IA generativa, você pode cadastrar sua chave gratuita do Gemini na aba **Configurações**.*"

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

def extract_text_from_document(file_path: str, ext: str) -> str:
    """Extrai texto puro de arquivos DOCX, TXT, MD, etc."""
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

        # 1. Se for Word (.docx) ou Texto (.txt, .md): extrai o texto diretamente para o Gemini
        extracted_text = extract_text_from_document(file_path, ext)
        if extracted_text and extracted_text.strip():
            document_content = f"--- CONTEÚDO EXTRAÍDO DO DOCUMENTO ({filename}) ---\n{extracted_text}\n--- FIM DO DOCUMENTO ---"
            response = _generate_with_fallback(
                client,
                contents=[document_content, prompt],
                config={"response_mime_type": "application/json"}
            )
        else:
            # 2. Se for PDF ou Imagem: upload via Gemini Files API com mime_type garantido
            mime_map = {
                ".pdf": "application/pdf",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp"
            }
            mime = mime_map.get(ext, "application/pdf")
            uploaded_file = client.files.upload(file=file_path, mime_type=mime)

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
