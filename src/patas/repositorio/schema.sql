-- Schema do MVP. Datas em texto ISO no horário local (2026-10-08T10:00), dinheiro em centavos.
-- Regra que muda com o negócio (preço, duração, dia de atendimento) é DADO nestas tabelas.
-- Regra de lógica (porte pelo peso, vacina em dia, antecedência) é CÓDIGO no serviço de agenda.

-------------------------------------------------------------------------------
-- Agenda: o que hoje vive no VetFácil e no Google Agenda
-------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tutor (
    id               TEXT PRIMARY KEY,
    nome             TEXT NOT NULL,
    telefone         TEXT NOT NULL UNIQUE,              -- só dígitos, com DDI (RN22)
    faltas_sem_aviso INTEGER NOT NULL DEFAULT 0,        -- RN26
    provisorio       INTEGER NOT NULL DEFAULT 0         -- criado por pré-agendamento (RN24)
);

CREATE TABLE IF NOT EXISTS animal (
    id            TEXT PRIMARY KEY,
    tutor_id      TEXT NOT NULL REFERENCES tutor(id),
    nome          TEXT NOT NULL,
    especie       TEXT NOT NULL CHECK (especie IN ('cao', 'gato')),
    peso_kg       REAL CHECK (peso_kg IS NULL OR peso_kg > 0),
    tem_historico INTEGER NOT NULL DEFAULT 0,           -- já passou em consulta aqui (RN09)
    provisorio    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_animal_tutor ON animal (tutor_id);

CREATE TABLE IF NOT EXISTS vacina (
    id          INTEGER PRIMARY KEY,
    animal_id   TEXT NOT NULL REFERENCES animal(id),
    nome        TEXT NOT NULL,
    aplicada_em TEXT NOT NULL,
    valida_ate  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vacina_animal ON vacina (animal_id);

CREATE TABLE IF NOT EXISTS profissional (
    id   TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('veterinaria', 'tosadora'))
);

-- Quando cada profissional trabalha. dia_semana: 0 = segunda ... 6 = domingo.
CREATE TABLE IF NOT EXISTS expediente (
    profissional_id TEXT NOT NULL REFERENCES profissional(id),
    dia_semana      INTEGER NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),
    inicio          TEXT NOT NULL,                      -- 08:00
    fim             TEXT NOT NULL,                      -- 19:00
    PRIMARY KEY (profissional_id, dia_semana, inicio)
);

CREATE TABLE IF NOT EXISTS feriado (
    data TEXT PRIMARY KEY,
    nome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS servico (
    id             TEXT PRIMARY KEY,
    nome           TEXT NOT NULL,
    categoria      TEXT NOT NULL CHECK (categoria IN ('consulta', 'vacina', 'exame', 'banho_tosa', 'outros')),
    especie        TEXT CHECK (especie IS NULL OR especie IN ('cao', 'gato')),  -- NULL: os dois
    agendavel      INTEGER NOT NULL,                    -- 0: o agente informa e passa para a Joyce
    preco_centavos INTEGER,                             -- NULL: por porte ou sob orçamento
    duracao_min    INTEGER
);

-- Banho e tosa: preço e duração mudam com o porte (RN05, RN02).
CREATE TABLE IF NOT EXISTS servico_porte (
    servico_id     TEXT NOT NULL REFERENCES servico(id),
    porte          TEXT NOT NULL CHECK (porte IN ('P', 'M', 'G', 'GG')),
    preco_centavos INTEGER NOT NULL,
    duracao_min    INTEGER NOT NULL,
    PRIMARY KEY (servico_id, porte)
);

-- Serviço restrito a dias e horas (RN03 dermatologia, RN07 banho de gato).
-- Serviço sem linha aqui vale o expediente inteiro do profissional.
CREATE TABLE IF NOT EXISTS servico_janela (
    servico_id TEXT NOT NULL REFERENCES servico(id),
    dia_semana INTEGER NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),
    inicio     TEXT NOT NULL,
    fim        TEXT NOT NULL,
    PRIMARY KEY (servico_id, dia_semana, inicio)
);

