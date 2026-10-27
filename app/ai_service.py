import os
from typing import Dict, Any, List
from . import database

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
            # Chamada usando modelo flash
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )

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
