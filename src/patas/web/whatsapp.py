"""Canal WhatsApp Cloud API (produção, fase 1): webhook de entrada e envio de respostas.

Fluxo de uma mensagem:
1. A Meta chama POST /webhook/whatsapp. A assinatura X-Hub-Signature-256 prova que veio dela.
2. A mensagem é gravada como pendente (ServicoConversa.receber) e o webhook responde 200 na hora:
   a Meta reenvia o que demora a ser confirmado, e o agente leva vários segundos.
3. O despachante espera alguns segundos de silêncio: uma rajada ("oi", "quanto tá o banho?", "?")
   vira um turno só (ADR 0004). Depois roda o agente e envia a resposta pela Graph API.

O telefone vem sempre do webhook, nunca do texto da mensagem.
"""

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import AbstractContextManager, closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from patas.agente.llm import ClienteLLM
from patas.agente.loop import Agente
from patas.config import agora_local
from patas.dominio.agenda import ServicoAgenda
from patas.dominio.conversa import ServicoConversa
from patas.dominio.telefone import normalizar_telefone
from patas.repositorio.sqlite import AgendaSQLite, AtendimentoSQLite, conectar

log = logging.getLogger(__name__)

VARIAVEIS = ["WHATSAPP_API_VERSAO", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_TOKEN", "WHATSAPP_APP_SECRET",
             "WHATSAPP_VERIFY_TOKEN"]
ESPERA_DA_RAJADA = 4.0  # segundos de silêncio antes de responder
RETOMAR_PENDENTES_DE = timedelta(hours=1)  # ao subir, só responde o que ficou sem resposta há pouco
LIMITE_DO_WHATSAPP = 4096  # caracteres por mensagem de texto

AVISO_LGPD = (
    "Olá! Aqui é o assistente virtual da Patas & Cia 🐾 Seus dados são usados só para este atendimento "
    "e para os agendamentos. Se preferir falar com a equipe, é só pedir."
)

# Mídia vira um marcador: o prompt já orienta pedir que o tutor escreva (o agente só lê texto).
MARCADORES = {
    "audio": "[áudio]", "voice": "[áudio]", "image": "[imagem]", "video": "[vídeo]", "document": "[documento]",
    "sticker": "[figurinha]", "location": "[localização]", "contacts": "[contato]",
}
IGNORADOS = {"reaction", "system", "request_welcome"}  # não pedem resposta

Enviar = Callable[[str, str], bool]


@dataclass(frozen=True)
class ConfigWhatsApp:
    versao: str
    phone_number_id: str
    # repr=False: um log ou erro que mostre a configuração nunca mostra os segredos.
    token: str = field(repr=False)
    app_secret: str = field(repr=False)
    verify_token: str = field(repr=False)

    @classmethod
    def do_ambiente(cls) -> "ConfigWhatsApp | None":
        """None quando nenhuma variável está preenchida: o canal fica desligado (só o simulador)."""
        valores = [os.environ.get(nome, "").strip() for nome in VARIAVEIS]
        if not any(valores):
            return None
        faltando = [nome for nome, valor in zip(VARIAVEIS, valores) if not valor]
        if faltando:
            # Falha fechada: canal pela metade (ex.: sem app secret) aceitaria webhook sem conferir a origem.
            raise RuntimeError(f"WhatsApp configurado pela metade. Faltam no .env: {', '.join(faltando)}")
        versao, phone_number_id = valores[0], valores[1]
        if not re.fullmatch(r"v\d+\.\d+", versao) or not phone_number_id.isdigit():
            raise RuntimeError("WHATSAPP_API_VERSAO deve ser como v23.0, e WHATSAPP_PHONE_NUMBER_ID só dígitos.")
        return cls(*valores)


