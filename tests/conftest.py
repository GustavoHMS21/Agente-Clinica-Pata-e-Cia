from datetime import date

import pytest

from patas.repositorio.sqlite import AgendaSQLite, conectar, criar_schema
from patas.seed import popular

# Terça-feira. Com o seed, o próximo dia útil é quarta 07/10 e o seguinte quinta 08/10.
HOJE = date(2026, 10, 6)


@pytest.fixture
def conn():
    conexao = conectar(":memory:")
    criar_schema(conexao)
    popular(conexao, HOJE)
    yield conexao
    conexao.close()


@pytest.fixture
def agenda(conn):
    return AgendaSQLite(conn)
