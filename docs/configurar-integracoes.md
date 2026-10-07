# Configurar as integrações: WhatsApp e Google Agenda

Passo a passo para quem é dono das contas. Os nomes dos botões nos painéis da Meta e do Google mudam de tempos em tempos; procure pelo sentido, não pelo texto exato.

**Regra de segurança:** IDs podem ser compartilhados (chat, documento). **Token, app secret, verify token e o arquivo JSON do Google são segredos:** vão só para o `.env` ou para a pasta `segredos/` (as duas bloqueadas no git), e no deploy para o cofre de segredos da plataforma.

## WhatsApp Cloud API com o número de teste da Meta

O número de teste é gratuito, já vem pronto e manda mensagens para até 5 números que você cadastrar. Serve para desenvolver sem tocar no número da clínica.

1. Entre em **developers.facebook.com** com a sua conta e vá em **Meus apps → Criar app**.
2. No caso de uso, escolha o de **WhatsApp** (conectar-se com clientes pelo WhatsApp). Tipo: **Empresa**.
3. Vincule a um **portfólio empresarial**. Pode criar um novo; para teste, não precisa de verificação da empresa.
4. No painel do app, abra **WhatsApp → Configuração da API**. Ali aparecem:
   - o **número de teste** (começa com +1 555);
   - a **identificação do número de telefone** (*Phone number ID*);
   - o **ID da conta do WhatsApp Business** (*WABA ID*);
   - o botão para gerar o **token de acesso temporário** (vale 24 horas).
5. No campo **Para**, cadastre o **seu WhatsApp** como destinatário e confirme com o código que chega no seu celular.
6. Use o botão de envio de teste do próprio painel (modelo `hello_world`) e confira que a mensagem chegou.
7. **App secret:** Configurações do app → Básico → Chave secreta do app → Mostrar.
8. **Verify token:** uma senha que você inventa e que o nosso servidor usa para provar à Meta que o webhook é nosso. Gere uma forte:
   ```powershell
   uv run python -c "import secrets; print(secrets.token_urlsafe(24))"
   ```

No `.env`:
```
WHATSAPP_PHONE_NUMBER_ID=<identificação do número de telefone>
WHATSAPP_TOKEN=<token de acesso>
WHATSAPP_APP_SECRET=<chave secreta do app>
WHATSAPP_VERIFY_TOKEN=<o que você gerou no passo 8>
```

O **webhook** (URL de callback + verify token + assinar o campo `messages`) é configurado depois, quando o servidor tiver uma URL pública com HTTPS: o deploy na Fly.io, ou um túnel temporário durante o desenvolvimento.

O token temporário expira em 24 horas. Para os testes, gere outro no mesmo painel. Em produção, usa-se um **token permanente** de um *usuário do sistema* do portfólio empresarial, com a permissão `whatsapp_business_messaging`.

## Google Agenda com conta de serviço

Uma chave de API simples do Google só lê agendas públicas. Para o agente criar e consultar eventos, usamos uma **conta de serviço**: um "usuário robô" que recebe acesso à agenda como se fosse uma pessoa.

1. Em **console.cloud.google.com**, crie um projeto (ex.: `patas-agenda-teste`).
2. **APIs e serviços → Biblioteca →** procure **Google Calendar API** → **Ativar**.
3. **IAM e administrador → Contas de serviço → Criar conta de serviço.** Nome: `patas-agente`. Não precisa dar papéis no projeto.
4. Abra a conta criada → **Chaves → Adicionar chave → Criar nova chave → JSON.** Um arquivo é baixado: mova para `segredos/google-agenda.json` dentro do projeto.
5. Em **calendar.google.com**, crie uma agenda nova: **Patas - Banho e tosa (teste)**.
6. Nas configurações dessa agenda, em **Compartilhar com pessoas específicas**, adicione o **e-mail da conta de serviço** (termina em `.iam.gserviceaccount.com`) com a permissão **Fazer alterações nos eventos**.
7. Na mesma página, em **Integrar agenda**, copie o **ID da agenda** (termina em `@group.calendar.google.com`).

No `.env`:
```
GOOGLE_AGENDA_ID=<ID da agenda>
GOOGLE_CREDENCIAIS=segredos/google-agenda.json
```

Se o passo 4 for bloqueado ("criação de chaves desativada"), a conta Google está numa organização que proíbe chaves de conta de serviço: use uma conta Gmail pessoal para o teste.
