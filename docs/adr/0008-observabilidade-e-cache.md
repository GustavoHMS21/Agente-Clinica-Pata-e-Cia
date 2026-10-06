# ADR 0008: observabilidade e cache do histórico

- Status: aceito
- Data: 2026-10-06
- Bloco: 9

## Contexto

O custo por mensagem era uma projeção (bloco 6): cerca de US$ 0,016 a 0,019 com o Sonnet 5.5, dois terços em histórico reenviado sem cache a cada chamada. Sem números reais, qualquer otimização seria palpite. Ordem adotada: medir primeiro, otimizar depois e medir de novo.

## Decisão 1: rastreio próprio, no banco

Tabela `execucao`: uma linha por turno, por chamada ao LLM e por ferramenta, com nome, resultado (stop_reason, `ok` ou código de erro), duração, tokens (sem cache, lidos do cache, gravados no cache, saída) e custo estimado em dólar (`agente/custos.py`).

| Opção | Por que não (ou sim) |
| --- | --- |
| Langfuse, LangSmith, Helicone | Ótimos em produção, mas são mais um serviço para subir, autenticar e pagar, e mandariam dados de tutores para mais um terceiro (LGPD). Ficam no roadmap |
| **Tabela no próprio banco** | **Escolhida.** Zero infraestrutura, consulta com SQL, nada sai da máquina |

- **Só metadados, nunca conteúdo:** o rastreio não guarda texto de conversa (que já está em `mensagem`, com a sua política de retenção). Teste garante.
- **Rastreio nunca derruba o atendimento:** falha ao gravar vira log, e o tutor recebe a resposta.
- **Custo desconhecido fica desconhecido:** modelo fora da tabela de preços grava `NULL`, nunca um palpite. A página mostra quantas chamadas ficaram sem preço.
- **Desfecho do turno:** `resposta`, `resposta_ajustada`, `urgencia_fora_do_horario`, `saude_bloqueada`, `falha_llm`, `recusa`, `corte_por_tamanho`, `limite_de_passos`, `sem_texto`. É o primeiro sinal de qualidade em produção.

Página `/operacao` (com login): conversas, mensagens, custo total e por mensagem, tempo de resposta (mediana e p95), aproveitamento do cache, desfechos, erros de ferramenta, passagens por motivo e ações concluídas pelo agente sem a Joyce (a métrica de sucesso da cliente).

## Decisão 2: contexto do turno como mensagem de sistema gravada no histórico

Antes, o contexto do turno (data e hora, proposta pendente, passagens) ficava no bloco `system`, depois do prompt fixo. Como ele muda a cada turno, tudo que vinha depois no prompt, ou seja o histórico inteiro, nunca entrava no cache.

Agora:
- o bloco `system` é só o prompt fixo, igual em toda chamada;
- o contexto entra como **mensagem `role: "system"` logo depois da mensagem do tutor** e é **gravado no histórico** (papel `sistema`);
- o histórico passa a ser só-acréscimo: o que foi enviado num turno é prefixo exato do turno seguinte (teste garante);
- cache automático (`cache_control` no nível da requisição) marca o fim das mensagens a cada chamada.

Bônus de segurança: mensagem de sistema no meio da conversa tem autoridade de operador, e o tutor não consegue imitá-la escrevendo um texto parecido.

## Resultado medido (Sonnet 5.5, mesma conversa de 4 mensagens)

| | Antes (estimado) | Depois (medido) |
| --- | --- | --- |
| Custo das 4 mensagens | US$ 0,064 a 0,076 | US$ 0,038 |
| Por mensagem | US$ 0,016 a 0,019 | US$ 0,0095 (US$ 0,019 na primeira, que grava o cache; cerca de US$ 0,006 nas seguintes) |
| Entrada vinda do cache | cerca de 40% | 86% |

Projeção para a clínica (60 conversas por dia): de US$ 120 a 150 por mês para algo perto de **US$ 70**.

## Limites conhecidos

- O cache vale por 5 minutos sem uso. Conversa com pausa longa paga a gravação de novo.
- Depois de 10 turnos, a janela do histórico (ADR 0004) começa a deslizar e o prefixo muda a cada turno, perdendo o cache do histórico. Conversas tão longas são raras na recepção.
- Mensagem de sistema no meio da conversa é recurso da API da Anthropic. O adaptador compatível com OpenAI converte para `role: "system"`, mas cada provedor trata isso de um jeito: medir antes de trocar.
