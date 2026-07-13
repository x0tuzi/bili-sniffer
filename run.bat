@echo off
cd /d "%~dp0"

:: 检查 venv, 没有就自动创建
if not exist "venv\Scripts\python.exe" (
    echo [*] 首次使用，正在创建虚拟环境...
    python -m venv venv 2>nul || python3 -m venv venv 2>nul
    if %errorlevel% neq 0 (
        echo [!] 创建失败！请确认 Python 已安装且路径正确
        pause
        exit /b 1
    )
    echo [*] 安装依赖...
    venv\Scripts\python -m pip install requests browser_cookie3 cryptography -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet 2>nul
    echo [*] 完成！正在启动...
)

venv\Scripts\python "%~dp0\bilibili_sniffer.py" %*
if %errorlevel% neq 0 pause
