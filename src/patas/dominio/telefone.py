def normalizar_telefone(bruto: str) -> str:
    """Deixa só dígitos, com DDI 55.

    '(11) 90000-1102', '+55 11 90000-1102' e '5511900001102' viram '5511900001102'.
    """
    digitos = "".join(c for c in bruto if c.isdigit())
    if len(digitos) in (10, 11):  # DDD + número, sem DDI
        digitos = "55" + digitos
    return digitos
