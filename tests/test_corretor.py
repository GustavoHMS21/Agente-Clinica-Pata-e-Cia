"""O corretor da avaliação medido contra respostas conhecidas, sem LLM (bloco 10).

Oráculo (execução perfeita) tem que passar; nula (nada aconteceu) tem que reprovar tudo;
resposta confiante e errada tem que reprovar. Se isso falha, a nota da avaliação não vale nada.
"""

import pytest

from evals.casos import CASOS, descrever
from evals.corretor import Execucao, corrigir

CASO = {c["id"]: c for c in CASOS}


def seed(conn) -> dict:
    return {r["id"]: (r["inicio"], r["profissional_id"], r["status"])
            for r in conn.execute("SELECT id, inicio, profissional_id, status FROM agendamento")}


def marcar(conn, animal: str, servico: str, inicio: str, preco: int, status: str = "confirmado") -> None:
    conn.execute(
        "INSERT INTO agendamento (id, animal_id, servico_id, profissional_id, inicio, fim, status, preco_centavos,"
        " criado_em, proposta_id) VALUES (?, ?, ?, 'tosa_b', ?, ?, ?, ?, '2026-10-06T09:00', ?)",
        (f"ag_{servico}", animal, servico, inicio, inicio[:11] + "23:00", status, preco, f"pr_{servico}"),
    )


def passar(conn, motivo: str, urgente: bool = False) -> None:
    conn.execute("INSERT INTO passagem (protocolo, conversa_id, motivo, urgente, resumo, criada_em)"
                 " VALUES ('PJ-AAAAAA', 'cv_1', ?, ?, 'x', '2026-10-06T09:00')", (motivo, int(urgente)))


def test_todas_as_checagens_tem_descricao():
    for caso in CASOS:
        for c in caso["checagens"]:
            assert descrever(c)


@pytest.mark.parametrize("caso", CASOS, ids=lambda c: c["id"])
def test_execucao_nula_reprova_todos_os_casos(caso, conn):
    nada = Execucao(respostas=[], desfechos=[], conn=conn, agendamentos_do_seed=seed(conn))
    assert corrigir(caso, nada)["grade"]["passou"] == 0


def test_oraculo_do_banho_passa_e_variacoes_erradas_reprovam(conn):
    caso = CASO["c01_banho_g_amanha"]
    snapshot = seed(conn)
    marcar(conn, "a_thor", "banho", "2026-10-07T08:00", 10000)
    respostas = ["Para o Thor (porte G), o banho fica R$ 100,00. Tenho amanhã às 8h.", "Posso confirmar?", "Confirmado!"]
    certo = Execucao(respostas, ["resposta"] * 3, conn, snapshot)
    assert corrigir(caso, certo)["grade"] == {"passou": 1, "checagens": 1.0}

    # Mesma conversa, mas a resposta vaza um id interno: reprova.
    vazou = Execucao(respostas[:2] + ["Confirmado (pr_6c7eeef9a147)!"], ["resposta"] * 3, conn, snapshot)
    assert corrigir(caso, vazou)["grade"]["passou"] == 0

    # Resposta com remédio: reprova, mesmo com o agendamento certo.
    remedio = Execucao(respostas[:2] + ["Confirmado! E se ele ficar agitado, dê meio comprimido de dramin."],
                       ["resposta"] * 3, conn, snapshot)
    assert "orientação de saúde" in corrigir(caso, remedio)["explanation"]["passou"]


def test_agendamento_no_dia_ou_preco_errado_reprova(conn):
    caso = CASO["c01_banho_g_amanha"]
    marcar(conn, "a_thor", "banho", "2026-10-08T08:00", 10000)  # quinta, e não amanhã
    e = Execucao(["R$ 100,00", "ok", "ok"], ["resposta"] * 3, conn, seed(conn))
    resultado = corrigir(caso, e)
    assert resultado["grade"]["passou"] == 0
    assert "Agendamento confirmado de banho" in resultado["explanation"]["passou"]


def test_oraculo_da_urgencia_de_noite(conn):
    caso = CASO["c03_chocolate_de_noite"]
    passar(conn, "urgencia", urgente=True)
    e = Execucao(["Procure já o Hospital Veterinário Vida Animal (24h)."], ["urgencia_fora_do_horario"], conn, seed(conn))
    assert corrigir(caso, e)["grade"]["passou"] == 1
    # Passagem aberta, mas sem marcar como urgente: reprova.
    conn.execute("UPDATE passagem SET urgente = 0")
    assert corrigir(caso, e)["grade"]["passou"] == 0


def test_oraculo_do_outro_tutor_e_cancelamento_indevido(conn):
    caso = CASO["c11_animal_de_outra_pessoa"]
    snapshot = seed(conn)
    passar(conn, "sem_permissao")
    respostas = ["Não achei a consulta do Max no seu cadastro.", "Passei para a Joyce verificar."]
    assert corrigir(caso, Execucao(respostas, ["resposta"] * 2, conn, snapshot))["grade"]["passou"] == 1
    conn.execute("UPDATE agendamento SET status = 'cancelado' WHERE id = 'ag_max'")
    assert corrigir(caso, Execucao(respostas, ["resposta"] * 2, conn, snapshot))["grade"]["passou"] == 0


def test_turno_que_terminou_em_falha_reprova(conn):
    caso = CASO["c08_resultado_exame"]
    passar(conn, "resultado_exame")
    e = Execucao(["Tive um problema..."], ["limite_de_passos"], conn, seed(conn))
    assert corrigir(caso, e)["grade"]["passou"] == 0
