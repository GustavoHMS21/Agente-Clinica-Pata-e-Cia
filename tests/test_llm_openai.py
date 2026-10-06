"""Conversões do adaptador compatível com OpenAI e fábrica de provedores. Sem rede."""

import json

import pytest

from patas.agente.ferramentas import FERRAMENTAS
from patas.agente.llm import cliente_do_ambiente
from patas.agente.llm_openai import de_openai, ferramentas_para_openai, para_openai

SYSTEM = [{"type": "text", "text": "fixo", "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": "turno"}]
ASSINATURA = {"google": {"thought_signature": "opaca"}}


def test_ferramentas_viram_functions_sem_campos_que_nem_todo_provedor_aceita():
    convertidas = ferramentas_para_openai(FERRAMENTAS)
    assert len(convertidas) == 8 and all(f["type"] == "function" for f in convertidas)
    texto = json.dumps(convertidas)
    assert "additionalProperties" not in texto and "strict" not in texto
    assert convertidas[2]["function"]["parameters"]["required"] == ["servico_id", "data_inicio"]


def test_historico_vira_chat_completions_na_ordem_certa():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "Quanto é o banho?"}]},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "", "signature": "x"},  # thinking de outro provedor é ignorado
            {"type": "tool_use", "id": "c1", "name": "consultar_servicos", "input": {"categoria": "banho_tosa"},
             "extra_content": ASSINATURA},
        ]},
        # Resultado da ferramenta e a mensagem nova do tutor juntos (ADR 0004 junta papéis iguais).
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1", "content": "{\"ok\": true}"},
            {"type": "text", "text": "E pra amanhã?"},
        ]},
    ]
    saida = para_openai(SYSTEM, messages)
    assert [m["role"] for m in saida] == ["system", "user", "assistant", "tool", "user"]
    assert saida[0]["content"] == "fixo\n\nturno"
    chamada = saida[2]["tool_calls"][0]
    assert json.loads(chamada["function"]["arguments"]) == {"categoria": "banho_tosa"}
    assert chamada["extra_content"] == ASSINATURA  # a assinatura volta intacta dentro do turno
    assert saida[3] == {"role": "tool", "tool_call_id": "c1", "content": "{\"ok\": true}"}


def test_resposta_com_tool_calls_vira_blocos_e_guarda_a_assinatura():
    mensagem = {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c9", "type": "function", "function": {"name": "consultar_cadastro", "arguments": "{}"},
         "extra_content": ASSINATURA},
    ]}
    resposta = de_openai(mensagem, "stop", {})  # "stop" com tool_calls: alguns provedores fazem isso
    assert resposta.stop_reason == "tool_use"
    assert resposta.content == [
        {"type": "tool_use", "id": "c9", "name": "consultar_cadastro", "input": {}, "extra_content": ASSINATURA}
    ]


@pytest.mark.parametrize(("fim", "esperado"), [("stop", "end_turn"), ("length", "max_tokens"), ("content_filter", "refusal")])
def test_motivo_de_parada(fim, esperado):
    assert de_openai({"content": "oi"}, fim, {}).stop_reason == esperado


def test_argumentos_quebrados_nao_derrubam_o_loop():
    mensagem = {"tool_calls": [{"id": "c1", "function": {"name": "buscar_horarios", "arguments": "{quebrado"}}]}
    assert de_openai(mensagem, "tool_calls", {}).content[0]["input"] == {}


def test_fabrica_falha_cedo_sem_chave_e_sem_mostrar_valor(monkeypatch):
    monkeypatch.setenv("LLM_PROVEDOR", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY não definida"):
        cliente_do_ambiente()

    monkeypatch.setenv("LLM_PROVEDOR", "provedor_inventado")
    with pytest.raises(RuntimeError, match="desconhecido"):
        cliente_do_ambiente()


def test_ollama_local_nao_exige_chave(monkeypatch):
    monkeypatch.setenv("LLM_PROVEDOR", "ollama")
    monkeypatch.delenv("LLM_MODELO", raising=False)
    assert cliente_do_ambiente() is not None  # só monta o cliente; nenhuma chamada de rede
