"""Interfaces de dados que o domínio enxerga.

O domínio nunca importa sqlite3. Ele recebe um objeto que cumpre estes contratos:
no MVP, as classes de repositorio/sqlite.py; no futuro, adaptadores para o VetFácil
e o Google Agenda (ADR 0001, decisão já tomada na descoberta).
"""

from datetime import date, datetime
from typing import Protocol

from patas.dominio.modelos import (
    Agendamento,
    Animal,
    Especie,
    Janela,
    Passagem,
    Proposta,
    Servico,
    Tutor,
    Vacina,
)


class RepositorioAgenda(Protocol):
    """O que hoje vive no VetFácil (ficha, vacinas, consultas) e no Google Agenda (banho)."""

    def buscar_tutor_por_telefone(self, telefone: str) -> Tutor | None: ...
    def obter_tutor(self, tutor_id: str) -> Tutor | None: ...
    def listar_animais(self, tutor_id: str) -> list[Animal]: ...
    def obter_animal(self, animal_id: str) -> Animal | None: ...
    def listar_vacinas(self, animal_id: str) -> list[Vacina]: ...

    def listar_servicos(self, categoria: str | None = None) -> list[Servico]: ...
    def obter_servico(self, servico_id: str) -> Servico | None: ...
    def listar_expediente(self, profissional_id: str) -> list[Janela]: ...
    def nome_profissional(self, profissional_id: str) -> str | None: ...
    def listar_feriados(self, de: date, ate: date) -> set[date]: ...

    def listar_ocupacoes(self, profissional_ids: list[str], de: datetime, ate: datetime) -> list[Agendamento]:
        """Agendamentos não cancelados que se sobrepõem a [de, ate)."""
        ...

    def listar_agendamentos_futuros(self, tutor_id: str, a_partir_de: datetime) -> list[Agendamento]: ...
    def obter_agendamento(self, agendamento_id: str) -> Agendamento | None: ...

    def criar_tutor_provisorio(self, nome: str, telefone: str) -> Tutor: ...
    def criar_animal(
        self, tutor_id: str, nome: str, especie: Especie, peso_kg: float | None, provisorio: bool
    ) -> Animal: ...

    def inserir_agendamento_se_livre(self, agendamento: Agendamento) -> Agendamento | None:
        """Insere se o profissional estiver livre. Atômico.

        Devolve None quando há conflito. Se já existe agendamento com o mesmo
        proposta_id, devolve o existente sem inserir de novo (idempotência).
        """
        ...

    def mover_agendamento_se_livre(
        self, agendamento_id: str, profissional_id: str, inicio: datetime, fim: datetime
    ) -> bool:
        """Remarca se o novo horário estiver livre (ignorando o próprio agendamento). Atômico."""
        ...

    def cancelar_agendamento(self, agendamento_id: str) -> None: ...


class RepositorioAtendimento(Protocol):
    """Dados do próprio atendimento. Sempre no nosso banco, mesmo com VetFácil integrado."""

    def salvar_proposta(self, proposta: Proposta) -> None: ...
    def obter_proposta(self, proposta_id: str) -> Proposta | None: ...
    def marcar_proposta_usada(self, proposta_id: str, agendamento_id: str | None, quando: datetime) -> None: ...
    def registrar_passagem(self, passagem: Passagem) -> None: ...
