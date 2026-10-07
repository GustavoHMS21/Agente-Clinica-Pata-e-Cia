# Deploy: como publicar o agente

A imagem Docker roda igual em qualquer plataforma. Publicar é: criar o serviço a partir do `Dockerfile`, montar um volume em `/data`, definir as variáveis abaixo e conferir o checklist. Decisões no [ADR 0010](adr/0010-deploy.md).

## Variáveis

| Variável | Segredo? | Valor | Observação |
| --- | --- | --- | --- |
| `ANTHROPIC_API_KEY` | **Sim** | Sua chave | Só no cofre de segredos da plataforma |
| `PAINEL_SENHA` | **Sim** | 12+ caracteres, gerada (`uv run python -c "import secrets; print(secrets.token_urlsafe(16))"`) | Diferente da senha local |
| `PAINEL_USUARIO` | Não | ex.: `joyce` | |
| `LLM_PROVEDOR` | Não | `anthropic` | Padrão já é `anthropic` |
| `LLM_MODELO` | Não | vazio | Padrão `claude-sonnet-5-5` |
| `PATAS_DADOS_DE_EXEMPLO` | Não | `1` | Cria o seed fictício na primeira subida. Com cliente real: `0` |
| `PORT` | Não | a da plataforma | A maioria define sozinha |

Não defina `PATAS_DB_PATH`: a imagem já aponta para `/data/patas.db`, dentro do volume. Por isso também **não importe o `.env` local inteiro** para a plataforma: ele tem `PATAS_DB_PATH=data/patas.db`, que tiraria o banco do volume e o apagaria a cada deploy.

## Testar a imagem na sua máquina

```powershell
docker build -t patas-agente .
docker run --rm -p 8000:8000 -v patas-dados:/data --env-file .env -e PATAS_DB_PATH=/data/patas.db patas-agente
```

Abra **http://127.0.0.1:8000/chat**. Neste Windows, `localhost` não alcança o container (ele tenta IPv6 primeiro); use `127.0.0.1`.

## Fly.io (região São Paulo)

```powershell
fly auth login
fly launch --no-deploy --region gru --name patas-agente   # detecta o Dockerfile e cria o fly.toml
fly volumes create patas_dados --region gru --size 1
```

No `fly.toml` gerado, acrescente o volume e a checagem de saúde:

```toml
[mounts]
  source = "patas_dados"
  destination = "/data"

[[http_service.checks]]
  method = "GET"
  path = "/saude"
  interval = "30s"
  timeout = "5s"
```

Segredos (um por vez, no seu terminal; o valor não fica no repositório):

```powershell
fly secrets set ANTHROPIC_API_KEY=... PAINEL_SENHA=...
fly secrets set PAINEL_USUARIO=joyce LLM_PROVEDOR=anthropic
fly deploy
```

Deixe **uma máquina só** (`fly scale count 1`): o SQLite vive no volume de uma máquina.

## Railway

1. New Project → Deploy from GitHub repo → este repositório (o `Dockerfile` é detectado).
2. No serviço: Volumes → Add Volume → mount path `/data`.
3. Variables: as da tabela acima (`ANTHROPIC_API_KEY` e `PAINEL_SENHA` como variáveis secretas).
4. Settings → Networking → Generate Domain (HTTPS automático). Healthcheck path: `/saude`.
5. Uma réplica só, pelo mesmo motivo do SQLite.

A cada push na branch configurada, o Railway publica de novo.

## Render

Web Service → Docker → este repositório. Disk: mount path `/data` (exige plano pago; no gratuito o SQLite zera a cada deploy). Environment: as variáveis da tabela. Health check path: `/saude`.

## Checklist depois de publicar

- [ ] `https://<domínio>/saude` responde `{"ok": true}`
- [ ] `/chat` sem login responde 401; com login abre a página
- [ ] O endereço é **https** (HTTP Basic sem HTTPS manda a senha legível)
- [ ] Uma conversa de teste no simulador funciona, e aparece em `/operacao` com custo
- [ ] Limite de gasto mensal configurado no console da Anthropic
- [ ] Reiniciar o serviço não apaga os agendamentos (o volume está montado em `/data`)
- [ ] Nenhum segredo apareceu no log de deploy da plataforma

## O que ainda falta para um cliente real

- Adaptador do WhatsApp (API oficial da Meta): webhook com validação de assinatura e espera para juntar rajadas (ADR 0004, 0007)
- Login com sessão e um usuário por pessoa no painel (ADR 0007)
- Cópia do backup diário para fora da máquina (o backup diário e as migrações já existem, ADR 0011)
- Rotina de retenção da LGPD: apagar conteúdo de conversas com mais de 90 dias (ADR 0004)
- Dados reais: P1 a P8 com a Beatriz, `PATAS_DADOS_DE_EXEMPLO=0`, contrato (DPA) com o provedor do LLM
