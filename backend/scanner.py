"""核心扫描引擎"""
import json, time, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests
import akshare as ak

# ===== 配置 =====
TOP_N = 20
MAX_WORKERS = 8
DATA_DAYS = 45
DRAMATIC_THRESHOLD = 5.0

NAMES = {
    "volume_breakout": "放量突破", "ma_golden_cross": "均线金叉",
    "macd_divergence": "MACD底背离", "rsi_oversold_rebound": "RSI超卖反弹",
    "consecutive_small_bullish": "连续小阳吸筹",
    "high_momentum": "高动量",
}
WEIGHTS = {"volume_breakout": 30, "ma_golden_cross": 25, "macd_divergence": 20,
           "rsi_oversold_rebound": 15, "consecutive_small_bullish": 25}


@dataclass
class Score:
    code: str; name: str; price: float; pct: float
    volume_ratio: float; market_cap: float
    hit_strategies: List[str] = field(default_factory=list)
    total_score: float = 0.0


# ===== 数据获取 =====
PROXY = {"http": "", "https": ""}
def _mkt(c): return "1" if str(c).startswith("6") else "0"


def fetch_all_stocks():
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    hd = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
    fields = "f2,f3,f5,f6,f8,f10,f12,f14,f20"
    items = []
    for p in range(1, 80):
        try:
            r = requests.get(url, params={"fid": "f6", "po": "0", "pz": "100", "pn": str(p),
                "np": "1", "fltt": "2", "invt": "2", "fs": fs, "fields": fields},
                headers=hd, timeout=15, proxies=PROXY)
            its = r.json()["data"]["diff"]
            if not its: break
            items.extend(its)
            if len(its) < 100: break
        except: break
    if not items: return pd.DataFrame()
    df = pd.DataFrame(items)
    fm = {"f12": "code", "f14": "name", "f2": "price", "f3": "pct",
          "f5": "volume", "f6": "amount", "f8": "turnover",
          "f10": "volume_ratio", "f20": "market_cap"}
    df = df.rename(columns={k: v for k, v in fm.items() if k in df.columns})
    df["code"] = df["code"].astype(str)
    for c in ["price", "pct", "volume", "turnover", "volume_ratio", "market_cap"]:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")
    m = (~df["name"].str.contains("ETF|LOF|债|转|C|N", na=False) &
         df["code"].str.match(r"^(600|601|603|605|000|001|002|003)") &
         (df["price"] > 0) & (df["pct"].notna()) & (df["volume"] > 0) &
         (df["pct"].abs() < 9.5))  # 排除涨停/跌停板
    return df[m].sort_values("amount", ascending=False, na_position="last")


def fetch_kline(code):
    try:
        s = (datetime.now() - timedelta(days=DATA_DAYS)).strftime("%Y%m%d")
        e = datetime.now().strftime("%Y%m%d")
        raw = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=s, end_date=e, adjust="qfq")
        if raw is None or raw.empty or len(raw) < 15: return None
        raw = raw.rename(columns={"日期": "date", "开盘": "open", "收盘": "close",
                                  "最高": "high", "最低": "low", "成交量": "volume", "涨跌幅": "pct_chg"})
        for c in ["open", "close", "high", "low", "volume"]:
            raw[c] = pd.to_numeric(raw[c], errors="coerce")
        return raw.dropna(subset=["close", "volume"]).sort_values("date").reset_index(drop=True)
    except: return None


# ===== 策略 =====
def _ma(s, w): return s.rolling(w).mean()


def _rsi(df, p=14):
    d = df["close"].diff(); g, l = d.clip(lower=0), (-d).clip(lower=0)
    ag = g.ewm(alpha=1/p, min_periods=p).mean()
    al = l.ewm(alpha=1/p, min_periods=p).mean()
    return 100 - 100/(1 + ag/al.replace(0, np.nan))


def _macd(df, f, s, sig):
    ef = df["close"].ewm(span=f, adjust=False).mean()
    es = df["close"].ewm(span=s, adjust=False).mean()
    d = ef - es; de = d.ewm(span=sig, adjust=False).mean()
    return d, de, 2*(d-de)


