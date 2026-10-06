"""Configuração lida do ambiente.

Segredos chegam só por variável de ambiente (.env local, cofre de segredos no deploy).
Nenhum valor sensível tem padrão aqui, e nenhuma função deste módulo imprime ou
devolve o valor da chave.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]


def carregar_ambiente() -> None:
    """Lê o .env da raiz, se existir. Chamado só pelos pontos de entrada (chat, servidor).

    Variável já definida no ambiente vence o .env: no deploy, o cofre manda.
    """
    load_dotenv(RAIZ / ".env", override=False)


def caminho_banco() -> Path:
    return Path(os.environ.get("PATAS_DB_PATH", RAIZ / "data" / "patas.db"))
