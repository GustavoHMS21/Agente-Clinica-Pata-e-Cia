"""Estado da conversa (ADR 0004).

O agente não guarda nada entre execuções. A cada turno este serviço entrega:
- o Contexto (quem é o tutor, que turno é, que horas são), vindo do banco e do canal;
- o histórico dos últimos turnos, já no formato da API;
- o estado estruturado (proposta aguardando resposta, passagens abertas).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from patas.dominio.agenda import Contexto
from patas.dominio.ids import novo_id
from patas.dominio.modelos import Conversa, Execucao, Mensagem, Papel, Passagem, Proposta
from patas.dominio.telefone import normalizar_telefone
from patas.repositorio.interface import RepositorioAgenda, RepositorioAtendimento

log = logging.getLogger(__name__)

INATIVIDADE_NOVA_CONVERSA = timedelta(hours=12)
TURNOS_NO_HISTORICO = 10
LIMITE_MENSAGEM = 2000
AVISO_CORTE = " [mensagem cortada]"

PAPEL_NA_API = {Papel.TUTOR: "user", Papel.FERRAMENTA: "user", Papel.AGENTE: "assistant", Papel.SISTEMA: "system"}


@dataclass(frozen=True)
class Estado:
    proposta_pendente: Proposta | None
    passagens_abertas: list[Passagem]


@dataclass(frozen=True)
class Turno:
    contexto: Contexto
    texto_do_tutor: str  # as mensagens do tutor deste turno, juntas
    historico: list[dict]  # últimos turnos no formato da API, terminando no texto do tutor
    estado: Estado


def para_api(mensagens: list[Mensagem]) -> list[dict]:
    """Converte para [{role, content}] e junta mensagens seguidas do mesmo papel.

    A API exige alternância user/assistant. Uma rajada do tutor e os resultados
    de ferramentas viram, cada um, uma única mensagem user.
    """
    historico: list[dict] = []
    for m in mensagens:
        role = PAPEL_NA_API[m.papel]
        if role == "system":
            # Mensagem de sistema no meio da conversa (contexto do turno): texto simples, nunca juntada.
            historico.append({"role": "system", "content": "\n".join(b["text"] for b in m.conteudo)})
            continue
        if historico and historico[-1]["role"] == role:
            historico[-1]["content"].extend(m.conteudo)
        else:
            historico.append({"role": role, "content": list(m.conteudo)})
    return historico


class ServicoConversa:
    def __init__(self, agenda: RepositorioAgenda, atendimento: RepositorioAtendimento) -> None:
        self._agenda = agenda
        self._atendimento = atendimento

    def receber(self, telefone: str, texto: str, quando: datetime) -> Conversa:
        """Guarda a mensagem do tutor sem processar. O canal decide quando abrir o turno."""
        telefone = normalizar_telefone(telefone)
        conversa = self._atendimento.buscar_conversa_recente(telefone, quando - INATIVIDADE_NOVA_CONVERSA)
        if conversa is None:
            conversa = Conversa(novo_id("cv"), telefone, quando, quando)
            self._atendimento.criar_conversa(conversa)

        texto = texto.strip()
        if len(texto) > LIMITE_MENSAGEM:
            texto = texto[:LIMITE_MENSAGEM] + AVISO_CORTE
        self._atendimento.adicionar_mensagem(
            Mensagem(conversa.id, None, Papel.TUTOR, [{"type": "text", "text": texto}], quando)
        )
        return conversa

    def abrir_turno(self, conversa_id: str, agora: datetime) -> Turno | None:
        """Junta as mensagens pendentes num turno. None se não havia nada novo."""
        numero = self._atendimento.abrir_turno(conversa_id)
        if numero is None:
            return None
        conversa = self._atendimento.obter_conversa(conversa_id)

        # Identifica de novo a cada turno: um pré-agendamento pode ter criado o tutor no turno anterior.
        tutor = self._agenda.buscar_tutor_por_telefone(conversa.telefone)
        contexto = Contexto(conversa.id, conversa.telefone, tutor.id if tutor else None, numero, agora)

        mensagens = self._atendimento.listar_mensagens(conversa.id, max(1, numero - TURNOS_NO_HISTORICO + 1))
        texto = "\n".join(
            bloco["text"] for m in mensagens if m.turno == numero and m.papel == Papel.TUTOR for bloco in m.conteudo
        )
        estado = Estado(
            proposta_pendente=self._atendimento.proposta_pendente(conversa.id, agora),
            passagens_abertas=self._atendimento.passagens_abertas(conversa.telefone),
        )
        return Turno(contexto, texto, para_api(mensagens), estado)

    def registrar(self, contexto: Contexto, papel: Papel, conteudo: list[dict]) -> None:
        """Grava o que o agente disse ou o que uma ferramenta devolveu, no turno corrente."""
        self._atendimento.adicionar_mensagem(
            Mensagem(contexto.conversa_id, contexto.turno, papel, conteudo, contexto.agora)
        )

    def rastrear(self, execucao: Execucao) -> None:
        """Grava um registro de rastreio (bloco 9). Falha aqui nunca derruba o atendimento."""
        try:
            self._atendimento.registrar_execucao(execucao)
        except Exception:
            log.exception("Falha ao gravar o rastreio da conversa %s", execucao.conversa_id)
