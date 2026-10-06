"""Custo estimado de cada chamada ao LLM, em dólares (bloco 9).

Tabela por modelo, em US$ por milhão de tokens: (entrada, saída, leitura de cache, gravação de cache).
A gravação de cache é a de 5 minutos (1,25x a entrada). Conferir os preços oficiais ao trocar de
modelo; modelo fora da tabela fica com custo desconhecido (None), nunca com um palpite.
"""

PRECOS_POR_MILHAO = {
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
}


def custo_usd(modelo: str, uso: dict) -> float | None:
    precos = PRECOS_POR_MILHAO.get(modelo)
    if precos is None:
        return None
    entrada, saida, cache_lido, cache_gravado = precos
    total = (
        uso.get("input_tokens", 0) * entrada
        + uso.get("output_tokens", 0) * saida
        + uso.get("cache_read_input_tokens", 0) * cache_lido
        + uso.get("cache_creation_input_tokens", 0) * cache_gravado
    )
    return total / 1_000_000
