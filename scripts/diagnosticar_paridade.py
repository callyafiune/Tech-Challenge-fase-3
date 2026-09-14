"""Investiga a paridade por camada e preserva candidatos sem publicar modelos."""

from __future__ import annotations

import argparse
import json
import platform
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
import onnx
import onnxruntime as ort
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType, StringTensorType
from threadpoolctl import threadpool_info, threadpool_limits

from medical_classifier.data import download_data, normalize, prepare_data, sha256
from medical_classifier.training import _fit_bundle


def ambiente() -> dict:
    """Registra versões e capacidades da CPU, sem copiar o ambiente do processo."""
    cpu = {}
    arquivo = Path("/proc/cpuinfo")
    if arquivo.is_file():
        campos = {"vendor_id", "model name", "cpu family", "model", "stepping", "flags"}
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            chave, separador, valor = linha.partition(":")
            if separador and chave.strip() in campos:
                cpu.setdefault(chave.strip(), valor.strip())
    return {
        "python": platform.python_version(),
        "sistema": platform.system(),
        "arquitetura": platform.machine(),
        "processador": platform.processor(),
        "cpu": cpu,
        "dependencias": {
            nome: version(nome)
            for nome in ("numpy", "scipy", "scikit-learn", "onnx", "onnxruntime", "skl2onnx")
        },
        "bibliotecas_numericas": [
            {
                chave: biblioteca.get(chave)
                for chave in ("internal_api", "version", "num_threads", "architecture")
            }
            for biblioteca in threadpool_info()
        ],
    }


def executar(grafo: onnx.ModelProto, entradas: np.ndarray, otimizar: bool = True) -> list:
    """Executa lotes iguais aos do gate, com uma thread nativa."""
    opcoes = ort.SessionOptions()
    opcoes.intra_op_num_threads = 1
    opcoes.graph_optimization_level = (
        ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if otimizar
        else ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    )
    sessao = ort.InferenceSession(
        grafo.SerializeToString(), sess_options=opcoes, providers=["CPUExecutionProvider"]
    )
    nome = sessao.get_inputs()[0].name
    lotes = [sessao.run(None, {nome: entradas[i : i + 64]}) for i in range(0, len(entradas), 64)]
    return [np.concatenate([lote[i] for lote in lotes]) for i in range(len(lotes[0]))]


def resumir(referencia: np.ndarray, observado: np.ndarray) -> dict:
    """Compara números e registra a pior linha sem incluir seu texto."""
    diferenca = np.abs(referencia - observado)
    finitos = np.isfinite(diferenca)
    indice = np.unravel_index(np.where(finitos, diferenca, np.inf).argmax(), diferenca.shape)
    linha = int(indice[0])
    return {
        "erro_maximo": float(diferenca.max()) if finitos.all() else None,
        "valores_nao_finitos": int((~np.isfinite(observado)).sum()),
        "linhas_acima_de_1e_4": int(np.any((diferenca > 1e-4) | ~finitos, axis=1).sum()),
        "concordancia_argmax": float(np.mean(referencia.argmax(1) == observado.argmax(1))),
        "pior_linha": linha,
        "referencia_pior_linha": [float(v) if np.isfinite(v) else None for v in referencia[linha]],
        "observado_pior_linha": [float(v) if np.isfinite(v) else None for v in observado[linha]],
    }


def converter(
    modelo, *, textual: bool, dimensao: int = 0, bloquear_linear: bool = False, bruto: bool = False
) -> onnx.ModelProto:
    """Varia apenas a representação ONNX do mesmo ajuste já concluído."""
    classificador = modelo.named_steps["classifier"] if hasattr(modelo, "named_steps") else modelo
    opcoes = {id(classificador): {"zipmap": False, "raw_scores": bruto}}
    entrada = StringTensorType([None, 1]) if textual else FloatTensorType([None, dimensao])
    return convert_sklearn(
        modelo,
        initial_types=[("entrada", entrada)],
        options=opcoes,
        target_opset=17,
        black_op={"LinearClassifier"} if bloquear_linear else None,
    )


