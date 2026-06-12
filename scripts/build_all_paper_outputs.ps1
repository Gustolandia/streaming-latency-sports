# Build paper outputs for all scenarios
$ErrorActionPreference = "Stop"

$scenarios = @("s1", "s2", "s2full", "s2sf12", "s2sf12j2")

foreach ($scenario in $scenarios) {
    Write-Host "Building outputs for scenario: $scenario" -ForegroundColor Cyan
    
    # Temporarily rename the runs file to what build_paper_s2_outputs.ps1 expects
    $srcFile = "runs/_paper_${scenario}_official_runs.txt"
    $dstFile = "runs/_paper_s2_official_runs.txt"
    
    if (-not (Test-Path $srcFile)) {
        Write-Warning "Missing $srcFile, skipping $scenario"
        continue
    }
    
    # Save original if it exists and it's different from source
    $originalExists = Test-Path $dstFile
    $needsRestore = $false
    
    if ($originalExists -and ($srcFile -ne $dstFile)) {
        Copy-Item $dstFile "$dstFile.bak" -Force
        $needsRestore = $true
    }
    
    # Copy scenario file to expected location (skip if source == destination)
    if ($srcFile -ne $dstFile) {
        Copy-Item $srcFile $dstFile -Force
    }
    
    try {
        & "scripts\build_paper_s2_outputs.ps1"
        
        # Rename output files to include scenario
        $outputs = @(
            "paper_s2_official.csv",
            "paper_s2_official_by_scenario_summary.csv",
            "paper_s2_official_overall_summary.csv",
            "paper_s2_meta_matrix.csv"
        )
        
        foreach ($out in $outputs) {
            $src = "data/processed/results/$out"
            $dst = $out -replace "s2", $scenario
            $dst = "data/processed/results/$dst"
            if (Test-Path $src) {
                if ($scenario -eq "s2") {
                    # Already correct name
                    Write-Host "  Kept: $src"
                } else {
                    Move-Item $src $dst -Force -ErrorAction SilentlyContinue
                    Write-Host "  Renamed: $src -> $dst"
                }
            }
            
            # Also check docs/results
            $srcDoc = "docs/results/$out"
            $dstDoc = $out -replace "s2", $scenario
            $dstDoc = "docs/results/$dstDoc"
            if (Test-Path $srcDoc) {
                if ($scenario -eq "s2") {
                    Write-Host "  Kept: $srcDoc"
                } else {
                    Move-Item $srcDoc $dstDoc -Force -ErrorAction SilentlyContinue
                    Write-Host "  Renamed: $srcDoc -> $dstDoc"
                }
            }
        }
        
        Write-Host "  Completed: $scenario" -ForegroundColor Green
    } finally {
        # Restore original runs file if we backed it up
        if ($needsRestore) {
            Move-Item "$dstFile.bak" $dstFile -Force
            Remove-Item "$dstFile.bak" -ErrorAction SilentlyContinue
        } elseif (-not $originalExists) {
            # Remove the temp file we created
            Remove-Item $dstFile -ErrorAction SilentlyContinue
        }
    }
}

Write-Host "DONE: Built outputs for all scenarios" -ForegroundColor Cyan
