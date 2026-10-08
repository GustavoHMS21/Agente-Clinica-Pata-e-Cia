"""Google Agenda do banho e tosa com um calendário falso: sem rede e sem credenciais."""

from datetime import datetime

import pytest

from patas.dominio.agenda import Contexto, ServicoAgenda
from patas.dominio.erros import Codigo, ErroRegra
from patas.repositorio.google_agenda import (
    MARCA,
    AgendaComGoogle,
    CalendarioGoogle,
    ErroGoogleAgenda,
    Evento,
    id_do_evento,
    ler_evento,
)
from patas.repositorio.sqlite import AgendaSQLite, AtendimentoSQLite
AGORA = datetime(2026, 10, 6, 9, 0)  # terça, como em test_agenda.py
QUINTA_8H, QUINTA_10H = datetime(2026, 10, 8, 8), datetime(2026, 10, 8, 10)


def ctx(tutor_id: str, turno: int = 1) -> Contexto:
    return Contexto(conversa_id="c1", telefone="5511900001110", tutor_id=tutor_id, turno=turno, agora=AGORA)


def erro(codigo: Codigo):
    return pytest.raises(ErroRegra, match=codigo.value)


class CalendarioFalso:
    def __init__(self):
        self.externos: list[Evento] = []  # o que a equipe lançou direto no Google
        self.gravados: dict[str, dict] = {}  # o que o agente gravou
        self.fora_do_ar = False

    def eventos(self, de, ate):
        self._checar()
        do_agente = [Evento(i, datetime.fromisoformat(c["start"]["dateTime"]),
                            datetime.fromisoformat(c["end"]["dateTime"]), True) for i, c in self.gravados.items()]
        return [e for e in self.externos + do_agente if e.inicio < ate and e.fim > de]

    def gravar(self, evento_id, corpo):
        self._checar()
        self.gravados[evento_id] = corpo

    def apagar(self, evento_id):
        self._checar()
        self.gravados.pop(evento_id, None)

    def lancar(self, inicio, fim, nome="externo"):
        self.externos.append(Evento(f"{nome}{len(self.externos)}", inicio, fim, False))

    def _checar(self):
        if self.fora_do_ar:
            raise ErroGoogleAgenda("fora do ar")


@pytest.fixture
def calendario():
    return CalendarioFalso()


@pytest.fixture
def agenda_google(conn, calendario):
    return AgendaComGoogle(AgendaSQLite(conn), calendario)


@pytest.fixture
def servico_google(conn, agenda_google):
    return ServicoAgenda(agenda_google, AtendimentoSQLite(conn))


def propor_e_confirmar_banho_do_thor(servico):
    proposta = servico.propor_agendamento(ctx("t_mariana"), "banho", QUINTA_8H, animal_id="a_thor")
    return servico.confirmar(ctx("t_mariana", turno=2), proposta.id)


# Leitura ---------------------------------------------------------------------

def test_cada_evento_da_equipe_ocupa_uma_tosadora(servico_google, calendario):
    calendario.lancar(QUINTA_8H, QUINTA_10H)
    assert propor_e_confirmar_banho_do_thor(servico_google).inicio == QUINTA_8H  # a outra tosadora atende

    calendario.lancar(QUINTA_8H, QUINTA_10H)  # agora as duas estão ocupadas pelo Google + o Thor
    with erro(Codigo.HORARIO_INDISPONIVEL):
        servico_google.propor_agendamento(ctx("t_mariana"), "banho", QUINTA_8H, animal_id="a_thor")


def test_janela_estreita_e_dia_inteiro_dao_a_mesma_distribuicao(agenda_google, calendario):
    # A busca olha o dia; a confirmação olha só o horário. As duas precisam concordar sobre quem está livre.
    calendario.lancar(datetime(2026, 10, 22, 8), datetime(2026, 10, 22, 10))  # vai para tosa_a
    calendario.lancar(datetime(2026, 10, 22, 9), datetime(2026, 10, 22, 11))  # tosa_a ocupada: vai para tosa_b
    janela = (datetime(2026, 10, 22, 10), datetime(2026, 10, 22, 11))
    assert agenda_google.listar_ocupacoes(["tosa_a"], *janela) == []
    assert len(agenda_google.listar_ocupacoes(["tosa_b"], *janela)) == 1


def test_consulta_de_veterinaria_nao_chama_o_google(agenda_google, calendario):
    calendario.fora_do_ar = True
    agenda_google.listar_ocupacoes(["vet_camila"], QUINTA_8H, QUINTA_10H)  # não levanta erro


def test_google_fora_do_ar_nao_oferece_horario_as_cegas(servico_google, calendario):
    calendario.fora_do_ar = True
    with pytest.raises(ErroGoogleAgenda):  # vira ERRO_INTERNO na ferramenta: o agente passa para a Joyce
        servico_google.buscar_horarios(ctx("t_mariana"), "banho", QUINTA_8H.date(), animal_id="a_thor")


# Escrita ---------------------------------------------------------------------

