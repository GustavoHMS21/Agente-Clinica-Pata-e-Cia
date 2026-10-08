-- Canal WhatsApp (produção, fase 1): a Meta reenvia a mesma mensagem quando acha que a entrega falhou.
-- Guardar o id de cada mensagem recebida deixa o processamento idempotente: a repetida é ignorada.
CREATE TABLE IF NOT EXISTS mensagem_recebida (
    wamid       TEXT PRIMARY KEY,                       -- id da mensagem na Meta (wamid....)
    telefone    TEXT NOT NULL,
    recebida_em TEXT NOT NULL
);
