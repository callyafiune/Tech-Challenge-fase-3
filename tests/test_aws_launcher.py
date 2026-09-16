"""Confere os limites do envio remoto e a identificação da instância de destino."""

import importlib.util
import json
from pathlib import Path

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
