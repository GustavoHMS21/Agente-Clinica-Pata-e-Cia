"""Backup do banco (Fase 1 de produção, ADR 0011).

Usa a API de backup do SQLite: copia o banco com o servidor rodando, sem pegar uma escrita
pela metade (copiar o arquivo direto poderia gerar uma cópia corrompida).

Uso manual:  python -m patas.backup
Automático:  o servidor faz um por dia às 3h (horário de Guarulhos) e mantém os 14 mais recentes.

As cópias ficam no mesmo volume do banco: protegem contra bug, apagamento e corrupção, não contra
perda do disco. Para isso, os snapshots diários do volume da plataforma (Fly.io guarda 5 dias)
e, no roadmap, uma cópia para armazenamento externo.
"""

import logging
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from patas.config import agora_local, caminho_banco, carregar_ambiente

log = logging.getLogger(__name__)

MANTER = 14
HORA_DO_BACKUP = 3


def pasta_de_backups() -> Path:
    return Path(os.environ.get("PATAS_BACKUP_DIR") or caminho_banco().parent / "backups")


def fazer_backup(banco: Path, pasta: Path, quando: datetime, manter: int = MANTER) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"patas-{quando:%Y%m%d-%H%M}.db"
    origem, copia = sqlite3.connect(banco), sqlite3.connect(destino)
    try:
        origem.backup(copia)
    finally:
        copia.close()
        origem.close()
    for antigo in sorted(pasta.glob("patas-*.db"))[:-manter]:  # nomes com data: ordem alfabética = cronológica
        antigo.unlink()
    return destino


def segundos_ate_o_proximo(agora: datetime, hora: int = HORA_DO_BACKUP) -> float:
    proximo = agora.replace(hour=hora, minute=0, second=0, microsecond=0)
    if proximo <= agora:
        proximo += timedelta(days=1)
    return (proximo - agora).total_seconds()


def agendar_backup_diario() -> threading.Thread:
    """Thread em segundo plano no próprio servidor (um processo só, ADR 0010): simples e sem cron."""

    def laco() -> None:
        while True:
            time.sleep(segundos_ate_o_proximo(agora_local()))
            try:
                destino = fazer_backup(caminho_banco(), pasta_de_backups(), agora_local())
                log.info("Backup diário feito: %s", destino.name)
            except Exception:
                log.exception("Backup diário falhou")  # nunca derruba o servidor

    thread = threading.Thread(target=laco, name="backup-diario", daemon=True)
    thread.start()
    return thread


def main() -> int:
    carregar_ambiente()
    destino = fazer_backup(caminho_banco(), pasta_de_backups(), agora_local())
    print(f"Backup feito: {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
