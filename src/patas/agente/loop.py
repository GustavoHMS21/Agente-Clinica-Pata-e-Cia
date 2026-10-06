"""Loop do agente: um turno = chamar o modelo, executar ferramentas, repetir até a resposta final.

Regras do loop (ADR 0005 e 0008):
- Dentro do turno, o histórico só cresce (append-only), com os blocos de thinking intactos.
- Entre turnos, o histórico vem do banco sem thinking: só texto, chamadas, resultados e o
  contexto de cada turno (mensagem de sistema), para o prefixo nunca mudar e entrar no cache.
- Limite de iterações; recusa, corte por tamanho e falha da API viram mensagem fixa + passagem para a Joyce.
- Cada turno, chamada ao LLM e ferramenta vira um registro de rastreio (bloco 9).
"""

import json
import logging
import time
from collections import Counter
from datetime import datetime

from patas.agente import guardrails, prompt
from patas.agente.custos import custo_usd
from patas.agente.ferramentas import FERRAMENTAS, Executor
from patas.agente.llm import ClienteLLM, FalhaLLM, RespostaLLM
from patas.dominio.agenda import Contexto, ServicoAgenda
from patas.dominio.conversa import ServicoConversa
from patas.dominio.erros import ErroRegra
from patas.dominio.modelos import Execucao, Papel

log = logging.getLogger(__name__)

MAX_ITERACOES = 8  # chamadas ao modelo por turno; um agendamento completo usa 3 ou 4
MAX_FALHAS_POR_FERRAMENTA = 3  # depois disso, a ferramenta fica bloqueada no turno

RESPOSTA_FALHA = "Tive um problema para concluir seu pedido. Já passei para a Joyce, da recepção, e ela te responde por aqui."
RESPOSTA_RECUSA = "Esse assunto eu prefiro deixar com a equipe. Já passei para a Joyce, e ela te responde por aqui."
CHAMADA_REPETIDA = json.dumps({"ok": False, "erro": {
    "codigo": "ARGUMENTO_INVALIDO",
    "mensagem": "Essa mesma chamada, com os mesmos argumentos, já falhou neste turno. Não foi executada de novo.",
    "proximo_passo": "Leia o erro anterior e mude os argumentos, pergunte ao tutor o que falta ou chame passar_para_joyce.",
}}, ensure_ascii=False)
FERRAMENTA_BLOQUEADA = json.dumps({"ok": False, "erro": {
    "codigo": "ARGUMENTO_INVALIDO",
    "mensagem": "Essa ferramenta já falhou várias vezes neste turno e foi bloqueada até a próxima mensagem do tutor.",
    "proximo_passo": "Pergunte ao tutor o dado que falta ou chame passar_para_joyce.",
}}, ensure_ascii=False)


def para_historico(blocos: list[dict]) -> list[dict]:
    """O que fica salvo para os próximos turnos: texto e chamadas de ferramenta, sem thinking."""
    salvos = []
    for b in blocos:
        if b.get("type") == "text" and b.get("text"):
            salvos.append({"type": "text", "text": b["text"]})
        elif b.get("type") == "tool_use":
            salvos.append({"type": "tool_use", "id": b["id"], "name": b["name"], "input": b["input"]})
    return salvos


def _ms(inicio: float) -> int:
    return int((time.perf_counter() - inicio) * 1000)


