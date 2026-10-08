def normalizar_telefone(bruto: str) -> str:
    """Deixa só dígitos, com DDI 55 e o 9 do celular.

    '(11) 90000-1102', '+55 11 90000-1102' e '5511900001102' viram '5511900001102'.
    O WhatsApp às vezes entrega celular brasileiro sem o 9 ('551187654321'): ele é recolocado,
    senão o tutor cadastrado não é reconhecido e a resposta pode não ser entregue.
    """
    digitos = "".join(c for c in bruto if c.isdigit())
    if len(digitos) in (10, 11):  # DDD + número, sem DDI
        digitos = "55" + digitos
    if len(digitos) == 12 and digitos.startswith("55") and digitos[4] in "6789":  # celular de 8 dígitos
        digitos = digitos[:4] + "9" + digitos[4:]
    return digitos
