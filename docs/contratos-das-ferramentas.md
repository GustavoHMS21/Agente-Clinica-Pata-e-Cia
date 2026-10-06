# Contratos das ferramentas: Patas & Cia

Bloco 3. O que cada ferramenta recebe, devolve e recusa. As regras citadas (RNxx) estão em [regras-de-negocio.md](regras-de-negocio.md).

São 8 ferramentas: 3 de leitura, 3 que só propõem, 1 que escreve na agenda e 1 que passa a conversa para a Joyce.

## Princípios

1. **A descrição da ferramenta é prompt.** O modelo escolhe a ferramenta lendo nome e descrição. Por isso elas são escritas para ele, em português, com quando usar e quando não usar. E não levam segredo nenhum.
2. **Ferramenta fina, regra no domínio.** A ferramenta valida os argumentos, chama o serviço de agenda e formata o resultado para o modelo. As regras (RN01 a RN27) moram no serviço de agenda. Assim, o mesmo código serve depois a um painel da Joyce e é testado sem LLM.
3. **Contexto injetado, não argumento.** Quem é o tutor, que horas são e em que turno a conversa está vem do código, nunca do modelo (RN22, RN23).
4. **Erro é dado, não exceção.** Toda recusa volta como resultado estruturado, com código, explicação e próximo passo. O modelo lê e continua a conversa. Exceção de verdade (banco fora do ar) vira `ERRO_INTERNO` e passa para a Joyce.
5. **Poucas ferramentas, de alto nível.** `buscar_horarios` já aplica todas as regras e devolve só horários válidos. O modelo nunca recebe a agenda bruta para filtrar sozinho.
6. **Escrita só por uma porta.** Marcar, remarcar e cancelar primeiro geram uma proposta; só `confirmar_proposta` muda a agenda. Ver [ADR 0002](adr/0002-escrita-em-duas-fases.md).

## Camadas

```
LLM
 |  chama pelo nome, com argumentos em JSON
 v
ferramentas/        valida schema, injeta contexto, formata resultado    (adaptador do LLM)
 |
 v
servico_agenda/     regras RN01-RN27, propostas, confirmação              (domínio)
 |
 v
repositorio/        interface de agenda: banco no MVP,                    (adaptador de dados)
                    VetFácil e Google Agenda no futuro
```

## Contexto injetado pelo código

O modelo nunca vê nem preenche estes campos. Cada ferramenta recebe `(argumentos_do_modelo, contexto)`.

| Campo | Origem | Uso |
| --- | --- | --- |
| `conversa_id` | Canal | Liga propostas e passagens à conversa |
| `telefone` | Metadado do canal | Identificação (RN22). Nunca vem do texto |
| `tutor_id` | Busca pelo telefone, antes do agente rodar | `null` quando o número não é cadastrado |
| `turno` | Contador de mensagens do tutor | Regra de confirmação (ADR 0002) |
| `agora` | Relógio do servidor, fuso America/Sao_Paulo | Antecedência, datas passadas, fora do horário |

A data de hoje e o dia da semana também entram no prompt de sistema, porque modelos erram conta de calendário.

## Formato de resposta (igual para todas)

```json
{ "ok": true, "dados": { } }
```
```json
{ "ok": false, "erro": { "codigo": "VACINA_PENDENTE", "mensagem": "V10 do Thor venceu em 12/08/2026.", "proximo_passo": "Oferecer agendar a vacina antes do banho." } }
```

Datas entram como `"2026-10-08T10:00"` (horário local) e saem com um rótulo pronto, `"quinta, 08/10 às 10h"`. O modelo copia o rótulo em vez de calcular o dia da semana.

## Ferramentas

### 1. `consultar_servicos` (leitura)

Preço, duração e regras dos serviços. Fonte única de preço (RN05).

| Entrada | Tipo | Obrigatório |
| --- | --- | --- |
| `categoria` | `consulta` · `vacina` · `exame` · `banho_tosa` · `outros` | Não (sem ela, devolve tudo) |

Saída: lista de `{ servico_id, nome, preco_por_porte | preco, duracao_min, agendavel_pelo_agente, regras[] }`. Exames, castração, ultrassom e táxi dog vêm com `agendavel_pelo_agente: false`. O modelo informa o preço e passa para a Joyce (RN11, RN13, RN14, RN17).

