"""Canal WhatsApp: webhook no formato real da Meta, assinado com uma chave de teste. Sem rede e sem LLM real."""

import hashlib
import hmac
import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from patas.agente.llm import RespostaLLM
from patas.dominio.telefone import normalizar_telefone
from patas.repositorio.sqlite import conectar
from patas.web import app as web
from patas.web import whatsapp
from patas.web.whatsapp import AVISO_LGPD, ConfigWhatsApp, assinatura_valida, extrair_mensagens

AGORA = datetime(2026, 10, 6, 9, 0)  # terça, clínica aberta
CONFIG = ConfigWhatsApp("v23.0", "1234567890", "token-de-teste", "segredo-de-teste", "verify-de-teste")
TUTOR = "5511900001101"  # a Ana do seed


class LLMContador:
    def __init__(self):
        self.chamadas = 0

    def criar(self, system, tools, messages):
        self.chamadas += 1
        return RespostaLLM("end_turn", [{"type": "text", "text": f"Resposta {self.chamadas}"}])


def payload(*mensagens, phone_number_id=CONFIG.phone_number_id, statuses=()):
    valor = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": phone_number_id},
             "messages": list(mensagens), "statuses": list(statuses)}
    return {"object": "whatsapp_business_account", "entry": [{"id": "waba", "changes": [{"field": "messages", "value": valor}]}]}


def texto(wamid, corpo, de=TUTOR):
    return {"from": de, "id": wamid, "timestamp": "1791280800", "type": "text", "text": {"body": corpo}}


def assinar(corpo: bytes, segredo=CONFIG.app_secret) -> dict:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest(),
            "Content-Type": "application/json"}


@pytest.fixture
def canal(banco, monkeypatch):
    """App com o canal ligado; envio e agendamento trocados por versões que só anotam."""
    monkeypatch.setattr(web, "agora_local", lambda: AGORA)
    monkeypatch.setattr(whatsapp, "agora_local", lambda: AGORA)
    llm = LLMContador()
    app = web.montar_app(llm, banco, "joyce", "senha-de-teste-123", CONFIG)
    despachante = app.state.whatsapp
    enviadas, agendadas = [], []
    despachante.enviar = lambda telefone, msg: enviadas.append((telefone, msg)) or True
    despachante.agendar = agendadas.append
    return TestClient(app), despachante, llm, enviadas, agendadas


def postar(cliente, dados, segredo=CONFIG.app_secret):
    corpo = json.dumps(dados).encode()
    return cliente.post("/webhook/whatsapp", content=corpo, headers=assinar(corpo, segredo))


def mensagens_do_tutor(banco):
    conn = conectar(banco)
    try:
        return [json.loads(r[0])[0]["text"] for r in conn.execute(
            "SELECT m.conteudo FROM mensagem m JOIN conversa c ON c.id = m.conversa_id"
            " WHERE c.telefone = ? AND m.papel = 'tutor' ORDER BY m.id", (TUTOR,))]
    finally:
        conn.close()


# Peças puras -----------------------------------------------------------------

def test_celular_sem_o_nove_ganha_o_nove_e_fixo_fica_igual():
    assert normalizar_telefone("551187654321") == "5511987654321"  # como o WhatsApp às vezes entrega
    assert normalizar_telefone("551133334444") == "551133334444"  # fixo: começa com 2 a 5
    assert normalizar_telefone("(11) 90000-1101") == TUTOR


def test_assinatura():
    corpo = b'{"a": 1}'
    assert assinatura_valida(corpo, assinar(corpo)["X-Hub-Signature-256"], CONFIG.app_secret)
    assert not assinatura_valida(corpo, assinar(corpo, "outro-segredo")["X-Hub-Signature-256"], CONFIG.app_secret)
    assert not assinatura_valida(b'{"a": 2}', assinar(corpo)["X-Hub-Signature-256"], CONFIG.app_secret)
    assert not assinatura_valida(corpo, None, CONFIG.app_secret)


