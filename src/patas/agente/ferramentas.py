"""As 8 ferramentas do agente (docs/contratos-das-ferramentas.md).

Duas partes:
- FERRAMENTAS: as definições que vão para a API. Nome, descrição e schema são lidos
  pelo modelo, ou seja, são prompt. Nada de segredo ou dado interno aqui.
- Executor: valida e converte os argumentos, chama o ServicoAgenda com o Contexto
  injetado pelo código e devolve JSON. Recusa de regra vira dado (ok: false), nunca exceção.
"""

import json
import logging
from datetime import date, datetime
from typing import Any

from patas.agente.formato import DIAS, reais, rotulo
from patas.dominio.agenda import MOTIVOS_PASSAGEM, AnimalNovo, Contexto, ServicoAgenda
from patas.dominio.erros import Codigo, ErroRegra
from patas.dominio.modelos import Agendamento, Especie, Opcao, Proposta, Servico, StatusAgendamento

log = logging.getLogger(__name__)

_DATA = {"type": "string", "description": "Data no formato AAAA-MM-DD."}
_DATA_HORA = {"type": "string", "description": "Data e hora no horário de Guarulhos, formato AAAA-MM-DDTHH:MM, sem fuso."}
# O animal é obrigatório e plano (sem objeto aninhado opcional): no teste real, campo de animal
# opcional era omitido pelo modelo, que repetia a chamada até o limite de passos (ADR 0006).
_ANIMAL = {
    "animal_id": {
        "type": "string",
        "description": 'O animal_id que veio de consultar_cadastro (ex.: a_thor). Animal sem cadastro: "novo", '
                       "com especie_animal e peso_kg_animal.",
    },
    "especie_animal": {"type": "string", "enum": ["cao", "gato"], "description": 'Só quando animal_id = "novo".'},
    "peso_kg_animal": {"type": "number",
                       "description": 'Só quando animal_id = "novo". Peso dito pelo tutor; obrigatório para banho e tosa.'},
}
_PROFISSIONAL_ID = {
    "type": "string",
    "description": "Id de profissional (ex.: vet_paula), nunca de animal. Omita se o tutor não pediu alguém específico.",
}


def _ferramenta(nome: str, descricao: str, propriedades: dict, obrigatorios: list[str]) -> dict:
    return {
        "name": nome,
        "description": descricao,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": propriedades,
            "required": obrigatorios,
            "additionalProperties": False,
        },
    }


FERRAMENTAS = [
    _ferramenta(
        "consultar_servicos",
        "Lista serviços da clínica com preço, duração e regras (dias, profissionais). É a única fonte de preço: "
        "nunca informe um valor que não veio daqui ou de uma proposta. Serviços com agendavel=false "
        "(exames, castração, retorno, táxi dog) você informa e passa para a Joyce.",
        {"categoria": {"type": "string", "enum": ["consulta", "vacina", "exame", "banho_tosa", "outros"],
                       "description": "Filtra por categoria. Sem ela, lista tudo."}},
        [],
    ),
    _ferramenta(
        "consultar_cadastro",
        "Animais, vacinas e agendamentos futuros do tutor que está escrevendo (identificado pelo telefone). "
        "Chame antes de marcar, remarcar ou cancelar. tutor=null significa número sem cadastro.",
        {},
        [],
    ),
    _ferramenta(
        "buscar_horarios",
        "Horários livres que já respeitam todas as regras do serviço e do animal (funcionamento, feriados, "
        "dias do serviço, porte, vacinas). Devolve até 5 opções, uma por turno de cada dia.",
        {
            "servico_id": {"type": "string", "description": "Id vindo de consultar_servicos."},
            **_ANIMAL,
            "data_inicio": _DATA,
            "data_fim": {**_DATA, "description": "Último dia da busca (AAAA-MM-DD). Até 14 dias depois do início."},
            "periodo": {"type": "string", "enum": ["manha", "tarde"]},
            "profissional_id": _PROFISSIONAL_ID,
        },
        ["servico_id", "animal_id", "data_inicio"],
    ),
    _ferramenta(
        "propor_agendamento",
        "Valida um horário e monta o resumo para o tutor aprovar. NÃO marca nada. Mostre ao tutor o resumo "
        "e os avisos devolvidos e espere ele responder. Número sem cadastro exige nome_tutor.",
        {
            "servico_id": {"type": "string"},
            **_ANIMAL,
            "nome_animal": {"type": "string", "description": 'Só quando animal_id = "novo", se o tutor disser o nome.'},
            "inicio": _DATA_HORA,
            "observacao": {"type": "string", "description": "Queixa do tutor, anotada sem comentário (até 300 caracteres)."},
            "nome_tutor": {"type": "string", "description": "Nome do tutor, só para número sem cadastro."},
            "profissional_id": {**_PROFISSIONAL_ID, "description": "O profissional_id da opção escolhida em buscar_horarios."},
        },
        ["servico_id", "animal_id", "inicio"],
    ),
    _ferramenta(
        "propor_remarcacao",
        "Valida a troca de horário de um agendamento do tutor e monta o resumo. NÃO remarca nada.",
        {"agendamento_id": {"type": "string"}, "novo_inicio": _DATA_HORA, "profissional_id": _PROFISSIONAL_ID},
        ["agendamento_id", "novo_inicio"],
    ),
    _ferramenta(
        "propor_cancelamento",
        "Valida o cancelamento de um agendamento do tutor e monta o resumo. NÃO cancela nada.",
        {"agendamento_id": {"type": "string"}},
        ["agendamento_id"],
    ),
    _ferramenta(
        "confirmar_proposta",
        "Executa uma proposta (marca, remarca ou cancela). Use SOMENTE depois que o tutor, numa mensagem "
        "nova, concordou com o resumo. Se ele mudou algo ou não respondeu, faça outra proposta.",
        {"proposta_id": {"type": "string"}},
        ["proposta_id"],
    ),
    _ferramenta(
        "passar_para_joyce",
        "Abre uma pendência para a Joyce (recepção). Use para: sinais de alerta de saúde (urgente=true), "
        "qualquer dúvida de saúde, resultado de exame, serviços não agendáveis, pedidos sobre animal de outra "
        "pessoa, erros que a ferramenta mandou passar adiante, ou quando o tutor pedir para falar com alguém. "
        "Depois, envie ao tutor a mensagem_para_tutor devolvida.",
        {
            "motivo": {"type": "string", "enum": sorted(MOTIVOS_PASSAGEM)},
            "urgente": {"type": "boolean"},
            "resumo": {"type": "string", "description": "O pedido em uma ou duas frases, para a Joyce (até 500 caracteres)."},
        },
        ["motivo", "urgente", "resumo"],
    ),
]

