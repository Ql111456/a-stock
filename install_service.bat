@echo off
chcp 65001 >nul
echo 正在创建开机自启任务...
schtasks /create /tn "StockMonitorWeb" /tr "cmd /c start \"\" http://localhost:8000" /sc onlogon /f /delay 0000:30 >nul
schtasks /create /tn "StockApp" /tr "cmd /c start /min \"StockWeb\" cmd /c cd /d D:\Downloads\stock-app ^&^& python run.py" /sc onlogon /f /delay 0000:05 >nul
schtasks /create /tn "StockScanner" /tr "cmd /c start /min \"StockScanner\" cmd /c cd /d D:\Downloads\stock-app ^&^& python -u scan_runner.py" /sc onlogon /f /delay 0000:10 >nul
echo.
echo 完成！已设置开机自动启动。
echo 重启电脑后会自动运行，打开 http://localhost:8000 查看。
echo 你也可以手动双击 start.bat 启动。
pause
