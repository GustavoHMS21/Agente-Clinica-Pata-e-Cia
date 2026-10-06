"""Regras puras: sem banco, sem relógio, sem LLM.

Recebem tudo por parâmetro e devolvem um valor. Por isso são testadas direto,
em milissegundos, e não mudam quando o banco virar VetFácil.
"""

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from patas.dominio.modelos import Especie, Janela, Opcao, Porte, Tutor, Vacina

PASSO = timedelta(minutes=15)  # grade de horários: :00, :15, :30, :45
ANTECEDENCIA_ALTERAR = timedelta(hours=2)  # RN25
ANTECEDENCIA_MARCAR = timedelta(minutes=30)  # decisão do MVP: não oferecer horário que começa em menos de 30 min
LIMITE_FALTAS = 2  # RN26
MEIO_DIA = 12

# RN01: horário da clínica (dia_semana -> abre, fecha). Domingo não abre.
FUNCIONAMENTO = {0: (8, 19), 1: (8, 19), 2: (8, 19), 3: (8, 19), 4: (8, 19), 5: (8, 13)}

# RN08. Quais vacinas e com que validade é a pergunta P3 para a Beatriz.
VACINAS_EXIGIDAS_BANHO = {
    Especie.CAO: frozenset({"v10", "antirrabica"}),
    Especie.GATO: frozenset({"v5", "antirrabica"}),
}

Intervalo = tuple[datetime, datetime]


def porte_pelo_peso(peso_kg: float) -> Porte:
    """RN06. 'Até 10 kg' é P; o limite exato em 10 e 20 kg é a pergunta P2."""
    if peso_kg <= 10:
        return Porte.P
    if peso_kg <= 20:
        return Porte.M
    if peso_kg <= 35:
        return Porte.G
    return Porte.GG


def vacinas_pendentes(especie: Especie, vacinas: Iterable[Vacina], na_data: date) -> list[str]:
    """RN08. Vale a data do banho, não a de hoje: vacina que vence antes do horário já conta como pendente."""
    validas = {v.nome for v in vacinas if v.valida_ate >= na_data}
    return sorted(VACINAS_EXIGIDAS_BANHO[especie] - validas)


def bloqueado_por_faltas(tutor: Tutor) -> bool:
    """RN26."""
    return tutor.faltas_sem_aviso >= LIMITE_FALTAS


def pode_alterar(inicio_agendamento: datetime, agora: datetime) -> bool:
    """RN25: remarcar ou desmarcar só com pelo menos 2h de antecedência."""
    return inicio_agendamento - agora >= ANTECEDENCIA_ALTERAR


def dentro_do_funcionamento(momento: datetime) -> bool:
    """RN01, sem considerar feriado (o serviço de agenda checa o feriado no banco)."""
    horario = FUNCIONAMENTO.get(momento.weekday())
    return horario is not None and horario[0] <= momento.hour < horario[1]


def faixas_do_dia(dia: date, expediente: Iterable[Janela], janelas_servico: Iterable[Janela]) -> list[Intervalo]:
    """Faixas em que o profissional trabalha E o serviço é feito (RN01, RN03, RN07).

    Serviço sem janela própria vale o expediente inteiro.
    """
    janelas_servico = list(janelas_servico)
    faixas = []
    for exp in (j for j in expediente if j.dia_semana == dia.weekday()):
        restricoes = [j for j in janelas_servico if j.dia_semana == dia.weekday()] if janelas_servico else [exp]
        for r in restricoes:
            inicio, fim = max(exp.inicio, r.inicio), min(exp.fim, r.fim)
            if inicio < fim:
                faixas.append((datetime.combine(dia, inicio), datetime.combine(dia, fim)))
    return faixas


def sobrepoe(inicio: datetime, fim: datetime, ocupacoes: Iterable[Intervalo]) -> bool:
    # Encostar não é sobrepor: 10h-10h30 e 10h30-11h convivem.
    return any(inicio < o_fim and fim > o_inicio for o_inicio, o_fim in ocupacoes)


def na_grade(inicio: datetime) -> bool:
    return inicio.minute % 15 == 0 and inicio.second == 0 and inicio.microsecond == 0


def cabe(inicio: datetime, fim: datetime, faixas: Iterable[Intervalo], ocupacoes: Iterable[Intervalo]) -> bool:
    """O horário está na grade, dentro de uma faixa e não sobrepõe ninguém."""
    return (
        na_grade(inicio)
        and any(f_inicio <= inicio and fim <= f_fim for f_inicio, f_fim in faixas)
        and not sobrepoe(inicio, fim, ocupacoes)
    )


def inicios_livres(
    faixas: Iterable[Intervalo], duracao: timedelta, ocupacoes: list[Intervalo], nao_antes_de: datetime
) -> list[datetime]:
    livres = []
    for f_inicio, f_fim in faixas:
        t = f_inicio
        while t + duracao <= f_fim:
            if t >= nao_antes_de and not sobrepoe(t, t + duracao, ocupacoes):
                livres.append(t)
            t += PASSO
    return livres


def turno(momento: datetime) -> str:
    return "manha" if momento.hour < MEIO_DIA else "tarde"


def espalhar(opcoes: Iterable[Opcao], limite: int) -> list[Opcao]:
    """Uma opção por turno de cada dia, em ordem: '10h ou 14h30' (C2), não '8h, 8h15, 8h30'."""
    escolhidas, vistos = [], set()
    for opcao in sorted(opcoes, key=lambda o: o.inicio):
        chave = (opcao.inicio.date(), turno(opcao.inicio))
        if chave not in vistos:
            vistos.add(chave)
            escolhidas.append(opcao)
            if len(escolhidas) == limite:
                break
    return escolhidas
