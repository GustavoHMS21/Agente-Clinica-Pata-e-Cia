# Cliente 03: Patas & Cia Clínica Veterinária (agente de agendamento)

Empresa fictícia. Caso simulado para portfólio.
Playbook de referência: https://claude.ai/code/artifact/0e27935f-96ef-4b07-a98d-30a3f305f6b9

## Nível
Intermediário. Primeiro projeto do portfólio em que o modelo decide o que fazer: chama ferramentas, conversa em vários turnos e age no mundo (marca, remarca e cancela).

## A empresa
- Patas & Cia Clínica Veterinária e Estética Animal, Guarulhos (SP)
- Funciona de segunda a sexta, 8h às 19h, e sábado, 8h às 13h. Domingo e feriado fechado
- Três veterinárias: Dra. Beatriz (dona, clínica geral), Dra. Camila (clínica geral e felinos), Dra. Paula (clínica geral e dermatologia)
- Banho e tosa com duas tosadoras
- Recepção: só a Joyce (balcão, pagamento, sala de espera, telefone e WhatsApp)
- Não faz emergência fora do horário nem internação; indica o Hospital Veterinário Vida Animal (24h)

## Quem é a Beatriz Okada
- Veterinária e dona da clínica, sem conhecimento técnico
- Pedido inicial: "um atendente virtual que marque horário sozinho"
- Limite claro: o atendente não pode dar palpite sobre a saúde do animal

## O problema, em números
- Canais de agendamento: WhatsApp (principal), telefone, Instagram e balcão
- Cerca de 60 conversas de WhatsApp por dia (mais na segunda e no sábado) e 30 ligações
- Cerca de dois terços das conversas são agendamento (marcar, remarcar, desmarcar); o resto é preço, serviços, resultado de exame, status do banho
- Média de 25 consultas e 20 banhos por dia
- Resposta: 10 a 15 minutos em dia tranquilo; uma a duas horas nos picos; fora do horário, só no dia seguinte
- Estimativa da Joyce: 10 a 15 clientes perdidos por semana por demora na resposta

## Sucesso, nas palavras da cliente
- Primeira resposta em até 5 minutos, a qualquer hora
- A maior parte dos agendamentos simples (banho e vacina de cliente já cadastrado) concluída sem a Joyce
- A Joyce fica com o que precisa de gente: balcão, tutor nervoso com animal doente
- "Maior parte" ainda precisa virar número (bloco de avaliação)

## Escopo desejado
- Marcar, remarcar e desmarcar horários
- Responder perguntas comuns: preço, horário de funcionamento, serviços oferecidos
- Fora: qualquer orientação sobre saúde do animal

## Sistemas
- Consultas e vacinas: VetFácil (sistema web pago por mês), com ficha, histórico, vacinas e agenda das veterinárias. Integração desconhecida (perguntar ao suporte)
- Banho e tosa: Google Agenda compartilhado, visto num tablet pelas tosadoras; a Joyce também marca lá
- Problema atual: animal marcado no banho com vacina vencida, porque as duas agendas não conversam
- WhatsApp: aplicativo WhatsApp Business num celular da recepção, também usado pelo WhatsApp Web. Número divulgado em todo lugar; a cliente não quer trocar de número

## Regras levantadas na descoberta
- Identificação: pelo telefone cadastrado no VetFácil; número desconhecido, a Joyce pergunta nome do tutor e do animal. Familiares mandam mensagem de outros números. Caso real: ex-marido desmarcou banho do cachorro que ficou com a ex-mulher
- Remarcar ou desmarcar: pedido de pelo menos 2 horas de antecedência, sem multa
- Banho: atraso de mais de 20 minutos perde o horário
- Duas faltas sem aviso: anotado no sistema; só marca de novo depois de conversar com a Joyce

## Decisões de arquitetura já tomadas
- Agente nunca fala direto com VetFácil ou Google Agenda: ferramentas falam com uma interface de agenda; no MVP, um banco próprio simula as duas agendas
- Canal atrás de uma interface: no MVP, chat de teste; adaptador do WhatsApp (API oficial da Meta) no roadmap
- Para o cliente real, a API do VetFácil decide o escopo: com API, agente marca consultas e vacinas; sem API, v1 marca só banho e faz pré-agendamento de consulta que a Joyce confirma

## Material recebido
- tabela_precos_patas_e_cia.txt: serviços, preços, durações, regras do banho e tosa, equipe e o que a clínica não faz
- conversas_whatsapp_patas_e_cia.txt: 15 conversas reais da semana de 28/09 a 03/10, com casos difíceis escolhidos pela Joyce

## Restrição do portfólio
- Prazo: 1 semana, com escopo bem cortado
- O que ficar de fora da v1 entra como roadmap no README

## Blocos do projeto
1. Descoberta com o cliente (concluído)
2. Precisa de agente? Qual tipo?
3. Ferramentas e contratos
4. Dados e agenda (banco)
5. Estado da conversa
6. Loop do agente, limites e confirmações
7. Guardrails e segurança
8. Interface
9. Observabilidade (tracing)
10. Avaliação de agente
11. Deploy
12. Case de portfólio

## Status
- Bloco 2 concluído: regras em docs/regras-de-negocio.md (RN01 a RN29); decisão em docs/adr/0001-agente-unico-com-ferramentas.md
- Bloco 3 concluído: docs/contratos-das-ferramentas.md e docs/adr/0002-escrita-em-duas-fases.md
- Bloco 4 concluído
  - 4a: stack (ADR 0003), schema, interfaces de repositório, implementação SQLite, seed
  - 4b: regras puras (src/patas/dominio/regras.py) e serviço de agenda (src/patas/dominio/agenda.py), 31 testes
- Bloco 5 concluído: ADR 0004, tabelas conversa e mensagem, src/patas/dominio/conversa.py, 39 testes no total
- Bloco 6 concluído: ADR 0005, src/patas/agente/ (prompt, ferramentas, llm, loop), chat de terminal
- Provedor trocável (ADR 0006): Claude Sonnet 5.5 em uso; Gemini e Ollama (ollama/Modelfile) disponíveis pelo .env; 63 testes
- Conversa real validada: preço, horário, proposta, confirmação no banco, recusa de promessa, urgência de saúde
- Bloco 7 concluído: src/patas/agente/guardrails.py, docs/seguranca.md, 6 ataques reais barrados, auditoria de segredos limpa, 82 testes
- P5 e P6 resolvidas com dados de exemplo (lista de sinais de alerta em 12 categorias; Hospital Vida Animal fictício)
- Bloco 8 concluído: ADR 0007, src/patas/web/ (simulador de WhatsApp e painel da Joyce), 97 testes
- Bloco 9 concluído: ADR 0008, rastreio na tabela execucao, página /operacao, cache do histórico (custo medido: US$ 0,0095 por mensagem, 86% da entrada vindo do cache), 101 testes
- Bloco atual: 10 (avaliação do agente)
- Pendente com a Beatriz: perguntas P1 a P8 em docs/regras-de-negocio.md
- Pendência paralela: números da avaliação no README do projeto 2
