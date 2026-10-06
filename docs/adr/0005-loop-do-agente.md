# ADR 0005: loop do agente, modelo e limites

- Status: aceito
- Data: 2026-10-06
- Bloco: 6

## Decisões

### 1. Loop escrito à mão, SDK direto

O SDK oferece um Tool Runner (beta) que faz o loop sozinho. Escolhemos o loop manual (`src/patas/agente/loop.py`, cerca de 60 linhas) por três motivos:
- é um projeto de aprendizado, e o loop é a peça que mais importa entender;
- precisamos gravar cada passo no banco (ADR 0004);
- não queremos depender de API beta no centro do sistema.

O SDK fica isolado em `agente/llm.py`. O loop recebe qualquer objeto com `criar(system, tools, messages)`, e os testes usam um LLM falso roteirizado: o código é testado sem chamada paga.

### 2. Modelo e parâmetros

| Parâmetro | Valor | Por quê |
| --- | --- | --- |
| Modelo | `claude-sonnet-5-5` (era `claude-opus-5-5`; troca no ADR 0006) | Modelo de uso diário, rápido e bom com ferramentas |
| `effort` | `medium`, explícito | Ponto de partida para ferramentas em vários passos (o padrão do Sonnet 5.5 é `high`). Ajuste guiado pela avaliação |
| Thinking | adaptativo (`disabled` dá erro 400 no Sonnet 5.5 e no Opus 5.5) | |
| `max_tokens` | 16.000 | Teto de thinking + resposta por chamada. Paga-se o que é usado, não o teto |
| Timeout e tentativas | 60 s, 2 tentativas | O SDK repete sozinho 429, 5xx e falha de rede |
| `strict: true` nas 8 ferramentas | | Garante argumentos válidos pelo schema. Faixas e tamanhos o domínio continua checando |
| `fallbacks: "default"` | | Se um classificador de segurança recusar, a API refaz a chamada num modelo de fallback, na mesma requisição |
| Cache | `cache_control` no prompt fixo | Ferramentas + prompt fixo são iguais em toda chamada; só o contexto do turno muda |

### 3. Thinking só vive dentro do turno (preserved thinking)

No Opus 5.5, cada bloco de thinking fica amarrado ao histórico exato que o produziu. Se o histórico anterior mudar, o bloco é rejeitado com erro 400 (em contas criadas a partir de 31/08/2026). O ADR 0004 corta o histórico nos últimos 10 turnos, e o contexto do turno muda a cada mensagem: as duas coisas invalidariam blocos antigos.

Regra adotada:
- **Dentro do turno**, o histórico só cresce, e os blocos de thinking voltam intactos para a API.
- **Entre turnos**, o banco guarda só texto, chamadas e resultados de ferramentas (`para_historico`). O turno seguinte não replica nenhum thinking antigo, então nada pode ser invalidado.
- `prefix_mismatch_behavior: "error"`: se um bug nosso replicar thinking inválido, a chamada falha alto em vez de degradar em silêncio.

Custo: o modelo não vê o raciocínio dos turnos anteriores, só o que foi dito e feito. Para recepção, isso basta.

### 4. Limites e saídas de emergência

| Situação | O que acontece |
| --- | --- |
| Mais de 8 chamadas ao modelo no mesmo turno | Para, responde mensagem fixa e passa para a Joyce |
| `stop_reason: "refusal"` | Mensagem fixa e passagem (`fora_do_escopo`) |
| `stop_reason: "max_tokens"` | Nenhuma ferramenta cortada é executada. Mensagem fixa e passagem |
| API fora do ar depois das tentativas | Mensagem fixa e passagem (`erro`) |
| Erro inesperado numa ferramenta | O modelo recebe `ERRO_INTERNO` e o traceback vai só para o log |

O tutor nunca fica sem resposta, e a Joyce sempre fica sabendo.

## Segurança

- A chave é lida pelo SDK direto do ambiente. Nenhuma função nossa recebe, imprime ou devolve o valor.
- O log de falha da API leva tipo, status, `request_id` e mensagem de erro. Nunca leva o corpo da requisição (que tem dados do tutor) nem a chave.
- O contexto dinâmico do prompt de sistema só leva campos do código. Texto do tutor e nomes digitados por ele ficam nas mensagens `user` e nos resultados de ferramentas.
- O prompt instrui a tratar mensagens e resultados como dados e a nunca expor ids internos. As travas que não dependem do modelo continuam no código (ADR 0002, contexto injetado). O bloco 7 testa os ataques.
