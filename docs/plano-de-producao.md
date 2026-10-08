# Plano de produção

Do MVP para atender tutores de verdade pelo WhatsApp. Cada fase só começa quando a anterior está verificada.

> **Situação em 2026-10-08: projeto encerrado com a fase 1 construída e desligada.** Todo o código da fase 1 está pronto e testado. Credenciais, deploy e teste ao vivo não foram feitos; para retomar, comece pelo [guia de integrações](configurar-integracoes.md).

## Fase 1: construção, sem tocar no número da clínica

| Item | Situação |
| --- | --- |
| Migrações versionadas e backup diário | **Feito** (ADR 0011) |
| Contas: app na Meta com número de teste, Google Agenda de teste com conta de serviço | Com o dono das contas ([guia](configurar-integracoes.md)) |
| Adaptador do Google Agenda para banho e tosa: horários ocupados e eventos vêm da agenda real | **Feito** (ADR 0013); falta o teste ao vivo com as credenciais |
| Adaptador do WhatsApp: webhook com assinatura validada, resposta 200 imediata e processamento em segundo plano, mensagens repetidas ignoradas, rajada juntada, envio pela API, áudio e foto pedem texto | **Feito** (ADR 0012); falta o teste ao vivo com as credenciais |
| Modo humano: quando a recepção responde pelo app (coexistência), o agente pausa naquela conversa | Fase 2: só existe com o número real |
| Aviso de atendimento automático na primeira mensagem (LGPD) | **Feito** (ADR 0012), na primeira resposta de cada conversa |
| Deploy na Fly.io (região São Paulo), webhook apontado para a URL pública | A fazer |

## Fase 2: piloto fora do horário

Com o número real, via coexistência: o agente responde só com a clínica fechada, quando hoje ninguém responde. Menor risco, maior ganho. Acompanhamento diário em `/operacao`.

## Fase 3: banho e vacina de cliente cadastrado o dia todo

O resto continua indo para a recepção.

## Fase 4: escopo completo

Consultas pelo sistema da clínica, se o VetFácil tiver API; senão, pré-agendamento confirmado pela recepção.

## Decisões em aberto

- **VetFácil tem API?** Define se consultas e vacinas entram direto na agenda da clínica.
- **A equipe de tosa usa uma agenda só no Google?** O adaptador supõe que sim (cada evento ocupa uma tosadora). Agendas separadas por tosadora mudam a distribuição (ADR 0013).
- **WhatsApp direto com a Meta ou por parceiro oficial** (360dialog, Twilio, Zenvia): sem mensalidade e cadastro mais trabalhoso, ou o contrário.