def diagnosticar(dados: Path, saida: Path) -> dict:
    """Treina no corpus fixado e decompõe a execução, mesmo se o gate falhar."""
    saida.mkdir(parents=True, exist_ok=True)
    candidato = saida / "candidato"
    if candidato.exists():
        raise FileExistsError(
            f"Use uma saída nova para preservar o candidato existente: {candidato}"
        )
    candidato.mkdir()
    download_data(dados)
    particoes = prepare_data(dados)
    erro_treino = None
    try:
        # A chamada direta preserva arquivos reprovados, sem promover uma versão.
        _fit_bundle(particoes.train, particoes.validation, candidato, particoes.audit, 0.55)
    except ValueError as erro:
        erro_treino = str(erro)
        if not all((candidato / nome).is_file() for nome in ("baseline.joblib", "model.onnx")):
            raise
    modelo = joblib.load(candidato / "baseline.joblib")
    grafo = onnx.load(candidato / "model.onnx")
    textos = particoes.validation.medical_abstract.map(normalize).tolist()
    entradas = np.array(textos, dtype=object).reshape(-1, 1)
    referencia = modelo.predict_proba(textos)
    # Estas execuções precedem conversões alternativas ou inspeção de intermediários.
    padrao = executar(grafo, entradas)[1]
    sem_otimizacao = executar(grafo, entradas, otimizar=False)[1]
    resumo = resumir(referencia, padrao)
    # Mantém a heurística da biblioteca como controle, mesmo após a correção do projeto.
    grafo_biblioteca = converter(modelo, textual=True)
    onnx.save(grafo_biblioteca, candidato / "conversor_padrao.onnx")
    resumo_biblioteca = resumir(referencia, executar(grafo_biblioteca, entradas)[1])
    pior = resumo_biblioteca["pior_linha"]
    inicio_lote = (pior // 64) * 64
    fim_lote = min(inicio_lote + 64, len(textos))
    posicao = pior - inicio_lote
    textos_lote = textos[inicio_lote:fim_lote]
    entradas_lote = entradas[inicio_lote:fim_lote]
    tfidf = modelo.named_steps["tfidf"]
    classificador = modelo.named_steps["classifier"]
    vetores = tfidf.transform(textos_lote).toarray()
    grafo_tfidf = convert_sklearn(
        modelo[:1], initial_types=[("entrada", StringTensorType([None, 1]))], target_opset=17
    )
    onnx.save(grafo_tfidf, candidato / "tfidf.onnx")
    vetores_onnx = executar(grafo_tfidf, entradas_lote)[0]
    erro_vetores = np.abs(vetores[posicao] - vetores_onnx[posicao])
    nomes = tfidf.get_feature_names_out()
    maiores = np.argsort(erro_vetores)[-10:][::-1]
    logits = classificador.decision_function(vetores)
    probabilidades_lote = classificador.predict_proba(vetores)
    comparacoes = {}
    for nome, bruto, bloquear in (
        ("linear_probabilidades", False, False),
        ("linear_logits", True, False),
        ("matmul_probabilidades", False, True),
        ("matmul_logits", True, True),
    ):
        isolado = converter(
            classificador,
            textual=False,
            dimensao=vetores.shape[1],
            bloquear_linear=bloquear,
            bruto=bruto,
        )
        onnx.save(isolado, candidato / f"{nome}.onnx")
        comparacoes[nome] = resumir(
            logits if bruto else probabilidades_lote, executar(isolado, vetores)[1]
        )
    alternativo = converter(modelo, textual=True, bloquear_linear=True)
    onnx.save(alternativo, candidato / "pipeline_matmul.onnx")
    relatorio = {
        "gerado_em": datetime.now(UTC).isoformat(),
        "ambiente": ambiente(),
        "auditoria_dados": particoes.audit,
        "erro_gate_treinamento": erro_treino,
        "modelo_publicado": False,
        "amostras": len(textos),
        "pipeline_do_projeto": resumo,
        "pipeline_conversor_padrao": resumo_biblioteca,
        "pipeline_sem_otimizacao": resumir(referencia, sem_otimizacao),
        "pipeline_matmul_softmax": resumir(referencia, executar(alternativo, entradas)[1]),
        "pior_linha_executada_sozinha": resumir(
            referencia[pior : pior + 1], executar(grafo, entradas[pior : pior + 1])[1]
        ),
        "lote_investigado": {
            "inicio_inclusivo": inicio_lote,
            "fim_exclusivo": fim_lote,
            "criterio": "Lote da pior linha do conversor padrão da biblioteca.",
        },
        "tfidf": {
            "erro_maximo_lote": float(np.abs(vetores - vetores_onnx).max()),
            "erro_maximo_pior_linha": float(erro_vetores.max()),
            "features_divergentes_pior_linha": int((erro_vetores > 1e-6).sum()),
            "dez_maiores_diferencas": [
                {
                    "indice": int(i),
                    "termo": str(nomes[i]),
                    "referencia": float(vetores[posicao, i]),
                    "onnx": float(vetores_onnx[posicao, i]),
                    "diferenca": float(erro_vetores[i]),
                }
                for i in maiores
            ],
        },
        "classificador_isolado_com_tfidf_sklearn": comparacoes,
        "classificador_sklearn_com_tfidf_onnx": resumir(
            probabilidades_lote, classificador.predict_proba(vetores_onnx)
        ),
        "artefatos_sha256": {arquivo.name: sha256(arquivo) for arquivo in candidato.iterdir()},
        "limites": [
            "Os índices das comparações isoladas são relativos ao lote investigado.",
            "As alternativas são diagnósticos; nenhuma delas substitui o modelo publicado.",
            "TF-IDF isolado e alternativas MatMul usam o conversor padrão como controle.",
            "Desabilitar otimizações do grafo não desabilita o despacho SIMD dos kernels.",
        ],
    }
    (saida / "diagnostico.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2, allow_nan=False) + "\n", "utf-8"
    )
    return relatorio


def main() -> None:
    """Executa a investigação em diretório próprio, sem modificar evidências anteriores."""
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("-h", "--help", action="help", help="Exibe esta ajuda e encerra.")
    parser.add_argument(
        "--dados",
        type=Path,
        default=Path("data/raw"),
        help="Diretório para os arquivos originais do corpus.",
    )
    parser.add_argument(
        "--saida",
        type=Path,
        default=Path("reports/diagnostico_paridade"),
        help="Diretório novo para relatório e candidato não publicado.",
    )
    argumentos = parser.parse_args()
    with threadpool_limits(limits=1):
        resultado = diagnosticar(argumentos.dados, argumentos.saida)
    print(
        json.dumps(
            {
                "relatorio": str(argumentos.saida / "diagnostico.json"),
                "erro_gate": resultado["erro_gate_treinamento"],
                "pipeline_do_projeto": resultado["pipeline_do_projeto"],
                "pipeline_conversor_padrao": resultado["pipeline_conversor_padrao"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
