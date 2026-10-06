# Regras de negócio: Patas & Cia

Bloco 2. Cada regra da tabela de preços e das 15 conversas, com o lugar onde ela vai morar no sistema.
Documento vivo: os blocos 3 (ferramentas), 7 (guardrails) e 10 (avaliação) partem daqui.

## Como decidir onde a regra mora

| Destino | Quando | Garantia |
| --- | --- | --- |
| **Ferramenta** (código) | Se a regra for quebrada, acontece uma ação errada no mundo: horário inválido, animal de outra pessoa cancelado, preço errado | Total. O modelo não consegue contornar |
| **Prompt** | Informação ou tom de conversa. Se errar, sai uma resposta ruim, mas nada muda na agenda | Nenhuma. O prompt é um pedido, não uma trava |
| **Joyce** (passagem para humano) | Depende de julgamento clínico, de confiança entre pessoas ou de um dado que o sistema não tem | Humana |

Regra prática: **prompt pede, código garante**. Toda regra que age no mundo precisa estar no código; o prompt pode repetir a mesma regra só para o agente conversar melhor (defesa em profundidade).

Fontes: T = tabela de preços, D = descoberta (MD do cliente), C1 a C15 = conversas.

## Tabela de regras

| ID | Regra | Fonte | Tipo | Onde | Nota |
| --- | --- | --- | --- | --- | --- |
| RN01 | Funciona seg a sex 8h–19h e sáb 8h–13h; domingo e feriado fechado | T | Determinística | Ferramenta + Prompt | A ferramenta só devolve horários válidos. Feriados ficam numa tabela no banco |
| RN02 | Duração: consulta 30 min, vacina 15 min, banho de 1h a 2h30 pelo porte, tosa completa +30 min | T | Determinística | Ferramenta | A duração define o tamanho do horário. O modelo não calcula |
| RN03 | Dermatologia só com a Dra. Paula, quinta 13h–19h | T, C9 | Determinística | Ferramenta | Quando não serve, o agente oferece clínica geral (C9). Isso é prompt |
| RN04 | Consulta de felinos com a Dra. Camila | T | Determinística | Ferramenta | Ver P1 |
| RN05 | Preço por serviço e porte | T | Conhecimento estruturado | Ferramenta (dados) | São ~40 linhas: consulta no banco, não RAG. O preço da confirmação sai da ferramenta, nunca do modelo |
| RN06 | Porte pelo peso: P até 10 kg, M 10–20, G 20–35, GG acima de 35 | T, C1 | Determinística | Ferramenta | O agente pergunta o peso; não deduz pela raça. Ver P2 |
| RN07 | Banho de gato só ter e qui, 8h–12h | T, C6 | Determinística | Ferramenta | |
| RN08 | Banho exige vacinas em dia | T, C6 | Determinística | Ferramenta | É a dor de hoje (agendas separadas). A ferramenta de banho lê a carteira no mesmo banco. Vencida: o agente oferece a vacina antes. Ver P3 |
| RN09 | Primeira vacina na clínica exige consulta no mesmo horário (consulta + vacina) | T, C10 | Determinística | Ferramenta | Animal sem histórico: a ferramenta converte em consulta + vacina e soma os preços |
| RN10 | Retorno em até 15 dias sem custo | T | Determinística | Joyce (v1) | Exige ler a ficha clínica. Roadmap |
| RN11 | Coleta de exame 8h–10h com jejum de 8h; resultado em até 2 dias úteis, enviado pela veterinária | T | Conhecimento | Prompt | Só informa. Agendar exame fica com a Joyce na v1 |
| RN12 | Pergunta sobre resultado de exame | C8 | Humano | Joyce | O agente não acessa nem comenta resultado |
| RN13 | Ultrassom só com pedido da veterinária | T | Humano | Joyce | |
| RN14 | Castração sob orçamento, só depois de consulta e exames; não estimar valor | T, C4 | Conhecimento | Prompt | Resposta padrão e oferta de consulta |
| RN15 | Taxa de R$ 40 para pulga ou carrapato | T | Conhecimento | Prompt | Só informa. A cobrança é no balcão |
| RN16 | Atraso de mais de 20 min no banho perde o horário | T, C14 | Determinística (aplicada no balcão) | Prompt | O agente informa e oferece remarcar. Quem aplica é a tosadora |
| RN17 | Táxi dog R$ 20 por trecho, até 5 km | T, C12 | Determinística, mas precisa de geolocalização | Prompt + Joyce | O agente informa o preço; a Joyce confirma a distância. Roadmap: ferramenta de distância |
| RN18 | Não atende silvestres, exóticos nem internação | T | Conhecimento | Prompt | |
| RN19 | Emergência fora do horário: indicar o Hospital Vida Animal (24h) | T, C3 | Julgamento (detectar) + Determinística (responder) | Código + Prompt | Ver "Urgência" abaixo |
| RN20 | Sinal de alerta dentro do horário: avisar a veterinária na hora | C13 | Julgamento | Joyce (urgente) | Ver "Urgência" abaixo |
| RN21 | Nunca orientar sobre saúde: diagnóstico, remédio, protocolo, gravidade | D, C10 | Julgamento | Prompt + guardrail + Joyce | C10: "quantas doses?" vira "a veterinária define o protocolo na consulta". Testado no bloco 7 |
| RN22 | Identificação pelo telefone cadastrado | D | Determinística | Ferramenta | O telefone vem do canal (metadado), nunca do texto da mensagem nem de argumento do modelo |
| RN23 | Número que não é do tutor só consulta preço e pede pré-agendamento; não remarca nem cancela | D (caso do ex-marido), C11 | Determinística | Ferramenta + Joyce | Negar por padrão. A Joyce resolve quem é da família |
| RN24 | Cliente ou animal novo: pré-agendamento que a Joyce confirma | D, C10 | Determinística | Ferramenta + Joyce | O sucesso da cliente foi definido para "cliente já cadastrado" |
| RN25 | Remarcar ou desmarcar com pelo menos 2h de antecedência, sem multa | D | Determinística | Ferramenta | Menos de 2h: Joyce. Ver P4 |
| RN26 | Duas faltas sem aviso bloqueiam novo agendamento até falar com a Joyce | D | Determinística | Ferramenta + Joyce | Marcação no cadastro do tutor |
| RN27 | Confirmar resumo (animal, serviço, data, profissional, preço) antes de marcar, remarcar ou cancelar | C2, C5, C11 | Determinística | Ferramenta + Prompt | Bloco 6: ferramenta em duas fases (propor, depois confirmar) |
| RN28 | Mensagem de áudio | C7 | Fora do canal da v1 | Joyce (v1) | O canal de teste é texto. Roadmap: transcrição |
| RN29 | Tutor muda de ideia no meio do pedido | C11 | Julgamento | Prompt + estado | Bloco 5. Como nada é feito sem a confirmação da RN27, a troca não vira ação errada |

