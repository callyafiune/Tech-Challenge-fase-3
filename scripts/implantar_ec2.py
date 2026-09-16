"""Implantação transacional da fase 3 por SSM; stdout contém somente o resultado JSON."""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

APP_DIR = Path("/opt/tech-challenge-fase-3")
PROJETO = "medical-classifier"
LEGADO = "tech-challenge-fase-2"
EXEMPLO = "The study evaluated hypertension and coronary artery disease in adult patients."
LIMITE_IMPLANTACAO = 1800
LIMITE_RECUPERACAO = 540
MEMORIA_MINIMA_MIB = 1536
MEMORIA_REUSO_MIB = 512
ROTULO_TEMPORARIO = "io.github.callyafiune.tech-challenge-fase-3.temporario=ssm"
_SINAIS_ATIVOS = False
_RECUPERANDO = False
_FIM_RECUPERACAO = None


class InterrupcaoImplantacao(RuntimeError):
    """Interrupção recuperável pelo mesmo caminho das falhas de implantação."""


class PrazoRecuperacaoEsgotado(RuntimeError):
    """Impede novas operações quando a reserva de recuperação já terminou."""


def desarmar_interrupcoes() -> None:
    global _RECUPERANDO, _FIM_RECUPERACAO
    if _FIM_RECUPERACAO is None:
        _FIM_RECUPERACAO = time.monotonic() + LIMITE_RECUPERACAO
    _RECUPERANDO = True
    if _SINAIS_ATIVOS:
        signal.alarm(0)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)


def tempo_disponivel(limite: float) -> float:
    if not _RECUPERANDO:
        return limite
    restante = _FIM_RECUPERACAO - time.monotonic()
    if restante <= 0:
        raise PrazoRecuperacaoEsgotado("O prazo de 540 segundos para recuperação terminou.")
    return min(limite, restante)


def interromper(numero, quadro) -> None:
    desarmar_interrupcoes()
    raise InterrupcaoImplantacao(f"Implantação interrompida pelo sinal {numero}.")


def verificar_memoria(
    caminho: Path = Path("/proc/meminfo"), minimo_mib: int = MEMORIA_MINIMA_MIB
) -> int:
    texto = caminho.read_text(encoding="ascii")
    valor = re.search(r"^MemAvailable:\s+(\d+)\s+kB$", texto, re.MULTILINE)
    disponivel = int(valor.group(1)) // 1024 if valor else 0
    if disponivel < minimo_mib:
        raise RuntimeError(f"MemAvailable insuficiente: {disponivel} MiB; mínimo {minimo_mib} MiB.")
    return disponivel


class Argumentos(argparse.ArgumentParser):
    def error(self, mensagem):
        raise ValueError(f"Argumentos inválidos: {mensagem}")


def argumentos(argv=None):
    """Valida os destinos autorizados antes de qualquer operação externa."""
    parser = Argumentos(description=__doc__)
    parser.add_argument("--revisao", required=True)
    parser.add_argument("--imagem-runtime", required=True)
    parser.add_argument("--imagem-treinamento", required=True)
    parser.add_argument("--imagem-airflow")
    parser.add_argument("--regiao", default="eu-west-1")
    parser.add_argument("--validar", action="store_true")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-fA-F0-9]{40}", args.revisao):
        raise ValueError("A revisão deve ser um SHA Git completo de 40 caracteres hexadecimais.")
    args.revisao = args.revisao.lower()
    if args.regiao != "eu-west-1":
        raise ValueError("Esta implantação está limitada à região eu-west-1.")
    registro = "076516546831.dkr.ecr.eu-west-1.amazonaws.com/tech-challenge-fase-3"
    imagens = [args.imagem_runtime, args.imagem_treinamento]
    if args.imagem_airflow is not None:
        imagens.append(args.imagem_airflow)
    for imagem in imagens:
        if not re.fullmatch(
            re.escape(registro) + r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}|@sha256:[a-f0-9]{64})",
            imagem,
        ):
            raise ValueError(
                "A imagem deve identificar tag ou digest no repositório ECR autorizado."
            )
    return args


