"""Cria o banco do MVP com os dados da tabela de preços e tutores fictícios das conversas.

Datas de vacinas e agendamentos são relativas a `hoje`, para a demonstração
funcionar em qualquer dia. Cada tutor existe para exercitar um caso das regras.

Uso: uv run python -m patas.seed [--recriar]
"""

import argparse
import sqlite3
import sys
from datetime import date, datetime, timedelta

from patas.config import agora_local, caminho_banco
from patas.repositorio.sqlite import conectar, criar_schema

SEG_A_SEX = range(0, 5)
SABADO = 5
QUINTA = 3
TERCA = 1

PROFISSIONAIS = [
    ("vet_beatriz", "Dra. Beatriz", "veterinaria"),
    ("vet_camila", "Dra. Camila", "veterinaria"),
    ("vet_paula", "Dra. Paula", "veterinaria"),
    ("tosa_a", "Tosadora A", "tosadora"),  # nomes das tosadoras não vieram na descoberta
    ("tosa_b", "Tosadora B", "tosadora"),
]
VETERINARIAS = ["vet_beatriz", "vet_camila", "vet_paula"]
TOSADORAS = ["tosa_a", "tosa_b"]

# Feriados nacionais e de Guarulhos. Confirmar a lista com a Beatriz.
FERIADOS = [
    ("2026-10-12", "Nossa Senhora Aparecida"),
    ("2026-11-02", "Finados"),
    ("2026-11-15", "Proclamação da República"),
    ("2026-11-20", "Consciência Negra"),
    ("2026-12-08", "Aniversário de Guarulhos"),
    ("2026-12-25", "Natal"),
    ("2027-01-01", "Confraternização Universal"),
]

# (id, nome, categoria, especie, agendavel, preco_centavos, duracao_min)
SERVICOS = [
    ("consulta_clinica", "Consulta clínica geral", "consulta", None, 1, 16000, 30),
    ("consulta_dermato", "Consulta com dermatologista", "consulta", None, 1, 23000, 30),
    ("consulta_felinos", "Consulta de felinos", "consulta", "gato", 1, 17000, 30),
    ("retorno", "Retorno em até 15 dias", "consulta", None, 0, 0, 30),
    ("vacina_v10", "Vacina V10", "vacina", "cao", 1, 9500, 15),
    ("vacina_antirrabica", "Vacina antirrábica", "vacina", None, 1, 6500, 15),
    ("vacina_gripe", "Vacina gripe canina", "vacina", "cao", 1, 11500, 15),
    ("vacina_giardia", "Vacina giárdia", "vacina", "cao", 1, 11000, 15),
    ("vacina_v5", "Vacina V5", "vacina", "gato", 1, 12000, 15),
    ("hemograma", "Hemograma", "exame", None, 0, 7500, None),
    ("bioquimico", "Bioquímico (perfil renal e hepático)", "exame", None, 0, 14000, None),
    ("ultrassom", "Ultrassom", "exame", None, 0, 22000, None),
    ("castracao", "Castração", "outros", None, 0, None, None),
    ("banho", "Banho", "banho_tosa", "cao", 1, None, None),
    ("banho_tosa_higienica", "Banho + tosa higiênica", "banho_tosa", "cao", 1, None, None),
    ("banho_tosa_completa", "Banho + tosa completa", "banho_tosa", "cao", 1, None, None),
    ("banho_gato", "Banho de gato", "banho_tosa", "gato", 1, 11000, 60),  # duração não informada: 60 min
    ("corte_unha", "Corte de unha avulso", "banho_tosa", None, 1, 3000, 15),  # duração não informada: 15 min
    ("hidratacao", "Hidratação (adicional)", "banho_tosa", "cao", 0, 3500, None),
    ("taxi_dog", "Táxi dog (cada trecho, até 5 km)", "outros", None, 0, 2000, None),
    ("taxa_pulga", "Taxa de pulga ou carrapato", "outros", None, 0, 4000, None),
]

# Banho e tosa por porte: (servico_id, {porte: (preco_centavos, duracao_min)})
DURACAO_PORTE = {"P": 60, "M": 90, "G": 120, "GG": 150}
PRECOS_PORTE = {
    "banho": {"P": 6500, "M": 8000, "G": 10000, "GG": 13000},
    "banho_tosa_higienica": {"P": 8500, "M": 10000, "G": 12500, "GG": 15500},
    "banho_tosa_completa": {"P": 9500, "M": 12000, "G": 15000, "GG": 19000},
}
EXTRA_TOSA_COMPLETA_MIN = 30

