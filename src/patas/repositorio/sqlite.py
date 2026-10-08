"""Implementação SQLite das interfaces de repositorio/interface.py.

No MVP, um arquivo só guarda a agenda e o atendimento. Toda consulta usa
parâmetros (?), nunca texto montado com f-string: isso fecha a porta para SQL injection.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time
from importlib import resources
from pathlib import Path

from patas.dominio.ids import novo_id
from patas.dominio.modelos import (
    Agendamento,
    Animal,
    Conversa,
    Especie,
    Execucao,
    Janela,
    Mensagem,
    Papel,
    Passagem,
    Porte,
    PrecoPorte,
    Proposta,
    Servico,
    StatusAgendamento,
    TipoProposta,
    Tutor,
    Vacina,
)


def conectar(caminho: Path | str) -> sqlite3.Connection:
    # isolation_level=None: leitura em autocommit; escrita abre transação explícita (transacao()).
    conn = sqlite3.connect(caminho, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def criar_schema(conn: sqlite3.Connection) -> list[str]:
    """Leva o banco à versão mais recente aplicando as migrações pendentes (ADR 0011).

    Seguro de chamar a cada subida do servidor: o que já foi aplicado não roda de novo.
    Devolve os nomes das migrações aplicadas agora.
    """
    pasta = resources.files("patas.repositorio").joinpath("migracoes")
    arquivos = sorted((p.name, p.read_text(encoding="utf-8")) for p in pasta.iterdir() if p.name.endswith(".sql"))
    return aplicar_migracoes(conn, arquivos)


def aplicar_migracoes(conn: sqlite3.Connection, migracoes: list[tuple[str, str]]) -> list[str]:
    """Aplica, em ordem, as migrações (nome, sql) ainda não registradas. Cada uma é tudo ou nada.

    No SQLite, ALTER TABLE só acrescenta colunas; mudar CHECK ou tipo exige recriar a tabela
    dentro da migração (criar nova, copiar, apagar a antiga, renomear).
    """
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migracao (versao TEXT PRIMARY KEY, aplicada_em TEXT NOT NULL)")
    aplicadas = {r[0] for r in conn.execute("SELECT versao FROM schema_migracao")}
    if not aplicadas and conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'tutor'").fetchone():
        # Banco criado antes das migrações existirem: já está na versão inicial.
        aplicadas = {migracoes[0][0]}
        conn.execute("INSERT INTO schema_migracao VALUES (?, datetime('now'))", (migracoes[0][0],))

    novas = []
    for nome, sql in migracoes:
        if nome in aplicadas:
            continue
        try:
            conn.executescript("BEGIN;\n" + sql)  # DDL no SQLite é transacional: falhou, nada fica pela metade
            conn.execute("INSERT INTO schema_migracao VALUES (?, datetime('now'))", (nome,))
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        novas.append(nome)
    return novas


@contextmanager
def transacao(conn: sqlite3.Connection) -> Iterator[None]:
    """BEGIN IMMEDIATE trava a escrita no início: duas confirmações nunca checam conflito ao mesmo tempo."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _dt(valor: datetime) -> str:
    return valor.isoformat(timespec="minutes")


def _ler_dt(texto: str | None) -> datetime | None:
    return datetime.fromisoformat(texto) if texto else None


def _tutor(r: sqlite3.Row) -> Tutor:
    return Tutor(r["id"], r["nome"], r["telefone"], r["faltas_sem_aviso"], bool(r["provisorio"]))


def _animal(r: sqlite3.Row) -> Animal:
    return Animal(
        r["id"], r["tutor_id"], r["nome"], Especie(r["especie"]), r["peso_kg"],
        bool(r["tem_historico"]), bool(r["provisorio"]),
    )


def _janela(r: sqlite3.Row) -> Janela:
    return Janela(r["dia_semana"], time.fromisoformat(r["inicio"]), time.fromisoformat(r["fim"]))


def _agendamento(r: sqlite3.Row) -> Agendamento:
    return Agendamento(
        id=r["id"],
        animal_id=r["animal_id"],
        servico_id=r["servico_id"],
        profissional_id=r["profissional_id"],
        inicio=datetime.fromisoformat(r["inicio"]),
        fim=datetime.fromisoformat(r["fim"]),
        status=StatusAgendamento(r["status"]),
        preco_centavos=r["preco_centavos"],
        criado_em=datetime.fromisoformat(r["criado_em"]),
        proposta_id=r["proposta_id"],
        observacao=r["observacao"],
    )


