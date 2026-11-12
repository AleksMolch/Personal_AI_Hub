# install_windows.ps1 — запуск Personal AI Hub на Windows одной командой.
#
# Назначение: заменить `make bootstrap` + `make up` для пользователей без Git
# Bash/make. Скрипт проверяет Docker, создаёт .env со случайными секретами
# (если файла нет), собирает и поднимает стек и открывает браузер.
#
# Использование (из корня репозитория):
#   powershell -ExecutionPolicy Bypass -File infra\scripts\install_windows.ps1
#
# Идемпотентность: существующий .env не перезаписывается; повторный запуск не
# ломает уже поднятый стек. Секреты никогда не выводятся в консоль.
$ErrorActionPreference = "Stop"

# Корень репозитория — родитель каталога scripts (т.е. на два уровня выше).
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $Root

function Write-Step([string]$message) {
    Write-Host ">> $message"
}

Write-Step "Проверка Docker..."
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Ошибка: docker не найден. Установите Docker Desktop и включите Linux-контейнеры." -ForegroundColor Red
    exit 1
}
if (-not (docker info 2>$null)) {
    Write-Host "Ошибка: Docker не запущен или недоступен. Запустите Docker Desktop." -ForegroundColor Red
    exit 1
}
if (-not (docker compose version 2>$null)) {
    Write-Host "Ошибка: docker compose не найден (нужна современная версия Docker)." -ForegroundColor Red
    exit 1
}

if (Test-Path ".env") {
    Write-Step "Файл .env уже существует — пропускаю генерацию."
}
else {
    if (-not (Test-Path ".env.example")) {
        Write-Host "Ошибка: не найден .env.example." -ForegroundColor Red
        exit 1
    }
    Write-Step "Генерирую .env со случайными секретами..."
    # Два независимых случайных hex-значения: мастер-ключ (32 байта) и пароль БД
    # (16 байт). Guid + timestamp дают достаточно энтропии для локального запуска.
    $masterKey = (([guid]::NewGuid().ToString("N")) + ([guid]::NewGuid().ToString("N"))).Substring(0, 64)
    $pgPassword = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")).Substring(0, 32)

    $envLines = Get-Content ".env.example"
    $out = $envLines | ForEach-Object {
        if ($_ -match '^APP_MASTER_KEY=') { "APP_MASTER_KEY=$masterKey" }
        elseif ($_ -match '^POSTGRES_PASSWORD=') { "POSTGRES_PASSWORD=$pgPassword" }
        else { $_ }
    }
    Set-Content -Path ".env" -Value $out -Encoding UTF8
    Write-Step ".env создан."
}

if (Select-String -Path ".env" -Pattern "CHANGE_ME" -Quiet) {
    Write-Host "Ошибка: в .env остались placeholder CHANGE_ME. Замените их вручную." -ForegroundColor Red
    exit 1
}

Write-Step "Сборка и запуск стека..."
docker compose up -d --build

Write-Step "Ожидание readiness API..."
$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/health/ready" -TimeoutSec 3
        if ($resp.status -eq "ready") { $ready = $true; break }
    }
    catch {
        Start-Sleep -Seconds 2
    }
    Start-Sleep -Seconds 2
}

if (-not $ready) {
    Write-Host "Предупреждение: API не ответил готовностью за 4 минуты. Проверьте: docker compose ps" -ForegroundColor Yellow
}
else {
    Write-Step "API готов."
}

Write-Step "Открываю http://localhost:3000 ..."
Start-Process "http://localhost:3000"

Write-Host ""
Write-Host "Готово. Дальше — http://localhost:3000 (вкладка «Первый запуск»)." -ForegroundColor Green
Write-Host "Остановить стек: docker compose down"
