# ADR 0006: provedor de LLM trocável pelo .env

- Status: aceito
- Data: 2026-10-06
- Bloco: 6

## Contexto

O primeiro teste real com o Claude falhou por falta de crédito na conta da API. O código tratou a falha como previsto (mensagem fixa e passagem para a Joyce). Para não travar o projeto, o MVP passa a rodar com o Gemini, e o Claude continua disponível.

## Decisão

- **Formato interno único.** O loop, o banco (ADR 0004) e as ferramentas falam em blocos (`text`, `tool_use`, `tool_result`). Nenhum deles sabe qual provedor está por trás.
- **Um adaptador por família de API:**
  - `agente/llm_anthropic.py`: Claude, formato nativo (parâmetros no ADR 0005).
  - `agente/llm_openai.py`: qualquer API compatível com OpenAI. Gemini hoje; Qwen, OpenRouter ou Ollama entram com uma linha em `PROVEDORES_OPENAI`.
- **Escolha pelo `.env`:** `LLM_PROVEDOR` (`anthropic` ou `gemini`) e `LLM_MODELO` opcional. A fábrica `cliente_do_ambiente()` falha cedo se a chave do provedor escolhido estiver vazia, sem imprimir valor.
- **Gemini:** endpoint `https://generativelanguage.googleapis.com/v1beta/openai/`, modelo padrão `gemini-3.8-flash` (o da documentação oficial em 2026-10-06), chave `GEMINI_API_KEY`.

## O que muda em relação ao Claude

| Ponto | Claude | Compatível com OpenAI |
| --- | --- | --- |
| Schema `strict` | Garantido pela API | Não garantido. O executor transforma argumento ausente ou inválido em `ARGUMENTO_INVALIDO`, e o modelo corrige |
| `additionalProperties: false` | Enviado | Removido: nem todo provedor aceita. O domínio valida de qualquer forma |
| Cache de prompt | `cache_control` explícito | Cada provedor faz o seu (no Gemini, automático por prefixo) |
| Raciocínio entre chamadas | Blocos de thinking no turno | `extra_content` (assinatura de pensamento) em cada tool_call, devolvido intacto dentro do turno |
| Fallback por recusa | `fallbacks: "default"` | Não há. `content_filter` vira `refusal`, com mensagem fixa e passagem para a Joyce |

A regra do ADR 0005 vale para os dois: dentro do turno, tudo volta intacto; entre turnos, o banco guarda só texto e ferramentas.

## Consequências

- Trocar de provedor é editar o `.env`, sem mudar código. Isso também deixa a avaliação do bloco 10 comparar provedores com o mesmo conjunto de casos.
- O comportamento muda com o modelo. Os testes garantem o nosso código; a qualidade de cada modelo só a avaliação mede.
