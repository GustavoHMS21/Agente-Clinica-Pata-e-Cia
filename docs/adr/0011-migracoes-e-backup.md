# ADR 0011: migrações versionadas e backup diário

- Status: aceito
- Data: 2026-10-06
- Fase: produção, fase 1

## Contexto

Até aqui, toda mudança de schema exigiu recriar o banco (`python -m patas.seed --recriar`). Em produção, isso apagaria tutores, agendamentos e conversas. Também não havia cópia de segurança.

## Decisão

**Migrações:** cada mudança de banco é um arquivo SQL numerado em `src/patas/repositorio/migracoes/` (`0001_inicial.sql`, `0002_...sql`). A tabela `schema_migracao` registra o que já rodou. Ao subir, o servidor aplica só as pendentes, em ordem, cada uma numa transação: se falhar, nada fica pela metade e o servidor não sobe.

- Ferramenta própria (cerca de 30 linhas em `sqlite.py`) em vez de Alembic: SQL escrito à mão continua visível (ADR 0003) e não entra ORM.
- Banco criado antes das migrações é reconhecido como versão inicial, sem ser recriado.
- No SQLite, `ALTER TABLE` só acrescenta coluna. Mudar `CHECK` ou tipo exige recriar a tabela dentro da migração (criar nova, copiar, apagar a antiga, renomear).
- Regra para quem mantém: **nunca editar uma migração que já rodou em produção**; toda mudança é um arquivo novo.

**Backup:** `patas/backup.py` usa a API de backup do SQLite, que copia o banco com o servidor rodando sem pegar escrita pela metade.

- Automático: uma thread no próprio servidor faz um backup por dia às 3h (horário de Guarulhos) e mantém os 14 mais recentes, em `/data/backups`.
- Manual: `python -m patas.backup`.
- As cópias ficam no mesmo volume: protegem contra bug, apagamento e corrupção. Contra perda do disco, os snapshots diários do volume da plataforma (na Fly.io, 5 dias). Cópia para armazenamento externo fica no roadmap.

**Restaurar:** parar o serviço, copiar o backup escolhido por cima de `/data/patas.db` e subir de novo. As migrações pendentes rodam sozinhas.

## Verificado

Testes em `tests/test_migracoes_backup.py`: banco novo recebe tudo; segunda subida não reaplica; banco antigo é reconhecido sem perder dados; migração nova preserva os dados; migração com erro não deixa nada pela metade; backup abre e tem os dados; rotação mantém só os mais recentes.