def assinatura_valida(corpo: bytes, cabecalho: str | None, app_secret: str) -> bool:
    """Confere o HMAC-SHA256 que a Meta calcula sobre o corpo cru com a chave secreta do app."""
    if not cabecalho or not cabecalho.startswith("sha256="):
        return False
    esperado = hmac.new(app_secret.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(cabecalho.removeprefix("sha256="), esperado)


@dataclass(frozen=True)
class Recebida:
    wamid: str  # id da mensagem na Meta: chave da deduplicação
    telefone: str
    texto: str


def extrair_mensagens(payload: dict, phone_number_id: str) -> list[Recebida]:
    """Mensagens de tutores no webhook. Status de entrega e outros números são ignorados."""
    recebidas = []
    for entrada in payload.get("entry") or []:
        for mudanca in entrada.get("changes") or []:
            valor = mudanca.get("value") or {}
            if mudanca.get("field") != "messages" or (valor.get("metadata") or {}).get("phone_number_id") != phone_number_id:
                continue
            for m in valor.get("messages") or []:
                texto = _texto(m)
                if texto and m.get("id") and m.get("from"):
                    recebidas.append(Recebida(m["id"], m["from"], texto))
    return recebidas


def _texto(m: dict) -> str:
    tipo = m.get("type")
    if tipo == "text":
        return (m.get("text") or {}).get("body", "").strip()
    if tipo == "button":  # resposta a botão de modelo
        return (m.get("button") or {}).get("text", "").strip()
    if tipo == "interactive":
        i = m.get("interactive") or {}
        return (i.get("button_reply") or i.get("list_reply") or {}).get("title", "").strip()
    if tipo in IGNORADOS:
        return ""
    midia = m.get(tipo) if isinstance(m.get(tipo), dict) else {}
    return f"{MARCADORES.get(tipo, '[mensagem não suportada]')} {midia.get('caption', '')}".strip()


class ClienteWhatsApp:
    """Envio pela Graph API. Nunca registra o token; o telefone aparece mascarado nos logs."""

    def __init__(self, config: ConfigWhatsApp) -> None:
        self._url = f"https://graph.facebook.com/{config.versao}/{config.phone_number_id}/messages"
        self._token = config.token

    def enviar_texto(self, telefone: str, texto: str) -> bool:
        corpo = {
            "messaging_product": "whatsapp",
            "to": telefone,
            "type": "text",
            "text": {"preview_url": False, "body": texto[:LIMITE_DO_WHATSAPP]},
        }
        pedido = urllib.request.Request(
            self._url, data=json.dumps(corpo).encode(), method="POST",
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(pedido, timeout=15) as resposta:
                resposta.read()
            return True
        except urllib.error.HTTPError as e:
            log.error("WhatsApp recusou o envio para %s: HTTP %s %s", mascarar(telefone), e.code, _erro_da_meta(e))
        except (urllib.error.URLError, TimeoutError) as e:
            log.error("Sem conexão com a Graph API ao enviar para %s: %s", mascarar(telefone), e)
        return False


def _erro_da_meta(e: urllib.error.HTTPError) -> str:
    # A Meta devolve {"error": {"code", "message"}}: só isso vai para o log, nunca o pedido (que tem o token).
    try:
        erro = json.loads(e.read()).get("error", {})
        return f"(código {erro.get('code')}: {str(erro.get('message', ''))[:200]})"
    except (ValueError, AttributeError):
        return ""


def mascarar(telefone: str) -> str:
    """LGPD: log de operação não precisa do número inteiro."""
    return f"…{telefone[-4:]}"


class Despachante:
    """Recebe do webhook, espera a rajada terminar e responde. Um turno por vez em cada conversa."""

    def __init__(
        self,
        banco: Path,
        llm: ClienteLLM,
        enviar: Enviar,
        trava_da_conversa: Callable[[str], AbstractContextManager],
        relogio: Callable[[], datetime] | None = None,
        espera: float = ESPERA_DA_RAJADA,
    ) -> None:
        self._banco = banco
        self._llm = llm
        self._trava = trava_da_conversa
        self._relogio = relogio or (lambda: agora_local())  # lido na hora: os testes fixam o relógio
        self._espera = espera
        self._temporizadores: dict[str, threading.Timer] = {}
        self._guarda = threading.Lock()
        # Públicos para os testes trocarem: envio falso e processamento sem espera.
        self.enviar: Enviar = enviar
        self.agendar: Callable[[str], None] = self._agendar_com_espera

    def receber(self, mensagens: list[Recebida]) -> None:
        """Grava as mensagens novas como pendentes e agenda a resposta. Rápido: roda dentro do webhook."""
        agora = self._relogio()
        conversas_novas: dict[str, None] = {}  # dict: sem repetição e na ordem de chegada
        with self._conexao() as conn:
            atendimento = AtendimentoSQLite(conn)
            conversas = ServicoConversa(AgendaSQLite(conn), atendimento)
            for m in mensagens:
                telefone = normalizar_telefone(m.telefone)
                if not atendimento.registrar_mensagem_recebida(m.wamid, telefone, agora):
                    continue  # a Meta reenviou: já está gravada
                conversas_novas[conversas.receber(telefone, m.texto, agora).id] = None
        for conversa_id in conversas_novas:
            self.agendar(conversa_id)

    def retomar_pendentes(self) -> int:
        """Na subida do servidor: responde o que ficou sem resposta (ex.: queda no meio de um turno)."""
        desde = self._relogio() - RETOMAR_PENDENTES_DE
        with self._conexao() as conn:
            ids = [c.id for c in AtendimentoSQLite(conn).conversas_com_pendencias() if c.ultima_mensagem_em >= desde]
        for conversa_id in ids:
            self.agendar(conversa_id)
        return len(ids)

    def processar(self, conversa_id: str) -> None:
        with self._guarda:
            if self._temporizadores.get(conversa_id) is threading.current_thread():
                del self._temporizadores[conversa_id]
        try:
            with self._trava(conversa_id):
                with self._conexao() as conn:
                    agenda, atendimento = AgendaSQLite(conn), AtendimentoSQLite(conn)
                    conversas = ServicoConversa(agenda, atendimento)
                    agente = Agente(self._llm, ServicoAgenda(agenda, atendimento), conversas)
                    resposta = agente.responder(conversa_id, self._relogio())
                    conversa = atendimento.obter_conversa(conversa_id)
                if resposta:
                    if conversa.turno == 1:
                        self.enviar(conversa.telefone, AVISO_LGPD)
                    self.enviar(conversa.telefone, resposta)
        except Exception:
            # Roda fora da requisição: sem este log, um erro aqui sumiria em silêncio.
            log.exception("Falha ao responder a conversa %s do WhatsApp", conversa_id)

    def _agendar_com_espera(self, conversa_id: str) -> None:
        # Cada mensagem nova reinicia a contagem: só responde depois de `espera` segundos de silêncio.
        with self._guarda:
            anterior = self._temporizadores.pop(conversa_id, None)
            if anterior:
                anterior.cancel()
            temporizador = threading.Timer(self._espera, self.processar, args=(conversa_id,))
            temporizador.daemon = True
            self._temporizadores[conversa_id] = temporizador
        temporizador.start()

    def _conexao(self) -> closing:
        # Uma conexão por uso: o sqlite3 não compartilha conexão entre threads.
        return closing(conectar(self._banco))
