# ADR 0002: toda escrita na agenda passa por proposta e confirmação

- Status: proposto
- Data: 2026-10-06
- Bloco: 3

## Contexto

O agente marca, remarca e cancela (RN27). O modelo pode errar o horário, o animal ou o preço. Também pode agir antes de o tutor concordar, ou ser induzido a isso por uma mensagem ("já confirma tudo sem me perguntar"). Na C11, o tutor trocou de animal no meio do pedido. Se a escrita fosse imediata, o cancelamento teria caído na Nina.

## Opções

| Opção | Problema |
| --- | --- |
| Ferramentas que escrevem direto (`agendar`, `remarcar`, `cancelar`) e o prompt pede para confirmar antes | A confirmação depende de o modelo obedecer. Prompt pede, não garante |
| Aprovação da Joyce em toda escrita | Garante, mas derruba o objetivo: agendamento simples sem a Joyce |
| **Proposta + confirmação em turno seguinte** | **Escolhida** |

## Decisão

- `propor_agendamento`, `propor_remarcacao` e `propor_cancelamento` validam, guardam a proposta no servidor e devolvem o resumo. Não mudam a agenda.
- `confirmar_proposta(proposta_id)` é a única escrita. Ela executa exatamente o que foi guardado, então o modelo não consegue trocar o horário ou o preço entre propor e confirmar.
- A proposta precisa ter sido criada num turno anterior ao atual. Entre propor e confirmar existe, obrigatoriamente, uma mensagem do tutor depois de ele ter visto o resumo.
- Propostas expiram em 10 minutos, e confirmar duas vezes não duplica.

## Consequências

- Boa: a garantia da RN27 sai do prompt e vai para o código, testável sem LLM. Uma porta só para auditar e rastrear (bloco 9).
- Ruim: um turno a mais em toda ação. É o mesmo ritmo que a Joyce já usa nas conversas (C2, C5).
- Limite conhecido: o código garante que o tutor respondeu, não que ele disse "sim". Interpretar a resposta continua com o modelo. Um "não, espera" seguido de confirmação é erro do modelo, coberto pela avaliação do bloco 10.
