"""Servidor web (bloco 8) com LLM falso, banco temporário e relógio fixo."""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from patas.agente.llm import RespostaLLM
from patas.repositorio.sqlite import conectar, criar_schema
from patas.seed import popular
from patas.web import app as web

HOJE = date(2026, 10, 6)  # o mesmo dia do conftest: terça

USUARIO, SENHA = "joyce", "senha-de-teste-123"
LOGIN = (USUARIO, SENHA)
DO_APP = {"X-Requested-With": "patas"}


class LLMFixo:
    def criar(self, system, tools, messages):
        return RespostaLLM("end_turn", [{"type": "text", "text": "Oi! Como posso ajudar?"}])


@pytest.fixture
def banco(tmp_path):
    caminho = tmp_path / "patas.db"
    conn = conectar(caminho)
    criar_schema(conn)
    popular(conn, HOJE)
    conn.close()
    return caminho


@pytest.fixture
def cliente(banco, monkeypatch):
    monkeypatch.setattr(web, "agora_local", lambda: datetime(2026, 10, 6, 9, 0))  # terça, aberta
    return TestClient(web.montar_app(LLMFixo(), banco, USUARIO, SENHA))


def test_tudo_exige_login_menos_a_checagem_de_saude(cliente):
    for rota in ["/chat", "/joyce", "/api/tutores", "/api/passagens", "/api/agenda"]:
        assert cliente.get(rota).status_code == 401
        assert cliente.get(rota, auth=(USUARIO, "senha-errada-123")).status_code == 401
    assert cliente.get("/saude").json() == {"ok": True}


def test_paginas_com_cabecalhos_de_seguranca(cliente):
    resposta = cliente.get("/joyce", auth=LOGIN)
    assert resposta.status_code == 200 and "Painel da Joyce" in resposta.text
    assert resposta.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in resposta.headers["Content-Security-Policy"]
    assert cliente.get("/docs", auth=LOGIN).status_code == 404


def test_escrita_sem_cabecalho_do_app_e_barrada(cliente):
    # CSRF: outro site poderia mandar este POST usando o login guardado no navegador.
    corpo = {"telefone": "(11) 90000-1101", "texto": "Oi"}
    assert cliente.post("/api/mensagens", json=corpo, auth=LOGIN).status_code == 403
    assert cliente.post("/api/mensagens", json=corpo, auth=LOGIN, headers=DO_APP).json() == {
        "resposta": "Oi! Como posso ajudar?"
    }


def test_telefone_invalido_e_recusado(cliente):
    corpo = {"telefone": "<script>", "texto": "Oi"}
    assert cliente.post("/api/mensagens", json=corpo, auth=LOGIN, headers=DO_APP).status_code == 422


def test_urgencia_aparece_no_painel_e_e_resolvida(cliente):
    corpo = {"telefone": "(11) 90000-1101", "texto": "o Thor está vomitando desde ontem"}
    cliente.post("/api/mensagens", json=corpo, auth=LOGIN, headers=DO_APP)

    abertas = cliente.get("/api/passagens", auth=LOGIN).json()
    assert [(p["motivo"], p["urgente"], p["tutor"]) for p in abertas] == [("urgencia", True, "Mariana Lopes")]

    protocolo = abertas[0]["protocolo"]
    rota = f"/api/passagens/{protocolo}/resolver"
    assert cliente.post(rota, auth=LOGIN, headers=DO_APP).json() == {"ok": True}
    assert cliente.post(rota, auth=LOGIN, headers=DO_APP).status_code == 404  # já resolvida
    assert cliente.get("/api/passagens", auth=LOGIN).json() == []


def test_agenda_do_dia(cliente):
    dados = cliente.get("/api/agenda?dia=2026-10-07", auth=LOGIN).json()
    assert [(a["inicio"][11:], a["animal"]) for a in dados["agendamentos"]] == [
        ("09:00", "Luna"), ("10:00", "Nina"), ("14:30", "Mel")
    ]


def test_operacao_resume_o_periodo(cliente):
    corpo = {"telefone": "(11) 90000-1101", "texto": "Oi"}
    cliente.post("/api/mensagens", json=corpo, auth=LOGIN, headers=DO_APP)
    dados = cliente.get("/api/operacao?dias=1", auth=LOGIN).json()
    assert (dados["conversas"], dados["mensagens"], dados["chamadas_llm"]) == (1, 1, 1)
    assert dados["desfechos"] == {"resposta": 1}
    assert cliente.get("/operacao", auth=LOGIN).status_code == 200


def test_servidor_nao_sobe_sem_login_forte(banco):
    with pytest.raises(RuntimeError, match="PAINEL_USUARIO"):
        web.montar_app(LLMFixo(), banco, "", "")
    with pytest.raises(RuntimeError, match="12 caracteres"):
        web.montar_app(LLMFixo(), banco, "joyce", "123")
