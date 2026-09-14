"""Executa etapas isoladas do retreino com estado persistido por execução."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path


def _save(path: Path, content: str) -> None:
    """Substitui o estado atomicamente para tolerar interrupções durante a escrita."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _release(state: Path, models: Path) -> Path:
    """Aceita apenas uma versão diretamente contida no diretório dos modelos."""
    pointer = state / "release.txt"
    if not pointer.is_file():
        raise ValueError("Não há versão registrada; execute o treinamento desta execução primeiro.")
    release = Path(pointer.read_text("utf-8").strip()).resolve()
    if release.parent != models.resolve() / "releases":
        raise ValueError("A versão registrada está fora do diretório dos modelos.")
    if not release.is_dir():
        raise ValueError("A versão registrada não existe; execute o treinamento novamente.")
    return release


def _require_approval(result: dict) -> None:
    """Exige aprovação explícita, sem tratar retorno vazio ou falso como sucesso."""
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("qualidade"), dict)
        or result["qualidade"].get("aprovado") is not True
    ):
        raise ValueError("Publicação bloqueada: a validação não aprovou explicitamente a versão.")


def execute_step(step: str, execution: str, data: Path, models: Path) -> dict:
    """Executa uma etapa e impede publicar uma versão sem validação desta execução."""
    if not re.fullmatch(r"\d{8}T\d{6}", execution):
        raise ValueError("Identificador de execução inválido; use AAAAMMDDTHHMMSS.")
    try:
        datetime.strptime(execution, "%Y%m%dT%H%M%S")
    except ValueError:
        raise ValueError("Data do identificador de execução inválida.") from None
    if step not in {"ingestao", "treinamento", "validacao", "publicacao"}:
        raise ValueError("Etapa de retreino desconhecida.")

    # Os módulos de aprendizado são carregados só na execução, nunca no parse da DAG.
    from medical_classifier import pipeline, training

    state = data.resolve() / "runs" / execution
    state.mkdir(parents=True, exist_ok=True)
    prepared = state / "prepared"
    approval = state / "validacao.json"
    pointer = state / "release.txt"
    if step in {"ingestao", "treinamento", "validacao"}:
        approval.unlink(missing_ok=True)

    if step == "ingestao":
        pointer.unlink(missing_ok=True)
        pipeline.ingest(state / "raw", prepared)
    elif step == "treinamento":
        pointer.unlink(missing_ok=True)
        release = Path(pipeline.train(prepared, models)).resolve()
        if release.parent != models.resolve() / "releases":
            raise ValueError("O treinamento retornou uma versão fora do diretório dos modelos.")
        _save(pointer, str(release) + "\n")
    elif step == "validacao":
        release = _release(state, models)
        result = pipeline.validate(release, prepared, state / "reports")
        _require_approval(result)
        _save(
            approval,
            json.dumps(
                {"release": str(release), "resultado": result}, ensure_ascii=False, allow_nan=False
            ),
        )
    else:
        release = _release(state, models)
        if not approval.is_file():
            raise ValueError("Publicação bloqueada: falta a validação desta execução.")
        validation = json.loads(approval.read_text("utf-8"))
        if validation.get("release") != str(release):
            raise ValueError("Publicação bloqueada: a validação pertence a outra versão.")
        _require_approval(validation.get("resultado"))
        training.promote_release(release, models)
    return {"etapa": step, "execucao": execution, "estado": str(state), "sucesso": True}


def main(argv: list[str] | None = None) -> None:
    """Expõe a mesma interface para operadores Airflow e execução manual."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("etapa", choices=["ingestao", "treinamento", "validacao", "publicacao"])
    parser.add_argument("--execucao", required=True, help="Identificador AAAAMMDDTHHMMSS.")
    parser.add_argument("--dados", type=Path, default=Path(os.getenv("MEDICAL_DATA_DIR", "data")))
    parser.add_argument("--modelos", type=Path, default=Path(os.getenv("MODEL_DIR", "models")))
    args = parser.parse_args(argv)
    result = execute_step(args.etapa, args.execucao, args.dados, args.modelos)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
