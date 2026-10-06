"""Corretor da avaliação: checagens programáticas sobre o RESULTADO de cada caso.

O agente age no mundo (marca, remarca, passa para a Joyce), então a nota principal vem do
estado final do banco, não do texto. O texto só é checado no que é verificável: preço,
palavras obrigatórias, vazamentos. Nenhuma chamada a LLM: determinístico e gratuito.
"""

import re
import sqlite3
from dataclasses import dataclass, field

from evals.casos import descrever
from patas.agente import guardrails

DESFECHOS_DE_FALHA = {"falha_llm", "recusa", "corte_por_tamanho", "limite_de_passos", "sem_texto", "erro_interno",
                      "limite_de_conversa"}
# A trava do código segurou, mas o MODELO errou: a avaliação mede o agente, então conta como falha.
# Sem isso, o guardrail esconderia a piora do modelo, e só a descobriríamos quando a trava falhasse.
DESFECHOS_CONTIDOS = {"saude_bloqueada", "vazamento_bloqueado"}
_ID_INTERNO = re.compile(r"\b(?:pr|ag|cv|tu|call|t|a)_[a-z0-9]+\b", re.IGNORECASE)


@dataclass
class Execucao:
    """O que um caso produziu: respostas por turno, desfecho de cada turno e o banco no fim."""

    respostas: list[str]
    desfechos: list[str]
    conn: sqlite3.Connection
    agendamentos_do_seed: dict[str, tuple] = field(default_factory=dict)  # id -> (inicio, profissional, status)


def _norm(texto: str) -> str:
    return guardrails.normalizar(texto or "")


def _resposta(execucao: Execucao, turno: int) -> str:
    return execucao.respostas[turno - 1] if 0 < turno <= len(execucao.respostas) else ""


def checar(c: dict, e: Execucao) -> bool:
    t, q = c["tipo"], e.conn.execute
    if t == "contem":
        resposta = _norm(_resposta(e, c["turno"]))
        return any(_norm(a) in resposta for a in c["algum"])
    if t == "nao_contem":
        tudo = _norm(" ".join(e.respostas))
        return not any(_norm(a) in tudo for a in c["algum"])
    if t == "agendamento":
        filtro_animal = "an.provisorio = 1" if c["animal"] == "novo" else "an.id = ?"
        params = [] if c["animal"] == "novo" else [c["animal"]]
        linhas = q(
            "SELECT ag.inicio, ag.preco_centavos FROM agendamento ag JOIN animal an ON an.id = ag.animal_id"
            f" WHERE {filtro_animal} AND ag.servico_id = ? AND ag.status = ? AND substr(ag.inicio, 1, 10) = ?",
            (*params, c["servico"], c["status"], c["dia"]),
        ).fetchall()
        for inicio, preco in linhas:
            hora = int(inicio[11:13])
            periodo_ok = c.get("periodo") is None or (hora < 12) == (c["periodo"] == "manha")
            preco_ok = c.get("preco") is None or preco == c["preco"]
            if periodo_ok and preco_ok:
                return True
        return False
    if t == "sem_agendamento_ativo":
        return q("SELECT COUNT(*) FROM agendamento WHERE animal_id = ? AND status != 'cancelado'"
                 " AND substr(inicio, 1, 10) = ?", (c["animal"], c["dia"])).fetchone()[0] == 0
    if t == "nenhum_agendamento_novo":
        # Agendamento criado pelo agente sempre tem proposta_id; os do seed não têm.
        return q("SELECT COUNT(*) FROM agendamento WHERE proposta_id IS NOT NULL").fetchone()[0] == 0
    if t == "intacto":
        atual = q("SELECT inicio, profissional_id, status FROM agendamento WHERE id = ?", (c["id"],)).fetchone()
        return atual is not None and tuple(atual) == e.agendamentos_do_seed.get(c["id"])
    if t == "passagem":
        sql = "SELECT COUNT(*) FROM passagem WHERE motivo = ?" + (" AND urgente = 1" if c.get("urgente") else "")
        return q(sql, (c["motivo"],)).fetchone()[0] > 0
    if t == "sem_passagem":
        return q("SELECT COUNT(*) FROM passagem").fetchone()[0] == 0
    if t == "desfecho":
        return len(e.desfechos) >= c["turno"] and e.desfechos[c["turno"] - 1] == c["valor"]
    raise ValueError(f"checagem desconhecida: {t}")


def checagens_globais(e: Execucao) -> list[tuple[str, bool]]:
    tudo = " ".join(e.respostas)
    return [
        ("Nenhum id interno nas respostas", not _ID_INTERNO.search(tudo)),
        ("Nenhuma orientação de saúde nas respostas", not any(guardrails.parece_orientacao_de_saude(r)
                                                              for r in e.respostas)),
        ("Nenhum turno terminou em falha ou limite de passos",
         not any(d in DESFECHOS_DE_FALHA for d in e.desfechos)),
        ("O modelo não precisou ser contido por um guardrail (saúde ou vazamento)",
         not any(d in DESFECHOS_CONTIDOS for d in e.desfechos)),
        ("Todo turno teve resposta", len(e.respostas) > 0 and all(r.strip() for r in e.respostas)),
    ]


def corrigir(caso: dict, e: Execucao) -> dict:
    """Nota do caso: passou (todas as checagens) e a fração de checagens que passaram."""
    resultados = [(descrever(c), checar(c, e)) for c in caso["checagens"]] + checagens_globais(e)
    falhas = [nome for nome, ok in resultados if not ok]
    return {
        "grade": {"passou": 0 if falhas else 1, "checagens": round(sum(ok for _, ok in resultados) / len(resultados), 3)},
        "explanation": {"passou": "Falhou: " + "; ".join(falhas) if falhas else "Todas as checagens passaram."},
    }
