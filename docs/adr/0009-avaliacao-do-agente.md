# ADR 0009: avaliação do agente

- Status: aceito (avaliação montada e pilotada; rodada completa de base ainda não executada)
- Data: 2026-10-06
- Bloco: 10

## Contexto

Os testes de unidade garantem o código com um LLM falso. Não dizem se o modelo de verdade marca o horário certo, recusa um ataque ou deixa de orientar sobre saúde. Sem avaliação, toda troca de prompt, modelo ou provedor é palpite. A cliente definiu o sucesso como "a maior parte dos agendamentos simples concluída sem a Joyce": isso precisa virar número.

## Decisão

Avaliação em `evals/`, rodando o agente real (o mesmo `Agente` da produção) contra casos fixos:

| Peça | Arquivo | O que faz |
| --- | --- | --- |
| Casos | `evals/casos.py` (revisão em `evals/casos.md`) | 30 casos: as 15 conversas reais adaptadas ao seed, 12 ataques, a regra de faltas e uma mensagem cheia de erros de digitação. Data fixa: terça, 06/10/2026 |
| Corretor | `evals/corretor.py` | Checagens programáticas, sem LLM juiz. A nota vem do **estado final do banco** (agendamento certo, nada indevido alterado, passagem certa) e do texto só no que é verificável (preço, palavras obrigatórias, vazamentos) |
| Executor | `evals/rodar.py` | Banco em memória por caso, grava cada caso ao terminar (retoma de onde parou), teto de tempo, erro de serviço fora da nota, detecção de modelo trocado, trava de integridade |

Métricas: `passou` (todas as checagens) e `checagens` (fração). Meta proposta: **agendamento simples ≥ 90%**.

### Decisões de desenho

- **Resultado, não texto.** O agente age no mundo; o que importa é o que ficou no banco. Texto livre tem muitas formas certas e daria um corretor frágil.
- **Guardrail que segurou conta como falha.** `saude_bloqueada` e `vazamento_bloqueado` reprovam o caso: a avaliação mede o modelo, e uma trava não pode esconder uma piora dele.
- **Trava de integridade.** Um hash de casos, corretor e executor; se algo muda, o executor não roda até o dono do projeto aprovar (`--approve-harness`). Ninguém melhora a nota mexendo na régua sem perceber.
- **Corretor testado antes de gastar.** Execução nula reprova os 30 casos, oráculo passa, e respostas confiantes mas erradas reprovam (`tests/test_corretor.py`).

## Piloto (5 casos, Claude Sonnet 5.5)

4 de 5 passaram. O caso do filhote de número novo (C10) achou dois bugs reais, corrigidos:
1. Primeira vacina: o agente marcava só a consulta (R$ 160), sem a vacina. O prompt e a ferramenta agora dizem que se agenda a vacina e o sistema monta consulta + vacina (R$ 255).
2. `nome_tutor` opcional era omitido mesmo com o nome na conversa; virou obrigatório (vazio quando o telefone tem cadastro).

E um na trava de loop: repetir a mesma chamada errada agora encerra o turno cedo e repete o erro original.

Custo medido por caso: de US$ 0 (urgência com resposta fixa) a US$ 0,047, mediana US$ 0,035.

## Pendências

- **Rodada completa de base:** 30 casos × 3 repetições ≈ US$ 2,70, uns 15 minutos. Antes, aprovar a versão atual (`uv run python -m evals.rodar --approve-harness`), porque o caso C10 ganhou uma quinta mensagem depois do piloto.
- **Tutor com falas fixas é frágil** quando o agente precisa de um turno a mais. Evolução possível: um LLM fazendo o papel do tutor, com objetivo definido. Mais realista, porém mais caro e com mais variação entre rodadas.
- **Tom e naturalidade** não são medidos (exigiriam um LLM juiz).

## Como rodar

```powershell
uv run python -m evals.rodar --approve-harness          # só quando casos/corretor/executor mudarem
uv run python -m evals.rodar --reps 3                   # rodada completa (retoma se cair)
uv run python -m evals.rodar --variant v1 --model claude-opus-5-5 --reps 3   # comparar outro modelo
```
