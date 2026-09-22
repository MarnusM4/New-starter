<#
.SYNOPSIS
    PLACEHOLDER PowerShell runbook for on-prem AD user creation.

    Runs on an Azure Automation Hybrid Runbook Worker inside the client's network,
    where it has line-of-sight to a domain controller. Triggered by LocalAdAction in
    Phase B with validated parameters from the ProvisioningPlan. Azure AD Connect syncs
    the resulting user up to Entra.

    DO NOT add business logic here that isn't already validated by the action layer —
    this runbook should only execute pre-approved, parameterised operations.
#>

param(
    [Parameter(Mandatory = $true)][string] $FirstName,
    [Parameter(Mandatory = $true)][string] $LastName,
    [Parameter(Mandatory = $true)][string] $SamAccountName,
    [Parameter(Mandatory = $true)][string] $UserPrincipalName,
    [string] $DisplayName,
    [string] $OUPath,
    [string[]] $Groups = @()
)

# TODO (Phase B): pull a temporary password from Azure Automation / Key Vault.
# TODO (Phase B): real OU resolution per client.

Import-Module ActiveDirectory

Write-Output "PLACEHOLDER: would create AD user $SamAccountName ($UserPrincipalName)"

# --- Phase B implementation sketch (left commented until creds/OU are confirmed) ---
# $securePwd = ConvertTo-SecureString (Get-AutomationVariable -Name 'TempPassword') -AsPlainText -Force
# New-ADUser `
#     -Name $DisplayName `
#     -GivenName $FirstName -Surname $LastName `
#     -SamAccountName $SamAccountName `
#     -UserPrincipalName $UserPrincipalName `
#     -Path $OUPath `
#     -AccountPassword $securePwd `
#     -ChangePasswordAtLogon $true `
#     -Enabled $true
# foreach ($g in $Groups) { Add-ADGroupMember -Identity $g -Members $SamAccountName }