### 2. `consultar_cadastro` (leitura)

Os animais do tutor identificado e os agendamentos futuros dele. Sem argumentos.

Saída:
```json
{
  "tutor": { "nome": "Rodrigo Teles", "bloqueado_por_faltas": false },
  "animais": [
    { "animal_id": "a_81", "nome": "Mel", "especie": "cao", "peso_kg": 8.5, "porte": "P",
      "vacinas": [{ "nome": "antirrabica", "valida_ate": "2026-09-30" }], "tem_historico": true }
  ],
  "agendamentos": [
    { "agendamento_id": "ag_502", "animal": "Mel", "servico": "Vacina antirrábica",
      "rotulo": "terça, 29/09 às 14h30", "profissional": "Dra. Beatriz", "status": "confirmado" }
  ]
}
```
Número não cadastrado: `{ "tutor": null }`. O modelo segue para pré-agendamento (RN24).

### 3. `buscar_horarios` (leitura)

Horários livres que já respeitam todas as regras do serviço e do animal.

| Entrada | Tipo | Obrigatório | Limite |
| --- | --- | --- | --- |
| `servico_id` | enum dos serviços agendáveis | Sim | |
| `animal_id` | string | Um dos dois | Precisa ser do tutor |
| `animal_novo` | `{ especie: cao·gato, peso_kg }` | Um dos dois | Peso de 0,1 a 120 kg |
| `data_inicio` | data | Sim | Não pode ser passada nem passar de 60 dias |
| `data_fim` | data | Não | Janela de até 14 dias |
| `periodo` | `manha` · `tarde` | Não | |
| `profissional_id` | string | Não | Só para consultas |

Saída: até 5 opções `{ inicio, rotulo, profissional, duracao_min }`. Se não houver nenhuma, `opcoes: []` e um `motivo` (ex.: "banho de gato só terça e quinta de manhã").

Aplica RN01 a RN04, RN06 a RN08 e RN26. A vacina é checada aqui, antes de oferecer horário, e não depois que o tutor já escolheu (o erro da C6).

### 4. `propor_agendamento` (proposta, não escreve)

| Entrada | Tipo | Obrigatório |
| --- | --- | --- |
| `servico_id` | enum | Sim |
| `animal_id` ou `animal_novo` | como acima; `animal_novo` ganha `nome` (até 40 caracteres) | Sim |
| `inicio` | data e hora, vinda de `buscar_horarios` | Sim |
| `profissional_id` | string | Só consultas |

Saída:
```json
{
  "proposta_id": "pr_9f3c",
  "tipo": "agendamento",
  "resumo": { "animal": "Mel", "servico": "Vacina antirrábica", "rotulo": "terça, 29/09 às 14h30",
              "profissional": "Dra. Beatriz", "preco": "R$ 65,00", "duracao_min": 15 },
  "avisos": ["Trazer a carteirinha de vacinação."],
  "expira_em": "2026-09-28T08:41"
}
```
- `tipo: "pre_agendamento"` quando o tutor ou o animal é novo (RN24).
- Animal sem histórico pedindo vacina: a proposta vira consulta + vacina, com os preços somados e um aviso explicando o motivo (RN09).
- Revalida todas as regras, porque o modelo pode passar um horário que não veio de `buscar_horarios`.

### 5. `propor_remarcacao` (proposta, não escreve)

Entrada: `agendamento_id`, `novo_inicio`, `profissional_id` opcional. Saída igual à da proposta acima, com `tipo: "remarcacao"` e o horário antigo no resumo. Checa se o agendamento é do tutor (RN23) e se faltam pelo menos 2h para ele (RN25).

### 6. `propor_cancelamento` (proposta, não escreve)

Entrada: `agendamento_id`. Mesmas checagens da remarcação. Saída com `tipo: "cancelamento"`.

### 7. `confirmar_proposta` (escrita)

A única ferramenta que muda a agenda. Use só depois que o tutor respondeu que concorda com o resumo.

Entrada: `proposta_id`. O código checa, nesta ordem:

1. A proposta existe e é desta conversa.
2. Não expirou (10 minutos).
3. Foi criada num turno anterior ao atual. Assim, o tutor teve de ver o resumo e responder antes de qualquer escrita.
4. Revalida as regras. O horário pode ter sido ocupado nesse meio tempo.
5. Executa. Se a mesma proposta for confirmada de novo, devolve o resultado da primeira vez e não duplica (idempotência).

