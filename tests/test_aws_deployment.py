"""Valida publicação Compose e contratos de implantação sem acessar a AWS."""

import importlib.util
import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

RAIZ = Path(__file__).resolve().parents[1]
REVISAO = "a" * 40
REGIAO = "eu-west-1"
REPOSITORIO = f"076516546831.dkr.ecr.{REGIAO}.amazonaws.com/tech-challenge-fase-3"
IMAGENS = {
    "ECR_RUNTIME_IMAGE": f"{REPOSITORIO}:runtime-{REVISAO}",
    "ECR_TRAINING_IMAGE": f"{REPOSITORIO}:treinamento-{REVISAO}",
    "ECR_AIRFLOW_IMAGE": f"{REPOSITORIO}:airflow-{REVISAO}",
}
ROTULO_TEMPORARIO = "io.github.callyafiune.tech-challenge-fase-3.temporario=ssm"


@pytest.fixture
def docker_compose_cli():
    """Localiza a CLI sem exigir conexão com um daemon Docker."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose é necessário para verificar os manifests de implantação.")
    disponivel = subprocess.run(
        [docker, "compose", "version"], capture_output=True, text=True, timeout=30
    )
    if disponivel.returncode:
        pytest.skip("O plugin Docker Compose não está disponível neste ambiente.")
    return docker


@pytest.fixture
def compose_config(tmp_path, docker_compose_cli):
    """Usa o parser real do Compose, inclusive suas regras de merge e tags de override."""
    docker = docker_compose_cli
    arquivo_env = tmp_path / "vazio.env"
    arquivo_env.write_text("", encoding="utf-8")
    ambiente = {
        chave: valor
        for chave, valor in os.environ.items()
        if not chave.startswith(("ECR_", "COMPOSE_"))
    }
    ambiente.update(
        IMAGENS,
        GRAFANA_ADMIN_PASSWORD="senha-sintetica-de-configuracao",
        API_PORT="18080",
        PROMETHEUS_PORT="19090",
        GRAFANA_PORT="13000",
        AIRFLOW_PORT="18081",
    )

    def carregar(arquivos, ausente=None):
        env = ambiente.copy()
        if ausente is not None:
            env.pop(ausente, None)
        argumentos = [docker, "compose", "--env-file", str(arquivo_env)]
        for arquivo in arquivos:
            argumentos.extend(["-f", str(RAIZ / arquivo)])
        argumentos.extend(["config", "--format", "json"])
        return subprocess.run(
            argumentos,
            cwd=RAIZ,
            env=env,
            capture_output=True,
            encoding="utf-8",
            timeout=30,
        )

    return carregar


def assert_exposicao_principal(configuracao):
    """A única publicação pública deve ser o único bind HTTP da API."""
    servicos = configuracao["services"]
    portas_api = servicos["api"]["ports"]
    assert len(portas_api) == 1, "O override não pode acumular binds local e público da API."
    assert portas_api[0]["host_ip"] == "0.0.0.0"
    assert portas_api[0]["target"] == 8000
    assert portas_api[0]["published"] == "18080"
    publicos = [
        nome
        for nome, servico in servicos.items()
        for porta in servico.get("ports", [])
        if porta.get("host_ip") not in {"127.0.0.1", "::1"}
    ]
    assert publicos == ["api"]
    for nome in ("prometheus", "grafana"):
        assert servicos[nome]["ports"]
        assert all(porta["host_ip"] == "127.0.0.1" for porta in servicos[nome]["ports"])


def test_override_aws_publica_so_api_e_preserva_imagens_e_volumes(compose_config):
    base = compose_config(["docker-compose.yml"])
    mesclado = compose_config(["docker-compose.yml", "docker-compose.aws.yml"])
    assert base.returncode == 0, base.stderr
    assert mesclado.returncode == 0, mesclado.stderr
    original = json.loads(base.stdout)
    configuracao = json.loads(mesclado.stdout)
    assert_exposicao_principal(configuracao)
    for nome, imagem in (("api", "ECR_RUNTIME_IMAGE"), ("pipeline", "ECR_TRAINING_IMAGE")):
        servico = configuracao["services"][nome]
        assert "build" not in servico
        assert servico["image"] == IMAGENS[imagem]
    pipeline = configuracao["services"]["pipeline"]
    assert int(pipeline["mem_limit"]) == 1024**3
    assert int(pipeline["memswap_limit"]) == int(pipeline["mem_limit"])
    assert float(pipeline["cpus"]) == 1.0
    assert configuracao["volumes"] == original["volumes"]
    for nome in ("api", "pipeline", "prometheus", "grafana"):
        assert configuracao["services"][nome]["volumes"] == original["services"][nome]["volumes"]
    modelo_api = next(
        volume
        for volume in configuracao["services"]["api"]["volumes"]
        if volume["target"] == "/app/models"
    )
    assert modelo_api["type"] == "volume"
    assert modelo_api["read_only"] is True


def test_override_airflow_mantem_loopback_e_volumes_da_stack(compose_config):
    base = compose_config(["docker-compose.airflow.yml"])
    mesclado = compose_config(["docker-compose.airflow.yml", "docker-compose.airflow.aws.yml"])
    assert base.returncode == 0, base.stderr
    assert mesclado.returncode == 0, mesclado.stderr
    original = json.loads(base.stdout)
    configuracao = json.loads(mesclado.stdout)
    airflow = configuracao["services"]["airflow"]
    assert "build" not in airflow
    assert airflow["image"] == IMAGENS["ECR_AIRFLOW_IMAGE"]
    assert len(airflow["ports"]) == 1
    assert airflow["ports"][0]["host_ip"] == "127.0.0.1"
    assert airflow["ports"][0]["target"] == 8080
    assert configuracao["volumes"] == original["volumes"]
    assert airflow["volumes"] == original["services"]["airflow"]["volumes"]
    for volume in ("dados", "modelos"):
        assert configuracao["volumes"][volume]["external"] is True
        assert configuracao["volumes"][volume]["name"] == f"medical-classifier_{volume}"


@pytest.mark.parametrize(
    ("arquivos", "ausente"),
    [
        (["docker-compose.yml", "docker-compose.aws.yml"], "ECR_RUNTIME_IMAGE"),
        (["docker-compose.yml", "docker-compose.aws.yml"], "ECR_TRAINING_IMAGE"),
        (["docker-compose.airflow.yml", "docker-compose.airflow.aws.yml"], "ECR_AIRFLOW_IMAGE"),
    ],
)
def test_override_rejeita_imagem_ecr_ausente(compose_config, arquivos, ausente):
    resultado = compose_config(arquivos, ausente=ausente)
    assert resultado.returncode != 0
    assert ausente in resultado.stderr


@pytest.fixture
def implantacao(monkeypatch):
    """Importa a automação como módulo, sem iniciar sua interface de linha de comando."""
    caminho = RAIZ / "scripts/implantar_ec2.py"
    assert caminho.is_file(), "O script de implantação ainda não foi implementado."
    spec = importlib.util.spec_from_file_location("implantar_ec2_em_teste", caminho)
    modulo = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, modulo)
    spec.loader.exec_module(modulo)
    return modulo


def argumentos_validos():
    return [
        "--revisao",
        REVISAO,
        "--imagem-runtime",
        IMAGENS["ECR_RUNTIME_IMAGE"],
        "--imagem-treinamento",
        IMAGENS["ECR_TRAINING_IMAGE"],
        "--regiao",
        REGIAO,
        "--validar",
    ]


@pytest.mark.parametrize("incluir_airflow", [False, True])
def test_validar_cli_nao_exige_credenciais_nem_executa_efeitos(
    implantacao, monkeypatch, capsys, incluir_airflow
):
    def proibido(*args, **kwargs):
        pytest.fail("O modo --validar não pode executar comandos nem criar diretórios.")

    monkeypatch.setattr(implantacao, "executar", proibido)
    monkeypatch.setattr(subprocess, "run", proibido)
    monkeypatch.setattr(socket, "create_connection", proibido)
    monkeypatch.setattr(Path, "mkdir", proibido)
    for chave in list(os.environ):
        if chave.startswith("AWS_"):
            monkeypatch.delenv(chave)
    argumentos = argumentos_validos()
    if incluir_airflow:
        argumentos.extend(["--imagem-airflow", IMAGENS["ECR_AIRFLOW_IMAGE"]])
    assert implantacao.APP_DIR == Path("/opt/tech-challenge-fase-3")
    assert implantacao.main(argumentos) == 0
    resposta = json.loads(capsys.readouterr().out)
    assert resposta["sucesso"] is True
    assert resposta["validado"] is True
    assert resposta["revisao"] == REVISAO


@pytest.mark.parametrize(
    ("opcao", "valor"),
    [
        ("--revisao", "g" * 40),
        ("--revisao", "a" * 39),
        ("--imagem-runtime", ""),
        ("--imagem-treinamento", ""),
        ("--imagem-runtime", IMAGENS["ECR_RUNTIME_IMAGE"].replace("076516546831", "123456789012")),
        ("--imagem-treinamento", IMAGENS["ECR_TRAINING_IMAGE"].replace("eu-west-1", "us-east-1")),
        (
            "--imagem-runtime",
            IMAGENS["ECR_RUNTIME_IMAGE"].replace("tech-challenge-fase-3", "tech-challenge-fase-2"),
        ),
    ],
)
def test_validacao_rejeita_revisao_ou_destino_divergente(implantacao, opcao, valor):
    argumentos = argumentos_validos()
    argumentos[argumentos.index(opcao) + 1] = valor
    with pytest.raises((SystemExit, ValueError)) as falha:
        implantacao.argumentos(argumentos)
    if isinstance(falha.value, SystemExit):
        assert falha.value.code != 0


def test_retorno_inicial_preserva_volumes_e_reativa_legados(implantacao, monkeypatch):
    observados = []
    atual = {
        "diretorio": Path("/opt/tech-challenge-fase-3/releases/atual"),
        "arquivo_env": "novo.env",
    }
    legados = ["container-fase2-um", "container-fase2-dois"]
    monkeypatch.setattr(
        implantacao,
        "compose",
        lambda estado, *opcoes, **kwargs: observados.append(("compose", estado, opcoes, kwargs)),
    )
    monkeypatch.setattr(
        implantacao,
        "executar",
        lambda argumentos, **kwargs: observados.append(("executar", argumentos)),
    )

    implantacao.restaurar(None, atual, legados)

    assert observados[0][0] == "compose"
    assert observados[0][1] is atual
    assert observados[0][2][0] == "down"
    assert not {"-v", "--volumes"}.intersection(observados[0][2])
    reativados = [
        item[1][2:]
        for item in observados
        if item[0] == "executar" and item[1][:2] == ["docker", "start"]
    ]
    assert sorted(nome for grupo in reativados for nome in grupo) == sorted(legados)


def test_retorno_de_atualizacao_restaura_configuracao_anterior_sem_legado(implantacao, monkeypatch):
    observados = []
    anterior = {
        "diretorio": Path("/opt/tech-challenge-fase-3/releases/anterior"),
        "arquivo_env": "anterior.env",
    }
    atual = {
        "diretorio": Path("/opt/tech-challenge-fase-3/releases/atual"),
        "arquivo_env": "novo.env",
    }
    monkeypatch.setattr(
        implantacao,
        "compose",
        lambda estado, *opcoes, **kwargs: observados.append((estado, opcoes, kwargs)),
    )

    def proibir_legado(*args, **kwargs):
        pytest.fail("O retorno de uma atualização não deve reiniciar a aplicação legada.")

    monkeypatch.setattr(implantacao, "executar", proibir_legado)
    implantacao.restaurar(anterior, atual, ["container-legado"])

    restauracoes = [item for item in observados if item[1][0] == "up"]
    assert restauracoes
    assert all(item[0] is anterior for item in restauracoes)
    assert {"api", "prometheus", "grafana"}.issubset(restauracoes[0][1])
    assert not any({"-v", "--volumes"}.intersection(opcoes) for _, opcoes, _ in observados)


def arquivo_fontes(inseguro=None):
    """Produz fontes sintéticas, inclusive um membro malicioso opcional após o arquivo válido."""
    arquivo = io.BytesIO()
    prefixo = f"Tech-Challenge-fase-3-{REVISAO}"
    with tarfile.open(fileobj=arquivo, mode="w:gz") as tar:
        conteudo = b"servico de teste\n"
        fonte = tarfile.TarInfo(f"{prefixo}/src/app.py")
        fonte.size = len(conteudo)
        tar.addfile(fonte, io.BytesIO(conteudo))
        if inseguro == "travessia":
            tar.addfile(tarfile.TarInfo(f"{prefixo}/../fora.txt"), io.BytesIO())
        elif inseguro == "link":
            link = tarfile.TarInfo(f"{prefixo}/src/atalho")
            link.type = tarfile.SYMTYPE
            link.linkname = "../../fora.txt"
            tar.addfile(link)
    arquivo.seek(0)
    return arquivo


@pytest.mark.parametrize("em_memoria", [True, False])
def test_extracao_aceita_arquivo_local_ou_em_memoria(implantacao, tmp_path, em_memoria):
    arquivo = arquivo_fontes()
    if not em_memoria:
        caminho = tmp_path / "fontes.tar.gz"
        caminho.write_bytes(arquivo.getvalue())
        arquivo = caminho
    destino = tmp_path / "release"

    implantacao.extrair_fontes(arquivo, destino, REVISAO)

    assert (destino / "src/app.py").read_bytes() == b"servico de teste\n"


@pytest.mark.parametrize("inseguro", ["travessia", "link"])
def test_extracao_rejeita_travessia_e_link_antes_de_gravar_fontes(implantacao, tmp_path, inseguro):
    destino = tmp_path / "release"
    externo = tmp_path / "fora.txt"
    externo.write_bytes(b"conteudo anterior")

    with pytest.raises(ValueError):
        implantacao.extrair_fontes(arquivo_fontes(inseguro), destino, REVISAO)

    assert not destino.exists(), "Mesmo o membro válido deve aguardar a validação do arquivo todo."
    assert externo.read_bytes() == b"conteudo anterior"


def respostas_api():
    pronta = {"status": "pronto", "backend": "onnx", "versao_modelo": "modelo-sintetico"}
    resposta = {
        "backend": "onnx",
        "versao_modelo": "modelo-sintetico",
        "classe_id": 3,
        "probabilidades": {"1": 0.1, "2": 0.1, "3": 0.6, "4": 0.1, "5": 0.1},
    }
    return pronta, resposta


def test_predicao_aceita_cinco_probabilidades_da_mesma_versao(implantacao):
    pronta, resposta = respostas_api()
    assert implantacao.validar_predicao(pronta, resposta) == "modelo-sintetico"


@pytest.mark.parametrize("invalido", ["versao", "nao_finito", "booleano", "soma"])
def test_predicao_bloqueia_resposta_inconsistente(implantacao, invalido):
    pronta, resposta = respostas_api()
    if invalido == "versao":
        resposta["versao_modelo"] = "outra-versao"
    elif invalido == "nao_finito":
        resposta["probabilidades"]["3"] = float("nan")
    elif invalido == "booleano":
        resposta["probabilidades"] = dict.fromkeys("12345", False)
        resposta["probabilidades"]["3"] = True
    else:
        resposta["probabilidades"]["3"] = 0.5
    with pytest.raises(ValueError):
        implantacao.validar_predicao(pronta, resposta)


@pytest.mark.parametrize("falha_airflow", [False, True])
def test_retorno_tenta_reativar_legado_mesmo_quando_limpeza_falha(
    implantacao, monkeypatch, falha_airflow
):
    observados = []
    atual = {
        "diretorio": Path("/opt/tech-challenge-fase-3/releases/atual"),
        "arquivo_env": "novo.env",
        "imagens": {"airflow": IMAGENS["ECR_AIRFLOW_IMAGE"] if falha_airflow else None},
    }
    legados = ["container-fase2-um", "container-fase2-dois"]

    def falhar_na_limpeza(estado, *opcoes, airflow=False):
        assert not {"-v", "--volumes"}.intersection(opcoes)
        if opcoes[0] == "down" and airflow == falha_airflow:
            raise RuntimeError("Falha sintética de limpeza do Compose.")
        return ""

    monkeypatch.setattr(implantacao, "compose", falhar_na_limpeza)
    monkeypatch.setattr(implantacao, "executar", lambda comando: observados.append(comando))

    with pytest.raises(RuntimeError):
        implantacao.restaurar(None, atual, legados)

    assert ["docker", "start", *legados] in observados


VERIFICAR_PERMISSOES_LINUX = r"""
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile

