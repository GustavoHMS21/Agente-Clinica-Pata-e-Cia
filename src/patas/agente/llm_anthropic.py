"""Adaptador Anthropic (Claude). Ver ADR 0005 para modelo, thinking e fallbacks."""

import anthropic

from patas.agente.llm import FalhaLLM, RespostaLLM

MODELO = "claude-opus-5-5"
EFFORT = "medium"  # padrão do Opus 5.5, explícito. Ajustar com a avaliação do bloco 10.
MAX_TOKENS = 16000  # teto de thinking + resposta por chamada
TIMEOUT_S = 60.0
TENTATIVAS = 2  # o SDK repete sozinho 408, 409, 429, 5xx e falha de conexão

BETAS = [
    # Preserved thinking: o histórico nunca replica thinking de turnos anteriores (ADR 0005).
    # "error" faz um bug nosso falhar alto em vez de degradar em silêncio.
    "thinking-binding-controls-2026-08-01",
    # Se um classificador de segurança recusar, a API refaz a chamada num modelo de fallback.
    "server-side-fallback-2026-07-01",
]


class ClienteClaude:
    def __init__(self, modelo: str | None = None) -> None:
        # Sem api_key explícita: o SDK lê ANTHROPIC_API_KEY do ambiente. A chave nunca passa por aqui.
        self._cliente = anthropic.Anthropic(timeout=TIMEOUT_S, max_retries=TENTATIVAS)
        self._modelo = modelo or MODELO

    def criar(self, system: list[dict], tools: list[dict], messages: list[dict]) -> RespostaLLM:
        try:
            resposta = self._cliente.beta.messages.create(
                model=self._modelo,
                max_tokens=MAX_TOKENS,
                system=system,
                tools=tools,
                messages=messages,
                thinking={"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "error"}},
                output_config={"effort": EFFORT},
                fallbacks="default",
                betas=BETAS,
            )
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as e:
            raise FalhaLLM(type(e).__name__) from e
        except anthropic.APIStatusError as e:
            # 400/401/403/404: erro nosso (requisição ou chave). A mensagem da API diz o que corrigir;
            # o corpo da requisição (com dados do tutor) e a chave nunca vão para o log.
            raise FalhaLLM(f"{type(e).__name__} status={e.status_code} request_id={e.request_id}: {e.message}") from e

        uso = resposta.usage
        return RespostaLLM(
            stop_reason=resposta.stop_reason,
            content=[b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in resposta.content],
            uso={
                "input_tokens": uso.input_tokens,
                "output_tokens": uso.output_tokens,
                "cache_read_input_tokens": uso.cache_read_input_tokens or 0,
                "modelo": resposta.model,
            },
        )
