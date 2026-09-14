<#
.SYNOPSIS
Verifica os contratos das evidências e a preservação do MP4 no modo de imagens.
.DESCRIPTION
Execute na raiz do projeto após renderizar o vídeo e disponibilizar a API do host.
Extrai apenas as definições das funções do gerador; não executa o script por dot-source.
#>
[CmdletBinding()]
param([string]$ApiUrl = 'http://127.0.0.1:8004')

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Raiz = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$Gerador = Join-Path $Raiz 'scripts/gerar_video.ps1'
$Tokens = $null
$Erros = $null
$Ast = [System.Management.Automation.Language.Parser]::ParseFile($Gerador, [ref]$Tokens, [ref]$Erros)
if ($Erros.Count -gt 0) { throw 'O gerador contém erros de sintaxe PowerShell.' }
foreach ($Nome in @('Campo', 'Testar-SucessoBooleano', 'Testar-ExecucaoDag', 'Verificar-VersaoApi', 'Verificar-AmbienteRelatorios')) {
    $Definicoes = @($Ast.FindAll({ param($No)
        $No -is [System.Management.Automation.Language.FunctionDefinitionAst]
    }, $true) | Where-Object Name -eq $Nome)
    if ($Definicoes.Count -ne 1) { throw "Função esperada não identificada: $Nome" }
    . ([scriptblock]::Create($Definicoes[0].Extent.Text))
}

$Resultados = @()
function Conferir([string]$Nome, [bool]$Condicao) {
    if (-not $Condicao) { throw "Verificação reprovada: $Nome" }
    $script:Resultados += [ordered]@{ caso = $Nome; sucesso = $true }
}

$JsonDag = [System.IO.File]::ReadAllText((Join-Path $Raiz 'reports/airflow_execucao.json'))
$Dag = $JsonDag | ConvertFrom-Json
Conferir 'Execução real completa aceita' (Testar-ExecucaoDag $Dag)
$Dag.tarefas.validacao = 'failed'
Conferir 'Tarefa reprovada rejeitada' (-not (Testar-ExecucaoDag $Dag))
$Dag = $JsonDag | ConvertFrom-Json
$Dag.sucesso = 'true'
Conferir 'Sucesso textual da DAG rejeitado' (-not (Testar-ExecucaoDag $Dag))
$Dag = $JsonDag | ConvertFrom-Json
$Dag.run_id = ''
Conferir 'Execução sem identificador rejeitada' (-not (Testar-ExecucaoDag $Dag))
$Dag = $JsonDag | ConvertFrom-Json
$Dag.modelo.release = ''
Conferir 'Execução sem versão publicada rejeitada' (-not (Testar-ExecucaoDag $Dag))
Conferir 'Documento vazio rejeitado' (-not (Testar-ExecucaoDag ([pscustomobject]@{})))
Conferir 'Sucesso textual da stack rejeitado' (-not (Testar-SucessoBooleano ([pscustomobject]@{ sucesso = 'true' })))
Conferir 'Sucesso booleano da stack aceito' (Testar-SucessoBooleano ([pscustomobject]@{ sucesso = $true }))
Conferir 'Falha booleana da stack rejeitada' (-not (Testar-SucessoBooleano ([pscustomobject]@{ sucesso = $false })))

$Pronta = [pscustomobject]@{ versao_modelo = 'versao-esperada'; backend = 'onnx' }
Verificar-VersaoApi $Pronta $Pronta 'versao-esperada'
Conferir 'API e relatórios da mesma versão aceitos' $true
$DivergenciaRejeitada = $false
try { Verificar-VersaoApi $Pronta $Pronta 'versao-diferente' }
catch { $DivergenciaRejeitada = $true }
Conferir 'API de versão divergente rejeitada' $DivergenciaRejeitada
foreach ($RespostaInvalida in @(
    [pscustomobject]@{ versao_modelo = 'outra-versao'; backend = 'onnx' },
    [pscustomobject]@{ versao_modelo = 'versao-esperada'; backend = 'sklearn' }
)) {
    $Rejeitada = $false
    try { Verificar-VersaoApi $Pronta $RespostaInvalida 'versao-esperada' }
    catch { $Rejeitada = $true }
    Conferir ("Predict divergente rejeitado: $($RespostaInvalida.versao_modelo)/$($RespostaInvalida.backend)") $Rejeitada
}
$HttpHost = [pscustomobject]@{ ambiente_servidores = 'host' }
$LatenciaModelo = [pscustomobject]@{ metodo = 'Inferência completa, sem HTTP' }
Verificar-AmbienteRelatorios $HttpHost $LatenciaModelo
Conferir 'Ambientes esperados dos gráficos aceitos' $true
foreach ($ParInvalido in @(
    @{ http = [pscustomobject]@{ ambiente_servidores = 'docker' }; latencia = $LatenciaModelo },
    @{ http = $HttpHost; latencia = [pscustomobject]@{ metodo = 'Percurso HTTP' } }
)) {
    $Rejeitado = $false
    try { Verificar-AmbienteRelatorios $ParInvalido.http $ParInvalido.latencia }
    catch { $Rejeitado = $true }
    Conferir ("Ambiente incorreto rejeitado: $($ParInvalido.http.ambiente_servidores)/$($ParInvalido.latencia.metodo)") $Rejeitado
}