class Agente:
    def __init__(self, llm: ClienteLLM, agenda: ServicoAgenda, conversas: ServicoConversa) -> None:
        self._llm = llm
        self._agenda = agenda
        self._conversas = conversas
        self._executor = Executor(agenda)

    def responder(self, conversa_id: str, agora: datetime) -> str | None:
        """Processa as mensagens pendentes da conversa. None quando não havia nada novo."""
        turno = self._conversas.abrir_turno(conversa_id, agora)
        if turno is None:
            return None
        ctx = turno.contexto
        inicio = time.perf_counter()
        texto, desfecho = self._turno(turno)
        # O registro do turno resume tudo: desfecho e tempo total que o tutor esperou.
        self._conversas.rastrear(Execucao(ctx.conversa_id, ctx.turno, ctx.agora, "turno", desfecho, "ok",
                                          _ms(inicio)))
        return texto

    def _turno(self, turno) -> tuple[str, str]:
        ctx = turno.contexto
        aberta = self._agenda.clinica_aberta(ctx.agora)

        # Guardrail de entrada: sinal de alerta de saúde é tratado pelo código, antes do modelo.
        alerta = guardrails.detectar_alerta(turno.texto_do_tutor)
        if alerta:
            ja_avisada = any(p.motivo == "urgencia" and p.conversa_id == ctx.conversa_id
                             for p in turno.estado.passagens_abertas)
            if not ja_avisada:
                self._passar(ctx, "urgencia", True, f"Alerta automático. Tutor escreveu: {turno.texto_do_tutor[:400]}")
            if not aberta:
                # Fora do horário, nada de improviso sobre saúde: resposta fixa, sem chamar o modelo.
                return self._responder_fixo(ctx, guardrails.RESPOSTA_URGENCIA_FECHADO), "urgencia_fora_do_horario"

        # Contexto do turno: mensagem de sistema logo depois do tutor, gravada no histórico (ADR 0008).
        contexto = prompt.contexto_do_turno(ctx.agora, ctx.tutor_id is not None, aberta, turno.estado, alerta)
        self._conversas.registrar(ctx, Papel.SISTEMA, [{"type": "text", "text": contexto}])
        system = prompt.system()
        messages = list(turno.historico) + [{"role": "system", "content": contexto}]
        falhas: set[str] = set()  # chamadas que já falharam neste turno: não repetimos (custo e loop)
        falhas_por_ferramenta: Counter[str] = Counter()  # mesma ferramenta errando com argumentos diferentes

        for _ in range(MAX_ITERACOES):
            inicio = time.perf_counter()
            try:
                resposta = self._llm.criar(system, FERRAMENTAS, messages)
            except FalhaLLM as e:
                log.error("LLM indisponível na conversa %s: %s", ctx.conversa_id, e)
                self._rastrear_llm(ctx, None, "falha", _ms(inicio))
                return self._encerrar_com_falha(ctx, "erro", "Falha ao chamar o modelo de linguagem.",
                                                RESPOSTA_FALHA), "falha_llm"
            self._rastrear_llm(ctx, resposta, resposta.stop_reason, _ms(inicio))

            if resposta.stop_reason == "refusal":
                return self._encerrar_com_falha(ctx, "fora_do_escopo", "O modelo recusou responder a mensagem do tutor.",
                                                RESPOSTA_RECUSA), "recusa"
            if resposta.stop_reason == "max_tokens":
                # Uma chamada de ferramenta cortada no meio nunca é executada.
                return self._encerrar_com_falha(ctx, "erro", "Resposta do modelo cortada por tamanho.",
                                                RESPOSTA_FALHA), "corte_por_tamanho"

            messages.append({"role": "assistant", "content": resposta.content})
            salvos = para_historico(resposta.content)
            chamadas = [b for b in resposta.content if b.get("type") == "tool_use"]
            if not chamadas:
                texto = "\n\n".join(b["text"] for b in salvos if b["type"] == "text").strip()
                return self._finalizar(ctx, texto)
            self._conversas.registrar(ctx, Papel.AGENTE, salvos)

            # Todas as respostas das ferramentas voltam numa única mensagem, na ordem das chamadas.
            resultados = []
            for chamada in chamadas:
                inicio = time.perf_counter()
                assinatura = json.dumps([chamada["name"], chamada["input"]], sort_keys=True, ensure_ascii=False)
                if assinatura in falhas:
                    conteudo, erro = CHAMADA_REPETIDA, True
                elif falhas_por_ferramenta[chamada["name"]] >= MAX_FALHAS_POR_FERRAMENTA:
                    conteudo, erro = FERRAMENTA_BLOQUEADA, True
                else:
                    conteudo, erro = self._executor.executar(chamada["name"], chamada["input"], ctx)
                    if erro:
                        falhas.add(assinatura)
                        falhas_por_ferramenta[chamada["name"]] += 1
                self._rastrear_ferramenta(ctx, chamada["name"], conteudo, erro, _ms(inicio))
                resultado = {"type": "tool_result", "tool_use_id": chamada["id"], "content": conteudo}
                if erro:
                    resultado["is_error"] = True
                resultados.append(resultado)
            messages.append({"role": "user", "content": resultados})
            self._conversas.registrar(ctx, Papel.FERRAMENTA, resultados)

        log.warning("Limite de %s iterações na conversa %s", MAX_ITERACOES, ctx.conversa_id)
        return self._encerrar_com_falha(ctx, "erro", "O atendimento automático passou do limite de passos.",
                                        RESPOSTA_FALHA), "limite_de_passos"

    def _finalizar(self, ctx: Contexto, texto: str) -> tuple[str, str]:
        """Guardrail de saída: o que vai para o tutor passa por aqui, e só isso fica no histórico."""
        texto, problemas = guardrails.limpar_resposta(texto)
        if problemas:
            log.warning("Resposta ajustada na conversa %s: %s", ctx.conversa_id, ", ".join(problemas))
        if not texto:
            return self._encerrar_com_falha(ctx, "erro", "O modelo terminou sem texto.", RESPOSTA_FALHA), "sem_texto"
        if guardrails.parece_orientacao_de_saude(texto):
            log.warning("Resposta bloqueada por parecer orientação de saúde na conversa %s", ctx.conversa_id)
            return self._encerrar_com_falha(ctx, "saude", "Resposta automática bloqueada: parecia orientação de saúde.",
                                            guardrails.RESPOSTA_SAUDE), "saude_bloqueada"
        return self._responder_fixo(ctx, texto), "resposta" + ("_ajustada" if problemas else "")

    def _encerrar_com_falha(self, ctx: Contexto, motivo: str, resumo: str, resposta: str) -> str:
        self._passar(ctx, motivo, False, resumo)
        return self._responder_fixo(ctx, resposta)

    def _passar(self, ctx: Contexto, motivo: str, urgente: bool, resumo: str) -> None:
        try:
            self._agenda.passar_para_joyce(ctx, motivo, urgente, resumo)
        except ErroRegra:
            log.exception("Não foi possível abrir a passagem para a Joyce na conversa %s", ctx.conversa_id)

    def _responder_fixo(self, ctx: Contexto, texto: str) -> str:
        self._conversas.registrar(ctx, Papel.AGENTE, [{"type": "text", "text": texto}])
        return texto

    # Rastreio -----------------------------------------------------------------

    def _rastrear_llm(self, ctx: Contexto, resposta: RespostaLLM | None, resultado: str, duracao_ms: int) -> None:
        uso = resposta.uso if resposta else {}
        modelo = uso.get("modelo", "desconhecido")
        self._conversas.rastrear(Execucao(
            ctx.conversa_id, ctx.turno, ctx.agora, "llm", modelo, resultado, duracao_ms,
            tokens_entrada=uso.get("input_tokens", 0),
            tokens_saida=uso.get("output_tokens", 0),
            tokens_cache_lidos=uso.get("cache_read_input_tokens", 0),
            tokens_cache_gravados=uso.get("cache_creation_input_tokens", 0),
            custo_usd=custo_usd(modelo, uso) if resposta else None,
        ))

    def _rastrear_ferramenta(self, ctx: Contexto, nome: str, conteudo: str, erro: bool, duracao_ms: int) -> None:
        resultado = "ok"
        if erro:
            try:
                resultado = json.loads(conteudo)["erro"]["codigo"]
            except (ValueError, KeyError, TypeError):
                resultado = "erro"
        self._conversas.rastrear(Execucao(ctx.conversa_id, ctx.turno, ctx.agora, "ferramenta", nome,
                                          resultado, duracao_ms))
