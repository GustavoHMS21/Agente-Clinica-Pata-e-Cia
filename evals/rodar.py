"""Executor da avaliação (bloco 10, ADR 0009).

Roda o agente de verdade (o mesmo Agente da produção, com o LLM do .env) em cada caso, num
banco em memória com o seed e a data fixa, corrige com evals/corretor.py e grava:
  evals/resultados/<variante>/results.jsonl   uma linha por (caso, repetição)
  evals/resultados/<variante>/traces/          conversa completa de cada caso
  evals/resultados/<variante>/errors.jsonl     falhas que não são nota (API fora, timeout)
Tudo isso fica só na máquina local (evals/resultados/ está no .gitignore).

Uso:
  uv run python -m evals.rodar --approve-harness      depois de revisar casos, corretor e executor
  uv run python -m evals.rodar                         variante baseline, 1 repetição
  uv run python -m evals.rodar --casos c01_banho_g_amanha,c03_chocolate_de_noite
  uv run python -m evals.rodar --variant v1 --model claude-opus-5-5 --reps 2

Cada caso chama o LLM pago. O resumo final mostra o custo medido.
"""

import argparse
import hashlib
import json
import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta
from pathlib import Path

from evals.casos import CASOS, HOJE
from evals.corretor import Execucao, corrigir
from patas.agente.llm import cliente_do_ambiente
from patas.agente.loop import Agente
from patas.agente.prompt import PROMPT_FIXO
from patas.config import carregar_ambiente
from patas.dominio.agenda import ServicoAgenda
from patas.dominio.conversa import ServicoConversa
from patas.repositorio.sqlite import AgendaSQLite, AtendimentoSQLite, conectar, criar_schema
from patas.seed import popular

RAIZ = Path(__file__).resolve().parents[1]
FLUXO = RAIZ / "evals" / "resultados"
ARQUIVOS_DO_HARNESS = ["evals/casos.py", "evals/corretor.py", "evals/rodar.py"]
TETO_POR_CASO_S = 300
MINUTOS_ENTRE_MENSAGENS = 2


class ErroDeExecucao(Exception):
    """Falha que não é nota do agente: vai para errors.jsonl e o caso roda de novo no próximo resume."""

    def __init__(self, classe: str, mensagem: str, uso: dict | None = None, modelo: str | None = None) -> None:
        super().__init__(mensagem)
        self.classe, self.mensagem, self.uso, self.modelo = classe, mensagem, uso or {}, modelo


# Trava de integridade --------------------------------------------------------------------


def sha_do_harness() -> str:
    h = hashlib.sha256()
    for rel in sorted(ARQUIVOS_DO_HARNESS):
        h.update(rel.encode())
        h.update((RAIZ / rel).read_bytes())
    return h.hexdigest()


def portao(aprovar: bool) -> None:
    arquivo = FLUXO / "harness.sha"
    atual = sha_do_harness()
    if aprovar:
        FLUXO.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(atual + "\n", encoding="utf-8")
        print(f"Harness aprovado ({atual[:12]}). Casos, corretor e executor ficam travados nesta versão.")
        return
    if not arquivo.exists() or arquivo.read_text(encoding="utf-8").strip() != atual:
        print("Casos, corretor ou executor mudaram desde a última aprovação (ou nunca foram aprovados).\n"
              "Revise as mudanças e rode uma vez com --approve-harness.")
        sys.exit(2)


# Um caso -----------------------------------------------------------------------------------


