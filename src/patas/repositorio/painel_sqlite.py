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

    def operacao(self, de: date, ate: date) -> dict:
        """Números do período [de, ate], para a página de operação (bloco 9)."""
        inicio, fim = f"{de.isoformat()}T00:00", f"{ate.isoformat()}T23:59:59"
        q = self._conn.execute

        turnos = q("SELECT conversa_id, nome, duracao_ms, substr(criada_em, 1, 10) AS dia FROM execucao"
                   " WHERE tipo = 'turno' AND criada_em BETWEEN ? AND ?", (inicio, fim)).fetchall()
        llm = q("SELECT COUNT(*) AS chamadas, COALESCE(SUM(custo_usd), 0) AS custo,"
                " SUM(custo_usd IS NULL) AS sem_preco, SUM(tokens_entrada) AS entrada, SUM(tokens_saida) AS saida,"
                " SUM(tokens_cache_lidos) AS cache_lidos, SUM(tokens_cache_gravados) AS cache_gravados,"
                " SUM(resultado = 'falha') AS falhas FROM execucao WHERE tipo = 'llm' AND criada_em BETWEEN ? AND ?",
                (inicio, fim)).fetchone()
        custo_por_dia = q("SELECT substr(criada_em, 1, 10) AS dia, SUM(custo_usd) AS custo FROM execucao"
                          " WHERE tipo = 'llm' AND criada_em BETWEEN ? AND ? GROUP BY dia ORDER BY dia",
                          (inicio, fim)).fetchall()
        erros = q("SELECT nome AS ferramenta, resultado AS codigo, COUNT(*) AS vezes FROM execucao"
                  " WHERE tipo = 'ferramenta' AND resultado != 'ok' AND criada_em BETWEEN ? AND ?"
                  " GROUP BY nome, resultado ORDER BY vezes DESC", (inicio, fim)).fetchall()
        passagens = q("SELECT motivo, COUNT(*) AS vezes FROM passagem WHERE criada_em BETWEEN ? AND ?"
                      " GROUP BY motivo ORDER BY vezes DESC", (inicio, fim)).fetchall()
        acoes = q("SELECT tipo, COUNT(*) AS vezes FROM proposta WHERE usada_em BETWEEN ? AND ?"
                  " GROUP BY tipo ORDER BY vezes DESC", (inicio, fim)).fetchall()

        duracoes = sorted(t["duracao_ms"] for t in turnos)
        desfechos: dict[str, int] = {}
        for t in turnos:
            desfechos[t["nome"]] = desfechos.get(t["nome"], 0) + 1
        entrada_total = (llm["entrada"] or 0) + (llm["cache_lidos"] or 0) + (llm["cache_gravados"] or 0)
        return {
            "de": de.isoformat(),
            "ate": ate.isoformat(),
            "conversas": len({t["conversa_id"] for t in turnos}),
            "mensagens": len(turnos),  # turnos: uma resposta do agente por rajada de mensagens do tutor
            "tempo_resposta_ms": {
                "mediana": duracoes[len(duracoes) // 2] if duracoes else None,
                "p95": duracoes[min(len(duracoes) - 1, int(len(duracoes) * 0.95))] if duracoes else None,
            },
            "chamadas_llm": llm["chamadas"],
            "falhas_llm": llm["falhas"] or 0,
            "custo_usd": round(llm["custo"], 4),
            "custo_por_mensagem_usd": round(llm["custo"] / len(turnos), 4) if turnos else None,
            "chamadas_sem_preco": llm["sem_preco"] or 0,
            "tokens": {"entrada": llm["entrada"] or 0, "saida": llm["saida"] or 0,
                       "cache_lidos": llm["cache_lidos"] or 0, "cache_gravados": llm["cache_gravados"] or 0},
            "aproveitamento_cache": round((llm["cache_lidos"] or 0) / entrada_total, 3) if entrada_total else None,
            "custo_por_dia": [dict(r) for r in custo_por_dia],
            "desfechos": dict(sorted(desfechos.items(), key=lambda kv: -kv[1])),
            "erros_de_ferramenta": [dict(r) for r in erros],
            "passagens_por_motivo": [dict(r) for r in passagens],
            "acoes_concluidas_pelo_agente": [dict(r) for r in acoes],
        }

    def tutores_para_simulador(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT t.nome, t.telefone, group_concat(an.nome, ', ') AS animais FROM tutor t"
            " LEFT JOIN animal an ON an.tutor_id = t.id WHERE t.provisorio = 0 GROUP BY t.id ORDER BY t.nome"
        )
        return [dict(r) for r in rows]
