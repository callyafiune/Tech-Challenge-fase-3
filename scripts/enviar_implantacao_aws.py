"""Envia a implantação à EC2 por SSM e verifica a versão pela API pública.

O modo --preparar gera o comando para inspeção sem acessar a AWS. Credenciais
permanecem na sessão AWS do operador/runner e no papel IAM da instância.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parents[1]
TEXTO_EXEMPLO = (
    "The study evaluated cardiovascular risk factors and the association "
    "between hypertension and coronary artery disease."
)


def parametros_ssm(fonte: bytes, argumentos: list[str]) -> dict:
    """Transporta código e argumentos sem depender de SSH ou interpolar credenciais."""
    codigo = base64.b64encode(fonte).decode("ascii")
    parametros = {
        "executionTimeout": ["2400"],
        "commands": [
            "set -eu",
            "umask 077",
            "arquivo=$(mktemp /tmp/medical-deploy.XXXXXX.py)",
            "trap 'rm -f \"$arquivo\"' EXIT",
            f"printf '%s' {shlex.quote(codigo)} | base64 --decode > \"$arquivo\"",
            'python3 "$arquivo" ' + shlex.join(argumentos),
        ],
    }
    if len(json.dumps(parametros).encode("utf-8")) > 60000:
        raise ValueError("O comando ultrapassa o tamanho máximo adotado de 60.000 bytes.")
    return parametros


def validar_destino(instancia: dict, url_publica: str) -> None:
    """Impede envio para uma máquina parada ou diferente da origem pública informada."""
    url = urlparse(url_publica)
    if url.scheme not in {"http", "https"} or url.username or url.password:
        raise ValueError("Informe uma origem HTTP/HTTPS sem credenciais na URL.")
    if url.path not in {"", "/"} or url.query or url.fragment:
        raise ValueError("Informe somente a origem pública, sem caminho, consulta ou fragmento.")
    if url.scheme != "http" or url.port != 8000:
        raise ValueError("Esta implantação publica a API por HTTP na porta 8000.")
    if instancia.get("State", {}).get("Name") != "running":
        raise ValueError("A instância precisa estar em execução antes da implantação.")
    if url.hostname != instancia.get("PublicIpAddress"):
        raise ValueError("O IP público informado não corresponde à instância selecionada.")


def validar_respostas(prontidao: dict, predicao: dict, versao: str) -> None:
    """Confere que o endereço público já responde com o classificador recém-implantado."""
    if any(item.get("versao_modelo") != versao for item in (prontidao, predicao)):
        raise ValueError("A versão pública difere do modelo confirmado na instância.")
    if any(item.get("backend") != "onnx" for item in (prontidao, predicao)):
        raise ValueError("O endpoint público não está usando o motor ONNX esperado.")
    if type(predicao.get("classe_id")) is not int or predicao["classe_id"] not in range(1, 6):
        raise ValueError("A resposta pública não contém uma classe médica válida.")


def consultar(url: str, corpo: dict | None = None) -> dict:
    """Consulta somente o exemplo público da demonstração, sem textos de pacientes."""
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    pedido = urllib.request.Request(url, data=dados, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(pedido, timeout=20) as resposta:
        return json.load(resposta)


def aws(argumentos: argparse.Namespace, comando: list[str]) -> dict:
    """Executa a AWS CLI sem imprimir tokens ou exportar credenciais para o servidor."""
    resultado = subprocess.run(
        [
            "aws",
            *(["--profile", argumentos.perfil] if argumentos.perfil else []),
            "--region",
            argumentos.regiao,
            "--no-cli-pager",
            "--cli-connect-timeout",
            "10",
            "--cli-read-timeout",
            "30",
            *comando,
            "--output",
            "json",
        ],
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "AWS_PAGER": ""},
        timeout=60,
    )
    if resultado.returncode:
        raise RuntimeError(resultado.stderr.strip() or "A AWS CLI retornou erro.")
    return json.loads(resultado.stdout)


def aguardar(argumentos: argparse.Namespace, comando_id: str) -> dict:
    """Tolera a consistência eventual do SSM e nunca interpreta erro como sucesso."""
    limite = time.monotonic() + 2500
    while time.monotonic() < limite:
        try:
            resultado = aws(
                argumentos,
                [
                    "ssm",
                    "get-command-invocation",
                    "--command-id",
                    comando_id,
                    "--instance-id",
                    argumentos.instancia,
                ],
            )
        except RuntimeError as erro:
            if "InvocationDoesNotExist" not in str(erro):
                raise
        else:
            estado = resultado["Status"]
            if estado == "Success":
                return resultado
            if estado not in {"Pending", "InProgress", "Delayed"}:
                argumentos.saida.with_name("falha_ssm.json").write_text(
                    json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                raise RuntimeError(
                    f"O comando SSM {comando_id} terminou com estado {estado}. "
                    "Consulte a saída no Systems Manager antes de repetir a implantação."
                )
        time.sleep(5)
    raise TimeoutError(f"O comando SSM {comando_id} não concluiu no prazo observado.")


def executar(argumentos: argparse.Namespace) -> dict:
    """Valida o destino, envia uma única operação e identifica o modelo publicamente."""
    script = RAIZ / "scripts" / "implantar_ec2.py"
    remotos = [
        "--revisao",
        argumentos.revisao,
        "--imagem-runtime",
        argumentos.imagem_runtime,
        "--imagem-treinamento",
        argumentos.imagem_treinamento,
        "--regiao",
        argumentos.regiao,
    ]
    if argumentos.imagem_airflow:
        remotos += ["--imagem-airflow", argumentos.imagem_airflow]
    subprocess.run([sys.executable, str(script), *remotos, "--validar"], check=True)
    parametros = parametros_ssm(script.read_bytes(), remotos)
    pasta = argumentos.saida.parent
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "parametros_ssm.json"
    arquivo.write_text(json.dumps(parametros, ensure_ascii=False, indent=2), encoding="utf-8")
    if argumentos.preparar:
        return {"preparado": True, "implantado": False, "parametros": str(arquivo.resolve())}

    identidade = aws(argumentos, ["sts", "get-caller-identity"])
    conta = argumentos.imagem_runtime.split(".", 1)[0]
    if identidade["Account"] != conta:
        raise ValueError("O perfil AWS pertence a uma conta diferente da imagem ECR.")
    resposta = aws(
        argumentos,
        [
            "ec2",
            "describe-instances",
            "--instance-ids",
            argumentos.instancia,
        ],
    )
    instancias = [i for r in resposta["Reservations"] for i in r["Instances"]]
    if len(instancias) != 1 or instancias[0]["InstanceId"] != argumentos.instancia:
        raise ValueError("A consulta não retornou exatamente a instância selecionada.")
    validar_destino(instancias[0], argumentos.url_publica)
    gerenciadas = aws(
        argumentos,
        [
            "ssm",
            "describe-instance-information",
            "--filters",
            f"Key=InstanceIds,Values={argumentos.instancia}",
        ],
    )["InstanceInformationList"]
    if len(gerenciadas) != 1 or gerenciadas[0]["PingStatus"] != "Online":
        raise ValueError("A instância precisa estar Online no Systems Manager.")
    envio = aws(
        argumentos,
        [
            "ssm",
            "send-command",
            "--document-name",
            "AWS-RunShellScript",
            "--instance-ids",
            argumentos.instancia,
            "--parameters",
            "file://" + str(arquivo.resolve()),
            "--timeout-seconds",
            "600",
            "--comment",
            f"Fase 3: {argumentos.revisao}",
        ],
    )
    comando_id = envio["Command"]["CommandId"]
    print(f"Comando SSM enviado: {comando_id}", file=sys.stderr, flush=True)
    argumentos.saida.write_text(
        json.dumps(
            {
                "concluido": False,
                "comando_ssm": comando_id,
                "instancia": argumentos.instancia,
                "revisao": argumentos.revisao,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    resultado = aguardar(argumentos, comando_id)
    remoto = json.loads(resultado["StandardOutputContent"])
    if remoto.get("sucesso") is not True:
        raise RuntimeError("A execução remota não confirmou implantação bem-sucedida.")
    if remoto.get("revisao") != argumentos.revisao:
        raise ValueError("A revisão confirmada pela instância difere da revisão solicitada.")
    origem = argumentos.url_publica.rstrip("/")
    saude = consultar(origem + "/health")
    prontidao = consultar(origem + "/ready")
    predicao = consultar(origem + "/predict", {"texto": TEXTO_EXEMPLO})
    validar_respostas(prontidao, predicao, remoto["versao_modelo"])
    return {
        "sucesso": True,
        "implantado": True,
        "comando_ssm": comando_id,
        "instancia": argumentos.instancia,
        "regiao": argumentos.regiao,
        "url_publica": origem,
        "revisao": argumentos.revisao,
        "remoto": remoto,
        "health": saude,
        "ready": prontidao,
        "predict": predicao,
        "fim_utc": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    """Oferece preparação inspecionável e implantação explícita no alvo informado."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--perfil", help="Perfil local; omita para usar a sessão OIDC do workflow.")
    parser.add_argument("--instancia", required=True)
    parser.add_argument("--revisao", required=True)
    parser.add_argument("--imagem-runtime", required=True)
    parser.add_argument("--imagem-treinamento", required=True)
    parser.add_argument("--imagem-airflow")
    parser.add_argument("--regiao", default="eu-west-1")
    parser.add_argument("--url-publica", required=True)
    parser.add_argument("--preparar", action="store_true")
    parser.add_argument(
        "--saida", type=Path, default=RAIZ / ".local/aws_fase3/ultima_implantacao.json"
    )
    argumentos = parser.parse_args()
    try:
        resultado = executar(argumentos)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyError) as erro:
        print(f"Implantação não confirmada: {erro}", file=sys.stderr)
        return 1
    argumentos.saida.write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
