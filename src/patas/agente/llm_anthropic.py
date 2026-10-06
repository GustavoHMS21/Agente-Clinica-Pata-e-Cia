"""Adaptador Anthropic (Claude). Ver ADR 0005 (thinking e fallbacks) e ADR 0006 (escolha do modelo)."""

import anthropic

from patas.agente.llm import FalhaLLM, RespostaLLM

MODELO = "claude-sonnet-5-5"  # modelo do dia a dia: rápido e capaz em ferramentas, metade do preço do Opus
EFFORT = "medium"  # ponto de partida para uso de ferramentas em vários passos (o padrão do Sonnet 5.5 é high)
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
                # Cache automático no fim das mensagens: o próximo passo do turno, e o próximo turno,
                # reaproveitam o histórico já processado (ADR 0008). O prompt fixo tem marcação própria.
                cache_control={"type": "ephemeral"},
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
                "cache_creation_input_tokens": uso.cache_creation_input_tokens or 0,
                "modelo": resposta.model,
            },
        )
