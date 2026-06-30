"""APScheduler 定时任务调度"""
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import json
from database import SessionLocal
from models import ScanResult, DramaticStock, ClosingReport, MinuteData, KlineData
from scanner import run_full_scan, NAMES

scheduler = BackgroundScheduler()


def _is_trade_time():
    now = datetime.now()
    if now.weekday() >= 5: return False
    t = now.hour * 60 + now.minute
    return (9*60+30 <= t <= 11*60+30) or (13*60 <= t <= 15*60+5)


def _is_after_close():
    now = datetime.now()
    return now.hour * 60 + now.minute >= 15*60+1 and now.weekday() < 5


def scheduled_scan():
    """每分钟检查，交易时段执行扫描"""
    if not _is_trade_time():
        return
    print(f"[定时] {datetime.now().strftime('%H:%M:%S')} 执行扫描...")
    top, dramatic, closing = run_full_scan()
    if not top: return

    db = SessionLocal()
    try:
        now = datetime.now()
        # 去重：删除同一分钟的旧数据
        minute_start = now.replace(second=0, microsecond=0)
        db.query(ScanResult).filter(ScanResult.scan_time >= minute_start).delete()

        for i, s in enumerate(top):
            db.add(ScanResult(code=s.code, name=s.name, price=s.price, pct=s.pct,
                volume_ratio=s.volume_ratio, market_cap=s.market_cap,
                strategies=" | ".join(NAMES.get(k, k) for k in s.hit_strategies),
                score=round(s.total_score, 1), rank=i+1, scan_time=now))
            if getattr(s, "min_chart", None):
                db.add(MinuteData(code=s.code, scan_time=now,
                    data_json=json.dumps(s.min_chart, ensure_ascii=False)))
            if getattr(s, "daily_chart", None):
                db.add(KlineData(code=s.code, ktype="daily", scan_time=now,
                    data_json=json.dumps(s.daily_chart, ensure_ascii=False)))
            if getattr(s, "weekly_chart", None):
                db.add(KlineData(code=s.code, ktype="weekly", scan_time=now,
                    data_json=json.dumps(s.weekly_chart, ensure_ascii=False)))

        for r in dramatic:
            db.add(DramaticStock(code=r["code"], name=r["name"],
                price=r["price"], pct=r["pct"], recorded_at=now))

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
    print(f"[定时] 完成: Top20={len(top)}")


def start_scheduler():
    scheduler.add_job(scheduled_scan, "cron", minute="*", id="stock_scan",
                      replace_existing=True)
    # 启动时也跑一次（如果恰好在交易时段）
    if _is_trade_time():
        scheduler.add_job(scheduled_scan, "date", run_date=datetime.now(),
                          id="stock_scan_init")
    scheduler.start()
    print("[调度器] 已启动，每分钟检查交易时段")


def stop_scheduler():
    scheduler.shutdown()
