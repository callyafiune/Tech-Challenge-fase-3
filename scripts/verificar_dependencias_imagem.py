"""Verifica o perfil instalado e emite inventário JSON, inclusive por stdin.

Exige packaging, dependência declarada do ONNX Runtime e fixada no lock de runtime.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import importlib.metadata
import json
import platform
import sys
from collections import deque
from typing import Any

PACOTE = "medical-classifier"
DESENVOLVIMENTO = {"pytest", "ruff", "pyyaml", "hatchling", "httpx", "pip", "setuptools", "wheel"}
TREINAMENTO = {
    "scikit-learn",
    "pandas",
    "joblib",
    "onnx",
    "skl2onnx",
    "threadpoolctl",
    "scipy",
    "ml-dtypes",
}
IMPORTS_BASE = [
    "fastapi",
    "uvicorn",
    "prometheus_client",
    "numpy",
    "onnxruntime",
    "medical_classifier.api",
]
IMPORTS_TREINAMENTO = [
    "sklearn",
    "pandas",
    "joblib",
    "onnx",
    "skl2onnx",
    "threadpoolctl",
    "medical_classifier.training",
    "medical_classifier.pipeline",
]


def verificar(perfil: str) -> dict[str, Any]:
    """Calcula o fechamento dos requisitos, incluindo marcadores e extras transitivos."""
    from packaging.markers import default_environment
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.specifiers import InvalidSpecifier, SpecifierSet
    from packaging.utils import canonicalize_name
    from packaging.version import InvalidVersion, Version

    erros: list[str] = []
    instalados = {}
    for distribuicao in importlib.metadata.distributions():
        nome_original = distribuicao.metadata.get("Name")
        if not nome_original:
            erros.append("Distribuição instalada sem nome nos metadados.")
            continue
        nome = canonicalize_name(nome_original)
        if nome in instalados:
            erros.append(f"Distribuição duplicada no ambiente: {nome}.")
        instalados[nome] = distribuicao

    extras = {PACOTE: {"treinamento"} if perfil == "treinamento" else set()}
    pendentes = deque([PACOTE])
    processados = {}
    fechamento: set[str] = set()
    ambiente = default_environment()
    while pendentes:
        nome = pendentes.popleft()
        ativos = extras[nome]
        if processados.get(nome) == ativos:
            continue
        processados[nome] = set(ativos)
        fechamento.add(nome)
        distribuicao = instalados.get(nome)
        if distribuicao is None:
            erros.append(f"Dependência obrigatória ausente: {nome}.")
            continue
        python_requerido = distribuicao.metadata.get("Requires-Python")
        if python_requerido:
            try:
                if not SpecifierSet(python_requerido).contains(
                    ambiente["python_full_version"], prereleases=True
                ):
                    erros.append(f"{nome} exige Python {python_requerido}.")
            except InvalidSpecifier:
                erros.append(f"Requisito de Python inválido nos metadados de {nome}.")
        declarados = {
            canonicalize_name(extra)
            for extra in distribuicao.metadata.get_all("Provides-Extra", [])
        }
        for extra in sorted(ativos - declarados):
            erros.append(f"O pacote {nome} não declara o extra solicitado {extra}.")
        for texto in distribuicao.requires or []:
            try:
                requisito = Requirement(texto)
            except InvalidRequirement:
                erros.append(f"Requisito inválido nos metadados de {nome}: {texto}.")
                continue
            # A instalação base permanece ativa; extras acrescentam dependências.
            if requisito.marker is not None and not any(
                requisito.marker.evaluate({**ambiente, "extra": extra}) for extra in {"", *ativos}
            ):
                continue
            dependencia = canonicalize_name(requisito.name)
            encontrada = instalados.get(dependencia)
            if encontrada is not None:
                try:
                    versao = Version(encontrada.version)
                    if not requisito.specifier.contains(versao, prereleases=True):
                        erros.append(
                            f"{nome} exige {requisito}; {dependencia} instalado: {versao}."
                        )
                except InvalidVersion:
                    erros.append(f"Versão inválida nos metadados de {dependencia}.")
            if requisito.url:
                erros.append(
                    f"Referência direta em {nome} não pode ser validada por versão: {requisito}."
                )
            solicitados = {canonicalize_name(extra) for extra in requisito.extras}
            if dependencia not in extras:
                extras[dependencia] = solicitados
                pendentes.append(dependencia)
            elif not solicitados <= extras[dependencia]:
                extras[dependencia].update(solicitados)
                pendentes.append(dependencia)

    fora = sorted(set(instalados) - fechamento)
    proibidos = sorted(
        set(instalados) & (DESENVOLVIMENTO | (TREINAMENTO if perfil == "runtime" else set()))
    )
    if fora:
        erros.append("Pacotes fora do fechamento do perfil: " + ", ".join(fora) + ".")
    if proibidos:
        erros.append("Pacotes proibidos neste perfil: " + ", ".join(proibidos) + ".")
    imports = []
    for modulo in IMPORTS_BASE + (IMPORTS_TREINAMENTO if perfil == "treinamento" else []):
        try:
            # Bibliotecas não podem intercalar mensagens com o documento JSON de stdout.
            with contextlib.redirect_stdout(sys.stderr):
                importlib.import_module(modulo)
            imports.append({"modulo": modulo, "sucesso": True})
        except Exception as erro:
            descricao = f"Falha ao importar {modulo}: {type(erro).__name__}: {erro}"
            erros.append(descricao)
            imports.append({"modulo": modulo, "sucesso": False, "erro": descricao})
    return {
        "sucesso": not erros,
        "perfil": perfil,
        "python": {"versao": platform.python_version(), "executavel": sys.executable},
        "pacotes": [
            {"nome": nome, "versao": distribuicao.version}
            for nome, distribuicao in sorted(instalados.items())
        ],
        "fechamento": sorted(fechamento),
        "extras_ativados": {
            nome: sorted(ativos) for nome, ativos in sorted(extras.items()) if ativos
        },
        "fora_do_fechamento": fora,
        "proibidos_presentes": proibidos,
        "imports": imports,
        "erros": sorted(set(erros)),
    }


def main() -> int:
    """Retorna código diferente de zero se o perfil ou algum import estiver incorreto."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--perfil", choices=["runtime", "treinamento"], required=True)
    argumentos = parser.parse_args()
    try:
        resultado = verificar(argumentos.perfil)
    except Exception as erro:
        resultado = {
            "sucesso": False,
            "perfil": argumentos.perfil,
            "erros": [f"Verificação interrompida: {type(erro).__name__}: {erro}"],
        }
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0 if resultado["sucesso"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
