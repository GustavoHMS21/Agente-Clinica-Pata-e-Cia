"""Google Agenda do banho e tosa (produção, fase 1, ADR 0013).

A equipe de tosa já usa uma agenda do Google. Este módulo a liga ao agente sem o domínio saber
que o Google existe (ADR 0001): AgendaComGoogle embrulha a RepositorioAgenda do SQLite.

- Leitura: cada evento que a equipe lança direto no Google ocupa uma tosadora (agenda única da
  equipe; a capacidade é o número de tosadoras).
- Escrita: o banho ou a tosa que o agente marca vira evento no Google, para a equipe ver.
  O Google é gravado antes do banco: se ele falhar, nada muda aqui e o agente passa para a Joyce.
"""

import json
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from patas.config import FUSO_DA_CLINICA, RAIZ
from patas.dominio.modelos import Agendamento, StatusAgendamento
from patas.repositorio.interface import RepositorioAgenda

log = logging.getLogger(__name__)

ESCOPO = ["https://www.googleapis.com/auth/calendar.events"]  # só eventos: não mexe em configuração da agenda
TEMPO_LIMITE = 15  # segundos por chamada
MARCA = "patas_agendamento"  # propriedade privada nos eventos criados pelo agente (guarda o id do agendamento)
EQUIPE = "tosadora"


class ErroGoogleAgenda(Exception):
    """Falha ao falar com o Google. A ferramenta transforma em ERRO_INTERNO: o agente passa para a Joyce."""


@dataclass(frozen=True)
class Evento:
    id: str
    inicio: datetime  # horário de Guarulhos, sem fuso (ADR 0003)
    fim: datetime
    do_agente: bool


class Calendario(Protocol):
    def eventos(self, de: datetime, ate: datetime) -> list[Evento]: ...
    def gravar(self, evento_id: str, corpo: dict) -> None:
        """Cria o evento com este id; se já existir, substitui."""
        ...
    def apagar(self, evento_id: str) -> None:
        """Apaga; evento que já não existe não é erro."""
        ...


def id_do_evento(agendamento_id: str) -> str:
    """Id determinístico: o mesmo agendamento nunca vira dois eventos (o Google aceita 0-9 e a-v)."""
    return "patas" + agendamento_id.encode().hex()


class CalendarioGoogle:
    def __init__(self, agenda_id: str, sessao) -> None:
        self._url = f"https://www.googleapis.com/calendar/v3/calendars/{quote(agenda_id, safe='')}/events"
        self._sessao = sessao  # AuthorizedSession: renova o token da conta de serviço sozinha

    @classmethod
    def do_ambiente(cls) -> "CalendarioGoogle | None":
        """None sem GOOGLE_AGENDA_ID: o banho e tosa fica só no banco local (como no MVP)."""
        agenda_id = os.environ.get("GOOGLE_AGENDA_ID", "").strip()
        if not agenda_id:
            return None
        info = ler_credenciais(os.environ.get("GOOGLE_CREDENCIAIS", "").strip())
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        credenciais = service_account.Credentials.from_service_account_info(info, scopes=ESCOPO)
        return cls(agenda_id, AuthorizedSession(credenciais))

    def eventos(self, de: datetime, ate: datetime) -> list[Evento]:
        params = {"timeMin": _com_fuso(de), "timeMax": _com_fuso(ate), "singleEvents": "true",
                  "timeZone": str(FUSO_DA_CLINICA), "maxResults": 250}
        eventos: list[Evento] = []
        while True:
            dados = self._pedir("GET", self._url, params=params).json()
            eventos.extend(e for e in map(ler_evento, dados.get("items", [])) if e)
            if not dados.get("nextPageToken"):
                return eventos
            params["pageToken"] = dados["nextPageToken"]

    def gravar(self, evento_id: str, corpo: dict) -> None:
        resposta = self._pedir("POST", self._url, json={**corpo, "id": evento_id}, aceitar=(409,))
        if resposta.status_code == 409:  # já existe (remarcação, ou evento apagado antes): substitui
            self._pedir("PUT", f"{self._url}/{evento_id}", json=corpo)

    def apagar(self, evento_id: str) -> None:
        self._pedir("DELETE", f"{self._url}/{evento_id}", aceitar=(404, 410))

    def _pedir(self, metodo: str, url: str, aceitar: Iterable[int] = (), **kwargs):
        try:
            resposta = self._sessao.request(metodo, url, timeout=TEMPO_LIMITE, **kwargs)
        except Exception as e:  # rede, DNS, token recusado na renovação
            raise ErroGoogleAgenda(f"Sem conexão com o Google Agenda: {type(e).__name__}") from None
        if resposta.status_code >= 400 and resposta.status_code not in aceitar:
            raise ErroGoogleAgenda(f"Google Agenda respondeu {resposta.status_code} em {metodo}")
        return resposta


