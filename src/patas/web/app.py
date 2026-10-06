"""Servidor web (bloco 8, ADR 0007): simulador de WhatsApp e painel da Joyce.

Rodar: uv run uvicorn patas.web.app:criar_app --factory --port 8000

O simulador faz o papel do canal: no WhatsApp real, o telefone vem do provedor
(webhook), nunca do usuário. Aqui ele é escolhido na tela só para teste.
"""

import os
import re
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from datetime import date, timedelta
from importlib import resources
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from patas.agente.llm import ClienteLLM, cliente_do_ambiente
from patas.agente.loop import Agente
from patas.config import agora_local, caminho_banco, carregar_ambiente
from patas.dominio.agenda import ServicoAgenda
from patas.dominio.conversa import ServicoConversa
from patas.repositorio.painel_sqlite import PainelSQLite
from patas.repositorio.sqlite import AgendaSQLite, AtendimentoSQLite, conectar

SENHA_MINIMA = 12
CABECALHOS_DE_SEGURANCA = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # Com HTTPS (deploy), o navegador passa a recusar HTTP neste domínio por 1 ano. Em http://localhost é ignorado.
    "Strict-Transport-Security": "max-age=31536000",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
}


class MensagemEntrada(BaseModel):
    telefone: str = Field(min_length=8, max_length=25, pattern=r"^[0-9()+\-\s]+$")
    texto: str = Field(min_length=1, max_length=4000)


def criar_app() -> FastAPI:
    """Raiz de composição: o único lugar que lê o ambiente e monta as peças reais (uvicorn --factory)."""
    carregar_ambiente()
    usuario = os.environ.get("PAINEL_USUARIO", "").strip()
    senha = os.environ.get("PAINEL_SENHA", "").strip()
    _validar_login(usuario, senha)  # antes de criar o cliente do LLM: falha rápida e sem custo
    return montar_app(cliente_do_ambiente(), caminho_banco(), usuario, senha)


def _validar_login(usuario: str, senha: str) -> None:
    # Falha fechada: sem login configurado, o servidor não sobe. O painel mostra dados de todos os
    # tutores e o simulador gasta crédito do LLM; nada disso pode ficar aberto por esquecimento.
    if not usuario or not senha:
        raise RuntimeError("Defina PAINEL_USUARIO e PAINEL_SENHA no .env: o servidor não sobe sem login.")
    if len(senha) < SENHA_MINIMA:
        raise RuntimeError(f"PAINEL_SENHA precisa de pelo menos {SENHA_MINIMA} caracteres.")