spec = importlib.util.spec_from_file_location("implantacao", sys.argv[1])
implantacao = importlib.util.module_from_spec(spec)
spec.loader.exec_module(implantacao)
with tempfile.TemporaryDirectory() as temporario:
    raiz = Path(temporario)
    raiz.chmod(0o755)
    destino = raiz / "release"
    revisao = "a" * 40
    arquivo = io.BytesIO()
    with tarfile.open(fileobj=arquivo, mode="w:gz") as tar:
        conteudo = b"scrape_configs: []\n"
        item = tarfile.TarInfo(f"Tech-Challenge-fase-3-{revisao}/monitoring/prometheus.yml")
        item.size = len(conteudo)
        tar.addfile(item, io.BytesIO(conteudo))
    arquivo.seek(0)
    anterior = os.umask(0o077)
    try:
        destino.mkdir()
        implantacao.extrair_fontes(arquivo, destino, revisao)
    finally:
        os.umask(anterior)
    fonte = destino / "monitoring/prometheus.yml"
    modos = {str(p.relative_to(raiz)): stat.S_IMODE(p.stat().st_mode)
             for p in [destino, fonte.parent, fonte]}
    assert modos == {"release": 0o755, "release/monitoring": 0o755,
                     "release/monitoring/prometheus.yml": 0o644}, modos
    usuarios = []
    if os.geteuid() == 0:
        for uid in (472, 65534):
            ler = "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text())"
            resposta = subprocess.run(
                [sys.executable, "-c", ler, str(fonte)],
                user=uid, group=uid, extra_groups=[], capture_output=True, text=True,
            )
            assert resposta.returncode == 0, resposta.stderr
            assert "scrape_configs" in resposta.stdout
            usuarios.append(uid)
    print(json.dumps({"modos": modos, "usuarios_que_leram": usuarios}))