# Respostas fixas: o agente não promete prazo que ninguém combinou (C8).
MENSAGEM_PASSAGEM = {
    "urgencia": "Já avisei a equipe agora mesmo. A Joyce vai te responder em seguida.",
    "padrao": "Passei para a Joyce, da recepção. Ela te responde por aqui.",
    "fora_do_horario": "Passei para a Joyce, da recepção. Ela te responde por aqui a partir do próximo horário de atendimento.",
}


class Executor:
    def __init__(self, agenda: ServicoAgenda) -> None:
        self._agenda = agenda

    def executar(self, nome: str, entrada: dict, ctx: Contexto) -> tuple[str, bool]:
        """Devolve (conteúdo JSON do tool_result, is_error)."""
        metodo = getattr(self, f"_{nome}", None) if nome in {f["name"] for f in FERRAMENTAS} else None
        entrada = _sem_vazios(entrada)
        try:
            if metodo is None:
                raise ErroRegra(Codigo.ARGUMENTO_INVALIDO, f"Ferramenta desconhecida: {nome}.")
            return _json({"ok": True, "dados": metodo(entrada, ctx)}), False
        except ErroRegra as e:
            erro = {"codigo": e.codigo.value, "mensagem": e.mensagem, "proximo_passo": e.proximo_passo}
            erro.update(self._extras(e.dados))
            return _json({"ok": False, "erro": erro}), True
        except (KeyError, ValueError, TypeError) as e:
            # Sem schema strict (alguns provedores), o modelo pode omitir um argumento ou mandar valor fora do enum.
            log.warning("Argumentos inválidos para %s: %s", nome, type(e).__name__, exc_info=True)
            erro = {"codigo": Codigo.ARGUMENTO_INVALIDO.value, "mensagem": f"Argumento ausente ou inválido: {e}.",
                    "proximo_passo": "Conferir o schema da ferramenta e chamar de novo com todos os campos obrigatórios."}
            return _json({"ok": False, "erro": erro}), True
        except Exception:
            # O traceback vai para o log do servidor; o modelo recebe só o código.
            log.exception("Falha inesperada na ferramenta %s", nome)
            erro = {"codigo": Codigo.ERRO_INTERNO.value, "mensagem": "Falha inesperada no sistema.",
                    "proximo_passo": "Chamar passar_para_joyce com motivo erro."}
            return _json({"ok": False, "erro": erro}), True

    # Ferramentas -------------------------------------------------------------

    def _consultar_servicos(self, e: dict, ctx: Contexto) -> list[dict]:
        return [self._servico(s) for s in self._agenda.servicos(e.get("categoria"))]

    def _consultar_cadastro(self, e: dict, ctx: Contexto) -> dict:
        cadastro = self._agenda.cadastro(ctx)
        if cadastro is None:
            return {"tutor": None}
        nomes = {f.animal.id: f.animal.nome for f in cadastro.animais}
        return {
            "tutor": {"nome": cadastro.tutor.nome, "bloqueado_por_faltas": cadastro.bloqueado_por_faltas,
                      "cadastro_provisorio": cadastro.tutor.provisorio},
            "animais": [
                {
                    "animal_id": f.animal.id,
                    "nome": f.animal.nome,
                    "especie": f.animal.especie.value,
                    "peso_kg": f.animal.peso_kg,
                    "porte": f.porte.value if f.porte else None,
                    "ja_passou_em_consulta_aqui": f.animal.tem_historico,
                    "vacinas": [{"nome": v.nome, "valida_ate": f"{v.valida_ate:%d/%m/%Y}"} for v in f.vacinas],
                }
                for f in cadastro.animais
            ],
            "agendamentos": [self._agendamento(a, nomes.get(a.animal_id, "")) for a in cadastro.agendamentos],
        }

    def _buscar_horarios(self, e: dict, ctx: Contexto) -> dict:
        servico_id = e["servico_id"]
        opcoes = self._agenda.buscar_horarios(
            ctx,
            servico_id,
            _data(e["data_inicio"], "data_inicio"),
            _data(e["data_fim"], "data_fim") if e.get("data_fim") else None,
            **_animal(e),
            periodo=e.get("periodo"),
            profissional_id=e.get("profissional_id"),
        )
        resposta: dict[str, Any] = {"opcoes": [self._opcao(o) for o in opcoes]}
        if not opcoes:
            servico = self._agenda.obter_servico(servico_id)
            resposta["motivo"] = (
                f"{servico.nome} só é feito: {_janelas(servico)}." if servico and servico.janelas
                else "Sem horários livres nesse período. Tente outras datas."
            )
        return resposta

    def _propor_agendamento(self, e: dict, ctx: Contexto) -> dict:
        proposta = self._agenda.propor_agendamento(
            ctx,
            e["servico_id"],
            _data_hora(e["inicio"], "inicio"),
            **_animal(e),
            profissional_id=e.get("profissional_id"),
            observacao=e.get("observacao"),
            nome_tutor=e.get("nome_tutor"),
        )
        return self._proposta(proposta)

    def _propor_remarcacao(self, e: dict, ctx: Contexto) -> dict:
        proposta = self._agenda.propor_remarcacao(
            ctx, e["agendamento_id"], _data_hora(e["novo_inicio"], "novo_inicio"), e.get("profissional_id")
        )
        return self._proposta(proposta)

    def _propor_cancelamento(self, e: dict, ctx: Contexto) -> dict:
        return self._proposta(self._agenda.propor_cancelamento(ctx, e["agendamento_id"]))

    def _confirmar_proposta(self, e: dict, ctx: Contexto) -> dict:
        agendamento = self._agenda.confirmar(ctx, e["proposta_id"])
        situacao = {
            StatusAgendamento.CONFIRMADO: "Confirmado na agenda.",
            StatusAgendamento.PENDENTE_JOYCE: "Pré-agendamento: o horário está reservado e a Joyce confirma o cadastro.",
            StatusAgendamento.CANCELADO: "Cancelado.",
        }[agendamento.status]
        return {"situacao": situacao, "agendamento": self._agendamento(agendamento, "")}

    def _passar_para_joyce(self, e: dict, ctx: Contexto) -> dict:
        passagem = self._agenda.passar_para_joyce(ctx, e["motivo"], bool(e["urgente"]), e["resumo"])
        if passagem.urgente:
            chave = "urgencia"
        else:
            chave = "padrao" if self._agenda.clinica_aberta(ctx.agora) else "fora_do_horario"
        return {"protocolo": passagem.protocolo, "mensagem_para_tutor": MENSAGEM_PASSAGEM[chave]}

    # Formatação --------------------------------------------------------------

    def _servico(self, s: Servico) -> dict:
        item: dict[str, Any] = {
            "servico_id": s.id,
            "nome": s.nome,
            "categoria": s.categoria,
            "agendavel": s.agendavel,
            "especie": s.especie.value if s.especie else "cao e gato",
        }
        if s.precos_por_porte:
            item["preco_por_porte"] = {p.porte.value: reais(p.preco_centavos) for p in s.precos_por_porte}
            item["duracao_por_porte_min"] = {p.porte.value: p.duracao_min for p in s.precos_por_porte}
            item["porte_pelo_peso"] = "P até 10 kg, M até 20 kg, G até 35 kg, GG acima de 35 kg"
        elif s.preco_centavos is not None:
            item["preco"] = reais(s.preco_centavos) if s.preco_centavos else "sem custo"
            item["duracao_min"] = s.duracao_min
        else:
            item["preco"] = "sob orçamento, depois de avaliação"
        if s.janelas:
            item["dias_e_horarios"] = _janelas(s)
        if s.profissionais and s.categoria in ("consulta", "vacina"):
            item["profissionais"] = [self._agenda.nome_profissional(p) for p in s.profissionais]
        return item

    def _opcao(self, o: Opcao) -> dict:
        return {
            "inicio": o.inicio.isoformat(timespec="minutes"),
            "rotulo": rotulo(o.inicio),
            "profissional": self._agenda.nome_profissional(o.profissional_id),
            "profissional_id": o.profissional_id,
            "duracao_min": int((o.fim - o.inicio).total_seconds() // 60),
        }

    def _agendamento(self, a: Agendamento, animal: str) -> dict:
        servico = self._agenda.obter_servico(a.servico_id)
        item = {
            "agendamento_id": a.id,
            "servico": servico.nome if servico else a.servico_id,
            "rotulo": rotulo(a.inicio),
            "profissional": self._agenda.nome_profissional(a.profissional_id),
            "preco": reais(a.preco_centavos),
            "status": a.status.value,
        }
        if animal:
            item["animal"] = animal
        return item

    def _proposta(self, p: Proposta) -> dict:
        d = p.dados
        resumo = {
            "animal": d.get("animal_nome"),
            "servico": d.get("servico_nome"),
            "quando": rotulo(datetime.fromisoformat(d["inicio"])),
            "profissional": d.get("profissional_nome"),
            "preco": reais(d["preco_centavos"]),
        }
        if "inicio_antigo" in d:
            resumo["horario_atual"] = rotulo(datetime.fromisoformat(d["inicio_antigo"]))
        return {
            "proposta_id": p.id,
            "tipo": p.tipo.value,
            "resumo": resumo,
            "avisos": d.get("avisos", []),
            "valida_ate": f"{p.expira_em:%H:%M}",
        }

    def _extras(self, dados: dict) -> dict:
        extras: dict[str, Any] = {}
        if "alternativas" in dados:
            extras["alternativas"] = [self._opcao(o) for o in dados["alternativas"]]
        if "pendentes" in dados:
            extras["vacinas_pendentes"] = dados["pendentes"]
        return extras


def _sem_vazios(entrada: dict) -> dict:
    """Campo opcional com "" ou null é ausência, não valor: modelos às vezes preenchem assim."""
    limpa = {}
    for chave, valor in (entrada or {}).items():
        if isinstance(valor, dict):
            valor = _sem_vazios(valor)
        if valor not in ("", None, {}):
            limpa[chave] = valor
    return limpa


def _json(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False)


def _data(texto: str, campo: str) -> date:
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        raise ErroRegra(Codigo.ARGUMENTO_INVALIDO, f"{campo} deve estar no formato AAAA-MM-DD.") from None


def _data_hora(texto: str, campo: str) -> datetime:
    try:
        valor = datetime.fromisoformat(texto)
    except (TypeError, ValueError):
        raise ErroRegra(Codigo.ARGUMENTO_INVALIDO, f"{campo} deve estar no formato AAAA-MM-DDTHH:MM.") from None
    if valor.tzinfo is not None:
        raise ErroRegra(Codigo.ARGUMENTO_INVALIDO, f"{campo} deve estar no horário de Guarulhos, sem fuso.")
    return valor


def _animal(e: dict) -> dict:
    """animal_id do cadastro, ou "novo" + especie_animal/peso_kg_animal/nome_animal -> argumentos do domínio."""
    animal_id = e.get("animal_id")
    if animal_id is None:
        raise ErroRegra(Codigo.ARGUMENTO_INVALIDO, "Faltou o animal_id.",
                        'Chamar consultar_cadastro e usar o animal_id; para animal sem cadastro, animal_id="novo".')
    if animal_id.strip().lower() != "novo":
        return {"animal_id": animal_id, "animal_novo": None}
    if "especie_animal" not in e:
        raise ErroRegra(Codigo.ARGUMENTO_INVALIDO, 'animal_id="novo" precisa de especie_animal (cao ou gato).',
                        "Perguntar ao tutor se é cão ou gato, e o peso, e chamar de novo.")
    return {"animal_id": None, "animal_novo": AnimalNovo(
        Especie(e["especie_animal"]), e.get("peso_kg_animal"), (e.get("nome_animal") or "").strip()
    )}


def _janelas(s: Servico) -> str:
    return ", ".join(f"{DIAS[j.dia_semana]} das {j.inicio.hour}h às {j.fim.hour}h" for j in s.janelas)
