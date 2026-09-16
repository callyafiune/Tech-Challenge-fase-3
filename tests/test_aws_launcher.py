"""Confere os limites do envio remoto e a identificação da instância de destino."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

CAMINHO = Path(__file__).resolve().parents[1] / "scripts" / "enviar_implantacao_aws.py"
ESPECIFICACAO = importlib.util.spec_from_file_location("enviar_implantacao_aws", CAMINHO)
modulo = importlib.util.module_from_spec(ESPECIFICACAO)
ESPECIFICACAO.loader.exec_module(modulo)


def test_envio_nao_incorpora_perfil_ou_credenciais_no_comando_remoto():
    parametros = modulo.parametros_ssm(b"print('implantacao')\n", ["--revisao", "a" * 40])
    texto = json.dumps(parametros)
    assert "AWS_SECRET_ACCESS_KEY" not in texto
    assert "--profile" not in texto
    assert parametros["executionTimeout"] == ["2400"]
    assert "python3" in parametros["commands"][-1]


def test_envio_rejeita_payload_grande_antes_de_contatar_aws():
    with pytest.raises(ValueError, match="tamanho"):
        modulo.parametros_ssm(b"x" * 65536, [])


@pytest.mark.parametrize("estado,ip", [("stopped", "54.246.245.167"), ("running", "203.0.113.5")])
def test_nao_envia_para_instancia_parada_ou_endereco_diferente(estado, ip):
    instancia = {"State": {"Name": estado}, "PublicIpAddress": ip}
    with pytest.raises(ValueError):
        modulo.validar_destino(instancia, "http://54.246.245.167:8000")


@pytest.mark.parametrize("url", ["http://54.246.245.167", "https://54.246.245.167:8000"])
def test_nao_implanta_quando_url_publica_nao_corresponde_a_porta_publicada(url):
    instancia = {"State": {"Name": "running"}, "PublicIpAddress": "54.246.245.167"}
    with pytest.raises(ValueError, match="porta 8000"):
        modulo.validar_destino(instancia, url)


def test_resultado_publico_precisa_corresponder_ao_modelo_implantado():
    with pytest.raises(ValueError, match="versão"):
        modulo.validar_respostas(
            {"backend": "onnx", "versao_modelo": "modelo-antigo"},
            {"backend": "onnx", "versao_modelo": "modelo-antigo", "classe_id": 4},
            "modelo-novo",
        )


def test_resultado_publico_aceita_mesma_versao_e_classe_medica():
    modulo.validar_respostas(
        {"backend": "onnx", "versao_modelo": "modelo-novo"},
        {"backend": "onnx", "versao_modelo": "modelo-novo", "classe_id": 4},
        "modelo-novo",
    )


COMANDO_ID = "f1fcd3d7-78bc-408d-bf52-642b67395a69"
INICIO_REMOTO = "2026-09-16T01:18:37.538Z"
RECIBO = "/opt/tech-challenge-fase-3/releases/20260916T011838140279Z-901c8f89fcce/receipt.json"
SENTINELA = "TOKEN_SENTINELA_NAO_PUBLICAR"


@pytest.fixture
def consulta_ssm(monkeypatch, tmp_path):
    """Executa o laço real com relógio e fronteira AWS controlados, sem esperar tempo real."""
    relogio = SimpleNamespace(agora=0.0)

    def dormir(segundos):
        assert 0 < segundos <= 30
        relogio.agora += segundos

    monkeypatch.setattr(modulo.time, "monotonic", lambda: relogio.agora)
    monkeypatch.setattr(modulo.time, "sleep", dormir)
    argumentos = SimpleNamespace(
        instancia="i-024a7c79b3ec2bfa1", saida=tmp_path / "ultima_implantacao.json"
    )
    return relogio, argumentos


def eventos_ssm(capsys):
    saida = capsys.readouterr()
    assert not saida.out, "O progresso deve preservar stdout para o resultado final."
    return [json.loads(linha) for linha in saida.err.splitlines()]


def test_polling_informa_mudancas_inicio_real_e_intervalo_sem_spam(
    consulta_ssm, monkeypatch, capsys
):
    relogio, argumentos = consulta_ssm

    def consultar_aws(*args, **kwargs):
        if relogio.agora < 125:
            return {"Status": "Pending"}
        resultado = {"Status": "InProgress" if relogio.agora < 260 else "Success"}
        if relogio.agora >= 140:
            resultado["ExecutionStartDateTime"] = INICIO_REMOTO
        return resultado

    monkeypatch.setattr(modulo, "aws", consultar_aws)
    assert modulo.aguardar(argumentos, COMANDO_ID)["Status"] == "Success"
    eventos = eventos_ssm(capsys)
    assert [e["tempo_observado_segundos"] for e in eventos if e["estado"] == "Pending"] == [
        0,
        60,
        120,
    ]
    assert eventos[3]["estado"] == "InProgress"
    assert eventos[3]["tempo_observado_segundos"] == 125
    assert eventos[4]["tempo_observado_segundos"] == 140
    assert eventos[-1]["estado"] == "Success"
    assert eventos[-1]["tempo_observado_segundos"] == 260
    for anterior, atual in zip(eventos, eventos[1:], strict=False):
        intervalo = atual["tempo_observado_segundos"] - anterior["tempo_observado_segundos"]
        assert 0 <= intervalo <= 60
        if (anterior["estado"], anterior["inicio_execucao_utc"]) == (
            atual["estado"],
            atual["inicio_execucao_utc"],
        ):
            assert intervalo == 60, "Repetições sem mudança devem respeitar o intervalo."
    assert all(e["inicio_execucao_utc"] is None for e in eventos[:4])
    assert all(e["inicio_execucao_utc"] == INICIO_REMOTO for e in eventos[4:])


def test_polling_limita_consulta_lenta_ao_proximo_aviso(consulta_ssm, monkeypatch, capsys):
    relogio, argumentos = consulta_ssm
    prazos = []

    def consultar_aws(*args, **kwargs):
        prazo = kwargs["prazo_segundos"]
        prazos.append(prazo)
        assert 0 < prazo <= 30
        relogio.agora += prazo
        return {"Status": "Pending" if relogio.agora < 125 else "Success"}

    monkeypatch.setattr(modulo, "aws", consultar_aws)
    modulo.aguardar(argumentos, COMANDO_ID)
    eventos = eventos_ssm(capsys)
    momentos = [0, *(e["tempo_observado_segundos"] for e in eventos)]
    assert all(0 <= b - a <= 60 for a, b in zip(momentos, momentos[1:], strict=False))
    assert min(prazos) < max(prazos), "O prazo deve diminuir perto do próximo aviso."


def test_falha_terminal_preserva_artefato_bruto_mas_expoe_so_diagnostico_validado(
    consulta_ssm, monkeypatch, capsys
):
    _, argumentos = consulta_ssm
    resposta = {
        "Status": "Failed",
        "ExecutionStartDateTime": INICIO_REMOTO,
        "ExecutionElapsedTime": "PT33.872S",
        "ResponseCode": 1,
        "StandardOutputContent": json.dumps(
            {
                "sucesso": False,
                "mensagem": f"Implantação falhou; consulte {RECIBO}.",
                "token": SENTINELA,
            }
        ),
        "StandardErrorContent": SENTINELA,
    }
    monkeypatch.setattr(modulo, "aws", lambda *a, **k: resposta)
    with pytest.raises(RuntimeError) as falha:
        modulo.aguardar(argumentos, COMANDO_ID)
    assert RECIBO in str(falha.value)
    assert "Failed" in str(falha.value)
    assert SENTINELA not in str(falha.value)
    eventos = eventos_ssm(capsys)
    assert SENTINELA not in json.dumps(eventos)
    assert eventos[-1]["inicio_execucao_utc"] == INICIO_REMOTO
    artefato = argumentos.saida.with_name("falha_ssm.json")
    assert json.loads(artefato.read_text(encoding="utf-8")) == resposta


@pytest.mark.parametrize(
    "conteudo",
    [
        SENTINELA,
        json.dumps({"sucesso": False, "mensagem": SENTINELA}),
        json.dumps({"sucesso": False, "receipt": "/tmp/" + SENTINELA}),
        json.dumps({"sucesso": False, "receipt": RECIBO.replace("901c8f89fcce", SENTINELA)}),
    ],
)
def test_falha_nao_publica_json_livre_ou_caminho_invalido(
    consulta_ssm, monkeypatch, capsys, conteudo
):
    _, argumentos = consulta_ssm
    monkeypatch.setattr(
        modulo,
        "aws",
        lambda *a, **k: {
            "Status": "TimedOut",
            "StandardOutputContent": conteudo,
            "StandardErrorContent": SENTINELA,
            "StatusDetails": SENTINELA,
        },
    )
    with pytest.raises(RuntimeError) as falha:
        modulo.aguardar(argumentos, COMANDO_ID)
    assert SENTINELA not in str(falha.value)
    assert SENTINELA not in capsys.readouterr().err
    assert argumentos.saida.with_name("falha_ssm.json").is_file()


def test_prazo_de_observacao_preserva_ultima_resposta_e_continua_informando(
    consulta_ssm, monkeypatch, capsys
):
    relogio, argumentos = consulta_ssm
    monkeypatch.setattr(modulo, "aws", lambda *a, **k: {"Status": "Pending"})
    with pytest.raises(TimeoutError, match="pode continuar em execução"):
        modulo.aguardar(argumentos, COMANDO_ID)
    assert relogio.agora == 600 + 2400 + 300
    artefato = json.loads(argumentos.saida.with_name("falha_ssm.json").read_text(encoding="utf-8"))
    assert artefato["Status"] == "Pending"
    assert artefato["ObservacaoExpirada"] is True
    assert artefato["ResultadoIndeterminado"] is True
    eventos = eventos_ssm(capsys)
    assert 54 <= len(eventos) <= 56, "A observação deve ter avisos periódicos sem log a cada poll."
    assert eventos[-1]["tempo_observado_segundos"] >= 3240


def test_erro_aws_publica_codigo_conhecido_sem_stderr_bruto(monkeypatch):
    resultado = SimpleNamespace(
        returncode=255, stdout="", stderr=f"An error occurred (AccessDeniedException): {SENTINELA}"
    )
    monkeypatch.setattr(modulo.subprocess, "run", lambda *a, **k: resultado)
    args = SimpleNamespace(perfil=None, regiao="eu-west-1")
    with pytest.raises(RuntimeError) as falha:
        modulo.aws(args, ["ssm", "get-command-invocation"])
    assert "AccessDeniedException" in str(falha.value)
    assert SENTINELA not in str(falha.value)


def test_polling_tolera_registro_tardio_e_timeout_de_consulta_sem_expor_erro(
    consulta_ssm, monkeypatch, capsys
):
    relogio, argumentos = consulta_ssm
    consultas = 0

    def consultar_aws(*args, **kwargs):
        nonlocal consultas
        consultas += 1
        if consultas == 1:
            raise RuntimeError("InvocationDoesNotExist " + SENTINELA)
        if consultas == 2:
            relogio.agora += kwargs["prazo_segundos"]
            raise modulo.subprocess.TimeoutExpired(
                "aws", kwargs["prazo_segundos"], stderr=SENTINELA
            )
        if consultas == 3:
            return {"Status": "Pending"}
        return {"Status": "Success", "ExecutionStartDateTime": INICIO_REMOTO}

    monkeypatch.setattr(modulo, "aws", consultar_aws)
    assert modulo.aguardar(argumentos, COMANDO_ID)["Status"] == "Success"
    eventos = eventos_ssm(capsys)
    assert eventos[0]["estado"] == "RegistroPendente"
    assert eventos[-1]["estado"] == "Success"
    assert any(e["estado"] == "Pending" for e in eventos)
    assert SENTINELA not in json.dumps(eventos)
    assert not argumentos.saida.with_name("falha_ssm.json").exists()


def test_metadados_ssm_desconhecidos_nao_sao_repetidos_no_console(
    consulta_ssm, monkeypatch, capsys
):
    _, argumentos = consulta_ssm
    monkeypatch.setattr(
        modulo,
        "aws",
        lambda *a, **k: {
            "Status": SENTINELA,
            "ExecutionStartDateTime": SENTINELA,
            "StandardErrorContent": SENTINELA,
        },
    )
    with pytest.raises(RuntimeError) as falha:
        modulo.aguardar(argumentos, COMANDO_ID)
    assert SENTINELA not in str(falha.value)
    eventos = eventos_ssm(capsys)
    assert eventos[-1]["estado"] == "Desconhecido"
    assert eventos[-1]["inicio_execucao_utc"] is None


def test_timeout_da_aws_cli_respeita_prazo_do_polling(monkeypatch):
    observados = []

    def executar(*args, **kwargs):
        observados.append(kwargs["timeout"])
        return SimpleNamespace(returncode=0, stdout='{"Status":"Pending"}', stderr="")

    monkeypatch.setattr(modulo.subprocess, "run", executar)
    args = SimpleNamespace(perfil=None, regiao="eu-west-1")
    assert (
        modulo.aws(args, ["ssm", "get-command-invocation"], prazo_segundos=17)["Status"]
        == "Pending"
    )
    assert observados == [17]


def test_janela_cobre_entrega_e_execucao_alem_de_2500_segundos(consulta_ssm, monkeypatch, capsys):
    relogio, argumentos = consulta_ssm
    monkeypatch.setattr(
        modulo,
        "aws",
        lambda *a, **k: {"Status": "InProgress" if relogio.agora < 2800 else "Success"},
    )
    assert modulo.aguardar(argumentos, COMANDO_ID)["Status"] == "Success"
    assert relogio.agora == 2800
    assert eventos_ssm(capsys)[-1]["estado"] == "Success"
    assert not argumentos.saida.with_name("falha_ssm.json").exists()


@pytest.mark.parametrize(
    "codigo", ["Throttling", "ThrottlingException", "ServiceUnavailable", "InternalServerError"]
)
def test_erro_transitorio_repete_consulta_sem_declarar_falha_remota(
    consulta_ssm, monkeypatch, capsys, codigo
):
    _, argumentos = consulta_ssm
    consultas = 0

    def consultar_aws(*args, **kwargs):
        nonlocal consultas
        consultas += 1
        if consultas == 1:
            return {"Status": "Pending"}
        if consultas < 4:
            raise RuntimeError(f"A AWS CLI retornou erro ({codigo}). {SENTINELA}")
        return {"Status": "Success"}

    monkeypatch.setattr(modulo, "aws", consultar_aws)
    assert modulo.aguardar(argumentos, COMANDO_ID)["Status"] == "Success"
    assert consultas == 4
    eventos = eventos_ssm(capsys)
    assert any(e["erro_consulta"] == codigo for e in eventos)
    assert SENTINELA not in json.dumps(eventos)
    assert not argumentos.saida.with_name("falha_ssm.json").exists()


def test_erros_transitorios_persistentes_esgotam_limite_sem_perder_codigo(
    consulta_ssm, monkeypatch, capsys
):
    relogio, argumentos = consulta_ssm
    consultas = 0

    def consultar_aws(*args, **kwargs):
        nonlocal consultas
        consultas += 1
        raise RuntimeError("A AWS CLI retornou erro (ThrottlingException). " + SENTINELA)

    monkeypatch.setattr(modulo, "aws", consultar_aws)
    with pytest.raises(RuntimeError, match="ThrottlingException") as falha:
        modulo.aguardar(argumentos, COMANDO_ID)
    assert consultas == 5
    assert relogio.agora <= 120
    assert "indeterminado" in str(falha.value)
    assert SENTINELA not in str(falha.value)
    artefato = json.loads(argumentos.saida.with_name("falha_ssm.json").read_text(encoding="utf-8"))
    assert artefato["ErroConsulta"] == "ThrottlingException"
    assert artefato["TentativasConsulta"] == 5
    assert artefato["ResultadoIndeterminado"] is True
    assert SENTINELA not in json.dumps(artefato)
    assert SENTINELA not in capsys.readouterr().err


def test_erro_fatal_da_consulta_preserva_estado_anterior_e_codigo_seguro(
    consulta_ssm, monkeypatch, capsys
):
    _, argumentos = consulta_ssm
    consultas = 0

    def consultar_aws(*args, **kwargs):
        nonlocal consultas
        consultas += 1
        if consultas == 1:
            return {"Status": "Pending", "ExecutionStartDateTime": INICIO_REMOTO}
        raise RuntimeError("A AWS CLI retornou erro (AccessDenied). " + SENTINELA)

    monkeypatch.setattr(modulo, "aws", consultar_aws)
    with pytest.raises(RuntimeError, match="AccessDenied") as falha:
        modulo.aguardar(argumentos, COMANDO_ID)
    artefato = json.loads(argumentos.saida.with_name("falha_ssm.json").read_text(encoding="utf-8"))
    assert artefato["Status"] == "Pending"
    assert artefato["ErroConsulta"] == "AccessDenied"
    assert artefato["ResultadoIndeterminado"] is True
    assert "indeterminado" in str(falha.value)
    assert SENTINELA not in str(falha.value) + capsys.readouterr().err


@pytest.mark.parametrize("primeira_consulta_expira", [True, False])
def test_progresso_mostra_consultas_expiradas_mesmo_apos_estado_anterior(
    consulta_ssm, monkeypatch, capsys, primeira_consulta_expira
):
    relogio, argumentos = consulta_ssm
    consultas = 0

    def consultar_aws(*args, **kwargs):
        nonlocal consultas
        consultas += 1
        if consultas == 1 and not primeira_consulta_expira:
            return {"Status": "Pending"}
        if consultas <= 3:
            relogio.agora += kwargs["prazo_segundos"]
            raise modulo.subprocess.TimeoutExpired(
                "aws", kwargs["prazo_segundos"], stderr=SENTINELA
            )
        return {"Status": "Success"}

    monkeypatch.setattr(modulo, "aws", consultar_aws)
    modulo.aguardar(argumentos, COMANDO_ID)
    eventos = eventos_ssm(capsys)
    estado = "ConsultaSemResposta" if primeira_consulta_expira else "Pending"
    assert any(
        e["estado"] == estado
        and e["consultas_sem_resposta"] > 0
        and e["erro_consulta"] == "TimeoutConsulta"
        for e in eventos
    )
    assert eventos[-1]["consultas_sem_resposta"] == (3 if primeira_consulta_expira else 2)
    assert eventos[-1]["erro_consulta"] is None
    assert SENTINELA not in json.dumps(eventos)
