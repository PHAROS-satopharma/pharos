# Embeds the fonts into "PHAROS Presentation.pptx" (so it opens the same on any laptop) and writes the PDF.
# PowerPoint runs without a window; one already open is left running.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path $here 'PHAROS Presentation.pptx'
$pdf = Join-Path $here 'PHAROS Presentation.pdf'
$wasRunning = [bool](Get-Process POWERPNT -ErrorAction SilentlyContinue)
$app = New-Object -ComObject PowerPoint.Application
try {
    # Open(FileName, ReadOnly, Untitled, WithWindow)
    $p = $app.Presentations.Open($src, 0, 0, 0)
    # SaveAs(FileName, ppSaveAsOpenXMLPresentation = 24, EmbedTrueTypeFonts = msoTrue): to a new file, then
    # over the source (PowerPoint skips the fonts when it saves over the file it has open)
    $tmp = Join-Path $here 'PHAROS Presentation.embedded.pptx'
    $p.SaveAs($tmp, 24, -1)
    # ppSaveAsPDF = 32
    $p.SaveAs($pdf, 32)
    $p.Close()
    Move-Item -Force $tmp $src
} finally {
    if (-not $wasRunning) { $app.Quit() }
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
Write-Output "wrote $pdf"
