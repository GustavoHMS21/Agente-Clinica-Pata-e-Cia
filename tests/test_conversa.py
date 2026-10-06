"""Estado da conversa (ADR 0004). Hoje é terça 06/10/2026."""

from datetime import datetime, timedelta

from patas.dominio.conversa import LIMITE_MENSAGEM, TURNOS_NO_HISTORICO
from patas.dominio.modelos import Papel

MARIANA = "(11) 90000-1101"
DESCONHECIDO = "+55 11 90000-1115"
T0 = datetime(2026, 10, 6, 9, 0)


def texto(t: str) -> list[dict]:
    return [{"type": "text", "text": t}]


def test_mesma_conversa_ate_12h_sem_mensagem(conversas):
    primeira = conversas.receber(MARIANA, "Bom dia! Tem horário pra banho hoje?", T0)
    assert conversas.receber(MARIANA, "E aí?", T0 + timedelta(hours=11)).id == primeira.id  # C8
    assert conversas.receber(MARIANA, "Oi de novo", T0 + timedelta(hours=23, minutes=1)).id != primeira.id


def test_rajada_de_mensagens_vira_um_turno_so(conversas):
    # C15: "oi", "quanto ta o banho", "?"
    conversa = conversas.receber(DESCONHECIDO, "oi", T0)
    conversas.receber(DESCONHECIDO, "quanto ta o banho", T0)
    conversas.receber(DESCONHECIDO, "?", T0)

    turno = conversas.abrir_turno(conversa.id, T0)
    assert turno.contexto.turno == 1
    assert turno.texto_do_tutor == "oi\nquanto ta o banho\n?"
    assert turno.historico == [{"role": "user", "content": texto("oi") + texto("quanto ta o banho") + texto("?")}]
    assert conversas.abrir_turno(conversa.id, T0) is None  # nada novo: não roda o agente


def test_historico_alterna_papeis_e_guarda_ferramentas(conversas):
    conversa = conversas.receber(MARIANA, "Quanto é o banho do Thor?", T0)
    turno = conversas.abrir_turno(conversa.id, T0)
    ctx = turno.contexto
    chamada = {"type": "tool_use", "id": "tu_1", "name": "consultar_servicos", "input": {"categoria": "banho_tosa"}}
    conversas.registrar(ctx, Papel.AGENTE, [chamada])
    conversas.registrar(ctx, Papel.FERRAMENTA, [{"type": "tool_result", "tool_use_id": "tu_1", "content": "{}"}])
    conversas.registrar(ctx, Papel.AGENTE, texto("Para o Thor (porte G), R$ 100,00."))

    conversas.receber(MARIANA, "Pode ser amanhã?", T0 + timedelta(minutes=2))
    seguinte = conversas.abrir_turno(conversa.id, T0 + timedelta(minutes=2))
    assert [m["role"] for m in seguinte.historico] == ["user", "assistant", "user", "assistant", "user"]
    assert seguinte.historico[-1]["content"] == texto("Pode ser amanhã?")


def test_historico_leva_so_os_ultimos_turnos(conversas):
    conversa = conversas.receber(MARIANA, "mensagem 1", T0)
    for n in range(1, TURNOS_NO_HISTORICO + 3):
        turno = conversas.abrir_turno(conversa.id, T0)
        conversas.registrar(turno.contexto, Papel.AGENTE, texto(f"resposta {n}"))
        conversas.receber(MARIANA, f"mensagem {n + 1}", T0)

    turno = conversas.abrir_turno(conversa.id, T0)
    assert len(turno.historico) == 2 * TURNOS_NO_HISTORICO - 1
    assert turno.historico[0]["role"] == "user"  # o corte cai sempre no início de um turno


def test_tutor_e_identificado_de_novo_a_cada_turno(conversas, agenda):
    conversa = conversas.receber(DESCONHECIDO, "oi", T0)
    assert conversas.abrir_turno(conversa.id, T0).contexto.tutor_id is None

    tutor = agenda.criar_tutor_provisorio("Cliente novo", "5511900001115")  # pré-agendamento no meio
    conversas.receber(DESCONHECIDO, "e agora?", T0)
    assert conversas.abrir_turno(conversa.id, T0).contexto.tutor_id == tutor.id


def test_estado_traz_a_proposta_aguardando_resposta(conversas, servico):
    conversa = conversas.receber(MARIANA, "Banho do Thor quinta 8h", T0)
    turno = conversas.abrir_turno(conversa.id, T0)
    proposta = servico.propor_agendamento(turno.contexto, "banho", datetime(2026, 10, 8, 8), animal_id="a_thor")

    conversas.receber(MARIANA, "Pode confirmar", T0 + timedelta(minutes=1))
    seguinte = conversas.abrir_turno(conversa.id, T0 + timedelta(minutes=1))
    assert seguinte.estado.proposta_pendente.id == proposta.id

    servico.confirmar(seguinte.contexto, proposta.id)
    conversas.receber(MARIANA, "Obrigada!", T0 + timedelta(minutes=2))
    assert conversas.abrir_turno(conversa.id, T0 + timedelta(minutes=2)).estado.proposta_pendente is None


def test_passagem_aberta_sobrevive_a_troca_de_conversa(conversas, servico):
    # C8: pergunta do exame de manhã, "E aí?" depois que a conversa já virou outra.
    conversa = conversas.receber("(11) 90000-1108", "Já saiu o exame do Pipoca?", T0)
    turno = conversas.abrir_turno(conversa.id, T0)
    servico.passar_para_joyce(turno.contexto, "resultado_exame", False, "Débora pergunta pelo exame do Pipoca.")

    amanha = T0 + timedelta(days=1)
    nova = conversas.receber("(11) 90000-1108", "E aí?", amanha)
    assert nova.id != conversa.id
    assert [p.motivo for p in conversas.abrir_turno(nova.id, amanha).estado.passagens_abertas] == ["resultado_exame"]


def test_mensagem_gigante_e_cortada(conversas):
    conversa = conversas.receber(MARIANA, "a" * (LIMITE_MENSAGEM + 500), T0)
    turno = conversas.abrir_turno(conversa.id, T0)
    assert len(turno.texto_do_tutor) < LIMITE_MENSAGEM + 30
    assert turno.texto_do_tutor.endswith("[mensagem cortada]")