def executar(comando: list[str], entrada: str | None = None) -> str:
    """Captura saídas sem divulgar credenciais, conteúdo de env ou respostas do AWS CLI."""
    ambiente = os.environ.copy()
    for nome in (
        "ECR_RUNTIME_IMAGE ECR_TRAINING_IMAGE ECR_AIRFLOW_IMAGE GRAFANA_ADMIN_PASSWORD "
        "GRAFANA_ADMIN_USER API_PORT PROMETHEUS_PORT GRAFANA_PORT AIRFLOW_PORT"
    ).split():
        ambiente.pop(nome, None)
    if comando[0] == "aws":
        for nome in (
            "AWS_PROFILE AWS_DEFAULT_PROFILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY "
            "AWS_SESSION_TOKEN AWS_WEB_IDENTITY_TOKEN_FILE AWS_ROLE_ARN AWS_ROLE_SESSION_NAME "
            "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_CONTAINER_CREDENTIALS_FULL_URI"
        ).split():
            ambiente.pop(nome, None)
        ambiente.update(
            AWS_SHARED_CREDENTIALS_FILE="/dev/null",
            AWS_CONFIG_FILE="/dev/null",
            AWS_EC2_METADATA_DISABLED="false",
        )
    resultado = subprocess.run(
        comando,
        input=entrada,
        capture_output=True,
        text=True,
        env=ambiente,
        timeout=tempo_disponivel(60 if _RECUPERANDO else LIMITE_IMPLANTACAO),
        check=False,
    )
    if resultado.returncode:
        raise RuntimeError(
            f"Comando {comando[0]} {comando[1]} falhou: código {resultado.returncode}."
        )
    return resultado.stdout


def compose(estado: dict, *opcoes: str, airflow: bool = False) -> str:
    nome = "docker-compose.airflow" if airflow else "docker-compose"
    projeto = f"{PROJETO}-airflow" if airflow else PROJETO
    pasta = Path(estado["diretorio"])
    comando = ["docker", "compose", "--project-directory", str(pasta)]
    comando += ["--env-file", estado["arquivo_env"], "-p", projeto]
    comando += ["-f", str(pasta / f"{nome}.yml"), "-f", str(pasta / f"{nome}.aws.yml")]
    return executar([*comando, *opcoes])


def extrair_fontes(arquivo: Path, destino: Path, revisao: str) -> None:
    """Extrai apenas arquivos e diretórios da revisão, sem links ou travessia de caminhos."""
    prefixo = f"Tech-Challenge-fase-3-{revisao}"
    parametros = {"fileobj": arquivo} if hasattr(arquivo, "read") else {"name": arquivo}
    with tarfile.open(mode="r:gz", **parametros) as tar:
        membros = tar.getmembers()
        if sum(item.size for item in membros) > 128 * 1024 * 1024:
            raise ValueError("O arquivo de fontes excede o limite de extração.")
        for item in membros:
            partes = PurePosixPath(item.name).parts
            if (
                "\\" in item.name
                or not partes
                or partes[0] != prefixo
                or ".." in partes
                or not (item.isdir() or item.isfile())
            ):
                raise ValueError("O arquivo de fontes contém caminho ou tipo não permitido.")
        for item in membros:
            alvo = destino.joinpath(*PurePosixPath(item.name).parts[1:])
            if item.isdir():
                alvo.mkdir(parents=True, exist_ok=True)
            else:
                alvo.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(item) as origem, alvo.open("xb") as saida:
                    shutil.copyfileobj(origem, saida)
        # Os mounts precisam ser legíveis por nobody/472 mesmo sob umask 077 do SSM.
        for caminho in (destino, *destino.rglob("*")):
            caminho.chmod(0o755 if caminho.is_dir() else 0o644)


def validar_predicao(pronta: dict, resposta: dict) -> str:
    versao = pronta.get("versao_modelo")
    probabilidades = resposta.get("probabilidades", {})
    if (
        pronta.get("status") != "pronto"
        or pronta.get("backend") != "onnx"
        or not isinstance(versao, str)
        or not versao
        or resposta.get("versao_modelo") != versao
        or resposta.get("backend") != "onnx"
        or type(resposta.get("classe_id")) is not int
        or resposta["classe_id"] not in range(1, 6)
        or not isinstance(probabilidades, dict)
        or set(probabilidades) != set("12345")
    ):
        raise ValueError("Resposta da API incompatível com o contrato do classificador.")
    valores = list(probabilidades.values())
    if (
        any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in valores)
        or abs(sum(valores) - 1) > 1e-4
    ):
        raise ValueError("As cinco probabilidades precisam ser finitas e somar um.")
    return versao


