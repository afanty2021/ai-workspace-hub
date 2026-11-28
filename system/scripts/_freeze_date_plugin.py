"""冻结墙钟 pytest 插件（时间炸弹巡检用，freeze_date_sweep.py 的伴生插件）。

冻结墙钟：FREEZE_ISO=2026-12-31T23:59:59.999999（本地时区 ISO 时刻）。
跨午夜步进：FREEZE_FLIP_AFTER=k + FREEZE_FLIP_TO=下一秒 ISO —— 每个用例开始时计数归零，
该用例内第 k 次读墙钟之后，时钟跳到 FREEZE_TO（模拟「用例跑着跑着过了午夜」）。

安装点=pytest_collection_finish：此时受评测试模块与其 import 的受评代码模块都已加载，
把模块属性 date/datetime 换成假类（只动「from datetime import date/datetime」绑定的模块）；
函数内局部 import（ump._today_iso/_calendar_gap_days）走 sys.modules['datetime']，
故 datetime 模块自身的 date/datetime 也换——假类 metaclass 的 __instancecheck__ 放行真类实例。
对照：FREEZE_ISO 取普通时刻全量须全绿，否则插件本身伤到测试、冻结结果不作数。

来源：2026-11-28 max 评审 B 席 freeze_plugin v2（全局一致版）入仓——
背景案=tests/test_us_liquidity.py 夹具写死 2026-11-19 ×脚本侧 today−30 窗口，
2026-12-20 起全量必红（「今天绿」不等于「下月绿」）。巡检入口见 freeze_date_sweep.py。
"""
from __future__ import annotations

import os
import sys
from datetime import date as RealDate
from datetime import datetime as RealDateTime

_ISO = os.environ.get("FREEZE_ISO")
_FLIP_AFTER = int(os.environ.get("FREEZE_FLIP_AFTER", "0") or 0)
_FLIP_TO = os.environ.get("FREEZE_FLIP_TO")
_T0 = RealDateTime.fromisoformat(_ISO) if _ISO else RealDateTime(2000, 1, 1)
_T1 = RealDateTime.fromisoformat(_FLIP_TO) if _FLIP_TO else None
_state = {"n": 0}


def _now():
    if _T1 is not None and _FLIP_AFTER and _state["n"] >= _FLIP_AFTER:
        return _T1
    return _T0


def _tick():
    if _T1 is not None:
        _state["n"] += 1


class _Meta(type):
    def __instancecheck__(cls, obj):
        base = RealDateTime if cls is FakeDateTime else RealDate
        return isinstance(obj, base)

    def __subclasscheck__(cls, sub):
        base = RealDateTime if cls is FakeDateTime else RealDate
        if cls is sub:
            return True
        try:
            return issubclass(sub, base)
        except TypeError:
            return False


class FakeDate(RealDate, metaclass=_Meta):
    @classmethod
    def today(cls):
        _tick()
        return cls.fromordinal(_now().toordinal())

    @classmethod
    def fromtimestamp(cls, t, tz=None):
        return super().fromtimestamp(t, tz)


class FakeDateTime(RealDateTime, metaclass=_Meta):
    @classmethod
    def now(cls, tz=None):
        _tick()
        return _now() if tz is None else _now().astimezone(tz)

    @classmethod
    def today(cls):
        _tick()
        return _now().replace(hour=0, minute=0, second=0, microsecond=0)

    @classmethod
    def utcnow(cls):
        _tick()
        return _now().astimezone(None).astimezone(__import__("datetime").timezone.utc).replace(tzinfo=None)


def pytest_collection_finish(session):
    import datetime as _dtm
    _dtm.date = FakeDate
    _dtm.datetime = FakeDateTime
    seen = {}
    for item in session.items:
        m = getattr(item, "module", None)
        if m is not None:
            seen[id(m)] = m
    for name in ("update_money_etf_premium", "generate_daily_report", "persist_market_data",
                 "update_cross_asset_history", "batch_ledger", "run_archive", "save_custom_data",
                 "market_data_io"):
        m = sys.modules.get(name)
        if m is not None:
            seen[id(m)] = m
    n = 0
    # 全局一致版：凡模块属性 date/datetime 仍是真类的绑定，一律换成假类
    # （白名单版会造「测试侧冻结、脚本侧真钟」不一致的假红）
    for name, m in list(sys.modules.items()):
        if name.startswith("_freeze_date_plugin"):
            continue
        try:
            if getattr(m, "date", None) is RealDate:
                m.date = FakeDate
                n += 1
            if getattr(m, "datetime", None) is RealDateTime:
                m.datetime = FakeDateTime
                n += 1
        except Exception:  # noqa: BLE001 — 个别模块（lazy import 代理）不允写属性，跳过
            continue
    print(f"\n[_freeze_date_plugin] t0={_T0.isoformat()} flip_after={_FLIP_AFTER} "
          f"flip_to={_FLIP_TO} patched_bindings={n} mode=global")


def pytest_runtest_setup(item):
    _state["n"] = 0