-- Quem faz cada serviço (RN03, RN04).
CREATE TABLE IF NOT EXISTS servico_profissional (
    servico_id      TEXT NOT NULL REFERENCES servico(id),
    profissional_id TEXT NOT NULL REFERENCES profissional(id),
    PRIMARY KEY (servico_id, profissional_id)
);

CREATE TABLE IF NOT EXISTS agendamento (
    id              TEXT PRIMARY KEY,
    animal_id       TEXT NOT NULL REFERENCES animal(id),
    servico_id      TEXT NOT NULL REFERENCES servico(id),
    profissional_id TEXT NOT NULL REFERENCES profissional(id),
    inicio          TEXT NOT NULL,
    fim             TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('confirmado', 'pendente_joyce', 'cancelado')),
    preco_centavos  INTEGER NOT NULL,
    criado_em       TEXT NOT NULL,
    proposta_id     TEXT UNIQUE,                        -- idempotência da confirmação (ADR 0002)
    observacao      TEXT CHECK (observacao IS NULL OR length(observacao) <= 300),
    CHECK (fim > inicio)
);
-- Sobreposição (inicio < fim_novo AND fim > inicio_novo) é checada em transação no código:
-- o SQLite não tem a restrição EXCLUDE do Postgres.
CREATE INDEX IF NOT EXISTS idx_agendamento_prof_inicio ON agendamento (profissional_id, inicio);
CREATE INDEX IF NOT EXISTS idx_agendamento_animal ON agendamento (animal_id);

-------------------------------------------------------------------------------
-- Atendimento: sempre no nosso banco
-------------------------------------------------------------------------------

-- Uma conversa acaba depois de 12h sem mensagem (ADR 0004).
CREATE TABLE IF NOT EXISTS conversa (
    id                 TEXT PRIMARY KEY,
    telefone           TEXT NOT NULL,                   -- do canal, nunca do texto
    iniciada_em        TEXT NOT NULL,
    ultima_mensagem_em TEXT NOT NULL,
    turno              INTEGER NOT NULL DEFAULT 0       -- execuções do agente (ADR 0004)
);
CREATE INDEX IF NOT EXISTS idx_conversa_telefone ON conversa (telefone, ultima_mensagem_em);

CREATE TABLE IF NOT EXISTS mensagem (
    id          INTEGER PRIMARY KEY,                    -- ordem de chegada dentro do turno
    conversa_id TEXT NOT NULL REFERENCES conversa(id),
    turno       INTEGER,                                -- NULL: do tutor, ainda não processada
    papel       TEXT NOT NULL CHECK (papel IN ('tutor', 'agente', 'ferramenta')),
    conteudo    TEXT NOT NULL,                          -- JSON: lista de blocos (text, tool_use, tool_result)
    criada_em   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mensagem_conversa ON mensagem (conversa_id, turno);

CREATE TABLE IF NOT EXISTS proposta (
    id             TEXT PRIMARY KEY,
    conversa_id    TEXT NOT NULL,
    tipo           TEXT NOT NULL CHECK (tipo IN ('agendamento', 'pre_agendamento', 'remarcacao', 'cancelamento')),
    dados          TEXT NOT NULL,                       -- JSON com o que será executado
    turno          INTEGER NOT NULL,
    criada_em      TEXT NOT NULL,
    expira_em      TEXT NOT NULL,
    usada_em       TEXT,
    agendamento_id TEXT
);

CREATE TABLE IF NOT EXISTS passagem (
    protocolo   TEXT PRIMARY KEY,
    conversa_id TEXT NOT NULL,
    tutor_id    TEXT,
    motivo      TEXT NOT NULL,
    urgente     INTEGER NOT NULL,
    resumo      TEXT NOT NULL CHECK (length(resumo) <= 500),
    criada_em   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'aberta' CHECK (status IN ('aberta', 'resolvida'))
);
