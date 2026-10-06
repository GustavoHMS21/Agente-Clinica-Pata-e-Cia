from uuid import uuid4


def novo_id(prefixo: str) -> str:
    # Aleatório, não sequencial: id em sequência convida a testar o vizinho.
    return f"{prefixo}_{uuid4().hex[:12]}"