def test_extrai_texto_midia_e_ignora_o_resto():
    dados = payload(
        texto("w1", "  Oi  "),
        {"from": TUTOR, "id": "w2", "type": "audio", "audio": {"id": "m"}},
        {"from": TUTOR, "id": "w3", "type": "image", "image": {"id": "m", "caption": "olha a pata dele"}},
        {"from": TUTOR, "id": "w4", "type": "interactive", "interactive": {"button_reply": {"title": "Sim"}}},
        {"from": TUTOR, "id": "w5", "type": "reaction", "reaction": {"emoji": "👍"}},
        statuses=[{"id": "w0", "status": "read"}],
    )
    assert [(r.wamid, r.texto) for r in extrair_mensagens(dados, CONFIG.phone_number_id)] == [
        ("w1", "Oi"), ("w2", "[áudio]"), ("w3", "[imagem] olha a pata dele"), ("w4", "Sim"),
    ]
    assert extrair_mensagens(payload(texto("w1", "Oi"), phone_number_id="999"), CONFIG.phone_number_id) == []


def test_configuracao(monkeypatch):
    for nome in whatsapp.VARIAVEIS:
        monkeypatch.delenv(nome, raising=False)
    assert ConfigWhatsApp.do_ambiente() is None  # nada preenchido: canal desligado
    monkeypatch.setenv("WHATSAPP_TOKEN", "abc")
    with pytest.raises(RuntimeError, match="pela metade"):
        ConfigWhatsApp.do_ambiente()
    assert "token-de-teste" not in repr(CONFIG) and "segredo-de-teste" not in repr(CONFIG)


# Webhook ---------------------------------------------------------------------

def test_verificacao_do_webhook(canal):
    cliente = canal[0]
    params = {"hub.mode": "subscribe", "hub.verify_token": CONFIG.verify_token, "hub.challenge": "4242"}
    assert cliente.get("/webhook/whatsapp", params=params).text == "4242"
    assert cliente.get("/webhook/whatsapp", params={**params, "hub.verify_token": "errado"}).status_code == 403


def test_sem_assinatura_valida_nada_e_gravado(canal, banco):
    cliente, _, _, _, agendadas = canal
    assert postar(cliente, payload(texto("w1", "Oi")), segredo="falsificado").status_code == 403
    assert mensagens_do_tutor(banco) == [] and agendadas == []


def test_rajada_vira_um_turno_com_aviso_lgpd_so_no_primeiro(canal, banco):
    cliente, despachante, llm, enviadas, agendadas = canal
    assert postar(cliente, payload(texto("w1", "Oi"), texto("w2", "quanto tá o banho?"))).status_code == 200
    assert postar(cliente, payload(texto("w1", "Oi"))).status_code == 200  # reenvio da Meta
    assert mensagens_do_tutor(banco) == ["Oi", "quanto tá o banho?"]
    conversa_id = agendadas[0]

    despachante.processar(conversa_id)  # o que o temporizador faria depois do silêncio
    assert llm.chamadas == 1  # as duas mensagens num turno só
    assert enviadas == [(TUTOR, AVISO_LGPD), (TUTOR, "Resposta 1")]

    postar(cliente, payload(texto("w3", "e a tosa?")))
    despachante.processar(conversa_id)
    assert enviadas[-1] == (TUTOR, "Resposta 2") and len(enviadas) == 3  # sem repetir o aviso


def test_celular_sem_o_nove_recebe_a_resposta_no_numero_com_nove(canal):
    cliente, despachante, _, enviadas, agendadas = canal
    postar(cliente, payload(texto("w1", "Oi", de="551187654321")))  # como o WhatsApp às vezes entrega
    despachante.processar(agendadas[0])
    assert {telefone for telefone, _ in enviadas} == {"5511987654321"}


def test_retoma_mensagem_que_ficou_sem_resposta(canal, banco):
    cliente, despachante, _, _, agendadas = canal
    postar(cliente, payload(texto("w1", "Oi")))  # gravada, mas o servidor "caiu" antes de responder
    agendadas.clear()
    assert despachante.retomar_pendentes() == 1 and len(agendadas) == 1
