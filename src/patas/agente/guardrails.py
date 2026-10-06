"""Guardrails em código, antes e depois do LLM (bloco 7, docs/seguranca.md).

O prompt pede; estas funções garantem. São listas simples e determinísticas: falso
positivo é barato (a Joyce olha e libera), falso negativo é o caso da C3.

As listas de sinais de alerta e de termos de medicamento são provisórias: quem define
o que é alerta é a Beatriz (pergunta P5 em docs/regras-de-negocio.md).
"""

import re
import unicodedata

# Sinais de alerta (RN19, RN20). Casam com o texto sem acento e em minúsculas.
SINAIS_DE_ALERTA = [
    r"vomit",  # vomitando, vômito
    r"diarreia",
    r"(nao|parou de) (quer )?(come|beb)",  # não come, não quer comer, parou de beber
    r"sangu|sangra",  # sangue, sangrando, sangramento
    r"convuls|desmai|inconscien",
    r"falta de ar|nao consegue respirar|respirando (mal|com dificuldade)|engasg",
    r"atropel|fratur",
    r"envenen|veneno|raticida|chumbinho",
    # Ingestão de algo tóxico, com até 40 caracteres entre o verbo e a coisa (C3: "comeu um pedaço grande de chocolate").
    r"\b(comeu|engoliu|ingeriu|lambeu|mastigou|bebeu)\b.{0,40}\b(chocolate|uvas?|passas?|cebola|alho|remedio|"
    r"comprimido|xilitol|chiclete|osso|pilha|produto de limpeza|agua sanitaria)",
    r"engoliu",
    r"nao (consegue )?(levanta|anda|mexe)",
]
_ALERTA = re.compile("|".join(f"(?:{p})" for p in SINAIS_DE_ALERTA))

# Resposta com cara de orientação de saúde: remédio, dose, tratamento caseiro (RN21).
TERMOS_DE_SAUDE = [
    r"\b\d+([.,]\d+)?\s*(mg|ml|gotas?|comprimidos?|capsulas?)\b",
    r"\b(dipirona|paracetamol|ibuprofeno|omeprazol|dramin|plasil|buscopan|simeticona|luftal)\b",
    r"\b(antibiotico|amoxicilina|metronidazol|anti-?inflamatorio|corticoide|antialergico)\b",
    r"\b(soro caseiro|carvao ativado|agua oxigenada|chazinho|cha de)\b",
    r"\b(de|der|ofereca|dar)\s+(a ele|a ela|pra ele|pra ela)?\s*(um|uma|meio|meia)\s+(comprimido|colher|dose)",
]
_SAUDE = re.compile("|".join(f"(?:{p})" for p in TERMOS_DE_SAUDE))

# Ids internos (pr_..., ag_..., a_thor, t_mariana, cv_..., tu_...) e nomes de ferramentas.
_ID_INTERNO = re.compile(r"\b(?:pr|ag|cv|tu|call|t|a)_[a-z0-9]+\b", re.IGNORECASE)
_FERRAMENTA = re.compile(
    r"\b(consultar_servicos|consultar_cadastro|buscar_horarios|propor_agendamento|propor_remarcacao|"
    r"propor_cancelamento|confirmar_proposta|passar_para_joyce)\b"
)

LIMITE_RESPOSTA = 1500  # WhatsApp aceita mais, mas recepção não manda textão

HOSPITAL_24H = "Hospital Veterinário Vida Animal, que funciona 24h"  # endereço e telefone: pergunta P6

RESPOSTA_URGENCIA_FECHADO = (
    "Pelo que você contou, ele precisa ser visto por um veterinário agora. A Patas & Cia está fechada "
    f"neste momento e não atende emergência fora do horário: procure já o {HOSPITAL_24H}. "
    "Avisei a nossa equipe, e a Joyce fala com você assim que a clínica abrir."
)

RESPOSTA_SAUDE = (
    "Sobre a saúde do seu pet, quem pode orientar é a veterinária, então não consigo indicar nada por aqui. "
    "Já passei para a Joyce te ajudar a marcar uma avaliação. Se for urgente, traga o animal à clínica ou, "
    f"fora do horário, procure o {HOSPITAL_24H}."
)


def normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sem_acento.lower())


def detectar_alerta(texto_do_tutor: str) -> bool:
    return bool(_ALERTA.search(normalizar(texto_do_tutor)))


def parece_orientacao_de_saude(resposta: str) -> bool:
    return bool(_SAUDE.search(normalizar(resposta)))


def limpar_resposta(resposta: str) -> tuple[str, list[str]]:
    """Remove ids internos e nomes de ferramentas, limita o tamanho. Devolve (texto, problemas)."""
    problemas = []
    if _ID_INTERNO.search(resposta):
        problemas.append("id_interno")
        resposta = _ID_INTERNO.sub("", resposta)
    if _FERRAMENTA.search(resposta):
        problemas.append("nome_de_ferramenta")
        resposta = _FERRAMENTA.sub("", resposta)
    if len(resposta) > LIMITE_RESPOSTA:
        problemas.append("resposta_longa")
        resposta = resposta[:LIMITE_RESPOSTA].rsplit(" ", 1)[0] + "..."
    resposta = re.sub(r"[ \t]{2,}", " ", resposta).strip()
    return resposta, problemas
