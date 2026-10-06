# ADR 0003: stack do MVP

- Status: aceito
- Data: 2026-10-06
- Bloco: 4

## Decisão

| Camada | Escolha | Por quê |
| --- | --- | --- |
| Linguagem | Python 3.12+ | Ecossistema de IA, SDK oficial da Anthropic, leitura fácil |
| Ambiente e dependências | uv | Um comando cria o ambiente e trava as versões (`uv.lock`) |
| Banco | SQLite (módulo `sqlite3` da biblioteca padrão), SQL escrito à mão em `schema.sql` | Zero instalação e nenhum ORM para aprender. Cada consulta fica visível |
| LLM | SDK da Anthropic direto, sem framework de agente (bloco 6) | O loop do agente tem poucas linhas. Escrevendo à mão, cada peça fica visível |
| API e interface | FastAPI (bloco 8) | Padrão do playbook para webhook de WhatsApp |
| Testes | pytest | |

Dependências entram só no bloco em que são usadas. O bloco 4 não depende de nenhuma biblioteca externa em produção, só de pytest para os testes.

## Consequências

- O SQLite não tem restrição de sobreposição de horário (o `EXCLUDE` do Postgres). O repositório resolve isso com uma transação `BEGIN IMMEDIATE`: checa o conflito e insere dentro dela, então duas escritas nunca checam ao mesmo tempo.
- Datas ficam em texto ISO no horário local de Guarulhos (`2026-10-08T10:00`), sem fuso. Basta porque a clínica tem uma unidade só. Com mais de um fuso, o certo seria gravar em UTC.
- Dinheiro em centavos (inteiro), nunca em float.
- Trocar para Postgres no deploy (bloco 11) muda só o adaptador do repositório. O domínio e as ferramentas não mudam, porque falam com a interface.
