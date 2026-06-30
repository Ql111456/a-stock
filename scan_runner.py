#!/usr/bin/env python3
"""独立扫描进程——每分钟检查交易时段，扫描结果写入数据库"""
import sys, os, json, time, traceback
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
os.environ["no_proxy"] = "*"

from database import SessionLocal, init_db
from models import ScanResult, DramaticStock, ClosingReport, MinuteData, KlineData
from scanner import run_full_scan, NAMES


def _is_trade_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return (9*60+30 <= t <= 11*60+30) or (13*60 <= t <= 15*60+5)


def save_to_db(top, dramatic, closing):
    db = SessionLocal()
    try:
        now = datetime.now()
        # 清旧数据
        minute_start = now.replace(second=0, microsecond=0)
        db.query(ScanResult).filter(ScanResult.scan_time >= minute_start).delete()
        db.query(DramaticStock).filter(DramaticStock.recorded_at >= minute_start).delete()
        db.query(MinuteData).filter(MinuteData.scan_time >= minute_start).delete()
        db.query(KlineData).filter(KlineData.scan_time >= minute_start).delete()

        for i, s in enumerate(top):
            db.add(ScanResult(code=s.code, name=s.name, price=s.price, pct=s.pct,
                volume_ratio=s.volume_ratio, market_cap=s.market_cap,
                strategies=" | ".join(NAMES.get(k, k) for k in s.hit_strategies),
                score=round(s.total_score, 1), rank=i+1, scan_time=now))
            mc = getattr(s, "min_chart", None)
            if mc:
                db.add(MinuteData(code=s.code, scan_time=now,
                    data_json=json.dumps(mc, ensure_ascii=False)))
            dc = getattr(s, "daily_chart", None)
            if dc:
                db.add(KlineData(code=s.code, ktype="daily", scan_time=now,
                    data_json=json.dumps(dc, ensure_ascii=False)))
            wc = getattr(s, "weekly_chart", None)
            if wc:
                db.add(KlineData(code=s.code, ktype="weekly", scan_time=now,
                    data_json=json.dumps(wc, ensure_ascii=False)))

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
    except Exception as e:
        db.rollback()
        print(f"[DB] 写入错误: {e}")
    finally:
        db.close()


def main():
    init_db()
    print("=" * 50)
    print("扫描器已启动（独立进程）")
    print("交易时段每分钟扫描 | 非交易时段休眠60s")
    print("=" * 50)

    last_scan = None
    while True:
        try:
            now = datetime.now()
            if _is_trade_time():
                # 每5分钟扫描一次（点刷新按钮可随时触发）
                if last_scan and (now - last_scan).total_seconds() < 295:
                    time.sleep(5)
                    continue

                print(f"\n[{now.strftime('%H:%M:%S')}] 扫描中...")
                t0 = time.time()
                top, dramatic, closing = run_full_scan()
                elapsed = time.time() - t0

                print(f"  结果: Top20={len(top)} Drama={len(dramatic)} Closing={'Y' if closing else 'N'} 耗时{elapsed:.0f}s")
                if top:
                    save_to_db(top, dramatic, closing)
                    print(f"  数据库已更新")
                    for s in top[:3]:
                        print(f"    {s.code} {s.name} {s.price:.2f} {s.pct:+.2f}%")
                last_scan = now
            else:
                print(f"[{now.strftime('%H:%M:%S')}] 非交易时段，等待60s...")
                last_scan = None  # 重置，允许开盘后立即扫描
            time.sleep(60)
        except KeyboardInterrupt:
            print("\n扫描器已停止")
            break
        except Exception as e:
            print(f"[错误] {e}")
            traceback.print_exc()
            time.sleep(30)


if __name__ == "__main__":
    main()
