param(
    [Parameter(Mandatory=$true)][string]$WavePath,
    [Parameter(Mandatory=$true)][string]$ReportPath
)
# Run with Windows PowerShell 5.1. Uses installed zh-CN dictation, never a microphone.
# This is auxiliary transcription evidence, not an audio-content approval.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$source = (Resolve-Path -LiteralPath $WavePath).Path
$culture = [System.Globalization.CultureInfo]::GetCultureInfo('zh-CN')
$engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine -ArgumentList $culture
$items = @()
try {
    $engine.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
    $engine.SetInputToWaveFile($source)
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    for ($i = 0; $i -lt 16 -and $watch.Elapsed.TotalSeconds -lt 45; $i++) {
        $result = $engine.Recognize([TimeSpan]::FromSeconds(10))
        if ($null -eq $result) { break }
        $items += [ordered]@{
            text = $result.Text
            confidence = $result.Confidence
            start_seconds = $result.Audio.AudioPosition.TotalSeconds
            duration_seconds = $result.Audio.Duration.TotalSeconds
        }
    }
} finally {
    $engine.Dispose()
}
$report = [ordered]@{
    engine = 'Windows installed zh-CN dictation'
    grammar = 'free dictation; no expected dialogue supplied'
    source = $source
    results = $items
    audio_content_review = 'pending; transcription does not establish music or overall sound quality'
}
$json = $report | ConvertTo-Json -Depth 5
[IO.File]::WriteAllText([IO.Path]::GetFullPath($ReportPath), $json, (New-Object Text.UTF8Encoding($false)))
$json
