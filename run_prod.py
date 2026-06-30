#!/usr/bin/env python3
"""生产环境启动入口"""
import os, sys, subprocess, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

# 启动Web服务
def start_web():
    os.chdir(os.path.join(os.path.dirname(__file__), "backend"))
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), workers=2)

# 启动扫描器
def start_scanner():
    time.sleep(3)
    from scan_runner import main as scan_main
    scan_main()

if __name__ == "__main__":
    threading.Thread(target=start_scanner, daemon=True).start()
    start_web()
