# ADR 0010: deploy em container, sem plataforma fixa

- Status: aceito (preparado e testado localmente; publicação a cargo do dono do projeto)
- Data: 2026-10-06
- Bloco: 11

## Decisão

- **Imagem Docker única** (`Dockerfile`) que roda em Fly.io, Railway, Render ou qualquer VPS. A escolha da plataforma fica para a hora de publicar; o guia está em `docs/deploy.md`.
- **Ponto de entrada de produção** `python -m patas.servidor`: cria o banco na primeira subida (com o seed fictício enquanto `PATAS_DADOS_DE_EXEMPLO=1`), acrescenta tabelas novas em bancos existentes e sobe o uvicorn.
- **Um processo, um volume.** SQLite em `/data`, num volume que sobrevive a deploys, com uma réplica só. Volume de clínica pequena (60 conversas por dia) cabe com folga. Mais de uma réplica exigiria Postgres (troca só do adaptador de repositório, ADR 0003).
- **CI no GitHub Actions** (`.github/workflows/testes.yml`): a cada push e pull request roda os testes e constrói a imagem. Os testes usam LLM falso: nenhum segredo no CI e custo zero.

## Segurança

| Ponto | Como ficou |
| --- | --- |
| Segredos | Nunca na imagem: `.dockerignore` barra `.env`, e eles chegam como variáveis da plataforma. Verificado: nenhum `.env` no container |
| Privilégio | O processo roda como usuário `patas` (uid 10001), não root |
| Superfície | Só `pyproject.toml`, `uv.lock` e `src/` entram na imagem; sem testes, avaliação, docs nem dependências de desenvolvimento |
| Rede local | Fora do container, o servidor escuta em `127.0.0.1` por padrão; só a imagem usa `0.0.0.0` |
| HTTPS | Dado pela plataforma. `Strict-Transport-Security` faz o navegador recusar HTTP no domínio |
| Proxy | `X-Forwarded-*` aceitos só do proxy da plataforma (`FORWARDED_ALLOW_IPS`) |
| Fuso | O seed e o relógio usam a hora de Guarulhos, não a do servidor (UTC) |
| Reprodutibilidade | Versões travadas pelo `uv.lock` (`uv sync --frozen`) |

## Verificado localmente (Docker 29.8)

Imagem de 377 MB. `/saude` 200; `/chat` 401 sem login e 200 com login; cabeçalho HSTS presente; processo como `patas`; nenhum `.env` no container; healthcheck `healthy`; depois de reiniciar, os 9 tutores continuam no volume e o seed não roda de novo.

## Limites conhecidos

Ver "O que ainda falta para um cliente real" em `docs/deploy.md`: adaptador do WhatsApp, login por pessoa, backup automático, migrações de schema e rotina de retenção da LGPD.
