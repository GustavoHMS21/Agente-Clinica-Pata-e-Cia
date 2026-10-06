"""Serviço de agenda com o banco do seed. Hoje é terça 06/10/2026, 9h."""

from datetime import date, datetime, timedelta

import pytest

from patas.dominio.agenda import AnimalNovo, Contexto
from patas.dominio.erros import Codigo, ErroRegra
from patas.dominio.modelos import Especie, Porte, StatusAgendamento, TipoProposta

AGORA = datetime(2026, 10, 6, 9, 0)
QUARTA, QUINTA, SEXTA = date(2026, 10, 7), date(2026, 10, 8), date(2026, 10, 9)
NUMERO_DESCONHECIDO = "5511900001110"  # Larissa, C10


def ctx(tutor_id: str | None, turno: int = 1, agora: datetime = AGORA, conversa: str = "c1") -> Contexto:
    return Contexto(conversa_id=conversa, telefone=NUMERO_DESCONHECIDO, tutor_id=tutor_id, turno=turno, agora=agora)


def erro(codigo: Codigo):
    return pytest.raises(ErroRegra, match=codigo.value)


# Horários ---------------------------------------------------------------------


def test_banho_oferece_um_horario_por_turno_a_partir_de_30_min(servico):
    opcoes = servico.buscar_horarios(ctx("t_mariana"), "banho", AGORA.date(), animal_id="a_thor")
    assert opcoes[0].inicio == datetime(2026, 10, 6, 9, 30)
    assert opcoes[0].fim - opcoes[0].inicio == timedelta(hours=2)  # Thor, 32 kg: porte G
    assert len({(o.inicio.date(), o.inicio.hour < 12) for o in opcoes}) == len(opcoes) == 5


def test_domingo_e_feriado_nao_tem_horario(servico):
    for dia in (date(2026, 10, 11), date(2026, 10, 12)):  # domingo, Nossa Senhora Aparecida
        assert servico.buscar_horarios(ctx("t_mariana"), "banho", dia, dia, animal_id="a_thor") == []


def test_banho_de_gato_so_terca_e_quinta_de_manha(servico):
    gato = AnimalNovo(Especie.GATO, 4.0)
    opcoes = servico.buscar_horarios(ctx(None), "banho_gato", AGORA.date(), animal_novo=gato)
    assert opcoes
    assert all(o.inicio.weekday() in (1, 3) and o.fim.hour <= 12 for o in opcoes)


def test_dermatologia_so_quinta_a_tarde_com_a_dra_paula(servico):
    opcoes = servico.buscar_horarios(ctx("t_mariana"), "consulta_dermato", AGORA.date(), animal_id="a_thor")
    assert all(o.inicio.weekday() == 3 and o.inicio.hour >= 13 and o.profissional_id == "vet_paula" for o in opcoes)
    with erro(Codigo.REGRA_DO_SERVICO):
        servico.buscar_horarios(ctx("t_mariana"), "consulta_dermato", AGORA.date(), animal_id="a_thor",
                                profissional_id="vet_beatriz")


def test_vacina_vencida_bloqueia_o_banho_antes_de_oferecer_horario(servico):
    # C6: a Joyce só descobriu depois de marcar.
    with pytest.raises(ErroRegra) as e:
        servico.buscar_horarios(ctx("t_ana"), "banho_gato", AGORA.date(), animal_id="a_frajola")
    assert e.value.codigo == Codigo.VACINA_PENDENTE
    assert e.value.dados["pendentes"] == ["antirrabica", "v5"]


def test_duas_faltas_bloqueiam_novo_agendamento(servico):
    with erro(Codigo.BLOQUEADO_POR_FALTAS):
        servico.buscar_horarios(ctx("t_carlos"), "consulta_felinos", AGORA.date(), animal_id="a_mimi")


def test_banho_sem_peso_pede_o_peso(servico):
    with erro(Codigo.PRECISA_PESO):
        servico.buscar_horarios(ctx("t_vanessa"), "banho", AGORA.date(), animal_id="a_bolt")


# Propostas --------------------------------------------------------------------


def test_primeira_vacina_vira_consulta_mais_vacina(servico):
    proposta = servico.propor_agendamento(ctx("t_vanessa"), "vacina_v10", datetime(2026, 10, 7, 11), animal_id="a_bolt")
    assert proposta.tipo == TipoProposta.AGENDAMENTO
    assert proposta.dados["preco_centavos"] == 16000 + 9500
    assert proposta.dados["fim"] == "2026-10-07T11:45"  # P7: consulta + vacina leva 45 min
    assert "consulta + vacina" in proposta.dados["observacao"]