class AgendaSQLite:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # Tutores e animais -------------------------------------------------------

    def buscar_tutor_por_telefone(self, telefone: str) -> Tutor | None:
        r = self._conn.execute("SELECT * FROM tutor WHERE telefone = ?", (telefone,)).fetchone()
        return _tutor(r) if r else None

    def obter_tutor(self, tutor_id: str) -> Tutor | None:
        r = self._conn.execute("SELECT * FROM tutor WHERE id = ?", (tutor_id,)).fetchone()
        return _tutor(r) if r else None

    def listar_animais(self, tutor_id: str) -> list[Animal]:
        rows = self._conn.execute("SELECT * FROM animal WHERE tutor_id = ? ORDER BY nome", (tutor_id,))
        return [_animal(r) for r in rows]

    def obter_animal(self, animal_id: str) -> Animal | None:
        r = self._conn.execute("SELECT * FROM animal WHERE id = ?", (animal_id,)).fetchone()
        return _animal(r) if r else None

    def listar_vacinas(self, animal_id: str) -> list[Vacina]:
        rows = self._conn.execute(
            "SELECT * FROM vacina WHERE animal_id = ? ORDER BY aplicada_em DESC", (animal_id,)
        )
        return [Vacina(r["animal_id"], r["nome"], date.fromisoformat(r["aplicada_em"])) for r in rows]

    def criar_tutor_provisorio(self, nome: str, telefone: str) -> Tutor:
        tutor = Tutor(novo_id("t"), nome, telefone, provisorio=True)
        self._conn.execute(
            "INSERT INTO tutor (id, nome, telefone, provisorio) VALUES (?, ?, ?, 1)",
            (tutor.id, tutor.nome, tutor.telefone),
        )
        return tutor

    def criar_animal(
        self, tutor_id: str, nome: str, especie: Especie, peso_kg: float | None, provisorio: bool
    ) -> Animal:
        animal = Animal(novo_id("a"), tutor_id, nome, especie, peso_kg, tem_historico=False, provisorio=provisorio)
        self._conn.execute(
            "INSERT INTO animal (id, tutor_id, nome, especie, peso_kg, tem_historico, provisorio)"
            " VALUES (?, ?, ?, ?, ?, 0, ?)",
            (animal.id, tutor_id, nome, especie.value, peso_kg, int(provisorio)),
        )
        return animal

    # Serviços, profissionais e calendário ------------------------------------

    def listar_servicos(self, categoria: str | None = None) -> list[Servico]:
        if categoria:
            rows = self._conn.execute("SELECT id FROM servico WHERE categoria = ? ORDER BY nome", (categoria,))
        else:
            rows = self._conn.execute("SELECT id FROM servico ORDER BY categoria, nome")
        return [s for r in rows.fetchall() if (s := self.obter_servico(r["id"]))]

    def obter_servico(self, servico_id: str) -> Servico | None:
        r = self._conn.execute("SELECT * FROM servico WHERE id = ?", (servico_id,)).fetchone()
        if not r:
            return None
        portes = self._conn.execute(
            "SELECT * FROM servico_porte WHERE servico_id = ? ORDER BY preco_centavos", (servico_id,)
        )
        janelas = self._conn.execute(
            "SELECT * FROM servico_janela WHERE servico_id = ? ORDER BY dia_semana, inicio", (servico_id,)
        )
        profissionais = self._conn.execute(
            "SELECT profissional_id FROM servico_profissional WHERE servico_id = ? ORDER BY profissional_id",
            (servico_id,),
        )
        return Servico(
            id=r["id"],
            nome=r["nome"],
            categoria=r["categoria"],
            agendavel=bool(r["agendavel"]),
            especie=Especie(r["especie"]) if r["especie"] else None,
            preco_centavos=r["preco_centavos"],
            duracao_min=r["duracao_min"],
            precos_por_porte=tuple(PrecoPorte(Porte(p["porte"]), p["preco_centavos"], p["duracao_min"]) for p in portes),
            janelas=tuple(_janela(j) for j in janelas),
            profissionais=tuple(p["profissional_id"] for p in profissionais),
        )

    def listar_expediente(self, profissional_id: str) -> list[Janela]:
        rows = self._conn.execute(
            "SELECT * FROM expediente WHERE profissional_id = ? ORDER BY dia_semana, inicio", (profissional_id,)
        )
        return [_janela(r) for r in rows]

    def nome_profissional(self, profissional_id: str) -> str | None:
        r = self._conn.execute("SELECT nome FROM profissional WHERE id = ?", (profissional_id,)).fetchone()
        return r["nome"] if r else None

    def tipo_profissional(self, profissional_id: str) -> str | None:
        r = self._conn.execute("SELECT tipo FROM profissional WHERE id = ?", (profissional_id,)).fetchone()
        return r["tipo"] if r else None

    def listar_dias_especiais(self, de: date, ate: date) -> dict[date, Janela | None]:
        rows = self._conn.execute(
            "SELECT data, abre, fecha FROM feriado WHERE data BETWEEN ? AND ?", (de.isoformat(), ate.isoformat())
        )
        dias: dict[date, Janela | None] = {}
        for r in rows:
            dia = date.fromisoformat(r["data"])
            if r["abre"] is None and r["fecha"] is None:
                dias[dia] = None
            else:
                dias[dia] = Janela(dia.weekday(), time.fromisoformat(r["abre"] or "00:00"),
                                   time.fromisoformat(r["fecha"] or "23:59"))
        return dias

    # Agendamentos ------------------------------------------------------------

    def listar_ocupacoes(self, profissional_ids: list[str], de: datetime, ate: datetime) -> list[Agendamento]:
        if not profissional_ids:
            return []
        # A f-string abaixo só monta "?, ?, ?". Os valores continuam indo como parâmetros.
        marcadores = ", ".join("?" for _ in profissional_ids)
        rows = self._conn.execute(
            f"SELECT * FROM agendamento WHERE status != 'cancelado' AND profissional_id IN ({marcadores})"
            " AND inicio < ? AND fim > ? ORDER BY inicio",
            (*profissional_ids, _dt(ate), _dt(de)),
        )
        return [_agendamento(r) for r in rows]

    def listar_agendamentos_futuros(self, tutor_id: str, a_partir_de: datetime) -> list[Agendamento]:
        rows = self._conn.execute(
            "SELECT ag.* FROM agendamento ag JOIN animal an ON an.id = ag.animal_id"
            " WHERE an.tutor_id = ? AND ag.status != 'cancelado' AND ag.inicio >= ? ORDER BY ag.inicio",
            (tutor_id, _dt(a_partir_de)),
        )
        return [_agendamento(r) for r in rows]

    def obter_agendamento(self, agendamento_id: str) -> Agendamento | None:
        r = self._conn.execute("SELECT * FROM agendamento WHERE id = ?", (agendamento_id,)).fetchone()
        return _agendamento(r) if r else None

    def inserir_agendamento_se_livre(self, agendamento: Agendamento) -> Agendamento | None:
        a = agendamento
        with transacao(self._conn):
            if a.proposta_id:
                r = self._conn.execute(
                    "SELECT * FROM agendamento WHERE proposta_id = ?", (a.proposta_id,)
                ).fetchone()
                if r:
                    return _agendamento(r)
            if self._tem_conflito(a.profissional_id, a.inicio, a.fim):
                return None
            self._conn.execute(
                "INSERT INTO agendamento (id, animal_id, servico_id, profissional_id, inicio, fim, status,"
                " preco_centavos, criado_em, proposta_id, observacao) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    a.id, a.animal_id, a.servico_id, a.profissional_id, _dt(a.inicio), _dt(a.fim),
                    a.status.value, a.preco_centavos, _dt(a.criado_em), a.proposta_id, a.observacao,
                ),
            )
        return a

    def mover_agendamento_se_livre(
        self, agendamento_id: str, profissional_id: str, inicio: datetime, fim: datetime
    ) -> bool:
        with transacao(self._conn):
            if self._tem_conflito(profissional_id, inicio, fim, ignorar_id=agendamento_id):
                return False
            self._conn.execute(
                "UPDATE agendamento SET profissional_id = ?, inicio = ?, fim = ? WHERE id = ?",
                (profissional_id, _dt(inicio), _dt(fim), agendamento_id),
            )
        return True

    def cancelar_agendamento(self, agendamento_id: str) -> None:
        self._conn.execute("UPDATE agendamento SET status = 'cancelado' WHERE id = ?", (agendamento_id,))

    def _tem_conflito(
        self, profissional_id: str, inicio: datetime, fim: datetime, ignorar_id: str | None = None
    ) -> bool:
        r = self._conn.execute(
            "SELECT 1 FROM agendamento WHERE profissional_id = ? AND status != 'cancelado'"
            " AND inicio < ? AND fim > ? AND id != ? LIMIT 1",
            (profissional_id, _dt(fim), _dt(inicio), ignorar_id or ""),
        ).fetchone()
        return r is not None


