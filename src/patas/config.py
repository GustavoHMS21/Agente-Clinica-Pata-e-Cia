"""Configuração lida do ambiente.

Segredos chegam só por variável de ambiente (.env local, cofre de segredos no deploy).
Nenhum valor sensível tem padrão aqui, e nenhuma função deste módulo imprime ou
devolve o valor da chave.
"""

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
FUSO_DA_CLINICA = ZoneInfo("America/Sao_Paulo")


def agora_local() -> datetime:
    """Hora de Guarulhos, sem fuso e em minutos (o formato do banco, ADR 0003).

    Não usa o relógio local da máquina: no deploy o servidor costuma rodar em UTC.
    """
    return datetime.now(FUSO_DA_CLINICA).replace(tzinfo=None, second=0, microsecond=0)


def carregar_ambiente() -> None:
    """Lê o .env da raiz, se existir. Chamado só pelos pontos de entrada (chat, servidor).

    Variável já definida no ambiente vence o .env: no deploy, o cofre manda.
    """
    load_dotenv(RAIZ / ".env", override=False)


def caminho_banco() -> Path:
    return Path(os.environ.get("PATAS_DB_PATH", RAIZ / "data" / "patas.db"))