def consultar(url: str, corpo: dict | None = None) -> bytes:
    dados = None if corpo is None else json.dumps(corpo).encode()
    pedido = urllib.request.Request(url, data=dados, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(pedido, timeout=tempo_disponivel(5)) as resposta:
        return resposta.read(1024 * 1024)


def esperar(url: str, limite_segundos: int = 180) -> bytes:
    limite = time.monotonic() + tempo_disponivel(limite_segundos)
    while time.monotonic() < limite:
        try:
            return consultar(url)
        except (urllib.error.URLError, TimeoutError, OSError):
            restante = limite - time.monotonic()
            if restante > 0:
                time.sleep(tempo_disponivel(min(2, restante)))
    tempo_disponivel(1)
    raise RuntimeError(f"O serviço não ficou pronto dentro de {limite_segundos} segundos.")


def conferir_api(porta: int) -> str:
    base = f"http://127.0.0.1:{porta}"
    return validar_predicao(
        json.loads(esperar(base + "/ready")),
        json.loads(consultar(base + "/predict", {"texto": EXEMPLO})),
    )


def containers_ativos() -> list[dict]:
    ids = executar(["docker", "ps", "-q"]).split()
    return json.loads(executar(["docker", "inspect", *ids])) if ids else []


def validar_porta(containers: list[dict]) -> None:
    ocupantes = [
        c
        for c in containers
        if any(
            item["HostPort"] == "8000"
            for entradas in c["NetworkSettings"]["Ports"].values()
            for item in (entradas or [])
        )
    ]
    for container in ocupantes:
        projeto = (container["Config"].get("Labels") or {}).get("com.docker.compose.project")
        if projeto not in (LEGADO, PROJETO):
            raise RuntimeError(
                "A porta 8000 pertence a um projeto não autorizado para substituição."
            )
    if not ocupantes:
        with socket.socket() as teste:
            try:
                teste.bind(("0.0.0.0", 8000))
            except OSError as erro:
                raise RuntimeError(
                    "A porta 8000 está ocupada por um processo não identificado."
                ) from erro


def restaurar(anterior: dict | None, atual: dict, legados: list[str]) -> None:
    """Tenta todas as restaurações, mesmo quando uma delas falha; nunca remove volumes."""
    etapas = []
    if atual.get("imagens", {}).get("airflow") and not (anterior or {}).get("imagens", {}).get(
        "airflow"
    ):
        etapas.append(lambda: compose(atual, "down", "--remove-orphans", airflow=True))
    if anterior:
        etapas.append(
            lambda: compose(anterior, "up", "-d", "--no-deps", "api", "prometheus", "grafana")
        )
        if anterior.get("imagens", {}).get("airflow"):
            etapas.append(
                lambda: compose(anterior, "up", "-d", "--no-deps", "airflow", airflow=True)
            )
    else:
        etapas.append(lambda: compose(atual, "down", "--remove-orphans"))
    for identificador, politica in atual.get("politicas_legadas", {}).items():
        etapas.append(
            lambda identificador=identificador, politica=politica: executar(
                ["docker", "update", f"--restart={politica_reinicio(politica)}", identificador]
            )
        )
    if not anterior and legados:
        etapas.append(lambda: executar(["docker", "start", *legados]))
    falhas = []
    for etapa in etapas:
        try:
            etapa()
        except Exception as erro:
            falhas.append(type(erro).__name__)
    if falhas:
        raise RuntimeError("A restauração apresentou falhas: " + ", ".join(falhas))


def politica_reinicio(politica: dict) -> str:
    nome, tentativas = politica.get("Name"), politica.get("MaximumRetryCount", 0)
    if nome == "":
        nome = "no"
    if nome not in ("no", "always", "unless-stopped", "on-failure"):
        raise ValueError("Política de reinício do legado desconhecida.")
    if type(tentativas) is not int or tentativas < 0:
        raise ValueError("Limite de tentativas do legado inválido.")
    return f"on-failure:{tentativas}" if nome == "on-failure" and tentativas else nome


def remover_temporario(nome: str) -> None:
    comando = ["docker", "ps", "-aq", "--filter", f"label={ROTULO_TEMPORARIO}"]
    ids = executar([*comando, "--filter", f"name=^/{nome}$"]).split()
    if ids:
        executar(["docker", "rm", "-f", *ids])


def limpar_temporarios() -> None:
    """Recupera órfãos de SIGKILL; somente nosso rótulo autoriza a remoção inicial."""
    ids = executar(["docker", "ps", "-aq", "--filter", f"label={ROTULO_TEMPORARIO}"]).split()
    if ids:
        executar(["docker", "rm", "-f", *ids])


def gravar_json(caminho: Path, dados: dict) -> None:
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.chmod(0o600)
    temporario.replace(caminho)


def ponteiro(imagem: str, anterior: dict | None = None):
    codigo = "import json,pathlib; p=pathlib.Path('/app/models/current.json'); "
    if anterior is None:
        codigo += 'print(p.read_text() if p.exists() else "null")'
    else:
        codigo += (
            "t=p.with_suffix('.rollback'); t.write_text("
            + repr(json.dumps(anterior))
            + "); t.replace(p)"
        )
    modo = "ro" if anterior is None else "rw"
    comando = "docker run --rm --network none --read-only --user 10001:10001".split()
    comando += ["-v", f"{PROJETO}_modelos:/app/models:{modo}", "--entrypoint", "python"]
    saida = executar([*comando, imagem, "-c", codigo])
    return json.loads(saida) if anterior is None else None


def implantar(args) -> dict:
    global _SINAIS_ATIVOS, _RECUPERANDO, _FIM_RECUPERACAO
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError(
            "A implantação exige Linux e execução como root; use --validar localmente."
        )
    import fcntl

    anteriores = {s: signal.getsignal(s) for s in (signal.SIGALRM, signal.SIGTERM)}
    try:
        _SINAIS_ATIVOS, _RECUPERANDO = True, False
        _FIM_RECUPERACAO = None
        for numero in anteriores:
            signal.signal(numero, interromper)
        signal.alarm(LIMITE_IMPLANTACAO)
        for programa in ("docker", "aws"):
            if not shutil.which(programa):
                raise RuntimeError(f"Pré-requisito ausente: {programa}.")
        versao = executar(["docker", "compose", "version", "--short"]).strip().lstrip("v")
        if tuple(map(int, versao.split(".")[:3])) < (2, 24, 4):
            raise RuntimeError("Docker Compose 2.24.4 ou superior é necessário.")
        APP_DIR.mkdir(parents=True, exist_ok=True)
        with (APP_DIR / "implantacao.lock").open("a") as trava:
            fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return implantar_travado(args)
    finally:
        signal.alarm(0)
        for numero, handler in anteriores.items():
            signal.signal(numero, handler)
        _SINAIS_ATIVOS, _RECUPERANDO = False, False
        _FIM_RECUPERACAO = None


def implantar_travado(args) -> dict:
    corrente = APP_DIR / "current.json"
    anterior = json.loads(corrente.read_text()) if corrente.exists() else None
    # Compatível com Python 3.9 do host, além do Python 3.11 da aplicação.
    identificador = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")  # noqa: UP017
    pasta = APP_DIR / "releases" / f"{identificador}-{args.revisao[:12]}"
    pasta.mkdir(parents=True)
    estado = {
        "revisao": args.revisao,
        "diretorio": str(pasta),
        "arquivo_env": str(pasta / "implantacao.env"),
        "imagens": {},
    }
    legados, cortado, ponteiro_anterior, temporarios = [], False, None, []
    try:
        limpar_temporarios()
        minimo = MEMORIA_REUSO_MIB if anterior and anterior.get("modelo") else MEMORIA_MINIMA_MIB
        estado["memoria_disponivel_mib"] = verificar_memoria(minimo_mib=minimo)
        url = f"https://github.com/callyafiune/Tech-Challenge-fase-3/archive/{args.revisao}.tar.gz"
        with urllib.request.urlopen(url, timeout=60) as resposta:
            arquivo = resposta.read(32 * 1024 * 1024 + 1)
        if len(arquivo) > 32 * 1024 * 1024:
            raise ValueError("O download das fontes excede 32 MiB.")
        extrair_fontes(io.BytesIO(arquivo), pasta, args.revisao)
        segredo = APP_DIR / "grafana.senha"
        if not segredo.exists():
            with os.fdopen(
                os.open(segredo, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w"
            ) as saida:
                saida.write(secrets.token_urlsafe(36))
        segredo.chmod(0o600)
        senha = segredo.read_text().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", senha):
            raise ValueError("O arquivo persistido da senha Grafana tem formato inválido.")
        registro = args.imagem_runtime.split("/")[0]
        token = executar(["aws", "ecr", "get-login-password", "--region", args.regiao])
        executar(["docker", "login", "--username", "AWS", "--password-stdin", registro], token)
        imagens = {
            "runtime": args.imagem_runtime,
            "treinamento": args.imagem_treinamento,
            "airflow": args.imagem_airflow or (anterior or {}).get("imagens", {}).get("airflow"),
        }
        for perfil, imagem in imagens.items():
            if imagem:
                executar(["docker", "pull", imagem])
                digests = json.loads(executar(["docker", "image", "inspect", imagem]))[0][
                    "RepoDigests"
                ]
                prefixo = registro + "/tech-challenge-fase-3@sha256:"
                estado["imagens"][perfil] = next(d for d in digests if d.startswith(prefixo))
        linhas = [
            f"ECR_{nome}_IMAGE={estado['imagens'][perfil]}"
            for perfil, nome in (
                ("runtime", "RUNTIME"),
                ("treinamento", "TRAINING"),
                ("airflow", "AIRFLOW"),
            )
            if perfil in estado["imagens"]
        ]
        descritor = os.open(estado["arquivo_env"], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descritor, "w") as saida:
            saida.write(
                "\n".join(
                    linhas
                    + [
                        f"GRAFANA_ADMIN_PASSWORD={senha}",
                        "GRAFANA_ADMIN_USER=admin",
                        "API_PORT=8000",
                    ]
                )
            )
        compose(estado, "config", "--quiet")
        compose(estado, "pull", "api", "prometheus", "grafana")
        if estado["imagens"].get("airflow"):
            compose(estado, "config", "--quiet", airflow=True)
        compose(estado, "create", "--no-deps", "pipeline")
        ponteiro_anterior = ponteiro(estado["imagens"]["runtime"])
        minimo = MEMORIA_REUSO_MIB if ponteiro_anterior else MEMORIA_MINIMA_MIB
        estado["memoria_antes_pipeline_mib"] = verificar_memoria(minimo_mib=minimo)
        estado["memoria_minima_pipeline_mib"] = minimo
        treinamento = f"medical-pipeline-{secrets.token_hex(6)}"
        temporarios.append(treinamento)
        try:
            preparo = json.loads(
                compose(
                    estado,
                    "run",
                    "--rm",
                    "--no-deps",
                    "--name",
                    treinamento,
                    "--label",
                    ROTULO_TEMPORARIO,
                    "pipeline",
                )
            )
        finally:
            remover_temporario(treinamento)
        temporarios.remove(treinamento)
        estado["pipeline_reutilizado"] = preparo.get("reutilizado") is True
        estado["modelo_treinado"] = not estado["pipeline_reutilizado"]
        candidato = f"medical-candidato-{secrets.token_hex(6)}"
        temporarios.append(candidato)
        try:
            comando = "docker run -d --read-only --user 10001:10001 --cap-drop ALL".split()
            comando += "--security-opt no-new-privileges --tmpfs /tmp:rw,size=64m,mode=1777".split()
            comando += ["--name", candidato, "-p", "127.0.0.1:18000:8000"]
            comando += ["--label", ROTULO_TEMPORARIO]
            comando += ["-v", f"{PROJETO}_modelos:/app/models:ro", "-e", "MODEL_BACKEND=onnx"]
            comando += ["-e", "MODEL_DIR=/app/models"]
            executar([*comando, estado["imagens"]["runtime"]])
            estado["modelo"] = conferir_api(18000)
            if any(
                preparo.get(tipo, {}).get("versao_modelo") != estado["modelo"]
                for tipo in ("qualidade", "latencia")
            ):
                raise ValueError("O modelo candidato diverge das evidências do pipeline.")
        finally:
            remover_temporario(candidato)
        temporarios.remove(candidato)
        ativos = containers_ativos()
        validar_porta(ativos)
        legados = [
            c["Id"]
            for c in ativos
            if (c["Config"].get("Labels") or {}).get("com.docker.compose.project") == LEGADO
        ]
        estado["politicas_legadas"] = {
            c["Id"]: c["HostConfig"]["RestartPolicy"] for c in ativos if c["Id"] in legados
        }
        for politica in estado["politicas_legadas"].values():
            politica_reinicio(politica)
        if not anterior and any(
            (c["Config"].get("Labels") or {}).get("com.docker.compose.project") == PROJETO
            for c in ativos
        ):
            raise RuntimeError(
                "Há uma fase 3 ativa sem current.json; a restauração não é verificável."
            )
        if anterior:
            gravar_json(APP_DIR / "current-anterior.json", anterior)
        cortado = True
        if legados:
            executar(["docker", "update", "--restart=no", *legados])
            executar(["docker", "stop", *legados])
        compose(estado, "up", "-d", "--no-deps", "api", "prometheus", "grafana")
        if estado["imagens"].get("airflow"):
            compose(estado, "up", "-d", "--no-deps", "airflow", airflow=True)
            esperar("http://127.0.0.1:8080/health", limite_segundos=300)
        if conferir_api(8000) != estado["modelo"]:
            raise ValueError("A API publicada carregou uma versão diferente da candidata.")
        esperar("http://127.0.0.1:9090/-/ready")
        if json.loads(esperar("http://127.0.0.1:3000/api/health")).get("database") != "ok":
            raise ValueError("O Grafana não confirmou a saúde do banco.")
        estado.update(
            sucesso=True,
            versao_modelo=estado["modelo"],
            legados_ativos=legados,
            receipt=str(pasta / "receipt.json"),
        )
        gravar_json(pasta / "receipt.json", estado)
        gravar_json(corrente, estado)
        return estado
    except Exception as erro:
        desarmar_interrupcoes()
        estado.update(
            sucesso=False,
            erro=type(erro).__name__,
            mensagem=str(erro)[:800],
            legados_ativos=legados,
            corte_iniciado=cortado,
            recuperacao_em_andamento=True,
            rollback_concluido=False,
        )
        falhas = []
        try:
            gravar_json(pasta / "receipt.json", estado)
        except OSError as falha:
            falhas.append("recibo inicial: " + type(falha).__name__)
        for nome in temporarios:
            try:
                remover_temporario(nome)
            except Exception as falha:
                falhas.append("temporário: " + type(falha).__name__)
        if anterior and ponteiro_anterior:
            try:
                ponteiro(estado["imagens"]["runtime"], ponteiro_anterior)
            except Exception as falha:
                falhas.append("modelo: " + type(falha).__name__)
        if cortado:
            try:
                restaurar(anterior, estado, legados)
                if anterior and conferir_api(8000) != anterior["modelo"]:
                    raise ValueError("A API restaurada não carregou o modelo anterior.")
            except Exception as falha:
                falhas.append("serviços: " + type(falha).__name__)
        estado.update(
            recuperacao_em_andamento=False,
            rollback_concluido=cortado and not falhas,
            rollback_erros=falhas,
        )
        gravar_json(pasta / "receipt.json", estado)
        raise RuntimeError(f"Implantação falhou; consulte {pasta / 'receipt.json'}.") from erro


def main(argv=None) -> int:
    try:
        args = argumentos(argv)
        resultado = {"sucesso": True, "validado": True, "revisao": args.revisao}
        if not args.validar:
            resultado = implantar(args)
        print(json.dumps(resultado, ensure_ascii=False))
        return 0
    except (Exception, SystemExit) as erro:
        if isinstance(erro, SystemExit) and erro.code == 0:
            return 0
        print(json.dumps({"sucesso": False, "mensagem": str(erro)[:800]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