def test_horario_ocupado_volta_com_alternativas(servico):
    # A Dra. Paula atende a Nina na quarta às 10h.
    with pytest.raises(ErroRegra) as e:
        servico.propor_agendamento(ctx("t_mariana"), "consulta_clinica", datetime(2026, 10, 7, 10),
                                   animal_id="a_thor", profissional_id="vet_paula")
    assert e.value.codigo == Codigo.HORARIO_INDISPONIVEL
    assert e.value.dados["alternativas"]


def test_animal_ou_agendamento_de_outro_tutor_parece_inexistente(servico):
    # C11: Rafael tenta mexer no Max, que está no nome da Cristina.
    with erro(Codigo.NAO_ENCONTRADO):
        servico.propor_cancelamento(ctx("t_rafael"), "ag_max")
    with erro(Codigo.NAO_ENCONTRADO):
        servico.propor_agendamento(ctx("t_rafael"), "banho", datetime(2026, 10, 7, 14), animal_id="a_max")


def test_numero_sem_cadastro_nao_remarca_nem_cancela(servico):
    with erro(Codigo.SEM_PERMISSAO):
        servico.propor_cancelamento(ctx(None), "ag_luna")


def test_menos_de_2h_pode_desmarcar_e_a_joyce_fica_sabendo(servico, conn):
    # P4: não é falta; as 2h são só para a Joyce conseguir colocar outro no lugar.
    em_cima = datetime(2026, 10, 7, 7, 30)  # banho da Luna às 9h
    proposta = servico.propor_cancelamento(ctx("t_patricia", agora=em_cima), "ag_luna")
    assert any("em cima da hora" in a for a in proposta.dados["avisos"])
    cancelado = servico.confirmar(ctx("t_patricia", turno=2, agora=em_cima), proposta.id)
    assert cancelado.status == StatusAgendamento.CANCELADO
    assert conn.execute("SELECT motivo FROM passagem").fetchone()["motivo"] == "vaga_liberada"
    assert conn.execute("SELECT faltas_sem_aviso FROM tutor WHERE id = 't_patricia'").fetchone()[0] == 0


def test_com_folga_desmarca_sem_incomodar_a_joyce(servico, conn):
    proposta = servico.propor_cancelamento(ctx("t_patricia"), "ag_luna")  # terça 9h, banho quarta 9h
    servico.confirmar(ctx("t_patricia", turno=2), proposta.id)
    assert conn.execute("SELECT COUNT(*) FROM passagem").fetchone()[0] == 0


def test_horario_que_ja_comecou_nao_se_desmarca_por_aqui(servico):
    with erro(Codigo.PRAZO_CURTO):
        servico.propor_cancelamento(ctx("t_patricia", agora=datetime(2026, 10, 7, 9, 10)), "ag_luna")


# Respostas da Beatriz (P1, P2, P8) ------------------------------------------------


def test_gato_e_sempre_com_a_dra_camila(servico, agenda):
    # P1: consulta de gato é a de felinos (R$ 170), e vacina de gato também é com a Camila.
    with pytest.raises(ErroRegra) as e:
        servico.buscar_horarios(ctx("t_ana"), "consulta_clinica", QUINTA, animal_id="a_frajola")
    assert "consulta de felinos" in e.value.mensagem
    agenda.cancelar_agendamento("ag_luna")  # irrelevante: só para garantir agenda livre não interfere
    opcoes = servico.buscar_horarios(ctx("t_ana"), "vacina_antirrabica", QUINTA, animal_id="a_frajola")
    assert opcoes and {o.profissional_id for o in opcoes} == {"vet_camila"}


def test_primeira_vacina_de_gato_e_consulta_de_felinos(servico):
    gato = AnimalNovo(Especie.GATO, 4.0, "Mingau")
    proposta = servico.propor_agendamento(ctx(None), "vacina_v5", datetime(2026, 10, 8, 10), animal_novo=gato,
                                          nome_tutor="Tutor Novo")
    assert proposta.dados["preco_centavos"] == 17000 + 12000
    assert proposta.dados["fim"] == "2026-10-08T10:45"
    assert proposta.dados["profissional_id"] == "vet_camila"


def test_sem_peso_o_porte_vem_da_raca_com_aviso(servico):
    # P2: animal que nunca foi pesado aqui; a tosadora confirma o porte na chegada, e o valor pode mudar.
    sem_peso = AnimalNovo(Especie.CAO, None, "Pipoca")
    with erro(Codigo.PRECISA_PESO):
        servico.propor_agendamento(ctx(None), "banho", datetime(2026, 10, 8, 8), animal_novo=sem_peso,
                                   nome_tutor="Tutor Novo")
    proposta = servico.propor_agendamento(ctx(None), "banho", datetime(2026, 10, 8, 8), animal_novo=sem_peso,
                                          nome_tutor="Tutor Novo", porte_estimado=Porte.M)
    assert proposta.dados["preco_centavos"] == 8000
    assert any("tosadora confirma" in a for a in proposta.dados["avisos"])


