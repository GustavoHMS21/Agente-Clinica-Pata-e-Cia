# ADR 0007: interface web (simulador de WhatsApp e painel da Joyce)

- Status: aceito
- Data: 2026-10-06
- Bloco: 8

## Contexto

O agente só rodava no terminal. Para o MVP de portfólio, é preciso mostrar os dois lados do produto: o tutor conversando e a Joyce recebendo o que o agente passou para ela. O WhatsApp oficial (API da Meta) exige conta comercial verificada e fica no roadmap. A descoberta já decidiu: o canal fica atrás de uma interface, e o MVP usa um chat de teste.

## Decisão

Um servidor **FastAPI** (`src/patas/web/app.py`) com:

| Rota | Para quê |
| --- | --- |
| `/chat` | Simulador de WhatsApp: escolhe um tutor do seed (ou número sem cadastro) e conversa com o agente |
| `/joyce` | Painel: passagens abertas (urgentes primeiro), botão "resolvida", agenda do dia; atualiza a cada 15 s |
| `/api/...` | JSON que as duas telas usam |
| `/saude` | Sem login, para o deploy checar se o servidor está de pé |

Telas em HTML com JavaScript puro, sem framework de frontend. O foco do projeto é o agente; duas telas não justificam um build de React.

## Arquitetura

- **App montado por função** (`criar_app(llm, banco, usuario, senha)`): os testes injetam um LLM falso e um banco temporário, como no loop (ADR 0005).
- **Uma conexão de banco por requisição:** o `sqlite3` não compartilha conexão entre threads, e o FastAPI atende rotas comuns num pool de threads.
- **Modelo de leitura para o painel** (`repositorio/painel_sqlite.py`): consulta de tela junta tabelas e vai direto ao banco, porque não decide nada. Escrita na agenda continua passando pelo `ServicoAgenda`.
- **Hora de Guarulhos explícita** (`config.agora_local()`, fuso `America/Sao_Paulo`): no deploy o servidor costuma rodar em UTC, e sem isso a clínica "abriria" 3 horas errado.
- **O simulador é o adaptador de canal do MVP.** O adaptador do WhatsApp (roadmap) vai receber o webhook da Meta, validar a assinatura, pegar o telefone do próprio webhook e esperar alguns segundos para juntar mensagens em rajada antes de chamar `Agente.responder` (ADR 0004). O agente não muda.

## Segurança

| Risco | Controle |
| --- | --- |
| Painel com dados de todos os tutores, simulador gastando crédito do LLM | Login (HTTP Basic) em todas as rotas. Usuário e senha vêm do `.env`; **sem eles, o servidor não sobe** (falha fechada). Senha de pelo menos 12 caracteres, comparada em tempo constante |
| CSRF: outro site dispara ações com o login guardado no navegador | Rotas de escrita exigem o cabeçalho `X-Requested-With: patas`; um cabeçalho próprio força a checagem de CORS, que outro site não passa |
| XSS: mensagem ou nome malicioso vira código na página | Todo texto entra com `textContent`, nunca `innerHTML`; o *negrito* do WhatsApp é montado nó a nó. CSP restringe scripts à própria origem |
| Página embutida em outro site (clickjacking) | `X-Frame-Options: DENY` |
| Rotas expostas pela documentação automática | `/docs` e `/openapi.json` desligados |
| Entrada inválida | Pydantic valida telefone (só dígitos e pontuação) e tamanho do texto; protocolo validado por regex |

HTTP Basic só é seguro com HTTPS, que vem no deploy (bloco 11). Para um cliente real, o próximo passo é login com sessão e um usuário por pessoa, para saber quem resolveu cada passagem.