def rodar_caso(caso: dict, rep: int, llm, modelo_esperado: str | None, pasta: Path) -> dict:
    conn = conectar(":memory:")
    try:
        criar_schema(conn)
        popular(conn, date.fromisoformat(HOJE))
        seed = {r["id"]: (r["inicio"], r["profissional_id"], r["status"])
                for r in conn.execute("SELECT id, inicio, profissional_id, status FROM agendamento")}
        agenda_repo, atendimento_repo = AgendaSQLite(conn), AtendimentoSQLite(conn)
        conversas = ServicoConversa(agenda_repo, atendimento_repo)
        agente = Agente(llm, ServicoAgenda(agenda_repo, atendimento_repo), conversas)

        inicio_caso = datetime.fromisoformat(caso.get("agora", HOJE + "T09:00"))
        respostas, cronometro = [], time.perf_counter()
        for i, mensagem in enumerate(caso["mensagens"]):
            momento = inicio_caso + timedelta(minutes=MINUTOS_ENTRE_MENSAGENS * i)
            for parte in (mensagem if isinstance(mensagem, list) else [mensagem]):  # rajada = um turno
                conversa = conversas.receber(caso["telefone"], parte, momento)
            respostas.append(agente.responder(conversa.id, momento) or "")
        latencia = time.perf_counter() - cronometro

        desfechos = [r["nome"] for r in conn.execute("SELECT nome FROM execucao WHERE tipo = 'turno' ORDER BY turno")]
        chamadas = conn.execute("SELECT nome, tokens_entrada, tokens_saida, tokens_cache_lidos, tokens_cache_gravados,"
                                " custo_usd FROM execucao WHERE tipo = 'llm'").fetchall()
        uso = {
            "input_tokens": sum(c["tokens_entrada"] for c in chamadas),
            "output_tokens": sum(c["tokens_saida"] for c in chamadas),
            "cache_read_input_tokens": sum(c["tokens_cache_lidos"] for c in chamadas),
            "cache_creation_input_tokens": sum(c["tokens_cache_gravados"] for c in chamadas),
        }
        modelos = sorted({c["nome"] for c in chamadas})
        modelo = modelos[0] if len(modelos) == 1 else ",".join(modelos) or None
        if "falha_llm" in desfechos:
            raise ErroDeExecucao("erro_de_servico", "O LLM não respondeu em algum turno.", uso, modelo)
        if modelo_esperado and any(m not in (modelo_esperado, "desconhecido") for m in modelos):
            # Fallback ou troca silenciosa de modelo invalida a comparação.
            raise ErroDeExecucao("modelo_trocado", f"Servido {modelos}, esperado {modelo_esperado}.", uso, modelo)

        nota = corrigir(caso, Execucao(respostas, desfechos, conn, seed))
        trace = _trace(conn)
        (pasta / "traces").mkdir(parents=True, exist_ok=True)
        (pasta / "traces" / f"{caso['id']}_rep{rep}.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=1), encoding="utf-8")
        return {
            "prompt_id": caso["id"],
            "rep": rep,
            "prompt": "\n".join(" / ".join(m) if isinstance(m, list) else m for m in caso["mensagens"]),
            "tags": caso["tags"],
            "stop_reason": "end_turn",
            "status": "ok",
            **nota,
            "model": modelo,
            "usage": uso,
            "latency_s": round(latencia, 1),
            "tool_calls": conn.execute("SELECT COUNT(*) FROM execucao WHERE tipo = 'ferramenta'").fetchone()[0],
            "custo_usd": round(sum(c["custo_usd"] or 0 for c in chamadas), 5),
            "meta": {"desfechos": desfechos, "turnos": len(respostas)},
        }
    finally:
        conn.close()


def _trace(conn) -> list[dict]:
    """Conversa no formato do relatório: system, user, assistant, tool_call, tool_result."""
    trace = [{"role": "system", "content": PROMPT_FIXO}]
    for r in conn.execute("SELECT papel, conteudo FROM mensagem ORDER BY turno, id"):
        blocos = json.loads(r["conteudo"])
        if r["papel"] == "tutor":
            trace.append({"role": "user", "content": "\n".join(b.get("text", "") for b in blocos)})
        elif r["papel"] == "sistema":
            trace.append({"role": "system", "content": "\n".join(b.get("text", "") for b in blocos)})
        elif r["papel"] == "agente":
            for b in blocos:
                if b["type"] == "text":
                    trace.append({"role": "assistant", "content": b["text"]})
                elif b["type"] == "tool_use":
                    trace.append({"role": "tool_call", "name": b["name"],
                                  "content": json.dumps(b["input"], ensure_ascii=False, indent=2)})
        else:
            trace += [{"role": "tool_result", "content": b["content"]} for b in blocos]
    return trace


# Execução ----------------------------------------------------------------------------------


def _ja_feitos(pasta: Path) -> set[tuple[str, int]]:
    arquivo = pasta / "results.jsonl"
    if not arquivo.exists():
        return set()
    return {(r["prompt_id"], r["rep"]) for r in map(json.loads, arquivo.read_text(encoding="utf-8").splitlines()) if r}


def _anexar(arquivo: Path, linha: dict, trava: threading.Lock) -> None:
    with trava, arquivo.open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


def _intervalo(acertos: int, n: int) -> tuple[float, float]:
    """Intervalo de confiança de Wilson, 95%: com poucos casos, a nota tem margem larga."""
    if n == 0:
        return 0.0, 0.0
    z, p = 1.96, acertos / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    margem = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centro - margem), min(1.0, centro + margem)


