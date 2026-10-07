"""Migrações e backup (Fase 1 de produção): o código que, se falhar, perde dado de cliente."""

import sqlite3
from datetime import date, datetime
from importlib import resources

import pytest

from patas.backup import fazer_backup, segundos_ate_o_proximo
from patas.repositorio.sqlite import aplicar_migracoes, conectar, criar_schema
from patas.seed import popular

INICIAL = resources.files("patas.repositorio").joinpath("migracoes", "0001_inicial.sql").read_text(encoding="utf-8")


def test_banco_novo_recebe_todas_e_a_segunda_subida_nao_reaplica():
    conn = conectar(":memory:")
    assert criar_schema(conn) == ["0001_inicial.sql"]
    assert criar_schema(conn) == []


def test_banco_de_antes_das_migracoes_e_reconhecido_sem_recriar():
    conn = conectar(":memory:")
    conn.executescript(INICIAL)  # como os bancos criados antes da Fase 1
    popular(conn, date(2026, 10, 6))
    assert criar_schema(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM tutor").fetchone()[0] == 9


def test_migracao_nova_preserva_os_dados():
    conn = conectar(":memory:")
    criar_schema(conn)
    popular(conn, date(2026, 10, 6))
    nova = ("0002_email_do_tutor.sql", "ALTER TABLE tutor ADD COLUMN email TEXT;")
    assert aplicar_migracoes(conn, [("0001_inicial.sql", INICIAL), nova]) == ["0002_email_do_tutor.sql"]
    assert conn.execute("SELECT COUNT(*) FROM tutor WHERE email IS NULL").fetchone()[0] == 9


def test_migracao_com_erro_nao_fica_pela_metade():
    conn = conectar(":memory:")
    criar_schema(conn)
    quebrada = ("0002_quebrada.sql", "CREATE TABLE nova (x INTEGER);\nINSERT INTO tabela_que_nao_existe VALUES (1);")
    with pytest.raises(sqlite3.OperationalError):
        aplicar_migracoes(conn, [("0001_inicial.sql", INICIAL), quebrada])
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'nova'").fetchone() is None
    assert conn.execute("SELECT COUNT(*) FROM schema_migracao").fetchone()[0] == 1
    assert not conn.in_transaction


def test_backup_copia_o_banco_e_guarda_so_os_mais_recentes(tmp_path):
    banco = tmp_path / "patas.db"
    conn = conectar(banco)
    criar_schema(conn)
    popular(conn, date(2026, 10, 6))
    conn.close()

    pasta = tmp_path / "backups"
    for minuto in range(3):
        ultimo = fazer_backup(banco, pasta, datetime(2026, 10, 6, 3, minuto), manter=2)
    assert sorted(p.name for p in pasta.iterdir()) == ["patas-20261006-0301.db", "patas-20261006-0302.db"]
    copia = sqlite3.connect(ultimo)
    assert copia.execute("SELECT COUNT(*) FROM tutor").fetchone()[0] == 9
    copia.close()


def test_horario_do_proximo_backup():
    assert segundos_ate_o_proximo(datetime(2026, 10, 6, 2, 0)) == 3600
    assert segundos_ate_o_proximo(datetime(2026, 10, 6, 4, 0)) == 23 * 3600
