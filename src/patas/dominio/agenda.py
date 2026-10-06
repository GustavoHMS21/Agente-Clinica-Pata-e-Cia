"""Serviço de agenda: aplica as regras RN01-RN27 usando os repositórios.

As ferramentas do agente (bloco 6) chamam só esta classe. Ela não confia em
argumento do modelo: todo id é checado contra o tutor do Contexto, que vem do
código (telefone do canal), nunca do texto da conversa.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from uuid import uuid4

from patas.dominio import regras
from patas.dominio.erros import Codigo, ErroRegra
from patas.dominio.ids import novo_id
from patas.dominio.modelos import (
    Agendamento,
    Animal,
    Especie,
    Opcao,
    Passagem,
    Porte,
    Proposta,
    Servico,
    StatusAgendamento,
    TipoProposta,
    Tutor,
    Vacina,
)
from patas.repositorio.interface import RepositorioAgenda, RepositorioAtendimento

VALIDADE_PROPOSTA = timedelta(minutes=10)
MAX_OPCOES = 5
MAX_ALTERNATIVAS = 3
JANELA_BUSCA_DIAS = 14
HORIZONTE_DIAS = 60
PESO_MIN, PESO_MAX = 0.1, 120.0
LIMITE_NOME = 40
LIMITE_OBSERVACAO = 300
LIMITE_RESUMO = 500
CONSULTA_DA_PRIMEIRA_VACINA = "consulta_clinica"  # RN09
CATEGORIAS = frozenset({"consulta", "vacina", "exame", "banho_tosa", "outros"})
MOTIVOS_PASSAGEM = frozenset({
    "urgencia", "saude", "resultado_exame", "exame_ou_cirurgia", "retorno", "taxi_dog", "sem_permissao",
    "prazo_curto", "faltas", "cadastro_novo", "fora_do_escopo", "pedido_do_tutor", "erro",
})


@dataclass(frozen=True)
class Contexto:
    """Injetado pelo código a cada mensagem. O modelo nunca vê nem preenche."""

    conversa_id: str
    telefone: str
    tutor_id: str | None
    turno: int
    agora: datetime


@dataclass(frozen=True)
class AnimalNovo:
    especie: Especie
    peso_kg: float | None = None
    nome: str = ""


@dataclass(frozen=True)
class FichaAnimal:
    animal: Animal
    porte: Porte | None
    vacinas: list[Vacina]


@dataclass(frozen=True)
class Cadastro:
    tutor: Tutor
    bloqueado_por_faltas: bool
    animais: list[FichaAnimal]
    agendamentos: list[Agendamento]


@dataclass(frozen=True)
class _Pedido:
    """Serviço + animal já validados: o que, para quem, quanto custa e quanto dura."""

    servico: Servico
    animal: Animal | None
    animal_novo: AnimalNovo | None
    especie: Especie
    preco_centavos: int
    duracao: timedelta
    profissionais: tuple[str, ...]
    pre_agendamento: bool  # RN24
    avisos: list[str] = field(default_factory=list)
    observacao: str | None = None


class ServicoAgenda:
    def __init__(self, agenda: RepositorioAgenda, atendimento: RepositorioAtendimento) -> None:
        self._agenda = agenda
        self._atendimento = atendimento

    # Leitura -----------------------------------------------------------------

    def servicos(self, categoria: str | None = None) -> list[Servico]:
        if categoria is not None and categoria not in CATEGORIAS:
            raise ErroRegra(Codigo.ARGUMENTO_INVALIDO, f"Categoria desconhecida: {categoria}.")
        return self._agenda.listar_servicos(categoria)

    def obter_servico(self, servico_id: str) -> Servico | None:
        return self._agenda.obter_servico(servico_id)

    def nome_profissional(self, profissional_id: str) -> str:
        return self._agenda.nome_profissional(profissional_id) or profissional_id

    def clinica_aberta(self, agora: datetime) -> bool:
        return regras.dentro_do_funcionamento(agora) and not self._agenda.listar_feriados(agora.date(), agora.date())

    def cadastro(self, ctx: Contexto) -> Cadastro | None:
        tutor = self._tutor(ctx)
        if tutor is None:
            return None
        fichas = [
            FichaAnimal(a, regras.porte_pelo_peso(a.peso_kg) if a.peso_kg else None, self._agenda.listar_vacinas(a.id))
            for a in self._agenda.listar_animais(tutor.id)
        ]
        return Cadastro(
            tutor=tutor,
            bloqueado_por_faltas=regras.bloqueado_por_faltas(tutor),
            animais=fichas,
            agendamentos=self._agenda.listar_agendamentos_futuros(tutor.id, ctx.agora),
        )

    def buscar_horarios(
        self,
        ctx: Contexto,
        servico_id: str,
        data_inicio: date,
        data_fim: date | None = None,
        animal_id: str | None = None,
        animal_novo: AnimalNovo | None = None,
        periodo: str | None = None,
        profissional_id: str | None = None,
    ) -> list[Opcao]:
        if periodo not in (None, "manha", "tarde"):
            raise ErroRegra(Codigo.ARGUMENTO_INVALIDO, "periodo deve ser manha ou tarde.")
        self._checar_data(ctx, data_inicio)
        limite = min(data_inicio + timedelta(days=JANELA_BUSCA_DIAS - 1), self._horizonte(ctx))
        data_fim = min(data_fim or limite, limite)

        pedido = self._resolver(ctx, servico_id, animal_id, animal_novo)
        self._checar_vacinas(pedido, data_inicio)
        profissionais = self._filtrar_profissionais(pedido, profissional_id)
        opcoes = self._opcoes(pedido.servico, profissionais, pedido.duracao, data_inicio, data_fim, ctx.agora)
        if periodo:
            opcoes = [o for o in opcoes if regras.turno(o.inicio) == periodo]
        return regras.espalhar(opcoes, MAX_OPCOES)

    # Propostas (não escrevem na agenda, ADR 0002) ----------------------------

    def propor_agendamento(
        self,
        ctx: Contexto,
        servico_id: str,
        inicio: datetime,
        animal_id: str | None = None,
        animal_novo: AnimalNovo | None = None,
        profissional_id: str | None = None,
        observacao: str | None = None,
        nome_tutor: str | None = None,
    ) -> Proposta:
        observacao = self._texto_opcional(observacao, LIMITE_OBSERVACAO, "observacao")
        nome_tutor = self._texto_opcional(nome_tutor, LIMITE_NOME, "nome_tutor")
        if ctx.tutor_id is None and not nome_tutor:
            raise ErroRegra(
                Codigo.ARGUMENTO_INVALIDO,
                "Número sem cadastro: o pré-agendamento precisa do nome do tutor.",
                "Perguntar o nome do tutor e propor de novo com nome_tutor.",
            )
        self._checar_data(ctx, inicio.date())

        pedido = self._resolver(ctx, servico_id, animal_id, animal_novo)
        self._checar_vacinas(pedido, inicio.date())
        candidatos = self._filtrar_profissionais(pedido, profissional_id)
        escolhido = self._primeiro_livre(pedido.servico, candidatos, inicio, pedido.duracao, ctx.agora)
        if escolhido is None:
            self._sem_horario(pedido.servico, candidatos, pedido.duracao, inicio.date(), ctx)

        animal_nome = pedido.animal.nome if pedido.animal else (pedido.animal_novo.nome or "Animal novo")
        nota = "; ".join(n for n in (pedido.observacao, observacao) if n) or None
        dados = {
            "servico_id": pedido.servico.id,
            "servico_nome": pedido.servico.nome,
            "animal_id": pedido.animal.id if pedido.animal else None,
            "animal_nome": animal_nome,
            "animal_novo": (
                {"especie": pedido.animal_novo.especie.value, "peso_kg": pedido.animal_novo.peso_kg,
                 "nome": animal_nome}
                if pedido.animal_novo else None
            ),
            "nome_tutor": nome_tutor,
            "profissional_id": escolhido,
            "profissional_nome": self._agenda.nome_profissional(escolhido),
            "inicio": inicio.isoformat(timespec="minutes"),
            "fim": (inicio + pedido.duracao).isoformat(timespec="minutes"),
            "preco_centavos": pedido.preco_centavos,
            "observacao": nota,
            "avisos": pedido.avisos,
        }
        tipo = TipoProposta.PRE_AGENDAMENTO if pedido.pre_agendamento else TipoProposta.AGENDAMENTO
        return self._nova_proposta(ctx, tipo, dados)

    def propor_remarcacao(
        self, ctx: Contexto, agendamento_id: str, novo_inicio: datetime, profissional_id: str | None = None
    ) -> Proposta:
        agendamento = self._agendamento_alteravel(ctx, agendamento_id)
        self._checar_data(ctx, novo_inicio.date())
        servico = self._agenda.obter_servico(agendamento.servico_id)
        if profissional_id is not None and profissional_id not in servico.profissionais:
            raise self._erro_profissional(servico)
        # Prefere quem já atendia; senão, qualquer um que faça o serviço.
        candidatos = [profissional_id] if profissional_id else [
            agendamento.profissional_id,
            *(p for p in servico.profissionais if p != agendamento.profissional_id),
        ]
        duracao = agendamento.fim - agendamento.inicio
        animal = self._agenda.obter_animal(agendamento.animal_id)
        if servico.categoria == "banho_tosa":
            self._checar_vacinas_animal(animal, novo_inicio.date())
        escolhido = self._primeiro_livre(servico, candidatos, novo_inicio, duracao, ctx.agora, agendamento.id)
        if escolhido is None:
            self._sem_horario(servico, candidatos, duracao, novo_inicio.date(), ctx, agendamento.id)

        dados = {
            "agendamento_id": agendamento.id,
            "servico_nome": servico.nome,
            "animal_nome": animal.nome,
            "inicio_antigo": agendamento.inicio.isoformat(timespec="minutes"),
            "profissional_id": escolhido,
            "profissional_nome": self._agenda.nome_profissional(escolhido),
            "inicio": novo_inicio.isoformat(timespec="minutes"),
            "fim": (novo_inicio + duracao).isoformat(timespec="minutes"),
            "preco_centavos": agendamento.preco_centavos,
        }
        return self._nova_proposta(ctx, TipoProposta.REMARCACAO, dados)

    def propor_cancelamento(self, ctx: Contexto, agendamento_id: str) -> Proposta:
        agendamento = self._agendamento_alteravel(ctx, agendamento_id)
        dados = {
            "agendamento_id": agendamento.id,
            "servico_nome": self._agenda.obter_servico(agendamento.servico_id).nome,
            "animal_nome": self._agenda.obter_animal(agendamento.animal_id).nome,
            "profissional_nome": self._agenda.nome_profissional(agendamento.profissional_id),
            "inicio": agendamento.inicio.isoformat(timespec="minutes"),
            "preco_centavos": agendamento.preco_centavos,
        }
        return self._nova_proposta(ctx, TipoProposta.CANCELAMENTO, dados)

    # Confirmação: a única escrita na agenda ----------------------------------

    def confirmar(self, ctx: Contexto, proposta_id: str) -> Agendamento:
        proposta = self._atendimento.obter_proposta(proposta_id)
        if proposta is None or proposta.conversa_id != ctx.conversa_id:
            raise ErroRegra(Codigo.PROPOSTA_INVALIDA, "Proposta não encontrada nesta conversa.")
        if proposta.usada_em is not None:
            # Idempotência: confirmar de novo devolve o mesmo resultado, sem repetir a ação.
            return self._agenda.obter_agendamento(proposta.agendamento_id)
        if ctx.agora > proposta.expira_em:
            raise ErroRegra(Codigo.PROPOSTA_INVALIDA, "A proposta expirou (10 minutos).")
        if proposta.turno >= ctx.turno:
            raise ErroRegra(Codigo.CONFIRMACAO_PREMATURA, "O tutor ainda não respondeu ao resumo.")

        if proposta.tipo in (TipoProposta.AGENDAMENTO, TipoProposta.PRE_AGENDAMENTO):
            resultado = self._executar_agendamento(ctx, proposta)
        elif proposta.tipo == TipoProposta.REMARCACAO:
            resultado = self._executar_remarcacao(ctx, proposta)
        else:
            resultado = self._executar_cancelamento(ctx, proposta)
        self._atendimento.marcar_proposta_usada(proposta.id, resultado.id, ctx.agora)
        return resultado

    def passar_para_joyce(self, ctx: Contexto, motivo: str, urgente: bool, resumo: str) -> Passagem:
        if motivo not in MOTIVOS_PASSAGEM:
            raise ErroRegra(Codigo.ARGUMENTO_INVALIDO, f"Motivo desconhecido: {motivo}.")
        resumo = (resumo or "").strip()
        if not resumo or len(resumo) > LIMITE_RESUMO:
            raise ErroRegra(Codigo.ARGUMENTO_INVALIDO, f"resumo é obrigatório e tem até {LIMITE_RESUMO} caracteres.")
        passagem = Passagem(
            protocolo=f"PJ-{uuid4().hex[:6].upper()}",
            conversa_id=ctx.conversa_id,
            tutor_id=ctx.tutor_id,
            motivo=motivo,
            urgente=urgente,
            resumo=resumo,
            criada_em=ctx.agora,
        )
        self._atendimento.registrar_passagem(passagem)
        return passagem

    # Execução das propostas --------------------------------------------------

    def _executar_agendamento(self, ctx: Contexto, proposta: Proposta) -> Agendamento:
        d = proposta.dados
        inicio, fim = datetime.fromisoformat(d["inicio"]), datetime.fromisoformat(d["fim"])
        novo = AnimalNovo(Especie(d["animal_novo"]["especie"]), d["animal_novo"]["peso_kg"], d["animal_novo"]["nome"]) \
            if d["animal_novo"] else None

        # Revalida tudo: entre a proposta e a confirmação, a agenda e o cadastro podem ter mudado.
        pedido = self._resolver(ctx, d["servico_id"], d["animal_id"], novo)
        self._checar_vacinas(pedido, inicio.date())
        if self._primeiro_livre(pedido.servico, [d["profissional_id"]], inicio, fim - inicio, ctx.agora) is None:
            self._sem_horario(pedido.servico, pedido.profissionais, fim - inicio, inicio.date(), ctx)

        animal_id = d["animal_id"]
        if animal_id is None:
            tutor = self._tutor(ctx) or self._agenda.buscar_tutor_por_telefone(ctx.telefone) \
                or self._agenda.criar_tutor_provisorio(d["nome_tutor"], ctx.telefone)
            animal_id = self._agenda.criar_animal(tutor.id, novo.nome, novo.especie, novo.peso_kg, provisorio=True).id

        status = StatusAgendamento.PENDENTE_JOYCE if proposta.tipo == TipoProposta.PRE_AGENDAMENTO \
            else StatusAgendamento.CONFIRMADO
        salvo = self._agenda.inserir_agendamento_se_livre(Agendamento(
            id=novo_id("ag"),
            animal_id=animal_id,
            servico_id=d["servico_id"],
            profissional_id=d["profissional_id"],
            inicio=inicio,
            fim=fim,
            status=status,
            preco_centavos=d["preco_centavos"],  # o preço prometido no resumo, não um recálculo
            criado_em=ctx.agora,
            proposta_id=proposta.id,
            observacao=d["observacao"],
        ))
        if salvo is None:
            self._sem_horario(pedido.servico, pedido.profissionais, fim - inicio, inicio.date(), ctx)

        if status == StatusAgendamento.PENDENTE_JOYCE:
            self.passar_para_joyce(
                ctx, "cadastro_novo", False,
                f"Pré-agendamento de {d['servico_nome']} para {d['animal_nome']} em {d['inicio']}. "
                "Confirmar cadastro do tutor e carteirinha de vacinação.",
            )
        return salvo

    def _executar_remarcacao(self, ctx: Contexto, proposta: Proposta) -> Agendamento:
        d = proposta.dados
        agendamento = self._agendamento_alteravel(ctx, d["agendamento_id"])
        servico = self._agenda.obter_servico(agendamento.servico_id)
        inicio, fim = datetime.fromisoformat(d["inicio"]), datetime.fromisoformat(d["fim"])
        livre = self._primeiro_livre(servico, [d["profissional_id"]], inicio, fim - inicio, ctx.agora, agendamento.id)
        if livre is None or not self._agenda.mover_agendamento_se_livre(agendamento.id, livre, inicio, fim):
            self._sem_horario(servico, servico.profissionais, fim - inicio, inicio.date(), ctx, agendamento.id)
        return self._agenda.obter_agendamento(agendamento.id)

    def _executar_cancelamento(self, ctx: Contexto, proposta: Proposta) -> Agendamento:
        agendamento = self._agendamento_alteravel(ctx, proposta.dados["agendamento_id"])
        self._agenda.cancelar_agendamento(agendamento.id)
        return self._agenda.obter_agendamento(agendamento.id)

    # Validações --------------------------------------------------------------

    def _tutor(self, ctx: Contexto) -> Tutor | None:
        return self._agenda.obter_tutor(ctx.tutor_id) if ctx.tutor_id else None

    def _resolver(
        self, ctx: Contexto, servico_id: str, animal_id: str | None, animal_novo: AnimalNovo | None
    ) -> _Pedido:
        tutor = self._tutor(ctx)
        if tutor and regras.bloqueado_por_faltas(tutor):
            raise ErroRegra(Codigo.BLOQUEADO_POR_FALTAS, "Tutor com duas faltas sem aviso.")

        servico = self._agenda.obter_servico(servico_id)
        if servico is None:
            raise ErroRegra(Codigo.ARGUMENTO_INVALIDO, f"Serviço desconhecido: {servico_id}.",
                            "Chamar consultar_servicos para ver os ids.")
        if not servico.agendavel:
            raise ErroRegra(Codigo.NAO_AGENDAVEL, f"{servico.nome} não é agendado pelo atendimento automático.")

        if (animal_id is None) == (animal_novo is None):
            raise ErroRegra(Codigo.ARGUMENTO_INVALIDO, "Informe exatamente um animal: do cadastro ou novo.")
        if animal_id is not None:
            animal = self._animal_do_tutor(ctx, animal_id)
            especie, peso, tem_historico = animal.especie, animal.peso_kg, animal.tem_historico
            pre = tutor.provisorio or animal.provisorio
        else:
            animal = None
            if animal_novo.peso_kg is not None and not PESO_MIN <= animal_novo.peso_kg <= PESO_MAX:
                raise ErroRegra(Codigo.ARGUMENTO_INVALIDO, f"Peso fora da faixa ({PESO_MIN} a {PESO_MAX} kg).")
            self._texto_opcional(animal_novo.nome, LIMITE_NOME, "animal_novo.nome")
            especie, peso, tem_historico, pre = animal_novo.especie, animal_novo.peso_kg, False, True

        if servico.especie is not None and servico.especie != especie:
            raise ErroRegra(Codigo.REGRA_DO_SERVICO, f"{servico.nome} é só para {servico.especie.value}.")

        if servico.precos_por_porte:
            if peso is None:
                raise ErroRegra(Codigo.PRECISA_PESO, "O preço e a duração do banho dependem do porte.")
            porte = regras.porte_pelo_peso(peso)
            faixa = next(p for p in servico.precos_por_porte if p.porte == porte)
            preco, duracao = faixa.preco_centavos, faixa.duracao_min
        else:
            preco, duracao = servico.preco_centavos, servico.duracao_min

        profissionais, avisos, observacao = servico.profissionais, [], None
        if servico.categoria == "vacina":
            avisos.append("Trazer a carteirinha de vacinação.")
            if not tem_historico:  # RN09: primeira vez aqui, consulta + vacina no mesmo horário
                consulta = self._agenda.obter_servico(CONSULTA_DA_PRIMEIRA_VACINA)
                preco += consulta.preco_centavos
                duracao = consulta.duracao_min
                profissionais = tuple(p for p in servico.profissionais if p in consulta.profissionais)
                observacao = "Primeira vez na clínica: consulta + vacina"
                avisos.append("Como é a primeira vacina aqui, a veterinária avalia antes e aplica no mesmo horário.")
        if servico.categoria == "banho_tosa":
            avisos.append("Atraso de mais de 20 minutos perde o horário.")
            if pre:
                avisos.append("Trazer a carteirinha: sem vacinas em dia o banho não é feito.")

        return _Pedido(servico, animal, animal_novo, especie, preco, timedelta(minutes=duracao),
                       profissionais, pre or tutor is None, avisos, observacao)

    def _animal_do_tutor(self, ctx: Contexto, animal_id: str) -> Animal:
        animal = self._agenda.obter_animal(animal_id)
        # "Não existe" e "não é seu" dão o mesmo erro: quem testa ids não descobre nada.
        if animal is None or ctx.tutor_id is None or animal.tutor_id != ctx.tutor_id:
            raise ErroRegra(Codigo.NAO_ENCONTRADO, "Animal não encontrado no cadastro deste tutor.")
        return animal

    def _agendamento_alteravel(self, ctx: Contexto, agendamento_id: str) -> Agendamento:
        if ctx.tutor_id is None:
            raise ErroRegra(Codigo.SEM_PERMISSAO, "Número sem cadastro não remarca nem cancela (RN23).")
        agendamento = self._agenda.obter_agendamento(agendamento_id)
        animal = self._agenda.obter_animal(agendamento.animal_id) if agendamento else None
        if (agendamento is None or agendamento.status == StatusAgendamento.CANCELADO
                or animal is None or animal.tutor_id != ctx.tutor_id):
            raise ErroRegra(Codigo.NAO_ENCONTRADO, "Agendamento não encontrado no cadastro deste tutor.")
        if not regras.pode_alterar(agendamento.inicio, ctx.agora):
            raise ErroRegra(Codigo.PRAZO_CURTO, "Faltam menos de 2 horas para o horário.")
        return agendamento

    def _checar_vacinas(self, pedido: _Pedido, na_data: date) -> None:
        # Animal novo não tem carteira no sistema: vira pré-agendamento e a Joyce confere no balcão.
        if pedido.servico.categoria == "banho_tosa" and pedido.animal is not None:
            self._checar_vacinas_animal(pedido.animal, na_data)

    def _checar_vacinas_animal(self, animal: Animal, na_data: date) -> None:
        pendentes = regras.vacinas_pendentes(animal.especie, self._agenda.listar_vacinas(animal.id), na_data)
        if pendentes:
            raise ErroRegra(Codigo.VACINA_PENDENTE, f"{animal.nome} está com vacina pendente: {', '.join(pendentes)}.",
                            pendentes=pendentes)

    def _filtrar_profissionais(self, pedido: _Pedido, profissional_id: str | None) -> list[str]:
        if profissional_id is None:
            return list(pedido.profissionais)
        if profissional_id not in pedido.profissionais:
            raise self._erro_profissional(pedido.servico)
        return [profissional_id]

    def _erro_profissional(self, servico: Servico) -> ErroRegra:
        nomes = ", ".join(self._agenda.nome_profissional(p) for p in servico.profissionais)
        return ErroRegra(Codigo.REGRA_DO_SERVICO, f"{servico.nome} é feito por: {nomes}.")

    def _checar_data(self, ctx: Contexto, dia: date) -> None:
        if not ctx.agora.date() <= dia <= self._horizonte(ctx):
            raise ErroRegra(Codigo.ARGUMENTO_INVALIDO, f"A data precisa estar entre hoje e {HORIZONTE_DIAS} dias à frente.")

    def _horizonte(self, ctx: Contexto) -> date:
        return ctx.agora.date() + timedelta(days=HORIZONTE_DIAS)

    @staticmethod
    def _texto_opcional(texto: str | None, limite: int, campo: str) -> str | None:
        texto = (texto or "").strip()
        if len(texto) > limite:
            raise ErroRegra(Codigo.ARGUMENTO_INVALIDO, f"{campo} tem até {limite} caracteres.")
        return texto or None

    # Disponibilidade ---------------------------------------------------------

    def _opcoes(
        self,
        servico: Servico,
        profissionais: list[str],
        duracao: timedelta,
        de: date,
        ate: date,
        agora: datetime,
        ignorar_id: str | None = None,
    ) -> list[Opcao]:
        feriados = self._agenda.listar_feriados(de, ate)
        ocupacoes = self._agenda.listar_ocupacoes(
            profissionais, datetime.combine(de, time.min), datetime.combine(ate + timedelta(days=1), time.min)
        )
        por_profissional = {
            p: [(o.inicio, o.fim) for o in ocupacoes if o.profissional_id == p and o.id != ignorar_id]
            for p in profissionais
        }
        expedientes = {p: self._agenda.listar_expediente(p) for p in profissionais}

        opcoes: dict[datetime, Opcao] = {}
        dia = de
        while dia <= ate:
            if dia not in feriados:
                for p in profissionais:  # em ordem: o primeiro profissional livre fica com o horário
                    faixas = regras.faixas_do_dia(dia, expedientes[p], servico.janelas)
                    for inicio in regras.inicios_livres(faixas, duracao, por_profissional[p],
                                                        agora + regras.ANTECEDENCIA_MARCAR):
                        opcoes.setdefault(inicio, Opcao(inicio, inicio + duracao, p))
            dia += timedelta(days=1)
        return sorted(opcoes.values(), key=lambda o: o.inicio)

    def _primeiro_livre(
        self,
        servico: Servico,
        profissionais: list[str],
        inicio: datetime,
        duracao: timedelta,
        agora: datetime,
        ignorar_id: str | None = None,
    ) -> str | None:
        fim = inicio + duracao
        if inicio < agora + regras.ANTECEDENCIA_MARCAR or self._agenda.listar_feriados(inicio.date(), inicio.date()):
            return None
        for p in profissionais:
            faixas = regras.faixas_do_dia(inicio.date(), self._agenda.listar_expediente(p), servico.janelas)
            ocupacoes = [(o.inicio, o.fim) for o in self._agenda.listar_ocupacoes([p], inicio, fim) if o.id != ignorar_id]
            if regras.cabe(inicio, fim, faixas, ocupacoes):
                return p
        return None

    def _sem_horario(
        self,
        servico: Servico,
        profissionais: list[str] | tuple[str, ...],
        duracao: timedelta,
        dia: date,
        ctx: Contexto,
        ignorar_id: str | None = None,
    ) -> None:
        ate = min(dia + timedelta(days=6), self._horizonte(ctx))
        alternativas = regras.espalhar(
            self._opcoes(servico, list(profissionais), duracao, dia, ate, ctx.agora, ignorar_id), MAX_ALTERNATIVAS
        )
        raise ErroRegra(Codigo.HORARIO_INDISPONIVEL, "Esse horário não está disponível.", alternativas=alternativas)

    def _nova_proposta(self, ctx: Contexto, tipo: TipoProposta, dados: dict) -> Proposta:
        proposta = Proposta(
            id=novo_id("pr"),
            conversa_id=ctx.conversa_id,
            tipo=tipo,
            dados=dados,
            turno=ctx.turno,
            criada_em=ctx.agora,
            expira_em=ctx.agora + VALIDADE_PROPOSTA,
        )
        self._atendimento.salvar_proposta(proposta)
        return proposta
