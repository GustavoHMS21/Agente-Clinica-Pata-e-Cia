# ADR 0004: estado da conversa

- Status: aceito
- Data: 2026-10-06
- Bloco: 5

## Contexto

O agente roda uma vez por mensagem e não guarda nada entre execuções. Tudo o que precisa sobreviver entre mensagens vai para o banco. WhatsApp não tem "sessão": o tutor some e volta horas depois (C8: 9h12 pergunta do exame, 14h40 "E aí?"), manda várias mensagens seguidas (C1, C15) e muda de ideia no meio (C11).

## Decisões

### 1. Memória em duas partes

| Parte | O que guarda | Quem usa |
| --- | --- | --- |
| **Transcrição** (`mensagem`) | Texto do tutor, respostas do agente, chamadas e resultados de ferramentas | O LLM, como histórico |
| **Estado estruturado** (`conversa`, `proposta`, `passagem`) | Turno, proposta aguardando resposta, passagens abertas para a Joyce | O código, que injeta isso no contexto do LLM a cada turno |

O tutor é identificado de novo a cada turno, pelo telefone. Assim, um tutor provisório criado por pré-agendamento já aparece no turno seguinte.

### 2. Turno = uma execução do agente, não uma mensagem

As mensagens do tutor chegam com `turno` vazio. Quando o agente roda, todas as pendentes entram no mesmo turno. Quanto tempo esperar por mais mensagens antes de rodar fica para o canal (bloco 8). Isso também mantém o sentido da regra de confirmação do ADR 0002: turno novo significa que o tutor escreveu de novo.

### 3. Fronteira da conversa: 12 horas sem mensagem

| Opção | Problema |
| --- | --- |
| 30 min a 2h | A C8 ("E aí?" cinco horas depois) perde o contexto |
| 24h ou mais | Conversa de ontem contamina a de hoje, e o histórico cresce |
| **12h** | Cobre o dia de atendimento e zera de um dia para o outro |

Mesmo numa conversa nova, as passagens abertas do telefone entram no estado. O "E aí?" do dia seguinte ainda encontra a pendência com a Joyce.

### 4. Histórico: os últimos 10 turnos

A conversa pode ter 30 turnos, mas o LLM recebe só os 10 últimos. O corte é sempre no início de um turno, que começa com uma mensagem do tutor. Isso nunca separa uma chamada de ferramenta do seu resultado, que a API exige juntos. O custo por mensagem fica limitado, e o que importa de turnos antigos (proposta, passagens) já está no estado.

### 5. Formato salvo

O conteúdo de cada mensagem é uma lista de blocos JSON no formato da API da Anthropic (`text`, `tool_use`, `tool_result`). O papel é nosso (`tutor`, `agente`, `ferramenta`) e vira `user`/`assistant` só na hora de montar o histórico. Trocar de provedor exige converter só os blocos.

### 6. Passagem para a Joyce não pausa o agente (no MVP)

O agente continua respondendo e vê as passagens abertas no estado. Assim, ele não tenta resolver de novo o que já está com a Joyce. Roadmap: um modo em que a Joyce assume a conversa e o agente fica em silêncio até ela devolver.

## Segurança e LGPD

- Mensagem do tutor tem limite de 2.000 caracteres. O excesso é cortado antes de chegar ao LLM, o que limita custo e abuso.
- Texto do tutor só entra como mensagem `user`, nunca no prompt de sistema. O estado injetado vem de campos do banco, não de texto livre da conversa (bloco 7).
- As mensagens têm dados pessoais. Roadmap: apagar o conteúdo das conversas com mais de 90 dias.
