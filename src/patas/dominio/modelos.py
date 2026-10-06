"""Entidades do domínio.

Dataclasses imutáveis, sem regra de negócio: as regras (RN01 a RN27) ficam no
serviço de agenda. Datas no horário local de Guarulhos, dinheiro em centavos.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import StrEnum


class Especie(StrEnum):
    CAO = "cao"
    GATO = "gato"


class Porte(StrEnum):
    P = "P"
    M = "M"
    G = "G"
    GG = "GG"


class StatusAgendamento(StrEnum):
    CONFIRMADO = "confirmado"
    PENDENTE_JOYCE = "pendente_joyce"  # pré-agendamento (RN24)
    CANCELADO = "cancelado"


class TipoProposta(StrEnum):
    AGENDAMENTO = "agendamento"
    PRE_AGENDAMENTO = "pre_agendamento"
    REMARCACAO = "remarcacao"
    CANCELAMENTO = "cancelamento"


@dataclass(frozen=True)
class Tutor:
    id: str
    nome: str
    telefone: str  # só dígitos, com DDI: 5511900001102
    faltas_sem_aviso: int = 0
    provisorio: bool = False  # criado por pré-agendamento; a Joyce completa


@dataclass(frozen=True)
class Animal:
    id: str
    tutor_id: str
    nome: str
    especie: Especie
    peso_kg: float | None
    tem_historico: bool  # já passou em consulta aqui (RN09)
    provisorio: bool = False


@dataclass(frozen=True)
class Vacina:
    animal_id: str
    nome: str
    aplicada_em: date
    valida_ate: date


@dataclass(frozen=True)
class Janela:
    """Faixa de horário num dia da semana. dia_semana segue date.weekday(): 0 = segunda."""

    dia_semana: int
    inicio: time
    fim: time


@dataclass(frozen=True)
class PrecoPorte:
    porte: Porte
    preco_centavos: int
    duracao_min: int


@dataclass(frozen=True)
class Servico:
    id: str
    nome: str
    categoria: str
    agendavel: bool  # False: o agente informa e passa para a Joyce
    especie: Especie | None = None  # None: cão e gato
    preco_centavos: int | None = None  # None: preço por porte ou sob orçamento
    duracao_min: int | None = None
    precos_por_porte: tuple[PrecoPorte, ...] = ()
    janelas: tuple[Janela, ...] = ()  # vazio: vale o expediente inteiro
    profissionais: tuple[str, ...] = ()


@dataclass(frozen=True)
class Agendamento:
    id: str
    animal_id: str
    servico_id: str
    profissional_id: str
    inicio: datetime
    fim: datetime
    status: StatusAgendamento
    preco_centavos: int
    criado_em: datetime
    proposta_id: str | None = None  # chave de idempotência da confirmação


@dataclass(frozen=True)
class Proposta:
    id: str
    conversa_id: str
    tipo: TipoProposta
    dados: dict = field(hash=False)  # o que será executado na confirmação (ADR 0002)
    turno: int
    criada_em: datetime
    expira_em: datetime
    usada_em: datetime | None = None
    agendamento_id: str | None = None


@dataclass(frozen=True)
class Passagem:
    """Passagem da conversa para a Joyce."""

    protocolo: str
    conversa_id: str
    tutor_id: str | None
    motivo: str
    urgente: bool
    resumo: str
    criada_em: datetime