def ler_credenciais(valor: str) -> dict:
    """Caminho do JSON da conta de serviço (local) ou o próprio JSON (cofre de segredos no deploy)."""
    if not valor:
        raise RuntimeError("GOOGLE_AGENDA_ID preenchido sem GOOGLE_CREDENCIAIS.")
    if valor.startswith("{"):
        texto = valor
    else:
        arquivo = Path(valor) if Path(valor).is_absolute() else RAIZ / valor
        if not arquivo.exists():
            raise RuntimeError(f"Arquivo de credenciais do Google não encontrado em {valor}.")
        texto = arquivo.read_text(encoding="utf-8")
    try:
        info = json.loads(texto)
    except ValueError:
        raise RuntimeError("GOOGLE_CREDENCIAIS não é um JSON válido.") from None
    if info.get("type") != "service_account":
        raise RuntimeError("GOOGLE_CREDENCIAIS precisa ser de conta de serviço (type service_account).")
    return info


def _com_fuso(momento: datetime) -> str:
    return momento.replace(tzinfo=FUSO_DA_CLINICA).isoformat()


def _local(momento: dict) -> datetime:
    if "dateTime" in momento:
        return datetime.fromisoformat(momento["dateTime"]).astimezone(FUSO_DA_CLINICA).replace(tzinfo=None)
    return datetime.combine(date.fromisoformat(momento["date"]), time.min)  # dia inteiro (ex.: folga)


def ler_evento(item: dict) -> Evento | None:
    """Evento do Google que ocupa horário. Marcado como "Disponível" ou cancelado não ocupa."""
    if item.get("status") == "cancelled" or item.get("transparency") == "transparent":
        return None
    privado = (item.get("extendedProperties") or {}).get("private") or {}
    return Evento(item["id"], _local(item["start"]), _local(item["end"]), MARCA in privado)


def distribuir(externos: list[Evento], equipe: list[str], proprias: list[Agendamento]) -> list[Agendamento]:
    """Cada evento lançado pela equipe ocupa uma tosadora: a primeira livre naquele horário.

    Sempre calculado sobre o dia inteiro: assim a busca de horários e a confirmação, que olham
    janelas diferentes, chegam à mesma distribuição.
    """
    ocupado = {p: [(o.inicio, o.fim) for o in proprias if o.profissional_id == p] for p in equipe}
    bloqueios = []
    for e in sorted(externos, key=lambda e: (e.inicio, e.fim, e.id)):
        livre = next((p for p in equipe if not any(i < e.fim and e.inicio < f for i, f in ocupado[p])), None)
        p = livre or equipe[0]  # agenda lotada além da equipe: quem já está ocupado continua ocupado
        ocupado[p].append((e.inicio, e.fim))
        bloqueios.append(Agendamento(f"google:{e.id}", "", "", p, e.inicio, e.fim, StatusAgendamento.CONFIRMADO,
                                     0, e.inicio))
    return bloqueios


