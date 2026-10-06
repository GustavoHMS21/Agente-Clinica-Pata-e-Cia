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

## O que os testes reais mostraram (2026-10-06)

| Provedor | Resultado |
| --- | --- |
| Claude (`claude-opus-5-5`) | Chave válida; conta sem crédito de API. Não testado de ponta a ponta |
| **Claude (`claude-sonnet-5-5`), escolhido** | Créditos resolvidos. Conversa completa (preço, horário, proposta, confirmação, recusa de lembrete, urgência de saúde com passagem para a Joyce) em cerca de 40 s para 4 turnos, de 1 a 4 s por chamada |
| Gemini, plano gratuito | Chave válida. Os 3.5 a 3.8 Flash davam 503 (alta demanda). O `gemini-2.5-flash` fez a conversa completa (preço, horário, proposta, confirmação no banco), mas a cota gratuita é de **20 requisições por dia por modelo**, uns 7 turnos. Serve para demonstração, não para desenvolver |
| Ollama local (`qwen3:8b`) | Funciona e escolhe as ferramentas certas, mas o Ollama usa **janela de 4.096 tokens** por padrão, e o prompt + ferramentas já ocupam cerca de 3.000. Corrigido com `ollama/Modelfile` (variante `patas-qwen3`, 16k tokens). Em CPU, de 30 s a 3 min por chamada |

Achados de comportamento e as correções:
- O modelo pedia o peso do animal em vez de consultar o cadastro. Virou regra explícita no prompt: "cadastro primeiro".
- O modelo prometeu "lembrete um dia antes", que nenhuma ferramenta faz. Virou regra explícita: "só prometa o que existe".
- Com `strict: true`, o JSON dos argumentos segue a ordem das propriedades do schema. Em `buscar_horarios`, `animal_id` vinha depois das datas; o modelo pulava o campo e colocava o animal em `profissional_id`, repetindo a chamada até o limite de 8 passos. Correção: campos que identificam o pedido (serviço, animal) primeiro, opcionais raros por último, com descrição clara.
- Campo opcional preenchido com `""` passou a valer como ausente (`_sem_vazios` no executor).
- O loop não executa de novo uma chamada idêntica que já falhou no mesmo turno: devolve o erro na hora, sem gastar outra chamada.

## Modelo escolhido

`claude-sonnet-5-5` com `effort: "medium"`, o modelo de uso diário: rápido, bom com ferramentas e com metade do preço do Opus 5.5 ($2 / $10 por milhão de tokens). Mantém tudo do ADR 0005 (thinking só dentro do turno, `block_binding`, `fallbacks: "default"`, recusa tratada). Gemini e Ollama continuam disponíveis pelo `.env`.

## Consequências

- Trocar de provedor é editar o `.env`, sem mudar código. Isso também deixa a avaliação do bloco 10 comparar provedores com o mesmo conjunto de casos.
- O comportamento muda com o modelo. Os testes garantem o nosso código; a qualidade de cada modelo só a avaliação mede.