$CaminhosFinais = @('reports/video/apresentacao_star.mp4', 'reports/video/evidencias.json')
$Antes = @{}
foreach ($Nome in $CaminhosFinais) {
    $Antes[$Nome] = (Get-FileHash -LiteralPath (Join-Path $Raiz $Nome) -Algorithm SHA256).Hash.ToLowerInvariant()
}
$Manifesto = Get-Content -LiteralPath (Join-Path $Raiz 'reports/video/evidencias.json') -Encoding UTF8 -Raw | ConvertFrom-Json
$Intermediarios = @($Manifesto.cenas | ForEach-Object { $_.imagem; $_.audio; $_.video })
$Intermediarios += @((Join-Path $Raiz '.local/video/narracao.txt'), (Join-Path $Raiz '.local/video/api-predicao.json'))
$HashesIntermediarios = @{}
foreach ($Caminho in $Intermediarios) {
    $HashesIntermediarios[$Caminho] = (Get-FileHash -LiteralPath $Caminho -Algorithm SHA256).Hash
}
Conferir 'Vídeo corresponde ao SHA-256 do manifesto' ($Antes['reports/video/apresentacao_star.mp4'] -eq $Manifesto.sha256_video)
$SondaTexto = & ffprobe -v error -show_entries 'format=duration,size:stream=codec_name,width,height' -of json (Join-Path $Raiz 'reports/video/apresentacao_star.mp4')
Conferir 'Nova leitura ffprobe conclui com sucesso' ($LASTEXITCODE -eq 0)
$Sonda = ($SondaTexto -join "`n") | ConvertFrom-Json
$Duracao = [double]::Parse($Sonda.format.duration, [Globalization.CultureInfo]::InvariantCulture)
$DuracaoManifesto = [double]::Parse($Manifesto.ffprobe.format.duration, [Globalization.CultureInfo]::InvariantCulture)
Conferir 'Duração renderizada não excede 300 segundos' ($Duracao -gt 0 -and $Duracao -le 300)
Conferir 'Duração do manifesto corresponde ao MP4' ([Math]::Abs($Duracao - $DuracaoManifesto) -lt 0.001)
Conferir 'MP4 contém vídeo H.264 1280x720 e áudio AAC' (@($Sonda.streams | Where-Object { $_.codec_name -eq 'h264' -and $_.width -eq 1280 -and $_.height -eq 720 }).Count -eq 1 -and @($Sonda.streams | Where-Object codec_name -eq 'aac').Count -eq 1)

$LogImagens = Join-Path $Raiz '.local/video/verificacao-imagens.log'
$ErroImagens = Join-Path $Raiz '.local/video/verificacao-imagens-erro.log'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Gerador -ApiUrl $ApiUrl -SomenteImagens 1> $LogImagens 2> $ErroImagens
$CodigoModoImagens = $LASTEXITCODE
$SaidaModoImagens = Get-Content -LiteralPath $LogImagens
Conferir 'Modo SomenteImagens conclui com sucesso' ($CodigoModoImagens -eq 0)
foreach ($Nome in $CaminhosFinais) {
    $Depois = (Get-FileHash -LiteralPath (Join-Path $Raiz $Nome) -Algorithm SHA256).Hash.ToLowerInvariant()
    Conferir ("Modo SomenteImagens preserva $Nome") ($Antes[$Nome] -eq $Depois)
}
$IntermediariosPreservados = $true
foreach ($Caminho in $Intermediarios) {
    $IntermediariosPreservados = $IntermediariosPreservados -and ($HashesIntermediarios[$Caminho] -eq (Get-FileHash -LiteralPath $Caminho -Algorithm SHA256).Hash)
}
Conferir 'Modo SomenteImagens preserva os 23 arquivos intermediários do vídeo' $IntermediariosPreservados
$ManifestoImagens = Get-Content -LiteralPath (Join-Path $Raiz '.local/video/imagens/evidencias-imagens.json') -Encoding UTF8 -Raw | ConvertFrom-Json
Conferir 'Modo SomenteImagens capturou a API real' ([bool]$ManifestoImagens.api_mesma_versao_relatorios)

$Registro = [ordered]@{
    registrado_em_utc = [DateTime]::UtcNow.ToString('o')
    comando = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File reports/video/verificar_gerador.ps1 -ApiUrl $ApiUrl"
    sucesso = $true
    verificacoes = $Resultados
    saida_somente_imagens = ($SaidaModoImagens -join "`n")
    codigo_saida_somente_imagens = $CodigoModoImagens
    sha256_script = (Get-FileHash -LiteralPath $Gerador -Algorithm SHA256).Hash.ToLowerInvariant()
    sha256_video = $Antes['reports/video/apresentacao_star.mp4']
    sha256_manifesto_final = $Antes['reports/video/evidencias.json']
    duracao_segundos = $Duracao
    ffprobe = $Sonda
}
$Utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $Raiz 'reports/video/verificacao.json'), ($Registro | ConvertTo-Json -Depth 8), $Utf8)
Write-Output "$($Resultados.Count) verificações aprovadas; MP4 e manifesto final preservados."
