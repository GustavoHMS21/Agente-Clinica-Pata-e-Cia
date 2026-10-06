"""Consultas de tela do painel da Joyce (modelo de leitura).

Leitura para tela pode ir direto ao banco, juntando tabelas, sem passar pelo domínio:
não decide nada, só mostra. Toda ESCRITA na agenda continua passando pelo ServicoAgenda.
A única escrita aqui é marcar uma passagem como resolvida, que é dado do próprio painel.
"""

import sqlite3
from datetime import date


class PainelSQLite:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def passagens_abertas(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT p.protocolo, p.motivo, p.urgente, p.resumo, p.criada_em, c.telefone, t.nome AS tutor"
            " FROM passagem p JOIN conversa c ON c.id = p.conversa_id LEFT JOIN tutor t ON t.id = p.tutor_id"
            " WHERE p.status = 'aberta' ORDER BY p.urgente DESC, p.criada_em"
        )
        return [dict(r) | {"urgente": bool(r["urgente"])} for r in rows]

    def resolver_passagem(self, protocolo: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE passagem SET status = 'resolvida' WHERE protocolo = ? AND status = 'aberta'", (protocolo,)
        )
        return cursor.rowcount == 1

    def agenda_do_dia(self, dia: date) -> list[dict]:
        rows = self._conn.execute(
            "SELECT ag.inicio, ag.fim, ag.status, ag.preco_centavos, ag.observacao, an.nome AS animal,"
            " t.nome AS tutor, t.telefone, s.nome AS servico, p.nome AS profissional"
            " FROM agendamento ag JOIN animal an ON an.id = ag.animal_id JOIN tutor t ON t.id = an.tutor_id"
            " JOIN servico s ON s.id = ag.servico_id JOIN profissional p ON p.id = ag.profissional_id"
            " WHERE ag.inicio >= ? AND ag.inicio < ? AND ag.status != 'cancelado' ORDER BY ag.inicio, p.nome",
            (f"{dia.isoformat()}T00:00", f"{dia.isoformat()}T23:59"),
        )
        return [dict(r) for r in rows]

    def tutores_para_simulador(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT t.nome, t.telefone, group_concat(an.nome, ', ') AS animais FROM tutor t"
            " LEFT JOIN animal an ON an.tutor_id = t.id WHERE t.provisorio = 0 GROUP BY t.id ORDER BY t.nome"
        )
        return [dict(r) for r in rows]