# (servico_id, dia_semana, inicio, fim)
JANELAS = [
    ("consulta_dermato", QUINTA, "13:00", "19:00"),  # RN03
    ("banho_gato", TERCA, "08:00", "12:00"),  # RN07
    ("banho_gato", QUINTA, "08:00", "12:00"),
]

QUEM_FAZ = {
    "consulta_clinica": VETERINARIAS,
    "consulta_dermato": ["vet_paula"],
    "consulta_felinos": ["vet_camila"],  # RN04, ver P1
    "vacina_v10": VETERINARIAS,
    "vacina_antirrabica": VETERINARIAS,
    "vacina_gripe": VETERINARIAS,
    "vacina_giardia": VETERINARIAS,
    "vacina_v5": VETERINARIAS,
    "banho": TOSADORAS,
    "banho_tosa_higienica": TOSADORAS,
    "banho_tosa_completa": TOSADORAS,
    "banho_gato": TOSADORAS,
    "corte_unha": TOSADORAS,
}


def proximo_dia_util(base: date, n: int, feriados: set[date]) -> date:
    """O n-ésimo dia de segunda a sexta depois de `base`, pulando feriados."""
    dia, contados = base, 0
    while contados < n:
        dia += timedelta(days=1)
        if dia.weekday() in SEG_A_SEX and dia not in feriados:
            contados += 1
    return dia


