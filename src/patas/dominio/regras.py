"""Regras puras: sem banco, sem relógio, sem LLM.

Recebem tudo por parâmetro e devolvem um valor. Por isso são testadas direto,
em milissegundos, e não mudam quando o banco virar VetFácil.
"""

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from patas.dominio.modelos import Especie, Janela, Opcao, Porte, Tutor, Vacina

PASSO = timedelta(minutes=15)  # grade de horários: :00, :15, :30, :45
EM_CIMA_DA_HORA = timedelta(hours=2)  # RN25 (P4): menos que isso pode, mas a Joyce fica sabendo para encaixar alguém
ANTECEDENCIA_MARCAR = timedelta(minutes=30)  # decisão do MVP: não oferecer horário que começa em menos de 30 min
LIMITE_FALTAS = 2  # RN26
MEIO_DIA = 12

# RN01: horário da clínica (dia_semana -> abre, fecha). Domingo não abre.
FUNCIONAMENTO = {0: (8, 19), 1: (8, 19), 2: (8, 19), 3: (8, 19), 4: (8, 19), 5: (8, 13)}

# RN08 (P3): obrigatórias para banho, por grupo de equivalência. Basta uma vacina válida de cada grupo:
# V8 vale como V10, V4 vale como V5. Gripe e giárdia são recomendadas, não obrigatórias.
VACINAS_EXIGIDAS_BANHO = {
    Especie.CAO: (("v10", "v8"), ("antirrabica",)),
    Especie.GATO: (("v5", "v4"), ("antirrabica",)),
}

Intervalo = tuple[datetime, datetime]


def porte_pelo_peso(peso_kg: float) -> Porte:
    """RN06 (P2): "até" inclui o número. 10 kg é P; de 10,1 a 20 é M; de 20,1 a 35 é G; acima de 35, GG."""
    if peso_kg <= 10:
        return Porte.P
    if peso_kg <= 20:
        return Porte.M
    if peso_kg <= 35:
        return Porte.G
    return Porte.GG


def vence_em(aplicada_em: date) -> date:
    """P3: toda vacina vale 1 ano a partir da data de aplicação."""
    try:
        return aplicada_em.replace(year=aplicada_em.year + 1)
    except ValueError:  # aplicada em 29/02
        return aplicada_em.replace(year=aplicada_em.year + 1, day=28)


def vacinas_pendentes(especie: Especie, vacinas: Iterable[Vacina], na_data: date) -> list[str]:
    """RN08. Vale a data do banho, não a de hoje: vacina que vence antes do horário já conta como pendente.

    Devolve o nome principal de cada grupo sem vacina válida (ex.: "v10", mesmo que a V8 resolvesse).
    """
    validas = {v.nome for v in vacinas if vence_em(v.aplicada_em) >= na_data}
    return sorted(grupo[0] for grupo in VACINAS_EXIGIDAS_BANHO[especie] if not validas & set(grupo))


def bloqueado_por_faltas(tutor: Tutor) -> bool:
    """RN26."""
    return tutor.faltas_sem_aviso >= LIMITE_FALTAS


def pode_alterar(inicio_agendamento: datetime, agora: datetime) -> bool:
    """RN25 (P4): remarcar ou desmarcar pode enquanto o horário não começou. Não conta como falta."""
    return inicio_agendamento > agora


def em_cima_da_hora(inicio_agendamento: datetime, agora: datetime) -> bool:
    """RN25 (P4): com menos de 2h, a Joyce precisa saber para tentar colocar outro no lugar."""
    return inicio_agendamento - agora < EM_CIMA_DA_HORA


def dentro_do_funcionamento(momento: datetime, dia_especial: Janela | None = None) -> bool:
    """RN01. dia_especial: horário reduzido do dia (Carnaval, 24 e 31/12); dia fechado é checado antes."""
    horario = FUNCIONAMENTO.get(momento.weekday())
    if horario is None or not horario[0] <= momento.hour < horario[1]:
        return False
    return dia_especial is None or dia_especial.inicio <= momento.time() < dia_especial.fim


def faixas_do_dia(
    dia: date, expediente: Iterable[Janela], janelas_servico: Iterable[Janela], dia_especial: Janela | None = None
) -> list[Intervalo]:
    """Faixas em que o profissional trabalha E o serviço é feito E a clínica está aberta (RN01, RN03, RN07, P8).

    Serviço sem janela própria vale o expediente inteiro. dia_especial corta o dia (ex.: quarta de Cinzas
    a partir das 12h, 24/12 até as 12h); dia totalmente fechado nem chega aqui.
    """
    janelas_servico = list(janelas_servico)
    faixas = []
    for exp in (j for j in expediente if j.dia_semana == dia.weekday()):
        restricoes = [j for j in janelas_servico if j.dia_semana == dia.weekday()] if janelas_servico else [exp]
        for r in restricoes:
            inicio, fim = max(exp.inicio, r.inicio), min(exp.fim, r.fim)
            if dia_especial is not None:
                inicio, fim = max(inicio, dia_especial.inicio), min(fim, dia_especial.fim)
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
