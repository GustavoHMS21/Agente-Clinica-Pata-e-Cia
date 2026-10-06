from datetime import datetime, time

from patas.dominio.modelos import Agendamento, Porte, StatusAgendamento
from patas.dominio.telefone import normalizar_telefone
from patas.repositorio.sqlite import novo_id

QUARTA_10H = datetime(2026, 10, 7, 10, 0)
QUARTA_10H30 = datetime(2026, 10, 7, 10, 30)
QUARTA_11H = datetime(2026, 10, 7, 11, 0)


def _consulta(profissional_id: str, inicio: datetime, fim: datetime, proposta_id: str | None = None) -> Agendamento:
    return Agendamento(
        id=novo_id("ag"),
        animal_id="a_thor",
        servico_id="consulta_clinica",
        profissional_id=profissional_id,
        inicio=inicio,
        fim=fim,
        status=StatusAgendamento.CONFIRMADO,
        preco_centavos=16000,
        criado_em=datetime(2026, 10, 6, 9, 0),
        proposta_id=proposta_id,
    )


def test_telefone_em_qualquer_formato_acha_o_mesmo_tutor(agenda):
    for bruto in ["(11) 90000-1102", "+55 11 90000-1102", "5511900001102"]:
        tutor = agenda.buscar_tutor_por_telefone(normalizar_telefone(bruto))
        assert tutor is not None and tutor.nome == "Rodrigo Teles"
    assert agenda.buscar_tutor_por_telefone(normalizar_telefone("(11) 90000-1115")) is None


def test_tabelas_de_regra_viram_servico_completo(agenda):
    banho = agenda.obter_servico("banho_tosa_completa")
    gg = next(p for p in banho.precos_por_porte if p.porte == Porte.GG)
    assert (gg.preco_centavos, gg.duracao_min) == (19000, 180)  # 2h30 + 30 min da tosa completa

    gato = agenda.obter_servico("banho_gato")
    assert [(j.dia_semana, j.inicio, j.fim) for j in gato.janelas] == [
        (1, time(8), time(12)),
        (3, time(8), time(12)),
    ]
    assert agenda.obter_servico("consulta_dermato").profissionais == ("vet_paula",)


def test_nao_marca_em_cima_de_outro_horario_do_mesmo_profissional(agenda):
    # Seed: Nina com a Dra. Paula na quarta 10h-10h30.
    assert agenda.inserir_agendamento_se_livre(_consulta("vet_paula", QUARTA_10H, QUARTA_10H30)) is None
    assert agenda.inserir_agendamento_se_livre(_consulta("vet_beatriz", QUARTA_10H, QUARTA_10H30)) is not None
    # Encostar no fim do outro horário não é conflito.
    assert agenda.inserir_agendamento_se_livre(_consulta("vet_paula", QUARTA_10H30, QUARTA_11H)) is not None


def test_confirmar_a_mesma_proposta_duas_vezes_nao_duplica(agenda, conn):
    primeiro = agenda.inserir_agendamento_se_livre(_consulta("vet_camila", QUARTA_10H, QUARTA_10H30, "pr_1"))
    segundo = agenda.inserir_agendamento_se_livre(_consulta("vet_camila", QUARTA_10H, QUARTA_10H30, "pr_1"))
    assert segundo.id == primeiro.id
    total = conn.execute("SELECT COUNT(*) FROM agendamento WHERE proposta_id = 'pr_1'").fetchone()[0]
    assert total == 1


def test_cancelar_libera_o_horario(agenda):
    agenda.cancelar_agendamento("ag_nina")
    assert agenda.inserir_agendamento_se_livre(_consulta("vet_paula", QUARTA_10H, QUARTA_10H30)) is not None


def test_remarcar_ignora_o_proprio_horario_mas_nao_o_dos_outros(agenda):
    # Empurrar a Nina 15 min sobrepõe só ela mesma: pode.
    assert agenda.mover_agendamento_se_livre("ag_nina", "vet_paula", datetime(2026, 10, 7, 10, 15), datetime(2026, 10, 7, 10, 45))
    # Mel está com a Dra. Beatriz na quarta 14h30: Nina não pode ir para lá.
    assert not agenda.mover_agendamento_se_livre("ag_nina", "vet_beatriz", datetime(2026, 10, 7, 14, 30), datetime(2026, 10, 7, 15, 0))