def test_agendamento_vira_evento_que_nao_conta_duas_vezes(servico_google, agenda_google, calendario):
    agendamento = propor_e_confirmar_banho_do_thor(servico_google)
    corpo = calendario.gravados[id_do_evento(agendamento.id)]
    assert corpo["summary"] == "Banho: Thor" and corpo["extendedProperties"]["private"][MARCA] == agendamento.id
    assert corpo["start"]["dateTime"] == "2026-10-08T08:00:00"
    ocupacoes = agenda_google.listar_ocupacoes([agendamento.profissional_id], QUINTA_8H, QUINTA_10H)
    assert [o.id for o in ocupacoes] == [agendamento.id]  # o evento do agente não vira um bloqueio a mais


def test_google_falhando_na_confirmacao_nao_grava_no_banco(servico_google, calendario, conn):
    proposta = servico_google.propor_agendamento(ctx("t_mariana"), "banho", QUINTA_8H, animal_id="a_thor")
    calendario.fora_do_ar = True
    with pytest.raises(ErroGoogleAgenda):
        servico_google.confirmar(ctx("t_mariana", turno=2), proposta.id)
    assert conn.execute("SELECT 1 FROM agendamento WHERE proposta_id = ?", (proposta.id,)).fetchone() is None


def test_remarcar_e_cancelar_acompanham_no_google(servico_google, calendario):
    # Banho da Luna (do seed, anterior à integração): a remarcação já cria o evento no horário novo.
    proposta = servico_google.propor_remarcacao(ctx("t_patricia"), "ag_luna", datetime(2026, 10, 9, 9))
    servico_google.confirmar(ctx("t_patricia", turno=2), proposta.id)
    assert calendario.gravados[id_do_evento("ag_luna")]["start"]["dateTime"] == "2026-10-09T09:00:00"

    proposta = servico_google.propor_cancelamento(ctx("t_patricia", turno=3), "ag_luna")
    servico_google.confirmar(ctx("t_patricia", turno=4), proposta.id)
    assert id_do_evento("ag_luna") not in calendario.gravados


# Formato do Google -----------------------------------------------------------

def test_leitura_dos_eventos_do_google():
    com_fuso = ler_evento({"id": "a", "start": {"dateTime": "2026-10-08T11:00:00Z"},
                           "end": {"dateTime": "2026-10-08T09:30:00-03:00"}})
    assert (com_fuso.inicio, com_fuso.fim, com_fuso.do_agente) == (QUINTA_8H, datetime(2026, 10, 8, 9, 30), False)
    dia_inteiro = ler_evento({"id": "b", "start": {"date": "2026-10-08"}, "end": {"date": "2026-10-09"}})
    assert (dia_inteiro.inicio, dia_inteiro.fim) == (datetime(2026, 10, 8), datetime(2026, 10, 9))
    assert ler_evento({"id": "c", "transparency": "transparent", "start": {}, "end": {}}) is None
    nosso = ler_evento({"id": "d", "start": {"date": "2026-10-08"}, "end": {"date": "2026-10-09"},
                        "extendedProperties": {"private": {MARCA: "ag_x"}}})
    assert nosso.do_agente
    assert set(id_do_evento("ag_1a2b3c")) <= set("0123456789abcdefghijklmnopqrstuv")


class Resposta:
    def __init__(self, status_code, dados=None):
        self.status_code, self._dados = status_code, dados or {}

    def json(self):
        return self._dados


class SessaoFalsa:
    def __init__(self, *respostas):
        self.respostas, self.pedidos = list(respostas), []

    def request(self, metodo, url, timeout, **kwargs):
        self.pedidos.append((metodo, url, kwargs))
        return self.respostas.pop(0)


def test_cliente_http_do_google():
    sessao = SessaoFalsa(
        Resposta(200, {"items": [{"id": "a", "start": {"date": "2026-10-08"}, "end": {"date": "2026-10-09"}}],
                       "nextPageToken": "p2"}),
        Resposta(200, {"items": [{"id": "b", "start": {"date": "2026-10-08"}, "end": {"date": "2026-10-09"}}]}),
        Resposta(409), Resposta(200),  # gravar: já existe, então substitui
        Resposta(410),  # apagar o que já foi apagado não é erro
        Resposta(500),
    )
    google = CalendarioGoogle("equipe@group.calendar.google.com", sessao)
    assert [e.id for e in google.eventos(QUINTA_8H, QUINTA_10H)] == ["a", "b"]  # seguiu a paginação
    google.gravar("patas1", {"summary": "x"})
    assert [p[0] for p in sessao.pedidos[2:]] == ["POST", "PUT"]
    assert "equipe%40group.calendar.google.com" in sessao.pedidos[0][1]
    google.apagar("patas1")
    with pytest.raises(ErroGoogleAgenda, match="500"):
        google.apagar("patas2")


def test_configuracao(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_AGENDA_ID", raising=False)
    assert CalendarioGoogle.do_ambiente() is None  # sem agenda: banho e tosa só no banco local
    monkeypatch.setenv("GOOGLE_AGENDA_ID", "equipe@group.calendar.google.com")
    monkeypatch.setenv("GOOGLE_CREDENCIAIS", str(tmp_path / "nao-existe.json"))
    with pytest.raises(RuntimeError, match="não encontrado"):
        CalendarioGoogle.do_ambiente()
    monkeypatch.setenv("GOOGLE_CREDENCIAIS", '{"type": "authorized_user"}')
    with pytest.raises(RuntimeError, match="conta de serviço"):
        CalendarioGoogle.do_ambiente()