Resumo: 16 regras têm código como dono ou co-dono, 11 passam pelo prompt e 10 envolvem a Joyce. As regras que ficam só no prompt (RN11, 14, 15, 16 e 18) são informação: se o agente errar, nada muda na agenda.

## Urgência (RN19 e RN20)

Decidir se um caso é grave já é julgamento clínico, e o agente não pode fazer isso. Por isso ele não faz triagem: só reconhece sinais de alerta e passa adiante.

- **Sinais de alerta:** a lista abaixo, definida pela Beatriz, não por nós.
- **Fora do horário:** resposta fixa vinda do código, com os dados do Hospital Vida Animal. O modelo não improvisa sobre saúde.
- **Dentro do horário:** passa para a Joyce marcado como urgente; ela avisa a veterinária (C13).
- **Detecção em duas camadas:** uma lista de palavras no código, antes do modelo, e o próprio agente pode chamar a passagem para a Joyce. Falso positivo é barato (a Joyce olha e libera); falso negativo foi a C3.
- **Queixa comum** (coceira, mancando, C7 e C9) não é alerta: vira consulta normal, e o agente anota a queixa sem comentar.

### Lista de sinais de alerta (P5)

Validada pela Dra. Beatriz em 2026-10-06, numa reunião de 30 minutos. **Validação de exemplo: o caso é fictício.** No código: `SINAIS_DE_ALERTA` em `src/patas/agente/guardrails.py`, com um teste por categoria.

