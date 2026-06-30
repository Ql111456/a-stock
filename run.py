#!/usr/bin/env python3
"""启动入口: python run.py"""
import os, sys, uvicorn

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

if __name__ == "__main__":
    print("=" * 50)
    print("A股主板潜力股监控系统")
    print("后端: FastAPI | 前端: Vue 3 + ECharts | 存储: SQLite")
    print("数据: 东方财富 + AkShare | 调度: APScheduler 每分钟")
    print("=" * 50)
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