def resumo(pasta: Path) -> None:
    linhas = [json.loads(l) for l in (pasta / "results.jsonl").read_text(encoding="utf-8").splitlines() if l]
    erros = (pasta / "errors.jsonl").read_text(encoding="utf-8").splitlines() if (pasta / "errors.jsonl").exists() else []
    print(f"\n=== {pasta.name}: {len(linhas)} execuções corrigidas, {len(erros)} falhas fora da nota")
    grupos: dict[str, list[int]] = {}
    for l in linhas:
        grupos.setdefault(l["tags"][0], []).append(l["grade"]["passou"])
    for nome, notas in [("TOTAL", [l["grade"]["passou"] for l in linhas]), *sorted(grupos.items())]:
        de, ate = _intervalo(sum(notas), len(notas))
        print(f"  {nome:22s} {sum(notas):3d}/{len(notas):<3d} = {sum(notas) / len(notas):5.0%}  (IC95% {de:.0%} a {ate:.0%})")
    custo = sum(l["custo_usd"] for l in linhas)
    tempos = sorted(l["latency_s"] for l in linhas)
    print(f"  custo medido: US$ {custo:.3f} (US$ {custo / len(linhas):.4f} por caso) | tempo mediano por caso:"
          f" {tempos[len(tempos) // 2]:.0f} s")
    for l in linhas:
        if not l["grade"]["passou"]:
            print(f"  ✗ {l['prompt_id']} (rep {l['rep']}): {l['explanation']['passou']}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Avaliação do agente da Patas & Cia.")
    p.add_argument("--variant", default="baseline", help="baseline ou v1, v2, ...")
    p.add_argument("--model", help="troca o modelo (LLM_MODELO) só nesta execução")
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--casos", help="ids separados por vírgula (padrão: todos)")
    p.add_argument("--paralelo", type=int, default=4)
    p.add_argument("--approve-harness", action="store_true", help="aprova a versão atual de casos/corretor/executor")
    a = p.parse_args()

    if a.variant != "baseline" and not (a.variant[0] == "v" and a.variant[1:].isdigit()):
        p.error("--variant precisa ser baseline ou v<N> (o relatório ignora outros nomes)")
    portao(a.approve_harness)
    if a.approve_harness:
        return 0

    carregar_ambiente()
    if a.model:
        import os
        os.environ["LLM_MODELO"] = a.model
    llm = cliente_do_ambiente()
    modelo_esperado = getattr(llm, "_modelo", None)

    pasta = FLUXO / a.variant
    pasta.mkdir(parents=True, exist_ok=True)
    escolhidos = [c for c in CASOS if not a.casos or c["id"] in a.casos.split(",")]
    feitos = _ja_feitos(pasta)
    tarefas = [(c, r) for c in escolhidos for r in range(a.reps) if (c["id"], r) not in feitos]
    print(f"{len(tarefas)} execuções a rodar ({len(escolhidos)} casos x {a.reps} rep, {len(feitos)} já feitas)"
          f" com {modelo_esperado or 'modelo do provedor'}.")

    trava, inicio_de = threading.Lock(), {}

    def trabalho(caso, rep):
        inicio_de[(caso["id"], rep)] = time.monotonic()
        return rodar_caso(caso, rep, llm, modelo_esperado, pasta)

    with ThreadPoolExecutor(max_workers=a.paralelo) as pool:
        futuros = {pool.submit(trabalho, c, r): (c, r) for c, r in tarefas}
        pendentes = set(futuros)
        while pendentes:
            prontos, pendentes = wait(pendentes, timeout=5)
            for f in prontos:
                caso, rep = futuros[f]
                try:
                    linha = f.result()
                    _anexar(pasta / "results.jsonl", linha, trava)
                    print(f"  {'✓' if linha['grade']['passou'] else '✗'} {caso['id']} rep {rep}"
                          f" ({linha['latency_s']:.0f} s, US$ {linha['custo_usd']:.4f})")
                except ErroDeExecucao as e:
                    _anexar(pasta / "errors.jsonl", {"prompt_id": caso["id"], "rep": rep, "classe": e.classe,
                                                     "mensagem": e.mensagem, "model": e.modelo, "usage": e.uso}, trava)
                    print(f"  ! {caso['id']} rep {rep}: {e.classe} ({e.mensagem})")
                except Exception as e:  # bug no harness: registra e segue com os outros casos
                    _anexar(pasta / "errors.jsonl", {"prompt_id": caso["id"], "rep": rep, "classe": "erro_do_harness",
                                                     "mensagem": f"{type(e).__name__}: {e}"}, trava)
                    print(f"  ! {caso['id']} rep {rep}: erro do harness ({type(e).__name__}: {e})")
            agora = time.monotonic()
            for f in list(pendentes):
                caso, rep = futuros[f]
                comecou = inicio_de.get((caso["id"], rep))
                if comecou and agora - comecou > TETO_POR_CASO_S:
                    # A thread segue em segundo plano; o caso é registrado como timeout e sai da espera.
                    pendentes.discard(f)
                    _anexar(pasta / "errors.jsonl", {"prompt_id": caso["id"], "rep": rep, "classe": "timeout",
                                                     "mensagem": f"Passou de {TETO_POR_CASO_S} s."}, trava)
                    print(f"  ! {caso['id']} rep {rep}: timeout")

    if (pasta / "results.jsonl").exists():
        resumo(pasta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
