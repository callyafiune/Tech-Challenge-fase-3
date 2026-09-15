"""Classes, normalização e integridade compartilhadas sem dependências de treinamento."""

import hashlib
import re
from pathlib import Path

CLASSES = {
    1: "Neoplasias",
    2: "Doenças do sistema digestivo",
    3: "Doenças do sistema nervoso",
    4: "Doenças cardiovasculares",
    5: "Condições patológicas gerais",
}


def sha256(path: Path) -> str:
    """Calcula a impressão digital de um arquivo."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text: str) -> str:
    """Unifica caixa e espaços antes da vetorização e da auditoria."""
    return re.sub(r"\s+", " ", text.lower()).strip()
