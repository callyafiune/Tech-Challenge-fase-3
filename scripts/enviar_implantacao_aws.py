"""Envia a implantação à EC2 por SSM e verifica a versão pela API pública.

O modo --preparar gera o comando para inspeção sem acessar a AWS. Credenciais
permanecem na sessão AWS do operador/runner e no papel IAM da instância.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
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
ESTADOS_TRANSITORIOS = {"Pending", "InProgress", "Delayed", "Cancelling"}
ESTADOS_CONHECIDOS = ESTADOS_TRANSITORIOS | {
    "Success",
    "Failed",
    "Cancelled",
    "TimedOut",
    "RegistroPendente",
    "ConsultaSemResposta",
}
ERROS_AWS_CONHECIDOS = {
    "InvocationDoesNotExist",
    "AccessDenied",
    "AccessDeniedException",
    "InvalidInstanceId",
    "InvalidCommandId",
    "Throttling",
    "ThrottlingException",
    "ExpiredToken",
    "UnrecognizedClientException",
    "RequestExpired",
    "InternalServerError",
    "ServiceUnavailable",
}
ERROS_AWS_TRANSITORIOS = {
    "Throttling",
    "ThrottlingException",
    "ServiceUnavailable",
    "InternalServerError",
}
MAX_TENTATIVAS_TRANSITORIAS = 5
PRAZO_ENTREGA_SSM = 600
PRAZO_EXECUCAO_SSM = 2400
MARGEM_OBSERVACAO_SSM = 300
PADRAO_RECIBO = r"/opt/tech-challenge-fase-3/releases/\d{8}T\d{12}Z-[a-f0-9]{12}/receipt\.json"


def parametros_ssm(fonte: bytes, argumentos: list[str]) -> dict:
    """Transporta código e argumentos sem depender de SSH ou interpolar credenciais."""
    codigo = base64.b64encode(fonte).decode("ascii")
    parametros = {
        "executionTimeout": [str(PRAZO_EXECUCAO_SSM)],
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


def codigo_erro_aws(texto: str) -> str:
    return next(
        (
            palavra
            for palavra in re.findall(r"\b[A-Za-z][A-Za-z0-9]*\b", texto)
            if palavra in ERROS_AWS_CONHECIDOS
        ),
        "NaoIdentificado",
    )


def aws(argumentos: argparse.Namespace, comando: list[str], *, prazo_segundos: float = 60) -> dict:
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
        timeout=prazo_segundos,
    )
    if resultado.returncode:
        codigo = codigo_erro_aws(resultado.stderr)
        raise RuntimeError(f"A AWS CLI retornou erro ({codigo}); saída bruta omitida.")
    return json.loads(resultado.stdout)


def diagnostico_remoto(resultado: dict) -> dict:
    """Aceita somente o contrato conhecido; mensagens e campos arbitrários não viram logs."""
    try:
        remoto = json.loads(resultado.get("StandardOutputContent", ""))
    except (ValueError, TypeError):
        return {}
    if not isinstance(remoto, dict) or type(remoto.get("sucesso")) is not bool:
        return {}
    diagnostico = {"sucesso": remoto["sucesso"]}
    recibo = remoto.get("receipt")
    if isinstance(recibo, str) and re.fullmatch(PADRAO_RECIBO, recibo):
        diagnostico["receipt"] = recibo
    mensagem = remoto.get("mensagem")
    if isinstance(mensagem, str):
        encontrado = re.fullmatch(rf"Implantação falhou; consulte ({PADRAO_RECIBO})\.", mensagem)
        if encontrado:
            diagnostico["receipt"] = encontrado.group(1)
    return diagnostico


def progresso_ssm(
    resultado: dict,
    inicio: float,
    consultas_sem_resposta: int = 0,
    erro_consulta: str | None = None,
) -> dict:
    estado = resultado.get("Status")
    estado = estado if estado in ESTADOS_CONHECIDOS else "Desconhecido"
    inicio_remoto = resultado.get("ExecutionStartDateTime")
    if not isinstance(inicio_remoto, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", inicio_remoto
    ):
        inicio_remoto = None
    elif inicio_remoto:
        try:
            datetime.fromisoformat(inicio_remoto.replace("Z", "+00:00"))
        except ValueError:
            inicio_remoto = None
    return {
        "evento": "progresso_ssm",
        "estado": estado,
        "tempo_observado_segundos": round(time.monotonic() - inicio, 1),
        "inicio_execucao_utc": inicio_remoto,
        "consultas_sem_resposta": consultas_sem_resposta,
        "erro_consulta": erro_consulta,
    }


def preservar_falha(argumentos: argparse.Namespace, resultado: dict) -> str:
    """Preserva a evidência original no artefato, exibindo apenas diagnóstico permitido."""
    arquivo = argumentos.saida.with_name("falha_ssm.json")
    arquivo.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    diagnostico = diagnostico_remoto(resultado)
    detalhe = (
        " Diagnóstico remoto: " + json.dumps(diagnostico, ensure_ascii=False) if diagnostico else ""
    )
    return f"Artefato preservado em {arquivo}.{detalhe}"


def aguardar(argumentos: argparse.Namespace, comando_id: str) -> dict:
    """Mostra transições e início remoto, com intervalo máximo de 60 s entre avisos."""
    inicio = ultimo_aviso = time.monotonic()
    limite = inicio + PRAZO_ENTREGA_SSM + PRAZO_EXECUCAO_SSM + MARGEM_OBSERVACAO_SSM
    assinatura = None
    consultas_sem_resposta = tentativas_transitorias = 0
    erro_consulta = None
    resultado = {"CommandId": comando_id, "InstanceId": argumentos.instancia}

    def avisar():
        nonlocal ultimo_aviso, assinatura
        progresso = progresso_ssm(resultado, inicio, consultas_sem_resposta, erro_consulta)
        nova = (progresso["estado"], progresso["inicio_execucao_utc"], erro_consulta)
        if nova != assinatura or time.monotonic() - ultimo_aviso >= 60:
            print(json.dumps(progresso, ensure_ascii=False), file=sys.stderr, flush=True)
            ultimo_aviso, assinatura = time.monotonic(), nova

    while time.monotonic() < limite:
        if assinatura is not None and time.monotonic() - ultimo_aviso >= 60:
            avisar()
        prazo = min(30, limite - time.monotonic(), ultimo_aviso + 60 - time.monotonic())
        if prazo <= 0:
            continue
        intervalo = 5
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
                prazo_segundos=prazo,
            )
        except subprocess.TimeoutExpired:
            consultas_sem_resposta += 1
            tentativas_transitorias = 0
            erro_consulta = "TimeoutConsulta"
            if "Status" not in resultado:
                resultado["Status"] = "ConsultaSemResposta"
        except RuntimeError as erro:
            erro_consulta = codigo_erro_aws(str(erro))
            if erro_consulta == "InvocationDoesNotExist":
                tentativas_transitorias = 0
                resultado = {**resultado, "Status": "RegistroPendente"}
            elif erro_consulta in ERROS_AWS_TRANSITORIOS:
                tentativas_transitorias += 1
                intervalo = min(30, 5 * 2 ** (tentativas_transitorias - 1))
            avisar()
            if (
                erro_consulta not in ERROS_AWS_TRANSITORIOS | {"InvocationDoesNotExist"}
                or tentativas_transitorias >= MAX_TENTATIVAS_TRANSITORIAS
            ):
                detalhe = preservar_falha(
                    argumentos,
                    {
                        **resultado,
                        "ErroConsulta": erro_consulta,
                        "TentativasConsulta": tentativas_transitorias,
                        "ResultadoIndeterminado": True,
                    },
                )
                raise RuntimeError(
                    f"Consulta SSM interrompida ({erro_consulta}); resultado remoto indeterminado. "
                    f"O comando pode continuar em execução; consulte-o antes de repetir. {detalhe}"
                ) from None
        else:
            erro_consulta = None
            tentativas_transitorias = 0
            avisar()
            estado = progresso_ssm(resultado, inicio)["estado"]
            if estado == "Success":
                return resultado
            if estado not in ESTADOS_TRANSITORIOS:
                detalhe = preservar_falha(argumentos, resultado)
                raise RuntimeError(
                    f"O comando SSM {comando_id} terminou com estado {estado}. {detalhe}"
                )
        avisar()
        pausa = min(intervalo, limite - time.monotonic(), ultimo_aviso + 60 - time.monotonic())
        if pausa > 0:
            time.sleep(pausa)
    detalhe = preservar_falha(
        argumentos,
        {
            **resultado,
            "ObservacaoExpirada": True,
            "ResultadoIndeterminado": True,
            "ErroConsulta": erro_consulta,
            "ConsultasSemResposta": consultas_sem_resposta,
        },
    )
    raise TimeoutError(
        f"Observação do comando SSM {comando_id} encerrada com resultado indeterminado. "
        f"O comando pode continuar em execução; consulte-o antes de repetir. {detalhe}"
    )


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
            str(PRAZO_ENTREGA_SSM),
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