def test_vespera_de_natal_so_ate_meio_dia(servico):
    # P8: em 24/12 a clínica funciona só até as 12h.
    perto_do_natal = datetime(2026, 12, 21, 9, 0)
    natal = date(2026, 12, 24)
    opcoes = servico.buscar_horarios(ctx("t_mariana", agora=perto_do_natal), "consulta_clinica", natal, natal,
                                     animal_id="a_thor")
    assert opcoes and all(o.fim.hour < 12 or (o.fim.hour, o.fim.minute) == (12, 0) for o in opcoes)
    assert servico.clinica_aberta(datetime(2026, 12, 24, 10, 0))
    assert not servico.clinica_aberta(datetime(2026, 12, 24, 13, 0))


def test_carnaval_fecha_e_quarta_de_cinzas_abre_ao_meio_dia(servico):
    # P8: Carnaval 2027 é 8 e 9 de fevereiro; quarta de Cinzas (10/02) abre às 12h.
    janeiro = datetime(2027, 1, 20, 9, 0)
    opcoes = servico.buscar_horarios(ctx("t_mariana", agora=janeiro), "consulta_clinica", date(2027, 2, 8),
                                     date(2027, 2, 10), animal_id="a_thor")
    assert {o.inicio.date() for o in opcoes} == {date(2027, 2, 10)}
    assert min(o.inicio for o in opcoes).hour == 12


# Confirmação (ADR 0002) --------------------------------------------------------


def test_confirmacao_so_no_turno_seguinte_e_sem_duplicar(servico):
    proposta = servico.propor_agendamento(ctx("t_mariana", turno=1), "banho", datetime(2026, 10, 8, 8),
                                          animal_id="a_thor")
    with erro(Codigo.CONFIRMACAO_PREMATURA):
        servico.confirmar(ctx("t_mariana", turno=1), proposta.id)

    agendamento = servico.confirmar(ctx("t_mariana", turno=2), proposta.id)
    assert agendamento.status == StatusAgendamento.CONFIRMADO
    assert agendamento.preco_centavos == 10000
    assert servico.confirmar(ctx("t_mariana", turno=3), proposta.id).id == agendamento.id


def test_proposta_expirada_ou_de_outra_conversa_nao_vale(servico):
    proposta = servico.propor_agendamento(ctx("t_mariana"), "banho", datetime(2026, 10, 8, 8), animal_id="a_thor")
    with erro(Codigo.PROPOSTA_INVALIDA):
        servico.confirmar(ctx("t_mariana", turno=2, agora=AGORA + timedelta(minutes=11)), proposta.id)
    with erro(Codigo.PROPOSTA_INVALIDA):
        servico.confirmar(ctx("t_mariana", turno=2, conversa="c2"), proposta.id)


def test_numero_novo_vira_pre_agendamento_para_a_joyce(servico, agenda, conn):
    # C10: filhote novo, número sem cadastro.
    filhote = AnimalNovo(Especie.CAO, 3.0)
    with erro(Codigo.ARGUMENTO_INVALIDO):
        servico.propor_agendamento(ctx(None), "vacina_v10", datetime(2026, 10, 6, 16), animal_novo=filhote)

    proposta = servico.propor_agendamento(ctx(None), "vacina_v10", datetime(2026, 10, 6, 16),
                                          animal_novo=filhote, nome_tutor="Larissa Campos")
    assert proposta.tipo == TipoProposta.PRE_AGENDAMENTO
    assert proposta.dados["preco_centavos"] == 16000 + 9500

    agendamento = servico.confirmar(ctx(None, turno=2), proposta.id)
    assert agendamento.status == StatusAgendamento.PENDENTE_JOYCE
    assert agenda.buscar_tutor_por_telefone(NUMERO_DESCONHECIDO).provisorio
    assert conn.execute("SELECT motivo FROM passagem").fetchone()["motivo"] == "cadastro_novo"


def test_remarcacao_move_o_horario(servico, agenda):
    # C5: Patrícia passa o banho da Luna para sexta.
    proposta = servico.propor_remarcacao(ctx("t_patricia"), "ag_luna", datetime(2026, 10, 9, 9))
    servico.confirmar(ctx("t_patricia", turno=2), proposta.id)
    assert agenda.obter_agendamento("ag_luna").inicio == datetime(2026, 10, 9, 9)
