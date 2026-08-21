$path = "apps/ui/src/App.tsx"
$text = Get-Content $path -Raw
$pattern = '  const world = research\?\.world_model;.*?const transfer100Gain = transfer100\?\.statistics\?\.transfer_gain\?\.mean;'
$replacement = @'
  const world = research?.world_model;
  const hermes = research?.hermes;
  const transfer100 = hermes?.transfer100;
  const transfer100Gain = transfer100?.statistics?.transfer_gain?.mean;
'@
$text = [regex]::Replace($text, $pattern, $replacement, 1)
[System.IO.File]::WriteAllText((Resolve-Path $path), $text)
