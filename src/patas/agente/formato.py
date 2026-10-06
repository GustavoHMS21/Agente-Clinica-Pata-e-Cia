"""Formatação para o tutor. O modelo copia estes textos em vez de calcular datas e preços."""

from datetime import date, datetime

DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def rotulo(momento: datetime) -> str:
    """'quinta, 08/10 às 10h' ou 'terça, 29/09 às 14h30'."""
    hora = f"{momento.hour}h" + (f"{momento.minute:02d}" if momento.minute else "")
    return f"{DIAS[momento.weekday()]}, {momento:%d/%m} às {hora}"


def rotulo_data(dia: date) -> str:
    return f"{DIAS[dia.weekday()]}, {dia:%d/%m/%Y}"


def reais(centavos: int) -> str:
    """16000 -> 'R$ 160,00'; 1234567 -> 'R$ 12.345,67'."""
    inteiro, resto = divmod(centavos, 100)
    return f"R$ {inteiro:,}".replace(",", ".") + f",{resto:02d}"