CHECKS = {
    "volume_breakout": lambda d: len(d)>=21 and d["volume"].iloc[-1]>d["volume"].rolling(20).mean().iloc[-2]*1.5 and d["close"].iloc[-1]>d["high"].rolling(20).max().iloc[-2],
    "ma_golden_cross": lambda d: len(d)>=21 and (lambda s,l:(s.iloc[-2]<=l.iloc[-2] and s.iloc[-1]>l.iloc[-1] and d["close"].iloc[-1]>s.iloc[-1]))(_ma(d["close"],5),_ma(d["close"],20)),
    "macd_divergence": lambda d: len(d)>=35 and (lambda dif: dif.loc[d["close"].iloc[-10:].idxmin()]>dif.loc[d["close"].iloc[-20:-10].idxmin()] if d["close"].iloc[-10:].min()<d["close"].iloc[-20:-10].min() else False)(_macd(d,12,26,9)[0]),
    "rsi_oversold_rebound": lambda d: len(d)>=17 and (lambda r: r.iloc[-2]<30 and r.iloc[-1]>r.iloc[-2])(_rsi(d,14)),
    "consecutive_small_bullish": lambda d: len(d)>=3 and all(1<=(r["close"]-r["open"])/r["open"]*100<=4 and r["close"]>r["open"] for _,r in d.iloc[-3:].iterrows()),
}


def scan_one(code, name, price, pct, vr, mc):
    df = fetch_kline(code)
    if df is None: return None
    latest = df.iloc[-1]; ap = float(latest["close"]); apct = float(latest.get("pct_chg", pct))
    if pd.isna(apct): apct = (ap/float(df.iloc[-2]["close"])-1)*100 if len(df)>1 else 0
    sc = Score(code=code, name=name, price=round(ap,2), pct=round(apct,2),
               volume_ratio=float(vr) if vr>0 else 1.0, market_cap=float(mc) if mc>0 else 0.0)
    for k, ck in CHECKS.items():
        try:
            if ck(df): sc.hit_strategies.append(k); sc.total_score += WEIGHTS[k]
        except: pass

    # 综合评分（策略命中 + 动量 + 趋势）
    if 1 <= sc.pct <= 7: sc.total_score += abs(sc.pct) * 2
    elif sc.pct > 7: sc.total_score += 14
    elif sc.pct < 0: sc.total_score += sc.pct * 0.5    # 下跌轻微扣分
    if sc.volume_ratio >= 1.2: sc.total_score += 5
    if sc.volume_ratio >= 1.5: sc.total_score += 8
    if sc.volume_ratio >= 2.0: sc.total_score += 7
    # 趋势加分：收盘 > MA20 = 偏多
    if len(df) >= 21 and df["close"].iloc[-1] > _ma(df["close"], 20).iloc[-1]:
        sc.total_score += 10

    # 入选阈值：策略命中 或 综合评分>=15
    if sc.hit_strategies or sc.total_score >= 15:
        if not sc.hit_strategies:
            sc.hit_strategies.append("高动量")
        return sc
    return None


