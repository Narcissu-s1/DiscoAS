@echo off
chcp 65001 >nul
setlocal

set "PROJECT_ROOT=%~dp0"
set "PYTHONW=%PROJECT_ROOT%.venv\Scripts\pythonw.exe"
set "ENTRYPOINT=%PROJECT_ROOT%main.py"

if not exist "%PYTHONW%" (
    echo [DiscoAS] 未找到项目虚拟环境：%PYTHONW%
    echo 请先安装依赖并创建 .venv。
    pause
    exit /b 1
)

if not exist "%ENTRYPOINT%" (
    echo [DiscoAS] 未找到启动入口：%ENTRYPOINT%
    pause
    exit /b 1
)

start "" "%PYTHONW%" "%ENTRYPOINT%"
exit /b 0
