"""Ponto de entrada de produção (bloco 11, ADR 0010): prepara o banco e sobe o servidor.

Uso: python -m patas.servidor   (é o comando da imagem Docker)

Variáveis: as do .env.example, mais
  HOST                 interface de rede. Padrão 127.0.0.1 (só esta máquina); a imagem usa 0.0.0.0
  PORT                 porta. Padrão 8000; as plataformas costumam definir a delas
  PATAS_DADOS_DE_EXEMPLO  1 (padrão) cria o banco com o seed fictício na primeira subida
  FORWARDED_ALLOW_IPS  de quem aceitar cabeçalhos X-Forwarded-*. Padrão 127.0.0.1; atrás do proxy da plataforma, *
  PATAS_BACKUP_DIARIO  1 (padrão) faz backup do banco todo dia às 3h; 0 desliga
  PATAS_BACKUP_DIR     pasta dos backups. Padrão: backups/ ao lado do banco
"""

import logging
import os

import uvicorn

from patas.backup import agendar_backup_diario
from patas.config import agora_local, caminho_banco, carregar_ambiente
from patas.repositorio.sqlite import conectar, criar_schema
from patas.seed import popular

log = logging.getLogger("patas.servidor")


def preparar_banco() -> None:
    banco = caminho_banco()
    novo = not banco.exists()
    banco.parent.mkdir(parents=True, exist_ok=True)
    conn = conectar(banco)
    try:
        aplicadas = criar_schema(conn)  # migrações pendentes (ADR 0011); banco existente nunca é recriado
        if aplicadas:
            log.warning("Migrações aplicadas: %s", ", ".join(aplicadas))
        if novo and os.environ.get("PATAS_DADOS_DE_EXEMPLO", "1") == "1":
            popular(conn, agora_local().date())
            log.warning("Banco novo criado com dados de EXEMPLO (fictícios) em %s", banco)
    finally:
        conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    carregar_ambiente()
    preparar_banco()
    if os.environ.get("PATAS_BACKUP_DIARIO", "1") == "1":
        agendar_backup_diario()
    uvicorn.run(
        "patas.web.app:criar_app",
        factory=True,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        workers=1,  # SQLite com um processo só: simples e sem disputa de escrita (ADR 0010)
    )


if __name__ == "__main__":
    main()
