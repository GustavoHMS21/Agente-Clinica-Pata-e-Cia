"""Adaptador para APIs compatíveis com OpenAI (Gemini, Qwen, OpenRouter, Ollama).

Converte o formato interno de blocos (text, tool_use, tool_result) para chat completions
e volta. As duas conversões são funções puras, testadas sem rede.

Assinaturas de pensamento: modelos com raciocínio (ex.: Gemini 3) podem devolver um
`extra_content` em cada tool_call, que precisa voltar intacto dentro do mesmo turno.
O adaptador guarda esse campo no bloco tool_use; entre turnos ele some junto com o
thinking (para_historico no loop), a mesma regra do ADR 0005.
"""

import json
from uuid import uuid4

import openai

from patas.agente.llm import FalhaLLM, RespostaLLM

TIMEOUT_S = 60.0
TENTATIVAS = 2

FIM_PARA_STOP_REASON = {
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}


class ClienteOpenAICompativel:
    def __init__(self, base_url: str, modelo: str, chave: str) -> None:
        # A chave vem do ambiente pela fábrica; fica só dentro do cliente HTTP, nunca em log.
        self._cliente = openai.OpenAI(api_key=chave, base_url=base_url, timeout=TIMEOUT_S, max_retries=TENTATIVAS)
        self._modelo = modelo

    def criar(self, system: list[dict], tools: list[dict], messages: list[dict]) -> RespostaLLM:
        try:
            resposta = self._cliente.chat.completions.create(
                model=self._modelo,
                messages=para_openai(system, messages),
                tools=ferramentas_para_openai(tools),
                tool_choice="auto",
            )
        except (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError) as e:
            raise FalhaLLM(type(e).__name__) from e
        except openai.APIStatusError as e:
            raise FalhaLLM(f"{type(e).__name__} status={e.status_code}: {e.message}") from e

        if not resposta.choices:
            raise FalhaLLM("Resposta sem choices")
        escolha = resposta.choices[0]
        uso = resposta.usage
        return de_openai(
            escolha.message.model_dump(exclude_none=True),
            escolha.finish_reason,
            {
                "input_tokens": uso.prompt_tokens if uso else 0,
                "output_tokens": uso.completion_tokens if uso else 0,
                "modelo": resposta.model,
            },
        )


def ferramentas_para_openai(tools: list[dict]) -> list[dict]:
    """Definições internas -> function tools. Sem 'strict' e sem 'additionalProperties',
    que nem todo provedor compatível aceita; o domínio valida os argumentos de qualquer forma."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": _sem_additional_properties(t["input_schema"]),
            },
        }
        for t in tools
    ]


def para_openai(system: list[dict], messages: list[dict]) -> list[dict]:
    """Histórico interno -> mensagens de chat completions."""
    saida = [{"role": "system", "content": "\n\n".join(b["text"] for b in system if b.get("type") == "text")}]
    for m in messages:
        blocos = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
        if m["role"] == "user":
            # Resultados de ferramenta primeiro: respondem à chamada anterior. O texto novo do tutor vem depois.
            for b in blocos:
                if b.get("type") == "tool_result":
                    saida.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
            texto = "\n".join(b["text"] for b in blocos if b.get("type") == "text")
            if texto:
                saida.append({"role": "user", "content": texto})
        else:
            texto = "\n\n".join(b["text"] for b in blocos if b.get("type") == "text" and b.get("text"))
            chamadas = []
            for b in blocos:
                if b.get("type") == "tool_use":
                    chamada = {
                        "id": b["id"],
                        "type": "function",
                        "function": {"name": b["name"], "arguments": json.dumps(b["input"], ensure_ascii=False)},
                    }
                    if "extra_content" in b:
                        chamada["extra_content"] = b["extra_content"]  # assinatura de pensamento, intacta
                    chamadas.append(chamada)
            if texto or chamadas:
                mensagem: dict = {"role": "assistant", "content": texto or None}
                if chamadas:
                    mensagem["tool_calls"] = chamadas
                saida.append(mensagem)
    return saida


def de_openai(mensagem: dict, finish_reason: str | None, uso: dict) -> RespostaLLM:
    """Mensagem do provedor -> RespostaLLM no formato interno."""
    blocos: list[dict] = []
    if mensagem.get("content"):
        blocos.append({"type": "text", "text": mensagem["content"]})
    for chamada in mensagem.get("tool_calls") or []:
        funcao = chamada.get("function", {})
        try:
            entrada = json.loads(funcao.get("arguments") or "{}")
        except json.JSONDecodeError:
            entrada = {}  # vira ARGUMENTO_INVALIDO no executor, e o modelo corrige na próxima chamada
        bloco = {
            "type": "tool_use",
            "id": chamada.get("id") or f"call_{uuid4().hex[:12]}",
            "name": funcao.get("name", ""),
            "input": entrada if isinstance(entrada, dict) else {},
        }
        if chamada.get("extra_content"):
            bloco["extra_content"] = chamada["extra_content"]
        blocos.append(bloco)

    stop_reason = FIM_PARA_STOP_REASON.get(finish_reason or "", "end_turn")
    if stop_reason == "end_turn" and any(b["type"] == "tool_use" for b in blocos):
        stop_reason = "tool_use"  # alguns provedores mandam "stop" mesmo com tool_calls
    return RespostaLLM(stop_reason, blocos, uso)


def _sem_additional_properties(schema):
    if isinstance(schema, dict):
        return {k: _sem_additional_properties(v) for k, v in schema.items() if k != "additionalProperties"}
    if isinstance(schema, list):
        return [_sem_additional_properties(v) for v in schema]
    return schema
