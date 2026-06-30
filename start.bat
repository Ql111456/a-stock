@echo off
chcp 65001 >nul
echo ====================================
echo   A股主板潜力股监控系统
echo   Web: http://localhost:8000
echo ====================================
echo.
rem 启动 Web 服务
start "StockWeb" cmd /c "cd /d D:\Downloads\stock-app && python run.py"
rem 等待3秒
timeout /t 3 /nobreak >nul
rem 启动扫描器
start "StockScanner" cmd /c "cd /d D:\Downloads\stock-app && python -u scan_runner.py"
echo 已启动！
echo 请在浏览器打开 http://localhost:8000
echo.
pause
