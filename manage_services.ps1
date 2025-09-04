# PowerShell script to manage LiteLLM services

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("start", "stop", "restart", "logs", "status", "build")]
    [string]$Action
)

$composeFile = "docker-compose.dev.yml"

switch ($Action) {
    "start" {
        Write-Host "🚀 Starting LiteLLM services..." -ForegroundColor Green
        docker-compose -f $composeFile up -d
    }
    "stop" {
        Write-Host "🛑 Stopping LiteLLM services..." -ForegroundColor Yellow
        docker-compose -f $composeFile down
    }
    "restart" {
        Write-Host "🔄 Restarting LiteLLM services..." -ForegroundColor Cyan
        docker-compose -f $composeFile restart
    }
    "logs" {
        Write-Host "📋 Showing LiteLLM logs (Press Ctrl+C to exit)..." -ForegroundColor Cyan
        docker-compose -f $composeFile logs -f
    }
    "status" {
        Write-Host "📊 LiteLLM services status:" -ForegroundColor Cyan
        docker-compose -f $composeFile ps
    }
    "build" {
        Write-Host "🔨 Building LiteLLM services..." -ForegroundColor Yellow
        docker-compose -f $composeFile build --no-cache
    }
}

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Operation completed successfully!" -ForegroundColor Green
} else {
    Write-Host "❌ Operation failed!" -ForegroundColor Red
}
