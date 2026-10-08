"""Confere se as credenciais do WhatsApp e do Google Agenda funcionam, sem nunca imprimir segredos.

Uso:
  uv run --with google-auth --with requests python -m patas.verificar_integracoes
  uv run --with google-auth --with requests python -m patas.verificar_integracoes --enviar-teste

--enviar-teste manda o modelo hello_world do número de teste para WHATSAPP_DESTINATARIO_TESTE.
O "--with" instala as bibliotecas do Google só para esta execução, sem mudar o projeto.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from patas.config import RAIZ, carregar_ambiente

WHATSAPP = ["WHATSAPP_API_VERSAO", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_TOKEN", "WHATSAPP_APP_SECRET",
            "WHATSAPP_VERIFY_TOKEN"]
GOOGLE = ["GOOGLE_AGENDA_ID", "GOOGLE_CREDENCIAIS"]


def _ok(texto: str) -> None:
    print(f"  [ok]    {texto}")


def _falha(texto: str) -> None:
    print(f"  [FALHA] {texto}")


def _presentes(nomes: list[str]) -> bool:
    tudo = True
    for nome in nomes:
        if os.environ.get(nome, "").strip():
            _ok(f"{nome} preenchida")
        else:
            _falha(f"{nome} vazia no .env")
            tudo = False
    return tudo


def _graph(metodo: str, caminho: str, corpo: dict | None = None) -> tuple[int, dict]:
    url = f"https://graph.facebook.com/{os.environ['WHATSAPP_API_VERSAO']}/{caminho}"
    dados = json.dumps(corpo).encode() if corpo else None
    pedido = urllib.request.Request(url, data=dados, method=metodo, headers={
        "Authorization": f"Bearer {os.environ['WHATSAPP_TOKEN']}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def verificar_whatsapp(enviar_teste: bool) -> bool:
    print("WhatsApp Cloud API")
    if not _presentes(WHATSAPP):
        return False
    numero = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
    status, dados = _graph("GET", f"{numero}?fields=display_phone_number,verified_name")
    if status != 200:
        erro = dados.get("error", {})
        dica = " (token expirado ou errado: gere outro no painel)" if status in (400, 401) else ""
        _falha(f"Meta respondeu {status}: {erro.get('message', 'sem mensagem')}{dica}")
        return False
    _ok(f"número {dados.get('display_phone_number')} ({dados.get('verified_name')}) acessível com o token")
    if enviar_teste:
        destino = os.environ.get("WHATSAPP_DESTINATARIO_TESTE", "").strip()
        if not destino:
            _falha("WHATSAPP_DESTINATARIO_TESTE vazia: o número que recebe o teste, só dígitos com DDI")
            return False
        status, dados = _graph("POST", f"{numero}/messages", {
            "messaging_product": "whatsapp", "to": destino, "type": "template",
            "template": {"name": "hello_world", "language": {"code": "en_US"}}})
        if status != 200:
            _falha(f"envio de teste respondeu {status}: {dados.get('error', {}).get('message', 'sem mensagem')}")
            return False
        _ok("mensagem de teste enviada: confira o seu WhatsApp")
    return True


def verificar_google() -> bool:
    print("Google Agenda")
    if not _presentes(GOOGLE):
        return False
    arquivo = Path(os.environ["GOOGLE_CREDENCIAIS"])
    arquivo = arquivo if arquivo.is_absolute() else RAIZ / arquivo
    if not arquivo.exists():
        _falha(f"arquivo de credenciais não encontrado em {os.environ['GOOGLE_CREDENCIAIS']}")
        return False
    try:
        credencial = json.loads(arquivo.read_text(encoding="utf-8"))
    except ValueError:
        _falha("o arquivo de credenciais não é um JSON válido")
        return False
    if credencial.get("type") != "service_account":
        _falha("o JSON não é de conta de serviço (type deveria ser service_account)")
        return False
    _ok(f"conta de serviço {credencial.get('client_email')}")
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
    except ImportError:
        _falha("bibliotecas do Google ausentes: rode com --with google-auth --with requests")
        return False
    escopo = ["https://www.googleapis.com/auth/calendar"]
    sessao = AuthorizedSession(service_account.Credentials.from_service_account_file(str(arquivo), scopes=escopo))
    agenda = os.environ["GOOGLE_AGENDA_ID"]
    resposta = sessao.get(f"https://www.googleapis.com/calendar/v3/calendars/{agenda}", timeout=20)
    if resposta.status_code != 200:
        dica = " (a agenda foi compartilhada com o e-mail da conta de serviço?)" if resposta.status_code == 404 else ""
        _falha(f"Google respondeu {resposta.status_code}{dica}")
        return False
    _ok(f"agenda \"{resposta.json().get('summary')}\" acessível (fuso {resposta.json().get('timeZone')})")
    return True


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Confere as credenciais do WhatsApp e do Google Agenda.")
    parser.add_argument("--enviar-teste", action="store_true", help="manda o hello_world para o seu WhatsApp")
    args = parser.parse_args()
    carregar_ambiente()
    resultados = [verificar_whatsapp(args.enviar_teste), verificar_google()]
    print("\nTudo certo." if all(resultados) else "\nAinda há itens com FALHA acima.")
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