def popular(conn: sqlite3.Connection, hoje: date) -> None:
    feriados = {date.fromisoformat(d) for d, _ in FERIADOS}
    d1 = proximo_dia_util(hoje, 1, feriados)
    d2 = proximo_dia_util(hoje, 2, feriados)

    def dias(n: int) -> str:
        return (hoje + timedelta(days=n)).isoformat()

    def em(dia: date, hora: str, minutos: int) -> tuple[str, str]:
        inicio = datetime.fromisoformat(f"{dia.isoformat()}T{hora}")
        return inicio.isoformat(timespec="minutes"), (inicio + timedelta(minutes=minutos)).isoformat(timespec="minutes")

    agora = datetime.combine(hoje, datetime.min.time()).isoformat(timespec="minutes")

    conn.execute("BEGIN")
    conn.executemany("INSERT INTO profissional VALUES (?, ?, ?)", PROFISSIONAIS)
    for pid, _, _ in PROFISSIONAIS:
        conn.executemany(
            "INSERT INTO expediente VALUES (?, ?, ?, ?)",
            [(pid, d, "08:00", "19:00") for d in SEG_A_SEX] + [(pid, SABADO, "08:00", "13:00")],
        )
    conn.executemany("INSERT INTO feriado VALUES (?, ?)", FERIADOS)

    conn.executemany("INSERT INTO servico VALUES (?, ?, ?, ?, ?, ?, ?)", SERVICOS)
    for servico_id, precos in PRECOS_PORTE.items():
        extra = EXTRA_TOSA_COMPLETA_MIN if servico_id == "banho_tosa_completa" else 0
        conn.executemany(
            "INSERT INTO servico_porte VALUES (?, ?, ?, ?)",
            [(servico_id, porte, preco, DURACAO_PORTE[porte] + extra) for porte, preco in precos.items()],
        )
    conn.executemany("INSERT INTO servico_janela VALUES (?, ?, ?, ?)", JANELAS)
    conn.executemany(
        "INSERT INTO servico_profissional VALUES (?, ?)",
        [(s, p) for s, pessoas in QUEM_FAZ.items() for p in pessoas],
    )

    # (id, nome, telefone, faltas_sem_aviso). Telefones fictícios das conversas.
    conn.executemany(
        "INSERT INTO tutor (id, nome, telefone, faltas_sem_aviso) VALUES (?, ?, ?, ?)",
        [
            ("t_mariana", "Mariana Lopes", "5511900001101", 0),  # C1: banho porte G, tudo em dia
            ("t_rodrigo", "Rodrigo Teles", "5511900001102", 0),  # C2: vacina já marcada
            ("t_carlos", "Carlos Henrique", "5511900001104", 2),  # RN26: duas faltas, bloqueado
            ("t_patricia", "Patrícia Nogueira", "5511900001105", 0),  # C5: banho para remarcar
            ("t_ana", "Ana Clara", "5511900001106", 0),  # C6: gato com vacina vencida
            ("t_debora", "Débora Santos", "5511900001108", 0),  # C8: pergunta de exame
            ("t_rafael", "Rafael Duarte", "5511900001111", 0),  # C11: tenta cancelar o Max
            ("t_cristina", "Cristina Duarte", "5511900001199", 0),  # C11: dona do Max
            ("t_vanessa", "Vanessa Ribeiro", "5511900001114", 0),  # C14: GG, filhote novo
        ],
    )
    # Larissa (C10, 5511900001110) e o número da C15 ficam de fora: números desconhecidos.

    # (id, tutor_id, nome, especie, peso_kg, tem_historico)
    conn.executemany(
        "INSERT INTO animal (id, tutor_id, nome, especie, peso_kg, tem_historico) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("a_thor", "t_mariana", "Thor", "cao", 32.0, 1),
            ("a_mel", "t_rodrigo", "Mel", "cao", 8.5, 1),
            ("a_mimi", "t_carlos", "Mimi", "gato", 3.8, 1),
            ("a_luna", "t_patricia", "Luna", "cao", 7.0, 1),
            ("a_frajola", "t_ana", "Frajola", "gato", 4.5, 1),
            ("a_pipoca", "t_debora", "Pipoca", "cao", 9.0, 1),
            ("a_nina", "t_rafael", "Nina", "cao", 12.0, 1),
            ("a_max", "t_cristina", "Max", "cao", 25.0, 1),
            ("a_zeus", "t_vanessa", "Zeus", "cao", 41.0, 1),
            ("a_bolt", "t_vanessa", "Bolt", "cao", None, 0),  # RN09 e RN06: sem histórico e sem peso
        ],
    )

    # (animal_id, nome, aplicada_em, valida_ate)
    conn.executemany(
        "INSERT INTO vacina (animal_id, nome, aplicada_em, valida_ate) VALUES (?, ?, ?, ?)",
        [
            ("a_thor", "v10", dias(-165), dias(200)),
            ("a_thor", "antirrabica", dias(-215), dias(150)),
            ("a_mel", "v10", dias(-245), dias(120)),
            ("a_mel", "antirrabica", dias(-368), dias(-3)),  # C2: venceu, vacina já marcada
            ("a_luna", "v10", dias(-100), dias(265)),
            ("a_luna", "antirrabica", dias(-100), dias(265)),
            ("a_frajola", "v5", dias(-400), dias(-35)),  # C6: vencida
            ("a_frajola", "antirrabica", dias(-400), dias(-35)),
            ("a_nina", "v10", dias(-30), dias(335)),
            ("a_max", "v10", dias(-60), dias(305)),
            ("a_zeus", "v10", dias(-20), dias(345)),
            ("a_zeus", "antirrabica", dias(-20), dias(345)),
        ],
    )

    # (id, animal_id, servico_id, profissional_id, inicio/fim, preco_centavos)
    agendamentos = [
        ("ag_mel", "a_mel", "vacina_antirrabica", "vet_beatriz", em(d1, "14:30", 15), 6500),
        ("ag_luna", "a_luna", "banho_tosa_higienica", "tosa_a", em(d1, "09:00", 60), 8500),
        ("ag_nina", "a_nina", "consulta_clinica", "vet_paula", em(d1, "10:00", 30), 16000),
        ("ag_max", "a_max", "consulta_clinica", "vet_beatriz", em(d2, "15:00", 30), 16000),
    ]
    conn.executemany(
        "INSERT INTO agendamento (id, animal_id, servico_id, profissional_id, inicio, fim, status,"
        " preco_centavos, criado_em) VALUES (?, ?, ?, ?, ?, ?, 'confirmado', ?, ?)",
        [(i, a, s, p, ini, fim, preco, agora) for i, a, s, p, (ini, fim), preco in agendamentos],
    )
    conn.execute("COMMIT")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cria o banco do MVP com dados fictícios.")
    parser.add_argument("--recriar", action="store_true", help="apaga o banco existente antes")
    args = parser.parse_args()

    caminho = caminho_banco()
    if caminho.exists():
        if not args.recriar:
            print(f"{caminho} já existe. Use --recriar para apagar e criar de novo.")
            return 1
        caminho.unlink()
    caminho.parent.mkdir(parents=True, exist_ok=True)

    conn = conectar(caminho)
    criar_schema(conn)
    popular(conn, agora_local().date())  # data de Guarulhos, não a do servidor (que pode estar em UTC)
    conn.close()
    print(f"Banco criado em {caminho}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
