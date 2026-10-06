"""Catálogo de erros (docs/contratos-das-ferramentas.md).

No domínio, recusa é exceção. A ferramenta (bloco 6) captura ErroRegra e devolve
ao modelo como dado: {"ok": false, "erro": {codigo, mensagem, proximo_passo}}.
"""

from enum import StrEnum


class Codigo(StrEnum):
    ARGUMENTO_INVALIDO = "ARGUMENTO_INVALIDO"
    NAO_ENCONTRADO = "NAO_ENCONTRADO"
    PRECISA_PESO = "PRECISA_PESO"
    REGRA_DO_SERVICO = "REGRA_DO_SERVICO"
    HORARIO_INDISPONIVEL = "HORARIO_INDISPONIVEL"
    VACINA_PENDENTE = "VACINA_PENDENTE"
    PRAZO_CURTO = "PRAZO_CURTO"
    SEM_PERMISSAO = "SEM_PERMISSAO"
    BLOQUEADO_POR_FALTAS = "BLOQUEADO_POR_FALTAS"
    NAO_AGENDAVEL = "NAO_AGENDAVEL"
    PROPOSTA_INVALIDA = "PROPOSTA_INVALIDA"
    CONFIRMACAO_PREMATURA = "CONFIRMACAO_PREMATURA"
    ERRO_INTERNO = "ERRO_INTERNO"


PROXIMO_PASSO = {
    Codigo.ARGUMENTO_INVALIDO: "Corrigir os argumentos e chamar de novo, ou perguntar ao tutor o que falta.",
    Codigo.NAO_ENCONTRADO: "Chamar consultar_cadastro para ver os animais e agendamentos deste tutor.",
    Codigo.PRECISA_PESO: "Perguntar o peso do animal em kg. Se o tutor não souber, estimar o porte pela raça e "
                         "chamar de novo com porte_estimado (a tosadora confirma na chegada).",
    Codigo.REGRA_DO_SERVICO: "Explicar a regra ao tutor e buscar uma alternativa.",
    Codigo.HORARIO_INDISPONIVEL: "Oferecer as alternativas que vieram junto.",
    Codigo.VACINA_PENDENTE: "Oferecer agendar a vacina antes do banho. Se o tutor disser que vacinou em outra "
                            "clínica, pedir a foto da carteirinha e chamar passar_para_joyce com motivo carteirinha.",
    Codigo.PRAZO_CURTO: "O horário já começou ou passou: chamar passar_para_joyce com motivo prazo_curto.",
    Codigo.SEM_PERMISSAO: "Chamar passar_para_joyce com motivo sem_permissao.",
    Codigo.BLOQUEADO_POR_FALTAS: "Chamar passar_para_joyce com motivo faltas.",
    Codigo.NAO_AGENDAVEL: "Informar o preço e chamar passar_para_joyce.",
    Codigo.PROPOSTA_INVALIDA: "Fazer uma nova proposta.",
    Codigo.CONFIRMACAO_PREMATURA: "Mostrar o resumo ao tutor e esperar a resposta dele antes de confirmar.",
    Codigo.ERRO_INTERNO: "Chamar passar_para_joyce com motivo erro.",
}


class ErroRegra(Exception):
    def __init__(self, codigo: Codigo, mensagem: str, proximo_passo: str | None = None, **dados) -> None:
        super().__init__(f"{codigo}: {mensagem}")
        self.codigo = codigo
        self.mensagem = mensagem
        self.proximo_passo = proximo_passo or PROXIMO_PASSO[codigo]
        self.dados = dados  # extras para o modelo, como alternativas ou vacinas pendentes
