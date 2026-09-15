"""Aquisição verificável do corpus e separação sem textos compartilhados."""

import hashlib
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

from medical_classifier.contracts import CLASSES, normalize, sha256

REVISION = "70a2d9106c724729be8b3c4ddb00d1b14ec300c8"
SOURCE = "https://raw.githubusercontent.com/sebischair/Medical-Abstracts-TC-Corpus"


def download_data(directory: Path) -> dict:
    """Baixa arquivos de uma revisão fixa e confere SHA-256 conhecido."""
    manifest = json.loads(Path(__file__).with_name("corpus_manifest.json").read_text("utf-8"))
    directory.mkdir(parents=True, exist_ok=True)
    for name, digest in manifest["sha256"].items():
        target = directory / name
        if not target.exists():
            with urllib.request.urlopen(f"{SOURCE}/{REVISION}/{name}", timeout=120) as response:
                content = response.read()
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError(f"Falha de integridade no download: {name}")
            temporary = target.with_suffix(".download")
            temporary.write_bytes(content)
            temporary.replace(target)
        if sha256(target) != digest:
            raise ValueError(f"Falha de integridade do corpus: {name}")
    return manifest


def read_corpus(path: Path) -> pd.DataFrame:
    """Valida schema, rótulos inteiros e resumos não vazios."""
    data = pd.read_csv(path)
    if set(data.columns) != {"condition_label", "medical_abstract"}:
        raise ValueError("O CSV deve conter condition_label e medical_abstract.")
    labels = data.condition_label
    if labels.isna().any() or not labels.isin(CLASSES).all():
        raise ValueError("O corpus contém rótulo inválido; esperado inteiro entre 1 e 5.")
    if data.medical_abstract.isna().any():
        raise ValueError("O corpus contém texto ausente.")
    if not data.medical_abstract.map(lambda value: isinstance(value, str)).all():
        raise ValueError("O corpus contém texto inválido.")
    data.medical_abstract = data.medical_abstract.map(normalize)
    if data.medical_abstract.str.len().eq(0).any():
        raise ValueError("O corpus contém texto vazio.")
    data.condition_label = labels.astype(int)
    return data


@dataclass
class DatasetSplit:
    """Partições e auditoria usadas no treinamento reproduzível."""

    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    audit: dict


def prepare_data(directory: Path, min_samples: int = 2000, seed: int = 42) -> DatasetSplit:
    """Preserva teste oficial, remove sobreposição e estratifica só o treino."""
    train = read_corpus(directory / "medical_tc_train.csv")
    test = read_corpus(directory / "medical_tc_test.csv")
    original_count = len(train)
    overlap = train.medical_abstract.isin(set(test.medical_abstract))
    train = train.loc[~overlap].copy()
    conflicts = train.groupby("medical_abstract").condition_label.nunique()
    ambiguous = set(conflicts[conflicts > 1].index)
    ambiguous_count = int(train.medical_abstract.isin(ambiguous).sum())
    train = train.loc[~train.medical_abstract.isin(ambiguous)]
    before_dedup = len(train)
    train = train.drop_duplicates("medical_abstract")
    if len(train) < min_samples:
        raise ValueError("O treinamento exige pelo menos 2.000 amostras válidas e únicas.")
    if set(train.condition_label) != set(CLASSES) or set(test.condition_label) != set(CLASSES):
        raise ValueError("Todas as cinco classes devem estar presentes nas partições.")
    fit, validation = train_test_split(
        train, test_size=0.2, stratify=train.condition_label, random_state=seed
    )
    test_counts = test.groupby(["medical_abstract", "condition_label"]).size()
    test_unique_labels = test.groupby("medical_abstract").condition_label.nunique()
    ambiguous_test = set(test_unique_labels[test_unique_labels > 1].index)
    audit = {
        "revisao_corpus": REVISION,
        "semente": seed,
        "treino_original": original_count,
        "teste_oficial": len(test),
        "teste_textos_unicos": int(test.medical_abstract.nunique()),
        "teste_linhas_ambiguas": int(test.medical_abstract.isin(ambiguous_test).sum()),
        "teste_teto_acuracia_deterministica": float(
            test_counts.groupby(level=0).max().sum() / len(test)
        ),
        "sobreposicoes_removidas_treino": int(overlap.sum()),
        "rotulos_conflitantes_removidos": ambiguous_count,
        "duplicatas_removidas_treino": before_dedup - len(train),
        "treino": len(fit),
        "validacao": len(validation),
        "sha256_treino": sha256(directory / "medical_tc_train.csv"),
        "sha256_teste": sha256(directory / "medical_tc_test.csv"),
        "distribuicao_treino": fit.condition_label.value_counts().sort_index().to_dict(),
        "distribuicao_validacao": validation.condition_label.value_counts().sort_index().to_dict(),
        "distribuicao_teste": test.condition_label.value_counts().sort_index().to_dict(),
    }
    return DatasetSplit(fit.reset_index(drop=True), validation.reset_index(drop=True), test, audit)
