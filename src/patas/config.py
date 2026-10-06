"""Configuração lida do ambiente.

Segredos chegam só por variável de ambiente (.env local, cofre de segredos no deploy).
Nenhum valor sensível tem padrão aqui.
"""

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def caminho_banco() -> Path:
    return Path(os.environ.get("PATAS_DB_PATH", RAIZ / "data" / "patas.db"))