"""


@pytest.mark.skipif(os.name != "posix", reason="Permissões POSIX exigem Linux ou ensaio Docker.")
def test_extracao_sob_umask_restritiva_mantem_configuracoes_legiveis():
    resultado = subprocess.run(
        [sys.executable, "-c", VERIFICAR_PERMISSOES_LINUX, str(RAIZ / "scripts/implantar_ec2.py")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert resultado.returncode == 0, resultado.stderr


@pytest.fixture
def ambiente_implantacao(implantacao, monkeypatch, tmp_path):
    """Simula apenas fronteiras externas e observa a transação real de implantação."""
    eventos = []
    temporarios = set()
    rotulos = {}
    handlers = {}
    memoria = tmp_path / "meminfo"
    memoria.write_text("MemTotal: 4194304 kB\nMemAvailable: 3145728 kB\n", encoding="utf-8")
    raiz = tmp_path / "host"
    raiz.mkdir()
    legado = {
        "Id": "fase2-api",
        "Config": {"Labels": {"com.docker.compose.project": "tech-challenge-fase-2"}},
        "HostConfig": {"RestartPolicy": {"Name": "on-failure", "MaximumRetryCount": 5}},
        "NetworkSettings": {"Ports": {"8000/tcp": [{"HostPort": "8000"}]}},
    }
    contexto = SimpleNamespace(
        eventos=eventos,
        temporarios=temporarios,
        rotulos=rotulos,
        handlers=handlers,
        memoria=memoria,
        raiz=raiz,
        falha=None,
        falha_disparada=False,
        legado=legado,
        ativos=[legado],
        versao_compose="2.24.4",
        memoria_apos_limpeza=None,
        incluir_airflow=False,
        recibos_antes_restauracao=[],
    )

    def falhar(etapa):
        if contexto.falha == (etapa, "timeout"):
            contexto.falha_disparada = True
            raise subprocess.TimeoutExpired(etapa, 1800)
        for motivo, numero in (("sigterm", signal.SIGTERM), ("sigalrm", signal.SIGALRM)):
            if contexto.falha == (etapa, motivo):
                assert numero in handlers, "A implantação precisa tratar sinais de encerramento."
                contexto.falha_disparada = True
                handlers[numero](numero, None)

    def executar(comando, entrada=None):
        eventos.append(("comando", comando))
        if comando[:4] == ["docker", "compose", "version", "--short"]:
            return contexto.versao_compose
        if comando[:2] == ["aws", "ecr"]:
            return "token-sintetico"
        if comando[:3] == ["docker", "image", "inspect"]:
            digest = comando[3] if "@sha256:" in comando[3] else f"{REPOSITORIO}@sha256:{'b' * 64}"
            return json.dumps([{"RepoDigests": [digest]}])
        if comando[:2] == ["docker", "compose"]:
            operacoes = comando[comando.index("-f", comando.index("-f") + 1) + 2 :]
            if operacoes[0] == "run":
                assert "--name" in operacoes, (
                    "O pipeline precisa de nome para limpeza após timeout."
                )
                registrar_container(operacoes)
                eventos.append(("pipeline", None))
                falhar("pipeline")
                return json.dumps(
                    {
                        "reutilizado": True,
                        "qualidade": {"versao_modelo": "modelo-novo"},
                        "latencia": {"versao_modelo": "modelo-novo"},
                    }
                )
            if operacoes[0] == "down":
                recibos = list(raiz.glob("releases/*/receipt.json"))
                contexto.recibos_antes_restauracao.extend(
                    json.loads(arquivo.read_text(encoding="utf-8")) for arquivo in recibos
                )
            return ""
        if comando[:2] == ["docker", "run"] and "--name" in comando:
            registrar_container(comando)
        if comando[:2] == ["docker", "ps"]:
            filtros = [comando[i + 1] for i, valor in enumerate(comando) if valor == "--filter"]
            selecionados = set(temporarios)
            for filtro in filtros:
                if filtro.startswith("name="):
                    selecionados = {
                        nome for nome in selecionados if re.search(filtro[5:], f"/{nome}")
                    }
                elif filtro.startswith("label="):
                    selecionados = {
                        nome for nome in selecionados if filtro[6:] in rotulos.get(nome, [])
                    }
                else:
                    pytest.fail(f"Filtro Docker não suportado pelo cenário: {filtro}")
            return "\n".join(sorted(selecionados))
        if comando[:3] == ["docker", "rm", "-f"]:
            temporarios.difference_update(comando[3:])
            if contexto.memoria_apos_limpeza is not None:
                memoria.write_text(contexto.memoria_apos_limpeza, encoding="utf-8")
        return ""

    def registrar_container(comando):
        nome = comando[comando.index("--name") + 1]
        temporarios.add(nome)
        rotulos[nome] = [comando[i + 1] for i, valor in enumerate(comando) if valor == "--label"]

    def conferir_api(porta):
        eventos.append(("api", porta))
        falhar("candidato" if porta == 18000 else "publicada")
        return "modelo-novo"

    def ler_ponteiro(imagem, anterior=None):
        eventos.append(("ponteiro", anterior))
        return {"versao": "modelo-anterior"}

    def baixar_fontes(*args, **kwargs):
        eventos.append(("download", None))
        return arquivo_fontes()

    def esperar(url, limite_segundos=180):
        eventos.append(("esperar", (url, limite_segundos)))
        return b'{"database":"ok"}'

    monkeypatch.setattr(implantacao, "APP_DIR", raiz)
    monkeypatch.setattr(implantacao, "executar", executar)
    monkeypatch.setattr(implantacao, "conferir_api", conferir_api)
    monkeypatch.setattr(implantacao, "ponteiro", ler_ponteiro)
    monkeypatch.setattr(implantacao, "containers_ativos", lambda: contexto.ativos)
    monkeypatch.setattr(implantacao, "esperar", esperar)
    monkeypatch.setattr(implantacao.urllib.request, "urlopen", baixar_fontes)
    monkeypatch.setattr(implantacao.shutil, "which", lambda nome: nome)
    monkeypatch.setattr(implantacao.sys, "platform", "linux")
    monkeypatch.setattr(implantacao.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setitem(
        sys.modules, "fcntl", SimpleNamespace(flock=lambda *a: None, LOCK_EX=2, LOCK_NB=4)
    )
    monkeypatch.setattr(signal, "SIGALRM", 14, raising=False)
    monkeypatch.setattr(signal, "alarm", lambda *a: 0, raising=False)
    monkeypatch.setattr(
        signal, "signal", lambda numero, handler: handlers.__setitem__(numero, handler)
    )
    if hasattr(implantacao, "verificar_memoria"):
        verificar = implantacao.verificar_memoria
        monkeypatch.setattr(
            implantacao, "verificar_memoria", lambda **opcoes: verificar(memoria, **opcoes)
        )

    def implantar():
        argumentos = argumentos_validos()
        if contexto.incluir_airflow:
            argumentos.extend(["--imagem-airflow", IMAGENS["ECR_AIRFLOW_IMAGE"]])
        return implantacao.implantar(implantacao.argumentos(argumentos))

    contexto.executar = implantar
    return contexto


def comandos_observados(ambiente):
    return [valor for evento, valor in ambiente.eventos if evento == "comando"]


def test_comando_create_gerado_pela_implantacao_e_aceito_pela_cli_real(
    docker_compose_cli, ambiente_implantacao
):
    """--help valida as opções do comando capturado sem criar containers nem usar o daemon."""
    ambiente = ambiente_implantacao
    assert ambiente.executar()["sucesso"] is True
    comandos = [
        comando
        for comando in comandos_observados(ambiente)
        if comando[:2] == ["docker", "compose"] and "create" in comando
    ]
    assert comandos, "A preparação do volume deve gerar um comando Compose create."
    env = os.environ.copy()
    for variavel in ("DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        env.pop(variavel, None)
    env["DOCKER_HOST"] = "tcp://127.0.0.1:1"
    for comando in comandos:
        resultado = subprocess.run(
            [docker_compose_cli, *comando[1:], "--help"],
            capture_output=True,
            encoding="utf-8",
            env=env,
            timeout=30,
        )
        assert resultado.returncode == 0, resultado.stderr


def test_memoria_insuficiente_aborta_antes_de_pull_treino_ou_corte(ambiente_implantacao):
    ambiente = ambiente_implantacao
    ambiente.memoria.write_text("MemTotal: 4194304 kB\nMemAvailable: 524288 kB\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        ambiente.executar()
    comandos = comandos_observados(ambiente)
    assert not any(
        comando[0] == "aws"
        or (comando[0] == "docker" and comando[1] in {"pull", "run", "update", "stop", "start"})
        or (comando[:2] == ["docker", "compose"] and "version" not in comando)
        for comando in comandos
    )
    assert not ambiente.temporarios
    assert ("download", None) not in ambiente.eventos
    assert not (ambiente.raiz / "current.json").exists()


def test_corte_so_acontece_apos_candidato_e_desativa_reinicio_do_legado(ambiente_implantacao):
    ambiente = ambiente_implantacao
    resultado = ambiente.executar()
    assert resultado["sucesso"] is True
    assert resultado["airflow_herdado"] is False
    comandos = comandos_observados(ambiente)
    desativar = ["docker", "update", "--restart=no", "fase2-api"]
    parar = ["docker", "stop", "fase2-api"]
    assert comandos.index(desativar) < comandos.index(parar)
    assert ambiente.eventos.index(("api", 18000)) < ambiente.eventos.index(("comando", parar))
    assert (
        resultado["politicas_legadas"]["fase2-api"]
        == ambiente.legado["HostConfig"]["RestartPolicy"]
    )
    assert not ambiente.temporarios


@pytest.mark.parametrize(
    ("etapa", "motivo"),
    [
        ("pipeline", "timeout"),
        ("pipeline", "sigalrm"),
        ("candidato", "sigterm"),
        ("publicada", "sigterm"),
    ],
)
def test_interrupcao_limpa_temporarios_e_recupera_legado_apos_corte(
    ambiente_implantacao, etapa, motivo
):
    ambiente = ambiente_implantacao
    ambiente.falha = (etapa, motivo)
    with pytest.raises(RuntimeError):
        ambiente.executar()
    assert ambiente.falha_disparada, "A execução precisa atingir a interrupção simulada."
    comandos = comandos_observados(ambiente)
    assert not ambiente.temporarios, (
        "Nenhum pipeline ou candidato desta transação pode ficar ativo."
    )
    assert not (ambiente.raiz / "current.json").exists()
    recibos = list(ambiente.raiz.glob("releases/*/receipt.json"))
    assert len(recibos) == 1
    recibo = json.loads(recibos[0].read_text(encoding="utf-8"))
    assert recibo["sucesso"] is False
    assert recibo["erro"] == ("TimeoutExpired" if motivo == "timeout" else "InterrupcaoImplantacao")
    if etapa == "publicada":
        restaurar = ["docker", "update", "--restart=on-failure:5", "fase2-api"]
        reiniciar = ["docker", "start", "fase2-api"]
        assert comandos.index(restaurar) < comandos.index(reiniciar)
        assert recibo["rollback_concluido"] is True
        assert ambiente.recibos_antes_restauracao
        assert ambiente.recibos_antes_restauracao[0]["recuperacao_em_andamento"] is True
        assert ambiente.recibos_antes_restauracao[0]["rollback_concluido"] is False
    else:
        assert not any(comando[:2] == ["docker", "stop"] for comando in comandos)


def test_retorno_aceita_politica_legada_vazia_e_restaura_sem_reinicio(ambiente_implantacao):
    ambiente = ambiente_implantacao
    ambiente.legado["HostConfig"]["RestartPolicy"] = {"Name": "", "MaximumRetryCount": 0}
    ambiente.falha = ("publicada", "sigterm")

    with pytest.raises(RuntimeError):
        ambiente.executar()

    assert ambiente.falha_disparada, "A política vazia não pode impedir a primeira implantação."
    comandos = comandos_observados(ambiente)
    alterar = ["docker", "update", "--restart=no", "fase2-api"]
    assert comandos.count(alterar) == 2
    ultima_alteracao = max(i for i, comando in enumerate(comandos) if comando == alterar)
    assert ultima_alteracao < comandos.index(["docker", "start", "fase2-api"])


def test_limpeza_inicial_libera_orfaos_antes_preflight_e_preserva_outros_containers(
    ambiente_implantacao,
):
    ambiente = ambiente_implantacao
    nosso = "medical-candidato-0123456789ab"
    alheio = "medical-candidato-abcdef012345"
    ambiente.temporarios.update([nosso, alheio, "servico-de-outro-projeto"])
    ambiente.rotulos[nosso] = [ROTULO_TEMPORARIO]
    ambiente.rotulos[alheio] = ["proprietario=outro"]
    ambiente.memoria.write_text("MemAvailable: 524288 kB\n", encoding="utf-8")
    ambiente.memoria_apos_limpeza = "MemAvailable: 3145728 kB\n"

    resultado = ambiente.executar()

    assert resultado["sucesso"] is True
    assert ambiente.temporarios == {alheio, "servico-de-outro-projeto"}
    remocoes = [c for c in comandos_observados(ambiente) if c[:3] == ["docker", "rm", "-f"]]
    assert remocoes[0][3:] == [nosso]
    assert ambiente.eventos.index(("comando", remocoes[0])) < ambiente.eventos.index(
        ("download", None)
    )
    assert all(
        alheio not in comando and "servico-de-outro-projeto" not in comando for comando in remocoes
    )


def test_airflow_recebe_orcamento_de_partida_compativel_com_healthcheck(ambiente_implantacao):
    ambiente = ambiente_implantacao
    ambiente.incluir_airflow = True
    resultado = ambiente.executar()
    assert resultado["sucesso"] is True
    assert ("esperar", ("http://127.0.0.1:8080/health", 300)) in ambiente.eventos


def test_deadline_recuperacao_decresce_e_nao_renova_ao_desarmar(implantacao, monkeypatch):
    relogio = [100.0]
    timeouts = []

    def executar(comando, **opcoes):
        timeouts.append(opcoes["timeout"])
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(implantacao.time, "monotonic", lambda: relogio[0])
    monkeypatch.setattr(implantacao.subprocess, "run", executar)
    implantacao.desarmar_interrupcoes()
    relogio[0] += 500
    implantacao.executar(["docker", "version"])
    relogio[0] += 15
    implantacao.desarmar_interrupcoes()
    implantacao.executar(["docker", "version"])
    relogio[0] += 25
    with pytest.raises(RuntimeError):
        implantacao.executar(["docker", "version"])
    assert timeouts == pytest.approx([40, 25])


def test_espera_http_respeita_prazo_restante_da_recuperacao(implantacao, monkeypatch):
    relogio = [100.0]

    def indisponivel(url):
        raise OSError("Serviço indisponível no cenário sintético.")

    def avancar(segundos):
        relogio[0] += segundos

    monkeypatch.setattr(implantacao.time, "monotonic", lambda: relogio[0])
    monkeypatch.setattr(implantacao.time, "sleep", avancar)
    monkeypatch.setattr(implantacao, "consultar", indisponivel)
    implantacao.desarmar_interrupcoes()
    relogio[0] += 537
    with pytest.raises(RuntimeError):
        implantacao.esperar("http://servico-sintetico/ready")
    assert relogio[0] <= 640


def estado_anterior(ambiente):
    """Representa uma fase 3 publicada, com digest Airflow rastreável da revisão anterior."""
    estado = {
        "diretorio": str(ambiente.raiz / "releases/anterior"),
        "arquivo_env": str(ambiente.raiz / "releases/anterior/implantacao.env"),
        "modelo": "modelo-anterior",
        "imagens": {"airflow": f"{REPOSITORIO}@sha256:{'c' * 64}"},
    }
    (ambiente.raiz / "current.json").write_text(json.dumps(estado), encoding="utf-8")
    return estado


@pytest.mark.parametrize("explicito", [False, True])
def test_recibo_distingue_airflow_herdado_de_imagem_solicitada(ambiente_implantacao, explicito):
    ambiente = ambiente_implantacao
    anterior = estado_anterior(ambiente)
    ambiente.ativos = [
        {
            **ambiente.legado,
            "Id": "fase3-api",
            "Config": {"Labels": {"com.docker.compose.project": "medical-classifier"}},
        }
    ]
    ambiente.incluir_airflow = explicito

    resultado = ambiente.executar()

    assert resultado["sucesso"] is True
    assert resultado["airflow_herdado"] is (not explicito)
    esperado = f"{REPOSITORIO}@sha256:{'b' * 64}" if explicito else anterior["imagens"]["airflow"]
    assert resultado["imagens"]["airflow"] == esperado
    recibo = json.loads(Path(resultado["receipt"]).read_text(encoding="utf-8"))
    assert recibo["airflow_herdado"] is (not explicito)


def test_estado_fase3_com_legado_ativo_aborta_antes_de_mudar_servicos(ambiente_implantacao):
    ambiente = ambiente_implantacao
    estado_anterior(ambiente)
    corrente = ambiente.raiz / "current.json"
    conteudo_anterior = corrente.read_bytes()

    with pytest.raises(RuntimeError) as falha:
        ambiente.executar()

    assert "legados ativos" in str(falha.value.__cause__)
    comandos = comandos_observados(ambiente)
    assert not any(
        comando[:2] in (["docker", "stop"], ["docker", "update"]) for comando in comandos
    )
    assert not any(comando[:2] == ["docker", "compose"] and "up" in comando for comando in comandos)
    assert ("api", 8000) not in ambiente.eventos
    assert corrente.read_bytes() == conteudo_anterior
    assert not ambiente.temporarios


def test_compose_com_sufixo_de_distribuicao_permite_implantacao(ambiente_implantacao):
    ambiente = ambiente_implantacao
    ambiente.versao_compose = "v2.24.4+ds1"
    assert ambiente.executar()["sucesso"] is True


@pytest.mark.parametrize(
    ("versao", "mensagem"),
    [("2.24.3+ds1", "2.24.4"), ("versao-desconhecida", "não é reconhecida")],
)
def test_compose_incompativel_aborta_antes_do_download(ambiente_implantacao, versao, mensagem):
    ambiente = ambiente_implantacao
    ambiente.versao_compose = versao
    with pytest.raises(RuntimeError, match=mensagem):
        ambiente.executar()
    assert ("download", None) not in ambiente.eventos
