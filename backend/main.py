"""FastAPI 主应用"""
import json, os, threading, traceback
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from database import init_db, SessionLocal
from models import ScanResult, DramaticStock, ClosingReport, MinuteData, KlineData
from scanner import run_full_scan, NAMES
from scheduler import start_scheduler, stop_scheduler

# ===== 应用生命周期 =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    yield
    stop_scheduler()

app = FastAPI(title="A股主板潜力股监控", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ===== 数据接口 =====

def _score_to_dict(s):
    return {
        "code": s.code, "name": s.name, "price": s.price,
        "pct": s.pct, "volume_ratio": s.volume_ratio,
        "market_cap": round(s.market_cap / 1e8, 1),
        "strategies": " | ".join(NAMES.get(k, k) for k in s.hit_strategies),
        "score": round(s.total_score, 1),
        "min_chart": getattr(s, "min_chart", None),
        "daily_chart": getattr(s, "daily_chart", None),
        "weekly_chart": getattr(s, "weekly_chart", None),
    }


@app.get("/api/debug")
def api_debug():
    """调试：强制重载模块并检查返回值"""
    import importlib, scanner
    importlib.reload(scanner)
    top, dramatic, closing = scanner.run_full_scan()
    return {"top_count": len(top), "drama_count": len(dramatic),
            "first": top[0].code if top else None}

@app.get("/api/scan")
def api_scan():
    """手动触发扫描"""
    import importlib, scanner
    importlib.reload(scanner)
    top, dramatic, closing = scanner.run_full_scan()
    db = SessionLocal()
    try:
        now = datetime.now()
        # 保存扫描结果
        for i, s in enumerate(top):
            db.add(ScanResult(code=s.code, name=s.name, price=s.price, pct=s.pct,
                volume_ratio=s.volume_ratio, market_cap=s.market_cap,
                strategies=" | ".join(NAMES.get(k, k) for k in s.hit_strategies),
                score=round(s.total_score, 1), rank=i+1, scan_time=now))
            # 保存图表数据
            if getattr(s, "min_chart", None):
                db.add(MinuteData(code=s.code, scan_time=now,
                    data_json=json.dumps(s.min_chart, ensure_ascii=False)))
            if getattr(s, "daily_chart", None):
                db.add(KlineData(code=s.code, ktype="daily", scan_time=now,
                    data_json=json.dumps(s.daily_chart, ensure_ascii=False)))
            if getattr(s, "weekly_chart", None):
                db.add(KlineData(code=s.code, ktype="weekly", scan_time=now,
                    data_json=json.dumps(s.weekly_chart, ensure_ascii=False)))
        # 剧烈行情
        for r in dramatic:
            db.add(DramaticStock(code=r["code"], name=r["name"],
                price=r["price"], pct=r["pct"], recorded_at=now))
        # 收盘报告
        if closing:
            today = now.strftime("%Y-%m-%d")
            db.query(ClosingReport).filter(ClosingReport.date == today).delete()
            for cat, items in [("A", closing["type_a"]), ("B", closing["type_b"])]:
                for item in items:
                    db.add(ClosingReport(date=today, category=cat, rank=item["rank"],
                        code=item["code"], name=item["name"], price=item["price"],
                        pct=item["pct"], volume_ratio=item["volume_ratio"],
                        market_cap=item["market_cap"], strategies=item["strategies"],
                        score=item["score"]))
        db.commit()
    finally:
        db.close()

    return {
        "time": now.strftime("%H:%M:%S"), "date": now.strftime("%Y-%m-%d"),
        "total_stocks": 0,   # 由前端从 top20 推算
        "top20": [_score_to_dict(s) for i, s in enumerate(top)],
        "dramatic": dramatic,
        "closing_report": closing,
    }


@app.get("/api/latest")
def api_latest():
    """获取最新扫描结果"""
    db = SessionLocal()
    try:
        now = datetime.now()
        # 最新一次扫描时间
        latest = db.query(ScanResult.scan_time).order_by(ScanResult.scan_time.desc()).first()
        if not latest:
            return {"status": "waiting", "top20": [], "dramatic": [], "closing_report": None,
                    "time": "--", "date": now.strftime("%Y-%m-%d")}

        scan_time = latest[0]
        results = db.query(ScanResult).filter(ScanResult.scan_time == scan_time).order_by(ScanResult.rank).all()
        top20 = []
        for r in results:
            item = {"rank": r.rank, "code": r.code, "name": r.name, "price": r.price,
                    "pct": r.pct, "volume_ratio": r.volume_ratio,
                    "market_cap": r.market_cap, "strategies": r.strategies, "score": r.score}
            # 图表数据
            mc = db.query(MinuteData).filter(MinuteData.code == r.code,
                MinuteData.scan_time == scan_time).first()
            dc = db.query(KlineData).filter(KlineData.code == r.code, KlineData.ktype == "daily",
                KlineData.scan_time == scan_time).first()
            wc = db.query(KlineData).filter(KlineData.code == r.code, KlineData.ktype == "weekly",
                KlineData.scan_time == scan_time).first()
            item["min_chart"] = json.loads(mc.data_json) if mc else None
            item["daily_chart"] = json.loads(dc.data_json) if dc else None
            item["weekly_chart"] = json.loads(wc.data_json) if wc else None
            top20.append(item)

        # 剧烈行情
        dramatic = []
        for r in db.query(DramaticStock).filter(DramaticStock.recorded_at == scan_time).all():
            dramatic.append({"code": r.code, "name": r.name, "price": r.price, "pct": r.pct})

        # 收盘报告
        today = now.strftime("%Y-%m-%d")
        closing = None
        cr = db.query(ClosingReport).filter(ClosingReport.date == today).all()
        if cr:
            type_a = [{"rank": x.rank, "code": x.code, "name": x.name, "price": x.price,
                       "pct": x.pct, "volume_ratio": x.volume_ratio, "market_cap": x.market_cap,
                       "strategies": x.strategies, "score": x.score}
                      for x in cr if x.category == "A"]
            type_b = [{"rank": x.rank, "code": x.code, "name": x.name, "price": x.price,
                       "pct": x.pct, "volume_ratio": x.volume_ratio, "market_cap": x.market_cap,
                       "strategies": x.strategies, "score": x.score}
                      for x in cr if x.category == "B"]
            closing = {"type_a": type_a, "type_b": type_b}

        return {"status": "ok", "time": scan_time.strftime("%H:%M:%S"),
                "date": scan_time.strftime("%Y-%m-%d"),
                "top20": top20, "dramatic": dramatic, "closing_report": closing}
    finally:
        db.close()


@app.get("/api/history")
def api_history(days: int = Query(7, ge=1, le=30)):
    """历史表现（最近N天每只股票被选中次数）"""
    db = SessionLocal()
    try:
        since = datetime.now() - timedelta(days=days)
        rows = db.query(ScanResult).filter(ScanResult.scan_time >= since).all()
        stats = {}
        for r in rows:
            if r.code not in stats:
                stats[r.code] = {"code": r.code, "name": r.name, "count": 0, "avg_score": 0, "total_score": 0}
            stats[r.code]["count"] += 1
            stats[r.code]["total_score"] += r.score
        for v in stats.values():
            v["avg_score"] = round(v["total_score"] / v["count"], 1)
        return sorted(stats.values(), key=lambda x: x["count"], reverse=True)[:30]
    finally:
        db.close()


# ===== 前端静态文件 =====
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# 挂载静态资源
if os.path.exists(FRONTEND_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="assets")
