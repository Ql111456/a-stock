"""数据库模型"""
from sqlalchemy import Column, String, Float, Integer, DateTime, Text
from database import Base
from datetime import datetime


class ScanResult(Base):
    __tablename__ = "scan_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), index=True)
    name = Column(String(20))
    price = Column(Float)
    pct = Column(Float)
    volume_ratio = Column(Float)
    market_cap = Column(Float)
    strategies = Column(String(100))
    score = Column(Float)
    rank = Column(Integer)
    scan_time = Column(DateTime, default=datetime.now, index=True)


class DramaticStock(Base):
    __tablename__ = "dramatic_stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10))
    name = Column(String(20))
    price = Column(Float)
    pct = Column(Float)
    recorded_at = Column(DateTime, default=datetime.now, index=True)


class ClosingReport(Base):
    __tablename__ = "closing_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String(10), index=True)
    category = Column(String(10))          # "A" or "B"
    rank = Column(Integer)
    code = Column(String(10))
    name = Column(String(20))
    price = Column(Float)
    pct = Column(Float)
    volume_ratio = Column(Float)
    market_cap = Column(Float)
    strategies = Column(String(100))
    score = Column(Float)
    created_at = Column(DateTime, default=datetime.now)


class MinuteData(Base):
    __tablename__ = "minute_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), index=True)
    scan_time = Column(DateTime, default=datetime.now, index=True)
    data_json = Column(Text)               # JSON: {times, prices, vols, avgs, preClose}


class KlineData(Base):
    __tablename__ = "kline_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), index=True)
    ktype = Column(String(10))             # "daily" / "weekly"
    scan_time = Column(DateTime, default=datetime.now)
    data_json = Column(Text)               # JSON: {dates, ohlc, vols}