class AtendimentoSQLite:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def salvar_proposta(self, proposta: Proposta) -> None:
        p = proposta
        self._conn.execute(
            "INSERT INTO proposta (id, conversa_id, tipo, dados, turno, criada_em, expira_em)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (p.id, p.conversa_id, p.tipo.value, json.dumps(p.dados, ensure_ascii=False), p.turno,
             _dt(p.criada_em), _dt(p.expira_em)),
        )

    def obter_proposta(self, proposta_id: str) -> Proposta | None:
        r = self._conn.execute("SELECT * FROM proposta WHERE id = ?", (proposta_id,)).fetchone()
        return _proposta(r) if r else None

    def marcar_proposta_usada(self, proposta_id: str, agendamento_id: str | None, quando: datetime) -> None:
        self._conn.execute(
            "UPDATE proposta SET usada_em = ?, agendamento_id = ? WHERE id = ?",
            (_dt(quando), agendamento_id, proposta_id),
        )

    def proposta_pendente(self, conversa_id: str, agora: datetime) -> Proposta | None:
        r = self._conn.execute(
            "SELECT * FROM proposta WHERE conversa_id = ? AND usada_em IS NULL AND expira_em >= ?"
            " ORDER BY criada_em DESC, rowid DESC LIMIT 1",
            (conversa_id, _dt(agora)),
        ).fetchone()
        return _proposta(r) if r else None

    def registrar_passagem(self, passagem: Passagem) -> None:
        p = passagem
        self._conn.execute(
            "INSERT INTO passagem (protocolo, conversa_id, tutor_id, motivo, urgente, resumo, criada_em)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (p.protocolo, p.conversa_id, p.tutor_id, p.motivo, int(p.urgente), p.resumo, _dt(p.criada_em)),
        )

    def passagens_abertas(self, telefone: str) -> list[Passagem]:
        rows = self._conn.execute(
            "SELECT p.* FROM passagem p JOIN conversa c ON c.id = p.conversa_id"
            " WHERE c.telefone = ? AND p.status = 'aberta' ORDER BY p.criada_em",
            (telefone,),
        )
        return [
            Passagem(r["protocolo"], r["conversa_id"], r["tutor_id"], r["motivo"], bool(r["urgente"]),
                     r["resumo"], datetime.fromisoformat(r["criada_em"]))
            for r in rows
        ]

    # Conversa ----------------------------------------------------------------

    def buscar_conversa_recente(self, telefone: str, desde: datetime) -> Conversa | None:
        r = self._conn.execute(
            "SELECT * FROM conversa WHERE telefone = ? AND ultima_mensagem_em >= ?"
            " ORDER BY ultima_mensagem_em DESC LIMIT 1",
            (telefone, _dt(desde)),
        ).fetchone()
        return _conversa(r) if r else None

    def obter_conversa(self, conversa_id: str) -> Conversa | None:
        r = self._conn.execute("SELECT * FROM conversa WHERE id = ?", (conversa_id,)).fetchone()
        return _conversa(r) if r else None

    def criar_conversa(self, conversa: Conversa) -> None:
        c = conversa
        self._conn.execute(
            "INSERT INTO conversa (id, telefone, iniciada_em, ultima_mensagem_em, turno) VALUES (?, ?, ?, ?, ?)",
            (c.id, c.telefone, _dt(c.iniciada_em), _dt(c.ultima_mensagem_em), c.turno),
        )

    def adicionar_mensagem(self, mensagem: Mensagem) -> None:
        m = mensagem
        with transacao(self._conn):
            self._conn.execute(
                "INSERT INTO mensagem (conversa_id, turno, papel, conteudo, criada_em) VALUES (?, ?, ?, ?, ?)",
                (m.conversa_id, m.turno, m.papel.value, json.dumps(m.conteudo, ensure_ascii=False),
                 _dt(m.criada_em)),
            )
            self._conn.execute(
                "UPDATE conversa SET ultima_mensagem_em = MAX(ultima_mensagem_em, ?) WHERE id = ?",
                (_dt(m.criada_em), m.conversa_id),
            )

    def abrir_turno(self, conversa_id: str) -> int | None:
        with transacao(self._conn):
            pendentes = self._conn.execute(
                "SELECT COUNT(*) FROM mensagem WHERE conversa_id = ? AND turno IS NULL", (conversa_id,)
            ).fetchone()[0]
            if not pendentes:
                return None
            self._conn.execute("UPDATE conversa SET turno = turno + 1 WHERE id = ?", (conversa_id,))
            turno = self._conn.execute("SELECT turno FROM conversa WHERE id = ?", (conversa_id,)).fetchone()[0]
            self._conn.execute(
                "UPDATE mensagem SET turno = ? WHERE conversa_id = ? AND turno IS NULL", (turno, conversa_id)
            )
        return turno

    def listar_mensagens(self, conversa_id: str, a_partir_do_turno: int) -> list[Mensagem]:
        # Ordena por turno antes do id: mensagem que chegou durante o turno anterior entra no seguinte.
        rows = self._conn.execute(
            "SELECT * FROM mensagem WHERE conversa_id = ? AND turno >= ? ORDER BY turno, id",
            (conversa_id, a_partir_do_turno),
        )
        return [
            Mensagem(r["conversa_id"], r["turno"], Papel(r["papel"]), json.loads(r["conteudo"]),
                     datetime.fromisoformat(r["criada_em"]))
            for r in rows
        ]


    def registrar_execucao(self, execucao: Execucao) -> None:
        e = execucao
        self._conn.execute(
            "INSERT INTO execucao (conversa_id, turno, criada_em, tipo, nome, resultado, duracao_ms, tokens_entrada,"
            " tokens_saida, tokens_cache_lidos, tokens_cache_gravados, custo_usd)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (e.conversa_id, e.turno, e.criada_em.isoformat(timespec="seconds"), e.tipo, e.nome, e.resultado,
             e.duracao_ms, e.tokens_entrada, e.tokens_saida, e.tokens_cache_lidos, e.tokens_cache_gravados,
             e.custo_usd),
        )


    def registrar_mensagem_recebida(self, wamid: str, telefone: str, quando: datetime) -> bool:
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO mensagem_recebida (wamid, telefone, recebida_em) VALUES (?, ?, ?)",
            (wamid, telefone, _dt(quando)),
        )
        return cursor.rowcount == 1

    def conversas_com_pendencias(self) -> list[Conversa]:
        rows = self._conn.execute(
            "SELECT DISTINCT c.* FROM conversa c JOIN mensagem m ON m.conversa_id = c.id WHERE m.turno IS NULL"
        )
        return [_conversa(r) for r in rows]


def _proposta(r: sqlite3.Row) -> Proposta:
    return Proposta(
        id=r["id"],
        conversa_id=r["conversa_id"],
        tipo=TipoProposta(r["tipo"]),
        dados=json.loads(r["dados"]),
        turno=r["turno"],
        criada_em=datetime.fromisoformat(r["criada_em"]),
        expira_em=datetime.fromisoformat(r["expira_em"]),
        usada_em=_ler_dt(r["usada_em"]),
        agendamento_id=r["agendamento_id"],
    )


def _conversa(r: sqlite3.Row) -> Conversa:
    return Conversa(
        r["id"], r["telefone"], datetime.fromisoformat(r["iniciada_em"]),
        datetime.fromisoformat(r["ultima_mensagem_em"]), r["turno"],
    )