class AgendaComGoogle:
    """RepositorioAgenda com o banho e tosa espelhado no Google. O resto passa direto para a base."""

    def __init__(self, base: RepositorioAgenda, calendario: Calendario) -> None:
        self._base = base
        self._calendario = calendario
        self._equipe = base.listar_profissionais(EQUIPE)

    def __getattr__(self, nome: str):
        return getattr(self._base, nome)

    # Leitura -------------------------------------------------------------------

    def listar_ocupacoes(self, profissional_ids: list[str], de: datetime, ate: datetime) -> list[Agendamento]:
        proprias = self._base.listar_ocupacoes(profissional_ids, de, ate)
        if not any(p in self._equipe for p in profissional_ids):
            return proprias  # consulta e vacina: o Google não entra
        dia_inicio = datetime.combine(de.date(), time.min)
        dia_fim = datetime.combine(ate.date(), time.min)
        if dia_fim < ate:
            dia_fim += timedelta(days=1)
        externos = [e for e in self._calendario.eventos(dia_inicio, dia_fim) if not e.do_agente]
        if not externos:
            return proprias
        do_dia = self._base.listar_ocupacoes(self._equipe, dia_inicio, dia_fim)
        bloqueios = [b for b in distribuir(externos, self._equipe, do_dia)
                     if b.profissional_id in profissional_ids and b.inicio < ate and b.fim > de]
        return sorted(proprias + bloqueios, key=lambda o: o.inicio)

    # Escrita: Google primeiro; se o banco recusar, o Google é desfeito ----------

    def inserir_agendamento_se_livre(self, agendamento: Agendamento) -> Agendamento | None:
        if agendamento.profissional_id not in self._equipe:
            return self._base.inserir_agendamento_se_livre(agendamento)
        evento_id = id_do_evento(agendamento.id)
        self._calendario.gravar(evento_id, self._corpo(agendamento))
        try:
            salvo = self._base.inserir_agendamento_se_livre(agendamento)
        except Exception:
            self._desfazer(evento_id)
            raise
        if salvo is None or salvo.id != agendamento.id:  # conflito, ou confirmação repetida (já tem evento)
            self._desfazer(evento_id)
        return salvo

    def mover_agendamento_se_livre(
        self, agendamento_id: str, profissional_id: str, inicio: datetime, fim: datetime
    ) -> bool:
        antes = self._base.obter_agendamento(agendamento_id)
        if profissional_id not in self._equipe and antes.profissional_id not in self._equipe:
            return self._base.mover_agendamento_se_livre(agendamento_id, profissional_id, inicio, fim)
        self._espelhar(replace(antes, profissional_id=profissional_id, inicio=inicio, fim=fim))
        if not self._base.mover_agendamento_se_livre(agendamento_id, profissional_id, inicio, fim):
            self._espelhar(antes)  # volta o evento para o horário antigo
            return False
        return True

    def cancelar_agendamento(self, agendamento_id: str) -> None:
        agendamento = self._base.obter_agendamento(agendamento_id)
        if agendamento and agendamento.profissional_id in self._equipe:
            self._calendario.apagar(id_do_evento(agendamento_id))
        self._base.cancelar_agendamento(agendamento_id)

    def _espelhar(self, agendamento: Agendamento) -> None:
        if agendamento.profissional_id in self._equipe:
            self._calendario.gravar(id_do_evento(agendamento.id), self._corpo(agendamento))
        else:
            self._calendario.apagar(id_do_evento(agendamento.id))

    def _desfazer(self, evento_id: str) -> None:
        try:
            self._calendario.apagar(evento_id)
        except ErroGoogleAgenda:
            # Sobra um evento do agente no Google: ele não ocupa horário (é ignorado na leitura), só aparece.
            log.exception("Não consegui apagar o evento %s do Google Agenda", evento_id)

    def _corpo(self, a: Agendamento) -> dict:
        animal = self._base.obter_animal(a.animal_id)
        servico = self._base.obter_servico(a.servico_id)
        tutor = self._base.obter_tutor(animal.tutor_id)
        a_confirmar = a.status == StatusAgendamento.PENDENTE_JOYCE
        linhas = [
            f"Tutor: {tutor.nome} ({tutor.telefone})",
            f"Profissional: {self._base.nome_profissional(a.profissional_id) or a.profissional_id}",
            "Pré-agendamento: a recepção confirma o cadastro." if a_confirmar else "Confirmado com o tutor.",
            "Marcado pelo assistente do WhatsApp.",
        ]
        if a.observacao:
            linhas.append(f"Obs.: {a.observacao}")
        return {
            "summary": f"{'[A CONFIRMAR] ' if a_confirmar else ''}{servico.nome}: {animal.nome}",
            "description": "\n".join(linhas),
            "start": {"dateTime": a.inicio.isoformat(), "timeZone": str(FUSO_DA_CLINICA)},
            "end": {"dateTime": a.fim.isoformat(), "timeZone": str(FUSO_DA_CLINICA)},
            "status": "confirmed",  # reativa um evento apagado antes com o mesmo id
            "extendedProperties": {"private": {MARCA: a.id}},
        }
