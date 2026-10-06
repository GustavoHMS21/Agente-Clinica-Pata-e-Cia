from datetime import date, datetime, time, timedelta

import pytest

from patas.dominio import regras
from patas.dominio.modelos import Especie, Janela, Opcao, Porte, Vacina

QUINTA = date(2026, 10, 8)


@pytest.mark.parametrize(
    ("peso", "porte"),
    [(10, Porte.P), (10.1, Porte.M), (20, Porte.M), (20.1, Porte.G), (35, Porte.G), (35.1, Porte.GG)],
)
def test_porte_pelo_peso_nos_limites(peso, porte):
    # P2: "até" inclui o número.
    assert regras.porte_pelo_peso(peso) == porte


def test_vacina_equivalente_vale_e_validade_conta_da_aplicacao():
    # P3: V8 vale como V10, V4 como V5; toda vacina vale 1 ano a partir da aplicação.
    cao = [Vacina("a", "v8", date(2026, 3, 1)), Vacina("a", "antirrabica", date(2026, 3, 1))]
    assert regras.vacinas_pendentes(Especie.CAO, cao, date(2027, 3, 1)) == []
    assert regras.vacinas_pendentes(Especie.CAO, cao, date(2027, 3, 2)) == ["antirrabica", "v10"]
    gato = [Vacina("g", "v4", date(2026, 5, 10)), Vacina("g", "antirrabica", date(2026, 5, 10))]
    assert regras.vacinas_pendentes(Especie.GATO, gato, date(2026, 10, 1)) == []
    assert regras.vence_em(date(2028, 2, 29)) == date(2029, 2, 28)


def test_pascoa_e_feriados_moveis():
    from patas.seed import feriados_do_ano, pascoa
    assert pascoa(2026) == date(2026, 4, 5) and pascoa(2027) == date(2027, 3, 28)
    dias = {d: (nome, abre, fecha) for d, nome, abre, fecha in feriados_do_ano(2026)}
    assert dias["2026-06-04"][0] == "Corpus Christi"
    assert dias["2026-02-18"][1] == "12:00"  # quarta de Cinzas abre ao meio-dia
    assert dias["2026-12-24"][2] == "12:00"  # véspera de Natal fecha ao meio-dia
    assert dias["2026-07-09"][0].startswith("Revolução Constitucionalista")


def test_vacina_conta_na_data_do_banho_nao_na_de_hoje():
    vacinas = [
        Vacina("a", "v10", date(2025, 10, 7)),
        Vacina("a", "antirrabica", date(2026, 1, 1)),
    ]
    assert regras.vacinas_pendentes(Especie.CAO, vacinas, date(2026, 10, 7)) == []
    assert regras.vacinas_pendentes(Especie.CAO, vacinas, date(2026, 10, 8)) == ["v10"]


def test_faixa_e_a_intersecao_do_expediente_com_a_janela_do_servico():
    expediente = [Janela(d, time(8), time(19)) for d in range(5)]
    dermato = [Janela(3, time(13), time(19))]
    assert regras.faixas_do_dia(QUINTA, expediente, dermato) == [
        (datetime(2026, 10, 8, 13), datetime(2026, 10, 8, 19))
    ]
    assert regras.faixas_do_dia(QUINTA - timedelta(days=1), expediente, dermato) == []


def test_inicios_livres_pulam_a_ocupacao_e_cabem_na_faixa():
    faixa = [(datetime(2026, 10, 8, 8), datetime(2026, 10, 8, 10))]
    ocupado = [(datetime(2026, 10, 8, 8, 30), datetime(2026, 10, 8, 9))]
    livres = regras.inicios_livres(faixa, timedelta(hours=1), ocupado, datetime(2026, 10, 8, 8))
    assert livres == [datetime(2026, 10, 8, 9)]


def test_espalhar_da_uma_opcao_por_turno():
    horarios = [datetime(2026, 10, 8, h, m) for h in (8, 9, 14, 15) for m in (0, 30)]
    opcoes = [Opcao(h, h + timedelta(minutes=30), "vet") for h in horarios]
    assert [o.inicio.hour for o in regras.espalhar(opcoes, 5)] == [8, 14]
