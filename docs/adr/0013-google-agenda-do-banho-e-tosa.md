# ADR 0013: Google Agenda do banho e tosa

- Status: aceito
- Data: 2026-10-08
- Fase: produção, fase 1

## Contexto

A equipe de banho e tosa marca horários numa agenda do Google: clientes de balcão, telefone, encaixes. Se o agente só olhar o próprio banco, oferece horários que a equipe já preencheu. Se o que o agente marca não aparecer no Google, a equipe marca por cima. O ADR 0001 previu esta troca: o domínio enxerga só a interface `RepositorioAgenda`.

## Decisão

`src/patas/repositorio/google_agenda.py`, ligado quando `GOOGLE_AGENDA_ID` está preenchido. Sem ele, nada muda.

**Decorador, não substituto.** `AgendaComGoogle` embrulha a `AgendaSQLite`. O banco continua sendo a fonte dos agendamentos do agente (idempotência, painel da Joyce, rastreio). O Google acrescenta o que a equipe lançou e recebe uma cópia do que o agente marcou. Consulta e vacina nem chamam o Google.

**Uma agenda para a equipe toda, capacidade = número de tosadoras.** Cada evento lançado no Google ocupa uma tosadora: a primeira livre naquele horário. A distribuição é sempre calculada sobre o dia inteiro, para que a busca (que olha o dia) e a confirmação (que olha só o horário) concordem sobre quem está livre. Os eventos criados pelo agente levam uma marca privada (`patas_agendamento`) e são ignorados na leitura, para não contar duas vezes. Evento "Disponível" não ocupa; evento de dia inteiro (ex.: folga) ocupa uma tosadora o dia todo.

**Escrita com o Google primeiro.**

| Operação | Ordem | Se falhar |
| --- | --- | --- |
| Agendar | grava o evento, depois o banco | Google falhou: nada gravado. Banco recusou (conflito ou confirmação repetida): o evento é apagado |
| Remarcar | move o evento, depois o banco | Banco recusou: o evento volta ao horário antigo |
| Cancelar | apaga o evento, depois cancela no banco | Google falhou: nada cancelado |

O id do evento é derivado do id do agendamento. Repetir uma gravação substitui o evento em vez de duplicá-lo, e agendamentos anteriores à integração ganham evento na primeira remarcação.

**Falha fechada.** Google fora do ar vira `ERRO_INTERNO` na ferramenta, e o agente passa o atendimento para a Joyce. Nunca oferece horário de banho sem olhar a agenda real.

**Credencial:** conta de serviço com escopo só de eventos. Localmente, o JSON fica na pasta `segredos/`; no deploy, o conteúdo do JSON vai no cofre da plataforma (`GOOGLE_CREDENCIAIS` aceita caminho ou o próprio JSON). A leitura é a mesma no servidor e no verificador.

## Alternativas descartadas

- **Uma agenda por tosadora:** mapeamento direto, sem distribuição. Exige que a equipe mude como trabalha hoje. Vale a pena se ela já usar agendas separadas: pergunta para a Beatriz.
- **Google como única fonte, sem banco:** perderia a idempotência da confirmação, o painel e o rastreio, e cada leitura dependeria da rede.
- **Sincronização periódica (copiar o Google para o banco a cada N minutos):** horário oferecido poderia estar velho. A leitura na hora custa poucas chamadas por turno.

## Pergunta em aberto

- A equipe usa **uma agenda só**, e cada evento é um animal com uma tosadora? Se usar agendas separadas por tosadora, ou se um evento puder ter dois animais, a distribuição muda.

## Verificado

`tests/test_google_agenda.py`, com um calendário falso:
- um evento da equipe ocupa uma tosadora e dois ocupam as duas;
- a janela estreita e o dia inteiro dão a mesma distribuição;
- consulta de veterinária não chama o Google;
- Google fora do ar não oferece horário;
- o agendamento vira evento com a marca e não conta duas vezes;
- Google falhando na confirmação não grava nada no banco;
- remarcar e cancelar acompanham no Google;
- leitura de fuso, dia inteiro e "Disponível";
- cliente HTTP: paginação, 409 vira substituição, 410 não é erro, 500 é erro;
- configuração incompleta é barrada.