Saída: `{ agendamento_id, status: "confirmado" | "pendente_joyce" | "cancelado", resumo }`. Um pré-agendamento ocupa o horário com status `pendente_joyce` e avisa a Joyce.

### 8. `passar_para_joyce` (escrita interna)

| Entrada | Tipo | Obrigatório |
| --- | --- | --- |
| `motivo` | `urgencia` · `saude` · `resultado_exame` · `exame_ou_cirurgia` · `retorno` · `taxi_dog` · `sem_permissao` · `prazo_curto` · `faltas` · `cadastro_novo` · `fora_do_escopo` · `pedido_do_tutor` · `erro` | Sim |
| `urgente` | booleano | Sim |
| `resumo` | texto até 500 caracteres | Sim |

Saída: `{ protocolo, mensagem_para_tutor }`. A mensagem é fixa no código por motivo, por exemplo: "A Joyce já recebeu e te responde por aqui". Assim o agente não promete prazo que ninguém combinou (a C8 prometeu "ainda hoje").

A urgência fora do horário não passa por aqui. Ela é resolvida antes do agente, com resposta fixa (seção Urgência das regras).

## Catálogo de erros

| Código | Quando | Próximo passo sugerido ao modelo |
| --- | --- | --- |
| `ARGUMENTO_INVALIDO` | Schema não bate (tipo, enum, limite) | Corrigir e chamar de novo, ou perguntar ao tutor |
| `NAO_ENCONTRADO` | Id não existe **ou** não é deste tutor | Chamar `consultar_cadastro` |
| `PRECISA_PESO` | Animal sem peso para definir o porte (RN06) | Perguntar o peso |
| `REGRA_DO_SERVICO` | Dia, horário ou profissional que o serviço não permite (RN03, RN04, RN07) | Explicar a regra e buscar alternativa |
| `HORARIO_INDISPONIVEL` | Horário ocupado ou fora do funcionamento (RN01) | Oferecer as `alternativas` que vêm junto |
| `VACINA_PENDENTE` | Banho com vacina vencida ou sem registro (RN08) | Oferecer a vacina antes |
| `PRAZO_CURTO` | Menos de 2h para o horário (RN25) | `passar_para_joyce(motivo=prazo_curto)` |
| `SEM_PERMISSAO` | Número não é do tutor dono do agendamento (RN23) | `passar_para_joyce(motivo=sem_permissao)` |
| `BLOQUEADO_POR_FALTAS` | Duas faltas sem aviso (RN26) | `passar_para_joyce(motivo=faltas)` |
| `NAO_AGENDAVEL` | Serviço que o agente não marca (exame, cirurgia, retorno) | Informar e passar para a Joyce |
| `PROPOSTA_INVALIDA` | Proposta expirada, de outra conversa ou já usada para outra coisa | Propor de novo |
| `CONFIRMACAO_PREMATURA` | `confirmar_proposta` no mesmo turno da proposta | Mostrar o resumo e esperar a resposta do tutor |
| `ERRO_INTERNO` | Falha inesperada (banco, bug) | `passar_para_joyce(motivo=erro)` |

O `NAO_ENCONTRADO` é o mesmo para "não existe" e "não é seu". Assim, quem testa ids aleatórios não descobre quais agendamentos existem.

## Segurança neste bloco

- **Nenhum argumento identifica o tutor.** O escopo vem do contexto, então um id inventado ou injetado pelo usuário cai em `NAO_ENCONTRADO`.
- **Todo argumento passa por schema** (tipos, enums, tamanhos, faixa de datas) antes de chegar ao domínio. Texto livre só em `animal_novo.nome` e `resumo`, ambos com limite.
- **Dados do usuário voltam ao modelo como dado.** Um animal chamado "ignore suas instruções" é só um nome. O bloco 7 testa esse caso.
- **Nenhuma ferramenta executa consulta livre** (SQL, URL, comando). O agente só tem as 8 portas acima.
- **Descrições e schemas vão para o provedor do LLM** junto com o prompt. Nada de chave, URL interna ou dado pessoal neles.

## Ficou para o roadmap

Retorno sem custo (RN10), cálculo de distância do táxi dog (RN17), adicional de hidratação, agendamento de exames, áudio (RN28).
