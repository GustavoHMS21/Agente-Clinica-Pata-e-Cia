"""Contrato do LLM e escolha do provedor (ADR 0006).

O loop do agente fala com qualquer objeto que tenha criar(system, tools, messages) e
devolva RespostaLLM. O formato interno é o de blocos (text, tool_use, tool_result), o
mesmo que o banco guarda (ADR 0004). Cada adaptador converte de e para o seu provedor:
- llm_anthropic.py: Claude, formato nativo.
- llm_openai.py: qualquer API compatível com OpenAI (Gemini, Qwen, OpenRouter, Ollama).

Nos testes, um cliente falso com respostas roteirizadas: zero chamada paga.
"""

import os
from dataclasses import dataclass, field
from typing import Protocol

# provedor -> (endereço compatível com OpenAI, variável da chave ou None, modelo padrão, timeout em segundos)
PROVEDORES_OPENAI = {
    # gemini-2.5-flash: em 2026-10-06 os 3.5 a 3.8 Flash davam 503 (alta demanda) no plano gratuito.
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "gemini-2.5-flash", 60.0),
    # Local: sem chave, sem custo, nenhum dado sai da máquina. Em CPU, cada chamada leva de 30 s a minutos.
    # patas-qwen3 = qwen3:8b com janela de 16k tokens (ollama/Modelfile); o padrão do Ollama, 4k, corta o prompt.
    "ollama": ("http://localhost:11434/v1", None, "patas-qwen3", 600.0),
}


@dataclass(frozen=True)
class RespostaLLM:
    stop_reason: str  # end_turn | tool_use | max_tokens | refusal
    content: list[dict]  # blocos como dict, prontos para voltar ao provedor dentro do mesmo turno
    uso: dict = field(default_factory=dict, hash=False)


class FalhaLLM(Exception):
    """O provedor não respondeu depois das tentativas, ou recusou a requisição."""


class ClienteLLM(Protocol):
    def criar(self, system: list[dict], tools: list[dict], messages: list[dict]) -> RespostaLLM: ...


def cliente_do_ambiente() -> ClienteLLM:
    """Monta o cliente pelo .env: LLM_PROVEDOR (anthropic | gemini | ollama) e LLM_MODELO opcional.

    Falha cedo, com mensagem clara, se a chave do provedor escolhido não estiver definida.
    O valor da chave nunca é impresso.
    """
    provedor = os.environ.get("LLM_PROVEDOR", "anthropic").strip().lower()
    modelo = os.environ.get("LLM_MODELO", "").strip() or None

    if provedor == "anthropic":
        _exigir("ANTHROPIC_API_KEY")
        from patas.agente.llm_anthropic import ClienteClaude
        return ClienteClaude(modelo)

    if provedor in PROVEDORES_OPENAI:
        base_url, variavel, padrao, timeout = PROVEDORES_OPENAI[provedor]
        if variavel:
            _exigir(variavel)
        chave = os.environ[variavel] if variavel else "sem-chave"  # o cliente exige um valor; o Ollama ignora
        from patas.agente.llm_openai import ClienteOpenAICompativel
        return ClienteOpenAICompativel(base_url, modelo or padrao, chave, timeout)

    raise RuntimeError(f"LLM_PROVEDOR desconhecido: {provedor}. Use: anthropic, {', '.join(PROVEDORES_OPENAI)}.")


def _exigir(variavel: str) -> None:
    if not os.environ.get(variavel, "").strip():
        raise RuntimeError(f"{variavel} não definida. Preencha no .env (modelo em .env.example).")
