"""Loop do agente: um turno = chamar o modelo, executar ferramentas, repetir até a resposta final.

Regras do loop (ADR 0005):
- Dentro do turno, o histórico só cresce (append-only), com os blocos de thinking intactos.
- Entre turnos, o histórico vem do banco sem thinking: só texto, chamadas e resultados.
- Limite de iterações; recusa, corte por tamanho e falha da API viram mensagem fixa + passagem para a Joyce.
"""

import logging

from patas.agente import prompt
from patas.agente.ferramentas import FERRAMENTAS, Executor
from patas.agente.llm import ClienteLLM, FalhaLLM
from patas.dominio.agenda import Contexto, ServicoAgenda
from patas.dominio.conversa import ServicoConversa
from patas.dominio.erros import ErroRegra
from patas.dominio.modelos import Papel

log = logging.getLogger(__name__)

MAX_ITERACOES = 8  # chamadas ao modelo por turno; um agendamento completo usa 3 ou 4

RESPOSTA_FALHA = "Tive um problema para concluir seu pedido. Já passei para a Joyce, da recepção, e ela te responde por aqui."
RESPOSTA_RECUSA = "Esse assunto eu prefiro deixar com a equipe. Já passei para a Joyce, e ela te responde por aqui."


def para_historico(blocos: list[dict]) -> list[dict]:
    """O que fica salvo para os próximos turnos: texto e chamadas de ferramenta, sem thinking."""
    salvos = []
    for b in blocos:
        if b.get("type") == "text" and b.get("text"):
            salvos.append({"type": "text", "text": b["text"]})
        elif b.get("type") == "tool_use":
            salvos.append({"type": "tool_use", "id": b["id"], "name": b["name"], "input": b["input"]})
    return salvos


class Agente:
    def __init__(self, llm: ClienteLLM, agenda: ServicoAgenda, conversas: ServicoConversa) -> None:
        self._llm = llm
        self._agenda = agenda
        self._conversas = conversas
        self._executor = Executor(agenda)

    def responder(self, conversa_id: str, agora) -> str | None:
        """Processa as mensagens pendentes da conversa. None quando não havia nada novo."""
        turno = self._conversas.abrir_turno(conversa_id, agora)
        if turno is None:
            return None
        ctx = turno.contexto
        system = prompt.system(prompt.contexto_do_turno(
            agora, ctx.tutor_id is not None, self._agenda.clinica_aberta(agora), turno.estado
        ))
        messages = list(turno.historico)

        for _ in range(MAX_ITERACOES):
            try:
                resposta = self._llm.criar(system, FERRAMENTAS, messages)
            except FalhaLLM as e:
                log.error("LLM indisponível na conversa %s: %s", ctx.conversa_id, e)
                return self._encerrar_com_falha(ctx, "erro", "Falha ao chamar o modelo de linguagem.", RESPOSTA_FALHA)

            if resposta.stop_reason == "refusal":
                return self._encerrar_com_falha(ctx, "fora_do_escopo", "O modelo recusou responder a mensagem do tutor.",
                                                RESPOSTA_RECUSA)
            if resposta.stop_reason == "max_tokens":
                # Uma chamada de ferramenta cortada no meio nunca é executada.
                return self._encerrar_com_falha(ctx, "erro", "Resposta do modelo cortada por tamanho.", RESPOSTA_FALHA)

            messages.append({"role": "assistant", "content": resposta.content})
            salvos = para_historico(resposta.content)
            if salvos:
                self._conversas.registrar(ctx, Papel.AGENTE, salvos)

            chamadas = [b for b in resposta.content if b.get("type") == "tool_use"]
            if not chamadas:
                texto = "\n\n".join(b["text"] for b in salvos if b["type"] == "text").strip()
                if not texto:
                    return self._encerrar_com_falha(ctx, "erro", "O modelo terminou sem texto.", RESPOSTA_FALHA)
                return texto

            # Todas as respostas das ferramentas voltam numa única mensagem, na ordem das chamadas.
            resultados = []
            for chamada in chamadas:
                conteudo, erro = self._executor.executar(chamada["name"], chamada["input"], ctx)
                resultado = {"type": "tool_result", "tool_use_id": chamada["id"], "content": conteudo}
                if erro:
                    resultado["is_error"] = True
                resultados.append(resultado)
            messages.append({"role": "user", "content": resultados})
            self._conversas.registrar(ctx, Papel.FERRAMENTA, resultados)

        log.warning("Limite de %s iterações na conversa %s", MAX_ITERACOES, ctx.conversa_id)
        return self._encerrar_com_falha(ctx, "erro", "O atendimento automático passou do limite de passos.",
                                        RESPOSTA_FALHA)

    def _encerrar_com_falha(self, ctx: Contexto, motivo: str, resumo: str, resposta: str) -> str:
        try:
            self._agenda.passar_para_joyce(ctx, motivo, False, resumo)
        except ErroRegra:
            log.exception("Não foi possível abrir a passagem para a Joyce na conversa %s", ctx.conversa_id)
        self._conversas.registrar(ctx, Papel.AGENTE, [{"type": "text", "text": resposta}])
        return resposta
