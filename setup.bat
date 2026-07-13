@echo off
setlocal enabledelayedexpansion
title bili-sniffer 安装器
chcp 65001 >nul 2>&1

echo.
echo   ═══════════════════════════════════════════
echo               bili-sniffer 安装器
echo   ═══════════════════════════════════════════
echo.

:: ==================== 检测 Python ====================
echo   [1/4] 检测 Python...

where python >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PY_VER=%%i
    echo         已找到 — !PY_VER!
    goto :check_pip
)

where python3 >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=*" %%i in ('python3 --version 2^>^&1') do set PY_VER=%%i
    echo         已找到 — !PY_VER!
    set PY_CMD=python3
    goto :check_pip
)

echo.
echo   ╔══════════════════════════════════════════════════╗
echo   ║  未找到 Python！需要先安装 Python 3.8 以上版本   ║
echo   ║                                                    ║
echo   ║  正在打开下载页面，请按以下步骤操作：              ║
echo   ║  1. 点击页面上的黄色 "Download Python" 按钮        ║
echo   ║  2. 运行下载的安装包                                ║
echo   ║  3. ⚠️ 必须勾选底部的 "Add Python to PATH"         ║
echo   ║  4. 点击 Install Now                                ║
echo   ║  5. 装完后回到这里，按任意键继续                    ║
echo   ╚══════════════════════════════════════════════════╝
echo.

start "" "https://www.python.org/downloads/"
echo   按任意键继续...
pause >nul

where python >nul 2>&1
if %errorlevel% neq 0 (
    where python3 >nul 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo   [!] 仍然找不到 Python，请确认安装时勾选了 "Add Python to PATH"
        echo   [!] 或者重启电脑后再运行本脚本
        pause
        exit /b 1
    )
    set PY_CMD=python3
) else (
    set PY_CMD=python
)

:check_pip
if "%PY_CMD%"=="" set PY_CMD=python

%PY_CMD% -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   [!] pip 不可用，请确保 Python 安装完整
    pause
    exit /b 1
)

echo.
echo   [2/4] 安装依赖包...

%PY_CMD% -m pip install requests browser_cookie3 cryptography --quiet 2>nul
if %errorlevel% neq 0 (
    echo         pip 安装失败，尝试使用镜像源...
    %PY_CMD% -m pip install requests browser_cookie3 cryptography -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet 2>nul
)

echo.
echo   [3/4] 下载脚本...
set "SCRIPT_DIR=%USERPROFILE%\bili-sniffer"
mkdir "%SCRIPT_DIR%" 2>nul

curl -fsSLo "%SCRIPT_DIR%\bilibili_sniffer.py" "https://raw.githubusercontent.com/x0tuzi/bili-sniffer/main/bilibili_sniffer.py" 2>nul
if %errorlevel% neq 0 (
    echo         curl 下载失败，尝试 PowerShell...
    powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/x0tuzi/bili-sniffer/main/bilibili_sniffer.py' -OutFile '%SCRIPT_DIR%\bilibili_sniffer.py'"
)

echo.
echo   [4/4] 创建快捷启动...

:: 生成 run.bat 放在脚本目录
(
echo @echo off
echo chcp 65001 ^>nul 2^>^&1
echo %PY_CMD% "%%~dp0\bilibili_sniffer.py" %%*
) > "%SCRIPT_DIR%\run.bat"

:: 生成到桌面
set "DESKTOP=%USERPROFILE%\Desktop"
if exist "%DESKTOP%" (
    (
    echo @echo off
    echo chcp 65001 ^>nul 2^>^&1
    echo %PY_CMD% "%SCRIPT_DIR%\bilibili_sniffer.py" %%*
    echo pause
    ) > "%DESKTOP%\bili-sniffer.bat"
)

echo.
echo   ═══════════════════════════════════════════
echo              安装完成！
echo   ═══════════════════════════════════════════
echo.
echo    启动方式：
echo      1. 双击桌面上的 bili-sniffer.bat
echo      2. 或在终端输入：%PY_CMD% "%SCRIPT_DIR%\bilibili_sniffer.py"
echo      3. 或双击目录里的 run.bat
echo.
echo    首次运行会自动检测 ffmpeg 等工具并给出安装提示
echo.
pause
