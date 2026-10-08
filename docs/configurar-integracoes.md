# Configurar as integrações: WhatsApp (número de teste) e Google Agenda

Passo a passo para o dono das contas. Os nomes dos botões nos painéis da Meta e do Google mudam de tempos em tempos: siga o sentido de cada passo, não o texto exato.

**Segurança:** token, chave secreta do app, verify token e o arquivo JSON do Google são segredos e vão **só** para o `.env` ou para a pasta `segredos/` (as duas bloqueadas no git e na imagem Docker); no deploy, para o cofre de segredos da plataforma. IDs (do número, da conta, da agenda) e o e-mail da conta de serviço não são segredo.

---

## Parte 1: WhatsApp Cloud API com o número de teste da Meta

O número de teste é gratuito, já vem pronto e envia mensagens para até 5 números cadastrados. Serve para desenvolver sem tocar no número da clínica.

### Passos

1. Abra **developers.facebook.com** com o dono logado. Se ele ainda não for desenvolvedor, o site pede para registrar a conta como desenvolvedor (aceitar termos e confirmar telefone ou e-mail): **o dono faz**.
2. **Meus apps → Criar app.**
3. Nome do app: `Patas Agente Teste`. E-mail de contato: o do dono.
4. Caso de uso: o de **WhatsApp** (algo como "Conectar-se com clientes pelo WhatsApp"). Se perguntar o tipo, **Empresa**.
5. Portfólio empresarial: vincule a um existente ou crie um novo. Para o número de teste, não precisa verificar a empresa.
6. Conclua a criação. No painel do app, abra **WhatsApp → Configuração da API** (API Setup).
7. Nessa tela, anote:
   - **Número de teste** (começa com +1 555): não é segredo;
   - **Identificação do número de telefone** (*Phone number ID*): não é segredo;
   - **ID da conta do WhatsApp Business** (*WhatsApp Business Account ID*): não é segredo;
   - **Versão da API**, que aparece no exemplo de comando da tela, no endereço `graph.facebook.com/vXX.X/...`: anote o `vXX.X`.
8. Em **Para** (*To*), adicione o WhatsApp do dono como destinatário. Chega um código no WhatsApp dele: **o dono digita**.
9. Clique em **Gerar token de acesso** (vale 24 horas). **Segredo:** vai direto para o `.env`.
10. Envie a mensagem de teste pelo próprio painel (modelo `hello_world`) e confirme com o dono que ela chegou.
11. **Chave secreta do app:** menu do app → **Configurações do app → Básico → Chave secreta do app → Mostrar** (pode pedir a senha do dono). **Segredo:** vai direto para o `.env`.
12. **Verify token:** uma senha que o próprio projeto inventa. Gere no terminal do projeto e coloque direto no `.env`:
    ```powershell
    uv run python -c "import secrets; print(secrets.token_urlsafe(24))"
    ```

### O que vai para o `.env`

```
WHATSAPP_API_VERSAO=vXX.X                  # passo 7
WHATSAPP_DESTINATARIO_TESTE=5511999999999   # WhatsApp do dono, só dígitos, com 55 e DDD
WHATSAPP_PHONE_NUMBER_ID=                   # passo 7
WHATSAPP_TOKEN=                             # passo 9 (segredo)
WHATSAPP_APP_SECRET=                        # passo 11 (segredo)
WHATSAPP_VERIFY_TOKEN=                      # passo 12 (segredo)
```

### Não faça agora

- **Webhook** (URL de callback): é configurado depois, quando o servidor tiver uma URL pública com HTTPS.
- **Token permanente:** o temporário expira em 24 horas. Para testar, gere outro no mesmo painel. O permanente (usuário do sistema do portfólio empresarial, com a permissão `whatsapp_business_messaging`) é só para produção.

---

## Parte 2: Google Agenda com conta de serviço

Uma chave de API simples do Google só lê agendas públicas. Para o agente consultar e criar eventos, usamos uma **conta de serviço**: um "usuário robô" que recebe acesso à agenda como se fosse uma pessoa.

### Passos

1. Abra **console.cloud.google.com** com o dono logado. Se for o primeiro acesso, ele aceita os termos do Google Cloud. **Não é preciso ativar faturamento** para a Calendar API.
2. Crie um projeto: `patas-agenda-teste`.
3. Com o projeto selecionado: **APIs e serviços → Biblioteca →** busque **Google Calendar API → Ativar**.
4. **IAM e administrador → Contas de serviço → Criar conta de serviço.** Nome: `patas-agente`. Pule a parte de papéis e de acesso de usuários e conclua.
5. Anote o **e-mail da conta de serviço** (termina em `.iam.gserviceaccount.com`): não é segredo.
6. Abra a conta criada → **Chaves → Adicionar chave → Criar nova chave → JSON → Criar.** O navegador baixa um arquivo. **Segredo:** mova para `segredos/google-agenda.json` dentro do projeto e apague a cópia da pasta de downloads.
7. Abra **calendar.google.com** e crie uma agenda nova (**Outras agendas → + → Criar nova agenda**): nome `Patas - Banho e tosa (teste)`, fuso **(GMT-03:00) Horário de Brasília**.
8. Nas configurações dessa agenda, em **Compartilhar com pessoas e grupos específicos**, adicione o **e-mail da conta de serviço** (passo 5) com a permissão **Fazer alterações nos eventos**.
9. Na mesma página, em **Integrar agenda**, anote o **ID da agenda** (termina em `@group.calendar.google.com`): não é segredo.

Se o passo 6 for bloqueado ("criação de chave de conta de serviço desativada"), a conta está numa organização que proíbe essas chaves: use uma conta Gmail pessoal.

### O que vai para o `.env`

```
GOOGLE_AGENDA_ID=                          # passo 9
GOOGLE_CREDENCIAIS=segredos/google-agenda.json
```

---

## Verificação final

Na pasta do projeto:

```powershell
uv run --with google-auth --with requests python -m patas.verificar_integracoes --enviar-teste
```

O resultado esperado é `[ok]` em todas as linhas, a mensagem "Tudo certo." e um `hello_world` chegando no WhatsApp do dono. O comando nunca mostra valores de segredo. Se algo falhar, a linha `[FALHA]` diz o que é: variável vazia, token expirado, agenda não compartilhada.
