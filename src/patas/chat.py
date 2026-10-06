"""Chat de teste no terminal, fingindo ser um tutor no WhatsApp.

Uso: uv run python -m patas.chat --telefone "(11) 90000-1101"
Cada mensagem chama o LLM configurado no .env (LLM_PROVEDOR), o que custa dinheiro.
Ctrl+C ou "sair" encerra.
"""

import argparse
import logging
import sys
from datetime import datetime

from patas.agente.llm import cliente_do_ambiente
from patas.agente.loop import Agente
from patas.config import caminho_banco, carregar_ambiente
from patas.dominio.agenda import ServicoAgenda
from patas.dominio.conversa import ServicoConversa
from patas.repositorio.sqlite import AgendaSQLite, AtendimentoSQLite, conectar


def main() -> int:
    parser = argparse.ArgumentParser(description="Converse com o agente como se fosse um tutor.")
    parser.add_argument("--telefone", required=True, help='ex.: "(11) 90000-1101" (Mariana, do seed)')
    args = parser.parse_args()

    carregar_ambiente()
    llm = cliente_do_ambiente()  # falha cedo se a chave do provedor escolhido não estiver no .env
    logging.basicConfig(level=logging.WARNING)
    banco = caminho_banco()
    if not banco.exists():
        print("Banco não encontrado. Rode antes: uv run python -m patas.seed")
        return 1

    conn = conectar(banco)
    agenda_repo, atendimento_repo = AgendaSQLite(conn), AtendimentoSQLite(conn)
    agenda = ServicoAgenda(agenda_repo, atendimento_repo)
    conversas = ServicoConversa(agenda_repo, atendimento_repo)
    agente = Agente(llm, agenda, conversas)

    print("Patas & Cia (teste). Digite sua mensagem; 'sair' encerra.\n")
    while True:
        try:
            texto = input("você> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if texto.lower() == "sair":
            break
        if not texto:
            continue
        agora = datetime.now().replace(second=0, microsecond=0)  # o banco guarda em minutos
        conversa = conversas.receber(args.telefone, texto, agora)
        resposta = agente.responder(conversa.id, agora)
        print(f"\npatas> {resposta}\n")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