# ===== 图表数据 =====
def fetch_minute_chart(code):
    try:
        r = requests.get("https://push2.eastmoney.com/api/qt/stock/trends2/get",
            params={"fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
                    "secid": f"{_mkt(code)}.{code}", "ndays": "1", "iscca": "0"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10, proxies=PROXY)
        d = r.json()
        if not d.get("data") or not d["data"].get("trends"): return None
        trends = d["data"]["trends"]; pre = d["data"].get("preClose", 0)
        ts, ps, vs, avs = [], [], [], []
        for t in trends:
            p = t.split(","); ts.append(p[0][:5]); ps.append(float(p[2]))
            vs.append(float(p[5]) or 0); avs.append(float(p[7]) if p[7] and p[7] != "-" else None)
        return {"times": ts, "prices": ps, "vols": vs, "avgs": avs, "preClose": pre}
    except: return None


def fetch_kline_chart(code, klt=101, lmt=60):
    try:
        r = requests.get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
            params={"fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                    "secid": f"{_mkt(code)}.{code}", "klt": str(klt), "fqt": "1",
                    "lmt": str(lmt), "end": "20500101"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10, proxies=PROXY)
        d = r.json()
        if not d.get("data") or not d["data"].get("klines"): return None
        dates, ohlc, vols = [], [], []
        for k in d["data"]["klines"]:
            p = k.split(","); dates.append(p[0])
            ohlc.append([float(p[1]), float(p[2]), float(p[3]), float(p[4])])
            vols.append([float(p[5]) or 0, 1 if float(p[2])>=float(p[1]) else -1])
        return {"dates": dates, "ohlc": ohlc, "vols": vols}
    except: return None


# ===== 主扫描函数 =====
def run_full_scan():
    """执行全市场扫描，返回 (top20, dramatic, closing_report)。"""
    t0 = time.time()
    print(f"[扫描] 开始...")

    stks = fetch_all_stocks()
    if stks.empty:
        print("[扫描] 行情获取失败")
        return [], [], None
    print(f"[扫描] 主板 {len(stks)} 只")

    # 剧烈行情
    dr = stks[stks["pct"].abs() >= DRAMATIC_THRESHOLD].nlargest(10, "pct")
    dramatic = [{"code": r["code"], "name": r["name"], "price": round(float(r["price"]), 2),
                  "pct": round(float(r["pct"]), 2)} for _, r in dr.iterrows()]

    # 活跃股筛选
    df = stks.copy()
    df["rk"] = (df.get("amount", 0) / 1e8).fillna(0)
    df["act"] = (df["rk"].rank(ascending=False) * 0.5 +
                 df.get("turnover", 0).fillna(0).rank(ascending=False) * 0.3 +
                 df.get("volume_ratio", 1).fillna(1).rank(ascending=False) * 0.2)
    cands = df.nsmallest(150, "act")

    # 多线程策略扫描
    rlist = []
    slist = [(r["code"], r["name"], r["price"], r["pct"],
              r.get("volume_ratio", 1), r.get("market_cap", 0))
             for _, r in cands.iterrows()]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(scan_one, *a): a[0] for a in slist}
        for f in as_completed(futures):
            try:
                sc = f.result()
                if sc and sc.total_score > 0: rlist.append(sc)
            except: pass

    rlist.sort(key=lambda x: x.total_score, reverse=True)
    top = rlist[:TOP_N]

    # 图表数据
    for s in top:
        s.min_chart = fetch_minute_chart(s.code)
        s.daily_chart = fetch_kline_chart(s.code, 101, 60)
        s.weekly_chart = fetch_kline_chart(s.code, 102, 30)

    elapsed = time.time() - t0
    print(f"[扫描] Top20={len(top)} 耗时{elapsed:.0f}s")

    # 收盘报告
    closing = None
    now = datetime.now()
    if now.hour * 60 + now.minute >= 15 * 60 + 1 and now.weekday() < 5:
        closing = _generate_closing(top)

    return top, dramatic, closing


def _generate_closing(top):
    """收盘报告：A类(强势延续) + B类(蓄力待发)。"""
    ta, tb = [], []
    for s in top:
        has_br = any(x in s.hit_strategies for x in ["volume_breakout", "ma_golden_cross"])
        has_qt = any(x in s.hit_strategies for x in ["macd_divergence", "rsi_oversold_rebound", "consecutive_small_bullish"])
        if has_br and 2 <= s.pct <= 8 and s.volume_ratio > 1.5: ta.append(s)
        elif has_qt and not has_br: tb.append(s)
    return {"type_a": [_score_row(i+1, s) for i, s in enumerate(ta[:10])],
            "type_b": [_score_row(i+1, s) for i, s in enumerate(tb[:10])]}


def _score_row(rank, s):
    return {"rank": rank, "code": s.code, "name": s.name, "price": s.price,
            "pct": s.pct, "volume_ratio": s.volume_ratio,
            "market_cap": round(s.market_cap / 1e8, 1),
            "strategies": " | ".join(NAMES[k] for k in s.hit_strategies),
            "score": round(s.total_score, 1)}
