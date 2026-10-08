# ADR 0012: canal WhatsApp pela Cloud API

- Status: aceito
- Data: 2026-10-07
- Fase: produção, fase 1

## Contexto

Até aqui, o simulador fazia o papel do WhatsApp: uma requisição, uma resposta, tudo na mesma chamada. O canal real funciona diferente. A Meta chama um webhook nosso a cada mensagem, espera resposta rápida, reenvia o que acha que falhou e não sabe nada sobre turnos. Tutores mandam mensagens em rajada. Qualquer um na internet pode chamar a URL do webhook.

## Decisão

Módulo `src/patas/web/whatsapp.py`, ligado só quando as variáveis `WHATSAPP_*` estão preenchidas (sem elas, o servidor sobe só com o simulador; preenchidas pela metade, não sobe).

| Problema | Solução |
| --- | --- |
| Alguém fingindo ser a Meta | Assinatura `X-Hub-Signature-256` (HMAC-SHA256 do corpo cru com a chave secreta do app) conferida em toda mensagem; sem ela, 403 e nada gravado. A verificação inicial da URL exige o verify token |
| A Meta espera resposta rápida; o agente leva segundos | O webhook só grava a mensagem como pendente e responde 200. O agente roda depois, numa thread |
| Reenvio da mesma mensagem | Tabela `mensagem_recebida` (migração 0002) com o id da Meta como chave: o repetido é ignorado |
| Rajada ("oi", "quanto tá o banho?", "?") | O despachante espera 4 s de silêncio por conversa (cada mensagem reinicia a contagem) e roda um turno só, que junta as pendentes (ADR 0004) |
| Servidor cai com mensagem sem resposta | Na subida, retoma as conversas com mensagem pendente da última hora |
| Áudio, foto, figurinha | Viram marcadores como `[áudio]` ou `[imagem] legenda`; o prompt já orienta pedir que o tutor escreva. Reações e eventos de sistema são ignorados |
| Celular brasileiro chega sem o 9 (`551187654321`) | `normalizar_telefone` recoloca o 9: o tutor é reconhecido e a resposta vai para o número completo |
| LGPD | Na primeira resposta de cada conversa, um aviso de que é atendimento automático, para que servem os dados e que dá para pedir a equipe |

O envio usa a Graph API por `urllib` (sem dependência nova). Os logs mostram só os 4 últimos dígitos do telefone e nunca o token; a configuração esconde os segredos no `repr`.

O simulador e o canal real dividem a mesma trava por conversa: um turno por vez, venha de onde vier.

## Alternativas descartadas

- **Fila externa (Redis, SQS):** uma thread por conversa e a tabela de mensagens pendentes bastam para um processo só (ADR 0010). A fila entra se um dia houver mais de uma máquina.
- **Responder dentro do webhook:** com 5 a 20 s de agente, a Meta reenviaria a mensagem e o tutor receberia respostas duplicadas.
- **MCP de WhatsApp não oficial:** risco de banimento do número da clínica.

## Ainda não feito

- **Modo humano** (a recepção responde pelo app e o agente pausa naquela conversa): só existe com o número real em coexistência, na fase 2.
- **Aviso só no primeiro contato da vida** em vez de por conversa: exige guardar o histórico de avisos; por conversa é simples e cumpre a transparência.

## Verificado

`tests/test_whatsapp.py`: assinatura válida, falsa e ausente; leitura de texto, mídia, botão, reação e status no formato real da Meta; outro número ignorado; configuração pela metade barrada e segredos fora do `repr`; verificação do webhook; mensagem sem assinatura não é gravada; reenvio ignorado; rajada vira um turno com uma chamada ao LLM; aviso LGPD só no primeiro turno; celular sem o 9 respondido no número com 9; retomada de pendentes.