| # | Categoria | Exemplo de frase | Por que é urgente |
| --- | --- | --- | --- |
| 1 | Ingestão tóxica | "comeu um pedaço grande de chocolate" (C3), "engoliu uma meia" | Chocolate, uva, cebola, xilitol e remédio humano intoxicam; corpo estranho obstrui o intestino |
| 2 | Vômito ou diarreia; não come nem bebe | "vomitando desde ontem e não quer comer" (C13) | Desidrata rápido, sobretudo filhote e idoso |
| 3 | Sangramento | "sangue no xixi" | Pode ser hemorragia interna ou intoxicação |
| 4 | Convulsão, desmaio, prostração | "não consegue levantar" | Neurológico ou choque |
| 5 | Dificuldade para respirar | "gengiva roxa", "engasgado" | Falta de oxigênio mata em minutos |
| 6 | Trauma | "atropelado", "caiu da sacada", "brigou com outro cachorro" | Lesão interna nem sempre aparece |
| 7 | Gato fazendo força e sem sair xixi | "forçando pra fazer xixi e não sai nada" | Obstrução urinária: fatal em 24 a 48h. O tutor quase nunca sabe que é grave |
| 8 | Barriga inchada e dura, ânsia sem vomitar | "barriga inchada e dura" | Torção gástrica em cão grande: cirurgia de emergência |
| 9 | Picada de peçonhento | "picado por escorpião" | Veneno |
| 10 | Insolação | "muito ofegante depois do passeio" | Hipertermia lesa órgãos |
| 11 | Parto difícil | "em trabalho de parto faz uma hora e nada" | Risco para mãe e filhotes |
| 12 | Olho machucado ou saltado | "olho machucado" | Perda da visão |

O que a Beatriz tirou da lista: queda de pelo, coceira, espirro leve, tártaro, mancar sem dor forte. Viram consulta normal.

Revisão: a cada 6 meses ou quando a Joyce relatar um caso urgente que o agente não pegou.

## Respostas da Beatriz (2026-10-06)

| # | Pergunta | Resposta | No código |
| --- | --- | --- | --- |
| P1 | Consulta de gato é só com a Dra. Camila? | Sim, sempre, consulta de felinos a R$ 170 (consultório preparado para gato). Encaixe de urgência no dia é a Joyce que decide | Consulta clínica e dermatologia só para cão (seed); consulta e vacina de gato só com a Camila; primeira vacina de gato = consulta de felinos + vacina (`agenda.py`) |
| P2 | 10 kg e 20 kg exatos? | "Até" inclui o número: 10 kg é P; 10,1 a 20 é M; 20,1 a 35 é G; acima de 35, GG. Vale a última pesagem. Sem pesagem e sem o tutor saber, vai pela raça e a tosadora confirma na chegada (o valor pode mudar) | `porte_pelo_peso` (já estava certo); novo `porte_estimado` com aviso |
| P3 | Vacinas para banho e validade? | Cão: V10 (aceita V8) e antirrábica. Gato: V5 (aceita V4) e antirrábica. Todas valem 1 ano da aplicação. Gripe e giárdia recomendadas, não obrigatórias. Filhote só depois das doses iniciais. Vacina de outra clínica: foto da carteirinha e a Joyce confere | Grupos de equivalência e `vence_em` em `regras.py`; prompt e passagem `carteirinha` |
| P4 | Cancelar com menos de 2h? | Pode, não é falta (falta é não vir e não avisar). As 2h são para a Joyce encaixar outro; ela só precisa saber | Sem bloqueio; aviso na proposta e passagem `vaga_liberada` ao confirmar. Só não se altera horário que já começou |
| P7 | Durações não informadas? | Banho de gato 1h30; corte de unha 15 min (agenda do banho); primeira vacina 45 min; vacina avulsa de paciente 15 min | Seed e `DURACAO_PRIMEIRA_VACINA` |
| P8 | Feriados? | Todos os nacionais (com 20/11), 9/7 (SP), 8/12 (Guarulhos), Corpus Christi; Carnaval seg e ter fechado, quarta abre às 12h; 24 e 31/12 só até as 12h | Calendário gerado por ano com a Páscoa calculada (`seed.py`); tabela `feriado` com horário reduzido |

Interpretação nossa, a confirmar: "gato é sempre com a Dra. Camila" vale também para vacina de gato, não só consulta. Sexta-feira Santa foi incluída entre os feriados nacionais.

## Perguntas resolvidas antes
- ~~**P5.** A Beatriz valida a lista de sinais de alerta.~~ Resolvida (exemplo): lista na seção Urgência.
- ~~**P6.** Endereço e telefone do Hospital Vida Animal.~~ Resolvida com dados de exemplo: Rua das Acácias, 250, Jardim Exemplo, Guarulhos, (11) 90000-2424. Trocar pelos reais antes de uso com cliente.

## Decisões do MVP (sem regra da cliente, revisar com a Beatriz)

- Não oferece horário que começa em menos de 30 minutos.
- Horários numa grade de 15 minutos (:00, :15, :30, :45).
- A validade da vacina é checada na data do banho, não na de hoje.