def montar_app(llm: ClienteLLM, banco: Path | str, usuario: str, senha: str) -> FastAPI:
    """Monta o app com o que receber, sem ler ambiente: é o que os testes usam."""
    _validar_login(usuario, senha)
    banco = Path(banco)
    if not banco.exists():
        raise RuntimeError("Banco não encontrado. Rode antes: uv run python -m patas.seed")

    basic = HTTPBasic(realm="Patas & Cia")

    def exigir_login(credenciais: HTTPBasicCredentials = Depends(basic)) -> None:
        # compare_digest: o tempo de comparação não revela quantos caracteres batem.
        usuario_ok = secrets.compare_digest(credenciais.username.encode(), usuario.encode())
        senha_ok = secrets.compare_digest(credenciais.password.encode(), senha.encode())
        if not (usuario_ok and senha_ok):
            raise HTTPException(401, "Login inválido.", headers={"WWW-Authenticate": 'Basic realm="Patas & Cia"'})

    def exigir_origem_do_app(x_requested_with: str | None = Header(default=None)) -> None:
        # CSRF: o navegador reenvia o login guardado para qualquer site que chame este servidor.
        # Um cabeçalho próprio obriga a uma checagem prévia (CORS) que outro site não passa.
        if x_requested_with != "patas":
            raise HTTPException(403, "Requisição sem o cabeçalho do aplicativo.")

    def conexao() -> Iterator[sqlite3.Connection]:
        # Uma conexão por requisição: o sqlite3 não compartilha conexão entre threads.
        conn = conectar(banco)
        try:
            yield conn
        finally:
            conn.close()

    # Sem /docs: a documentação automática listaria as rotas para quem chegar sem login.
    app = FastAPI(title="Patas & Cia", docs_url=None, redoc_url=None, openapi_url=None)
    login = [Depends(exigir_login)]
    escrita = [Depends(exigir_login), Depends(exigir_origem_do_app)]

    @app.middleware("http")
    async def cabecalhos(request: Request, call_next):
        resposta = await call_next(request)
        resposta.headers.update(CABECALHOS_DE_SEGURANCA)
        return resposta

    @app.get("/saude")
    def saude() -> dict:
        """Sem login: só diz ao deploy que o servidor está de pé (bloco 11)."""
        return {"ok": True}

    @app.get("/", dependencies=login)
    def inicio() -> RedirectResponse:
        return RedirectResponse("/chat")

    @app.get("/chat", response_class=HTMLResponse, dependencies=login)
    def pagina_chat() -> str:
        return _pagina("chat.html")

    @app.get("/joyce", response_class=HTMLResponse, dependencies=login)
    def pagina_joyce() -> str:
        return _pagina("joyce.html")

    @app.get("/api/tutores", dependencies=login)
    def tutores(conn: sqlite3.Connection = Depends(conexao)) -> list[dict]:
        return PainelSQLite(conn).tutores_para_simulador()

    travas: dict[str, threading.Lock] = {}
    guarda_das_travas = threading.Lock()

    def trava_da_conversa(conversa_id: str) -> threading.Lock:
        with guarda_das_travas:
            return travas.setdefault(conversa_id, threading.Lock())

    @app.post("/api/mensagens", dependencies=escrita)
    def mensagem(entrada: MensagemEntrada, conn: sqlite3.Connection = Depends(conexao)) -> dict:
        agenda_repo, atendimento_repo = AgendaSQLite(conn), AtendimentoSQLite(conn)
        conversas = ServicoConversa(agenda_repo, atendimento_repo)
        conversa = conversas.receber(entrada.telefone, entrada.texto, agora_local())
        # Um turno por vez em cada conversa: duas mensagens rápidas não rodam o agente em paralelo
        # (o histórico se embaralharia). A segunda espera e responde o que ainda estiver pendente.
        with trava_da_conversa(conversa.id):
            agente = Agente(llm, ServicoAgenda(agenda_repo, atendimento_repo), conversas)
            resposta = agente.responder(conversa.id, agora_local())
        return {"resposta": resposta or ""}

    @app.get("/api/passagens", dependencies=login)
    def passagens(conn: sqlite3.Connection = Depends(conexao)) -> list[dict]:
        return PainelSQLite(conn).passagens_abertas()

    @app.post("/api/passagens/{protocolo}/resolver", dependencies=escrita)
    def resolver(protocolo: str, conn: sqlite3.Connection = Depends(conexao)) -> dict:
        if not re.fullmatch(r"PJ-[0-9A-F]{6}", protocolo) or not PainelSQLite(conn).resolver_passagem(protocolo):
            raise HTTPException(404, "Passagem não encontrada ou já resolvida.")
        return {"ok": True}

    @app.get("/operacao", response_class=HTMLResponse, dependencies=login)
    def pagina_operacao() -> str:
        return _pagina("operacao.html")

    @app.get("/api/operacao", dependencies=login)
    def operacao(dias: int = 7, conn: sqlite3.Connection = Depends(conexao)) -> dict:
        dias = max(1, min(dias, 90))
        hoje = agora_local().date()
        return PainelSQLite(conn).operacao(hoje - timedelta(days=dias - 1), hoje)

    @app.get("/api/agenda", dependencies=login)
    def agenda(dia: date | None = None, conn: sqlite3.Connection = Depends(conexao)) -> dict:
        dia = dia or agora_local().date()
        return {"dia": dia.isoformat(), "agendamentos": PainelSQLite(conn).agenda_do_dia(dia)}

    return app


def _pagina(nome: str) -> str:
    return resources.files("patas.web").joinpath("static", nome).read_text(encoding="utf-8")
