# Payload is JSON decoded by windows_service.py, never interpolated as code.
try {
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $name = "rime-config-$sid"
    $marker = 'Managed by rime-config service installer v1'
    $previous = Get-ScheduledTask -TaskPath '\' | Where-Object { $_.TaskName -eq $name }
    if ($p.operation -eq 'status') {
        if ($null -eq $previous) { Write-Output "Not installed: $name"; exit 0 }
        $previous | Select-Object TaskName, State | Format-List | Out-String | Write-Output
        Get-ScheduledTaskInfo -TaskName $name -TaskPath '\' |
            Select-Object LastRunTime, LastTaskResult, NextRunTime | Format-List | Out-String | Write-Output
        exit 0
    }
    if ($previous -and $previous.Description -ne $marker) {
        throw 'Refusing to replace or delete a task not owned by this installer.'
    }
    if ($p.operation -eq 'uninstall' -and $null -eq $previous) {
        Write-Output "Not installed: $name"; exit 0
    }
    $xml = $null
    $running = $false
    if ($previous) {
        $xml = Export-ScheduledTask -TaskName $name -TaskPath '\'
        $running = $previous.State -eq 'Running'
    }
    # Construct everything before touching the existing task.
    if ($p.operation -eq 'install') {
        $action = New-ScheduledTaskAction -Execute $p.executable -Argument $p.arguments -WorkingDirectory $p.directory
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $sid
        # Some Windows scheduler configurations do not retry on-demand failures.
        # A repeating trigger also recovers those exits; IgnoreNew prevents overlap.
        $recovery = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
            -RepetitionInterval (New-TimeSpan -Minutes 1)
        $principal = New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
            -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        $definition = New-ScheduledTask -Action $action -Trigger @($trigger, $recovery) `
            -Principal $principal -Settings $settings -Description $marker
    }
    try {
        if ($previous) { Stop-ScheduledTask -TaskName $name -TaskPath '\' }
        if ($p.operation -eq 'install') {
            Register-ScheduledTask -TaskName $name -TaskPath '\' -InputObject $definition -Force | Out-Null
            Start-ScheduledTask -TaskName $name -TaskPath '\'
        } else {
            Unregister-ScheduledTask -TaskName $name -TaskPath '\' -Confirm:$false
        }
    } catch {
        $original = $_.Exception.Message
        try {
            $current = Get-ScheduledTask -TaskPath '\' | Where-Object { $_.TaskName -eq $name }
            if ($current) { Stop-ScheduledTask -TaskName $name -TaskPath '\' }
            if ($xml) {
                Register-ScheduledTask -TaskName $name -TaskPath '\' -Xml $xml -Force | Out-Null
                if ($running) { Start-ScheduledTask -TaskName $name -TaskPath '\' }
            } elseif ($current) {
                Unregister-ScheduledTask -TaskName $name -TaskPath '\' -Confirm:$false
            }
        } catch {
            throw "$original; recovery failed for ${name}: $($_.Exception.Message)"
        }
        throw "$original; previous task restored."
    }
    Write-Output "$($p.operation) completed: $name"
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
