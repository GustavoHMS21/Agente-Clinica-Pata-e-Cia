"""Guardrails de entrada e saída (bloco 7). Os casos vêm das 15 conversas reais."""

from datetime import datetime

import pytest

from patas.agente import guardrails
from patas.agente.llm import RespostaLLM
from patas.agente.loop import Agente

TERCA_9H = datetime(2026, 10, 6, 9, 0)  # aberta
TERCA_22H = datetime(2026, 10, 6, 22, 0)  # fechada, como a C3 (21h47)


@pytest.mark.parametrize("texto", [
    "Boa noite, meu cachorro comeu um pedaço grande de chocolate agora, o que eu faço??",  # C3
    "Oi, meu cachorro está vomitando desde ontem e não quer comer. Tem horário hoje?",  # C13
    "ela ta com SANGUE no xixi",
    "acho que ele engoliu uma meia",
    "tá com falta de ar",
    "meu gato tá forçando pra fazer xixi e não sai nada",  # 7: obstrução urinária
    "o dogue alemão tá com a barriga inchada e dura",  # 8: torção gástrica
    "foi picado por escorpião no quintal",  # 9
    "voltou do passeio muito ofegante, acho que foi insolação",  # 10
    "a cachorra entrou em trabalho de parto faz uma hora e nada",  # 11
    "brigou com outro cachorro e tá com o olho machucado",  # 6 e 12
])
def test_sinais_de_alerta(texto):
    assert guardrails.detectar_alerta(texto)


@pytest.mark.parametrize("texto", [
    "Oi, a Dra Paula atende sábado? Queria levar a Kiara pra ver a alergia dela, ela se coça muito",  # C9
    "você quer consulta para o Bob que está mancando da pata de trás",  # C7
    "Quanto custa castração de gata?",  # C4
    "quanto ta o banho",  # C15
    "ele tá com muita queda de pelo",  # queixa comum, não é "queda de altura"
    "tem picada de pulga na barriga dela",  # pulga não é peçonhento
])
def test_queixa_comum_e_pergunta_nao_sao_alerta(texto):
    assert not guardrails.detectar_alerta(texto)


def test_resposta_perde_ids_internos_e_nomes_de_ferramentas():
    texto, problemas = guardrails.limpar_resposta(
        "Confirmado (pr_6c7eeef9a147)! Usei consultar_cadastro e achei o a_thor."
    )
    assert "pr_" not in texto and "a_thor" not in texto and "consultar_cadastro" not in texto
    assert set(problemas) == {"id_interno", "nome_de_ferramenta"}


@pytest.mark.parametrize("texto", [
    "Pode dar 1 comprimido de dipirona para ele",
    "Dê 5 ml de soro caseiro a cada hora",
    "Um chazinho de camomila ajuda a acalmar",
])
def test_detecta_resposta_com_orientacao_de_saude(texto):
    assert guardrails.parece_orientacao_de_saude(texto)


def test_resposta_segura_sobre_saude_passa():
    texto = "Não posso indicar nenhum remédio. Já avisei a Joyce como urgente; traga o Thor à clínica agora."
    assert not guardrails.parece_orientacao_de_saude(texto)


# No loop ------------------------------------------------------------------------


class LLMRoteiro:
    def __init__(self, respostas):
        self.respostas, self.chamadas = list(respostas), []

    def criar(self, system, tools, messages):
        self.chamadas.append(system)
        return self.respostas.pop(0)


def texto(t: str) -> RespostaLLM:
    return RespostaLLM("end_turn", [{"type": "text", "text": t}])


def falar(conversas, agente, mensagem, quando, telefone="(11) 90000-1101"):
    conversa = conversas.receber(telefone, mensagem, quando)
    return agente.responder(conversa.id, quando)


def passagens(conn):
    return [(r["motivo"], bool(r["urgente"])) for r in conn.execute("SELECT motivo, urgente FROM passagem")]


def test_alerta_fora_do_horario_tem_resposta_fixa_sem_chamar_o_modelo(servico, conversas, conn):
    llm = LLMRoteiro([])
    resposta = falar(conversas, Agente(llm, servico, conversas), "ele comeu chocolate, o que eu faço?", TERCA_22H)
    assert resposta == guardrails.RESPOSTA_URGENCIA_FECHADO
    assert llm.chamadas == []
    assert passagens(conn) == [("urgencia", True)]


def test_alerta_no_horario_abre_passagem_antes_e_avisa_o_modelo(servico, conversas, conn):
    llm = LLMRoteiro([texto("A equipe foi avisada, traga o Thor agora."), texto("Combinado.")])
    agente = Agente(llm, servico, conversas)
    falar(conversas, agente, "o Thor está vomitando desde ontem", TERCA_9H)
    assert passagens(conn) == [("urgencia", True)]
    assert "ALERTA" in llm.chamadas[0][1]["text"]

    falar(conversas, agente, "ainda vomitando, to indo", TERCA_9H)  # segundo alerta na mesma conversa
    assert passagens(conn) == [("urgencia", True)]  # não duplica


def test_resposta_com_remedio_e_trocada_e_vai_para_a_joyce(servico, conversas, conn):
    llm = LLMRoteiro([texto("Pode dar meio comprimido de dipirona até chegar.")])
    resposta = falar(conversas, Agente(llm, servico, conversas), "ele está meio quietinho", TERCA_9H)
    assert resposta == guardrails.RESPOSTA_SAUDE
    assert passagens(conn) == [("saude", False)]
    salvo = conn.execute("SELECT conteudo FROM mensagem WHERE papel = 'agente'").fetchone()["conteudo"]
    assert "dipirona" not in salvo  # o histórico guarda o que o tutor recebeu
