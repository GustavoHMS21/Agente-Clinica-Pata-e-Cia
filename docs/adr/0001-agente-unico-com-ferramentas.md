# ADR 0001: agente único com ferramentas, envolvido por código determinístico

- Status: proposto (aguarda revisão do Gutto e respostas P1 a P6 da Beatriz)
- Data: 2026-10-06
- Bloco: 2

## Contexto

Cerca de 60 conversas por dia no WhatsApp; dois terços são agendamento (marcar, remarcar, desmarcar) e o resto é preço, serviços e status. As conversas mudam de rumo no meio: começam em preço e viram agendamento (C1, C12, C15), desmarcam e remarcam na mesma conversa (C5), trocam de animal e de tutor (C11), pedem um horário que a regra não permite e precisam de alternativa (C6, C9). As regras de agenda são claras e estão em [regras-de-negocio.md](../regras-de-negocio.md).

## As 5 perguntas do playbook

| # | Pergunta | Resposta |
| --- | --- | --- |
| 1 | As regras são claras e a entrada é estruturada? | Regras sim, entrada não: texto livre de WhatsApp. As regras claras vão para o código das ferramentas |
| 2 | É tarefa de linguagem de um passo só? | Não. Várias trocas de mensagem até confirmar |
| 3 | Os passos são sempre os mesmos? | Na pergunta de preço, sim. No agendamento, não (C5, C9, C11) |
| 4 | Os passos variam conforme o caso? | Sim: **agente** |
| 5 | Precisa de mais de 15 a 20 ferramentas ou domínios muito distintos? | Não. Cerca de 8 ferramentas, um domínio só: **agente único** |

## Opções avaliadas

| Opção | Por que não (ou por que sim) |
| --- | --- |
| Workflow puro (árvore de decisão) | Quebra com as mudanças de rumo. Cada caminho novo vira um galho a mais |
| Roteador de intenção + agente só no agendamento (exemplo do playbook) | A intenção muda dentro da mesma conversa, então o roteador teria de reclassificar a cada mensagem. A parte de dúvidas é pequena (uma tabela de ~40 linhas) e cabe numa ferramenta. É uma chamada de LLM e um componente a mais sem ganho no MVP |
| **Agente único + código em volta** | **Escolhida.** Um loop, poucas peças, e as regras críticas ficam no código, fora do alcance do modelo |
| Multiagente | Sem justificativa: um domínio, poucas ferramentas, sem paralelismo |

## Decisão

Um agente único (LLM em loop escolhendo ferramentas), com código determinístico antes e depois dele:

```
mensagem do canal
  -> [código] identifica o tutor pelo telefone do canal (RN22)
  -> [código] rede de urgência: sinal de alerta? (RN19, RN20)
        sim, fora do horário -> resposta fixa com o Hospital Vida Animal
        sim, no horário      -> passa para a Joyce como urgente
  -> [agente] LLM + ferramentas, no escopo do tutor identificado
        -> ferramentas -> interface de agenda -> banco (simula VetFácil e Google Agenda)
  -> [código] ação só acontece depois da confirmação do tutor (RN27)
```

Ferramentas (contratos completos em [contratos-das-ferramentas.md](../contratos-das-ferramentas.md)):

| Ferramenta | Risco |
| --- | --- |
| `consultar_servicos` | Leitura |
| `consultar_cadastro` (animais e agendamentos do tutor) | Leitura |
| `buscar_horarios` | Leitura |
| `propor_agendamento` · `propor_remarcacao` · `propor_cancelamento` | Proposta, não escreve |
| `confirmar_proposta` | Escrita (única porta, ver [ADR 0002](0002-escrita-em-duas-fases.md)) |
| `passar_para_joyce` | Escrita interna |

## Segurança já decidida aqui

- O telefone do tutor é injetado pelo código a partir do canal. Nenhuma ferramenta recebe telefone ou id de tutor como argumento do modelo, então "sou o marido da Cristina" no texto não dá acesso a nada (RN23).
- Ferramentas só enxergam os animais do tutor identificado (menor privilégio).
- O preço e o resumo da confirmação vêm da ferramenta, não do texto gerado pelo modelo.

## Consequências

- Boa: menos peças para aprender e depurar; regras críticas testáveis com teste unitário comum, sem LLM.
- Ruim: custo e latência variam por conversa; precisa de limite de iterações (bloco 6) e trace (bloco 9).
- Revisar esta decisão se: a parte de dúvidas crescer a ponto de precisar de RAG, o volume tornar o custo relevante (aí um roteador barato na frente compensa), ou o número de ferramentas passar de 15.
