# tests/test_planted_benchmark.py
"""planted 合成对照检查（tools/planted-benchmark）的离线断言。

定位与 run_check 一致：固定种子回归基线（单实现、非校准）。本文件锁三样东西——
① 生成器：边项、漂移、截断、状态机、复现性与固定锚点、往返一致、配对、写守卫；
② 判定逻辑：三态、样本不足态、每条判据逐项（单项违例必须翻红）；
③ 端到端：三条管道各自「埋边被检出 / 对照沉默」，以及对照被换成有边市场时必须报「过松」。
全部合成数据、零联网、tmp_path 落盘。
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import run_check
import synth

N_PERM = 100           # 基准档置换数（p 值分辨率 1/101）
N_PERM_FAST = 40       # 只看三态翻转的用例用更少置换数
NAN = float("nan")


@pytest.fixture(scope="module")
def sr_baseline(tmp_path_factory):
    return run_check.check_sr(tmp_path_factory.mktemp("sr-base"), n_perm=N_PERM)


@pytest.fixture(scope="module")
def event_baseline(tmp_path_factory):
    return run_check.check_event(tmp_path_factory.mktemp("ev-base"))


@pytest.fixture(scope="module")
def rps_baseline(tmp_path_factory):
    return run_check.check_rps(tmp_path_factory.mktemp("rps-base"))


def _acf(x: np.ndarray, k: int) -> float:
    x = x - x.mean()
    return float((x[k:] @ x[:-k]) / (x @ x))


# ---------------------------------------------------------------- 生成器

def test_momentum_edge_is_slow_trend_not_noise():
    """动量边 = MOM×AR(1) 慢趋势：序列有真实正自相关，边项自身高度自相关；
    同种子不加动量项时自相关≈0。"""
    n = synth.N_EVENT_BARS
    r_mom = synth.daily_returns(synth.SEED_MOM, n, momentum=synth.MOM_COEF_EVENT)
    r_plain = synth.daily_returns(synth.SEED_MOM, n)
    assert _acf(r_mom, 1) > 0.2 and _acf(r_mom, 20) > 0.1
    assert abs(_acf(r_plain, 1)) < 0.05 and abs(_acf(r_plain, 20)) < 0.05
    edge = r_mom - r_plain
    assert np.abs(edge).max() > 0.01 and _acf(edge, 1) > 0.9   # 是慢趋势，不是当期噪声


def test_base_drift_realized_and_parameter_one_for_one():
    """全部序列带基准漂移：35 只噪声票合计的实现值落在设定值 3SE 内；
    drift 参数同种子逐根一一对应。"""
    n = synth.N_EVENT_BARS
    pooled = np.concatenate([synth.daily_returns(synth.SEED_NOISE + i, n) for i in range(35)])
    assert abs(pooled.mean() - synth.BASE_DRIFT) < 3 * synth.VOL / np.sqrt(len(pooled))
    r1 = synth.daily_returns(123, n)
    r2 = synth.daily_returns(123, n, drift=2 * synth.BASE_DRIFT)
    np.testing.assert_allclose(r2 - r1, synth.BASE_DRIFT)


def test_bottom_reversal_episode_shape_and_paired_eps():
    """反弹注入：每个 episode 恰好 BOUNCE_DAYS 天、间隔 ≥ BOUNCE_DAYS+BOUNCE_COOL；
    非注入日与同种子 daily_returns 逐根相等（对照市场只差 bounce 项）。"""
    n = synth.N_EVENT_BARS
    for i in range(3):
        seed = synth.SEED_BOUNCE + i
        mask = synth.bounce_mask(seed, n)
        steps = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
        starts, ends = np.flatnonzero(steps == 1), np.flatnonzero(steps == -1)
        assert len(starts) >= 10
        assert np.all(ends - starts == synth.BOUNCE_DAYS)
        assert np.all(np.diff(starts) >= synth.BOUNCE_DAYS + synth.BOUNCE_COOL)
        r, plain = synth.bottom_reversal_returns(seed, n), synth.daily_returns(seed, n)
        assert np.allclose(r[mask] - plain[mask], synth.BOUNCE)
        off = ~mask & (np.abs(plain) < 0.09)                   # 排除可能触到截断的样本
        assert np.all(r[off] == plain[off])


def test_daily_clip_applied():
    r = synth.daily_returns(7, 4000, vol=0.2)
    assert np.abs(r).max() == synth.DAILY_CLIP
    assert (np.abs(r) >= synth.DAILY_CLIP - 1e-12).sum() > 100    # 确有样本触到截断


def test_reproducible_with_fixed_anchor():
    """同种子两次生成逐值相同；末日恒为固定锚点 ANCHOR，不取系统时钟。"""
    kw = dict(momentum=synth.MOM_COEF_EVENT)
    a, b = synth.ohlc_frame(synth.SEED_MOM, 300, **kw), synth.ohlc_frame(synth.SEED_MOM, 300, **kw)
    assert a[0].equals(b[0]) and all(np.array_equal(x, y) for x, y in zip(a[1:], b[1:]))
    assert a[0][-1].strftime("%Y-%m-%d") == synth.ANCHOR
    rows = synth.jsonl_rows(synth.SEED_MOM, 300, **kw)
    assert rows[-1]["date"] == synth.ANCHOR and all(r["source"] == synth.SOURCE for r in rows)


def test_prices_stay_finite_positive_including_lowest_band():
    """合成价格跨多个数量级：有效数字量化后恒正且有限，相邻收盘收益不超截断
    （定点位舍入会把 1e-7 量级的价格 round 成 0.0 → 下游除零）。"""
    lo = None
    for i, (sym, kw) in enumerate(synth.event_market_tickers().items()):
        c = np.array([r["close"] for r in synth.jsonl_rows(**kw)])
        assert np.isfinite(c).all() and (c > 0).all()
        assert np.abs(np.log(c[1:] / c[:-1])).max() <= synth.DAILY_CLIP + 1e-5   # 截断作用在对数收益上
        lo = c.min() if lo is None else min(lo, c.min())
    assert lo < 0.01                        # 确实覆盖到极小价位


def test_jsonl_roundtrip_exact_all_tickers(tmp_path):
    """全部合成票、两条事件管道：落盘 jsonl 与生成器逐值一致，两管道的加载器读回相同。"""
    tickers = synth.event_market_tickers()
    assert len(tickers) == synth.N_TICKERS == 12 + 12 + 35
    synth.write_cache(tmp_path, tickers)
    sb = run_check._load_module(run_check.SB_NAME, run_check.SB_PATH)
    jn = run_check._load_module(run_check.JN_NAME, run_check.JN_PATH)
    for sym, kw in tickers.items():
        rows = [json.loads(ln) for ln in (tmp_path / f"{sym}.jsonl").read_text().splitlines()]
        extra = {k: v for k, v in kw.items() if k not in ("seed", "n", "gen")}
        dates, o, hgh, low, c = synth.ohlc_frame(kw["seed"], kw["n"], kw.get("gen", "daily"), **extra)
        assert [r["date"] for r in rows] == [d.strftime("%Y-%m-%d") for d in dates]
        for key, arr in (("open", o), ("high", hgh), ("low", low), ("close", c)):
            np.testing.assert_array_equal([r[key] for r in rows], [synth._q(x) for x in arr])
        file_vals = {k: np.array([r[k] for r in rows]) for k in ("open", "high", "low", "close")}
        di, o2, h2, l2, c2 = sb.load_symbol(tmp_path / f"{sym}.jsonl")
        np.testing.assert_array_equal([o2, h2, l2, c2], [file_vals[k] for k in ("open", "high", "low", "close")])
        dj, o3, c3 = jn.load_symbol(tmp_path / f"{sym}.jsonl")
        np.testing.assert_array_equal([o3, c3], [file_vals["open"], file_vals["close"]])
        assert (dj == di).all()


def test_all_codes_pass_both_pipelines_whitelist():
    sb = run_check._load_module(run_check.SB_NAME, run_check.SB_PATH)
    jn = run_check._load_module(run_check.JN_NAME, run_check.JN_PATH)
    for sym in synth.event_market_tickers():
        assert sb.UNIVERSE_RE.match(sym) and jn.UNIVERSE_RE.match(sym), sym


def test_noise_market_is_planted_minus_edge_terms():
    """配对：对照市场与埋边市场同票码、同种子，只去掉动量项与反弹项。"""
    planted, noise = synth.event_market_tickers(), synth.noise_market_tickers()
    assert set(planted) == set(noise) and len(planted) == synth.N_TICKERS
    for sym in synth.EDGE_MOM + synth.EDGE_BOUNCE:
        assert planted[sym]["seed"] == noise[sym]["seed"]
        assert "momentum" not in noise[sym] and noise[sym].get("gen", "daily") == "daily"


# ---------------------------------------------------------------- 写守卫（r4 I-1）

def _fake_repo(tmp_path, monkeypatch):
    fake = tmp_path / "repo"
    real = fake / "data" / "wyckoff" / "daily"
    real.mkdir(parents=True)
    (real / "609900.SH.jsonl").write_text('{"date": "2020-01-01", "close": 1, "source": "mootdx-wyckoff"}\n')
    monkeypatch.setattr(synth, "REPO", fake)
    monkeypatch.setattr(synth, "DATA_DIR", fake / "data")
    monkeypatch.setattr(synth, "SYNTH_HOME", fake / "data" / "planted-benchmark")
    return fake, real


TICK1 = {synth.EDGE_BOUNCE[0]: dict(seed=1, n=30, gen="bounce")}


@pytest.mark.parametrize("target", ["wyckoff/daily", "market/series", ".", ".."])
def test_write_guard_rejects_real_data_dirs(tmp_path, monkeypatch, target):
    """指向仓库 data/ 下任何非 planted-benchmark 目录一律拒绝，哨兵文件原样；
    经符号链接绕入同样拒绝。"""
    fake, real = _fake_repo(tmp_path, monkeypatch)
    before = {p.name: p.read_text() for p in real.iterdir()}
    victim = (real / target).resolve()
    with pytest.raises(SystemExit):
        synth.write_cache(victim, TICK1)
    with pytest.raises(SystemExit):
        synth.write_sr_market(victim)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(SystemExit):
        synth.write_cache(link / target if target not in (".", "..") else link, TICK1)
    assert {p.name: p.read_text() for p in real.iterdir()} == before


def test_write_guard_allows_synthetic_home_and_outside(tmp_path, monkeypatch):
    fake, real = _fake_repo(tmp_path, monkeypatch)
    assert synth.write_cache(fake / "data" / "planted-benchmark" / "cache", TICK1).is_dir()
    assert synth.write_sr_market(fake / "data" / "planted-benchmark" / "sr").is_dir()
    assert synth.write_cache(tmp_path / "elsewhere", TICK1).is_dir()
    assert synth.write_sr_market(tmp_path / "elsewhere-sr").is_dir()
    assert set(p.name for p in real.iterdir()) == {"609900.SH.jsonl"}


def test_write_cache_clears_own_stale_and_refuses_foreign(tmp_path):
    own = tmp_path / "c"
    own.mkdir()
    (own / "609901.SH.jsonl").write_text(json.dumps({"source": synth.SOURCE}) + "\n")
    synth.write_cache(own, TICK1)                                   # 自己上一轮写的陈旧票被清掉
    assert not (own / "609901.SH.jsonl").exists()
    foreign = own / "999999.SH.jsonl"
    foreign.write_text('{"source": "someone-else"}\n')
    with pytest.raises(SystemExit):
        synth.write_cache(own, TICK1)
    assert foreign.read_text() == '{"source": "someone-else"}\n'      # 不是自己的不清理


def test_cli_guard_rejects_real_cache_before_any_write(tmp_path, monkeypatch, capsys):
    """CLI 旗标误传到真实缓存路径：写守卫先于一切写入生效。"""
    fake, real = _fake_repo(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        run_check.main(["event", "--cache-root", str(real)])
    with pytest.raises(SystemExit):
        run_check.main(["sr", "--sr-root", str(fake / "data"), "--n-perm", "5"])
    assert [p.name for p in real.iterdir()] == ["609900.SH.jsonl"]
    assert (real / "609900.SH.jsonl").read_text().startswith('{"date": "2020-01-01"')


# ---------------------------------------------------------------- 判定逻辑

def test_verdict_three_states_and_insufficient():
    v = run_check._verdict
    assert v(True, False) == run_check.VERDICT_OK
    assert v(False, False) == run_check.VERDICT_STRICT
    assert v(True, True) == run_check.VERDICT_LOOSE
    assert v(True, True, False) == run_check.VERDICT_INSUFF
    assert v(False, False, False) == run_check.VERDICT_INSUFF        # 样本不足优先于三态


def test_nan_comparisons_never_pass():
    assert not run_check._gt(NAN, -1) and not run_check._lt(NAN, 99)
    assert not run_check._gt(None, -1) and not run_check._lt(None, 99)
    assert run_check._gt(2, 1) and run_check._lt(1, 2)


GOOD_EDGE = dict(alpha_mean=0.02, alpha_t=10.0, pos_ratio=1.0, n_sig=700)
CLEAN = dict(alpha_mean=0.0005, alpha_t=0.5, n_eff=35, n_sig=2000)
RC = run_check


@pytest.mark.parametrize("patch", [
    dict(alpha_mean=RC.EDGE_ALPHA_MIN / 2),      # 只违 alpha 下限
    dict(alpha_t=RC.EDGE_T_MIN / 2),             # 只违 t 下限
    dict(alpha_t=NAN), dict(alpha_t=None),       # t 缺失/NaN
    dict(alpha_mean=NAN),                        # alpha 缺失
    dict(pos_ratio=RC.EDGE_POS_MIN - 0.3),       # 只违正率
    dict(n_sig=RC.EDGE_NSIG_MIN - 1),            # 只违信号数
])
def test_judge_event_each_positive_criterion_bites(patch):
    assert not RC._judge_event({**GOOD_EDGE, **patch}, {}, CLEAN, CLEAN)["planted_passed"]
    assert RC._judge_event(GOOD_EDGE, {}, CLEAN, CLEAN)["planted_passed"]


EMPTY = object()                                       # 对照臂整体没有样本


@pytest.mark.parametrize("noise, expected", [
    (dict(alpha_mean=RC.NOISE_ALPHA_MAX * 3), RC.VERDICT_LOOSE),     # 只违 alpha 上限
    (dict(alpha_t=RC.NOISE_T_MAX * 2), RC.VERDICT_LOOSE),            # 只违 t 上限
    (dict(alpha_t=NAN), RC.VERDICT_INSUFF),                          # t 为 NaN → 不足，不算干净
    (dict(n_eff=RC.NOISE_NEFF_MIN - 1), RC.VERDICT_INSUFF),          # 有效票不足
    (EMPTY, RC.VERDICT_INSUFF),                                       # 空样本 → 不足，不算干净
])
def test_judge_event_chuji_control_arm_states(noise, expected):
    control = {} if noise is EMPTY else {**CLEAN, **noise}
    res = RC._judge_event(GOOD_EDGE, {}, control, CLEAN)
    assert res["verdict"] == expected
    assert res["noise_leaked"] == (expected == RC.VERDICT_LOOSE)


def test_judge_event_jinniu_control_arm_participates():
    """jinniu 臂只判阴性——但对照票上有 alpha 时同样报「过松」。"""
    leak = dict(alpha_mean=0.02, alpha_t=6.0, n_eff=35, n_sig=1500)
    res = RC._judge_event(GOOD_EDGE, {}, CLEAN, leak)
    assert res["verdict"] == RC.VERDICT_LOOSE
    assert res["jinniu_positive"].startswith("未验证")


GOOD_P = dict(d9_d0_spread=0.15, ic_mean=0.10, ic_t=7.0, ic_t_overlap=30.0)
CLEAN_N = dict(d9_d0_spread=0.003, ic_t=0.1, ic_t_overlap=0.3, n_windows=75)


@pytest.mark.parametrize("patch", [
    dict(d9_d0_spread=RC.RPS_SPREAD_MIN / 2),    # 只违价差下限
    dict(ic_mean=RC.RPS_IC_MEAN_MIN / 2),        # 只违 IC 均值下限
    dict(ic_t=RC.RPS_IC_T_MIN / 2),              # 只违 t 下限
    dict(ic_t=NAN),
])
def test_judge_rps_each_positive_criterion_bites(patch):
    assert not RC._judge_rps({**GOOD_P, **patch}, CLEAN_N)["planted_passed"]
    assert RC._judge_rps(GOOD_P, CLEAN_N)["planted_passed"]


@pytest.mark.parametrize("noise, expected", [
    (dict(d9_d0_spread=RC.RPS_NOISE_SPREAD_MAX * 2), RC.VERDICT_LOOSE),
    (dict(ic_t=RC.RPS_NOISE_T_MAX * 2), RC.VERDICT_LOOSE),
    (dict(ic_t=NAN), RC.VERDICT_INSUFF),
    (dict(n_windows=RC.RPS_MIN_WINDOWS - 1), RC.VERDICT_INSUFF),
])
def test_judge_rps_control_states(noise, expected):
    res = RC._judge_rps(GOOD_P, {**CLEAN_N, **noise})
    assert res["verdict"] == expected


def test_judge_rps_reports_factory_naive_t_separately():
    """出厂 validity.py 的 naive t 在对照市场过 2：只进报告位，不改三态判定。"""
    res = RC._judge_rps(GOOD_P, {**CLEAN_N, "ic_t_overlap": 3.8})
    assert res["validity_naive_leaked"] and res["verdict"] == RC.VERDICT_OK
    assert not RC._judge_rps(GOOD_P, CLEAN_N)["validity_naive_leaked"]
    assert RC._judge_rps(GOOD_P, CLEAN_N)["naive_inflation"] == pytest.approx(30.0 / 7.0)


def test_sr_matrix_all_pass_needs_every_cell():
    rows = {t: {r: 0.001 for r in run_check.SR_ROWS} for t in run_check.TIERS}
    assert run_check._matrix_all_pass(rows)
    for tier in run_check.TIERS:
        for row in run_check.SR_ROWS:
            bad = copy.deepcopy(rows)
            bad[tier][row] = run_check.ALPHA                 # 等于阈值即不过（单侧 p<α）
            assert not run_check._matrix_all_pass(bad)
    bad = copy.deepcopy(rows)
    bad["base"]["vs随机"] = NAN
    assert not run_check._matrix_all_pass(bad)               # NaN 不算通过


def test_warmup_contract_reports_first_available_bar():
    rows = 501

    def frame(first_nonnan):                      # 1-based 首个非空 bar 序号
        col = [np.nan] * rows
        for i in range(first_nonnan - 1, rows):
            col[i] = 1.0
        return pd.DataFrame({"x": col})

    ok = {"rps50": frame(250), "rps120": frame(250), "rps250": frame(251)}
    assert RC._warmup_contract(ok) == {"documented_min_bars": 250,
                                       "first_bar": {"rps50": 250, "rps120": 250, "rps250": 251},
                                       "ok": True}
    late = {"rps50": frame(300), "rps120": frame(370), "rps250": frame(500)}
    got = RC._warmup_contract(late)
    assert got["first_bar"] == {"rps50": 300, "rps120": 370, "rps250": 500} and not got["ok"]


# ---------------------------------------------------------------- 端到端：SR

def test_sr_planted_found_control_rejected(sr_baseline):
    v = sr_baseline
    assert v["verdict"] == run_check.VERDICT_OK and v["planted_passed"] and not v["noise_leaked"]
    for tier in run_check.TIERS:
        assert all(v["planted"][tier][r] < run_check.ALPHA for r in run_check.SR_ROWS)
        # 对照宇宙的 vs随机 / vs等权 两行都不显著放过（两档）。
        # vs沪深300 行在出厂对照宇宙的基准档是 0.037——六格里有一格偶然通过，这一行
        # 的阴性对照在出厂市场上没有被锁住（README 已知限制）。
        assert v["noise"][tier]["vs随机"] >= run_check.ALPHA
        assert v["noise"][tier]["vs等权"] >= run_check.ALPHA


def test_sr_matrix_rows_wired_to_real_tests(tmp_path):
    """三行 p 值必须真算：与暴露出的周序列经同一函数重算逐值相等（钉成常数会被抓住）。"""
    wf = run_check.build_weekly_frame(synth.write_sr_market(tmp_path), run_check._sr_spec(),
                                      bench_symbol=synth.SR_BENCH, pick_bypass_single=True)
    rows, series = run_check._sr_matrix(wf, n_perm=30)
    start = run_check.coverage_start(wf, min_universe=synth.SR_N)
    for tier, cost in (("base", run_check.CostModel.base()), ("stress", run_check.CostModel.stress())):
        assert rows[tier]["vs等权"] == run_check.paired_block_bootstrap(series[tier]["vs等权"])
        assert rows[tier]["vs沪深300"] == run_check.paired_block_bootstrap(series[tier]["vs沪深300"])
        assert rows[tier]["vs随机"] == run_check.perm_test_vs_random(
            wf, cost, k=run_check.K, n=30, strategy=run_check._l0, start=start)["p_value"]
    assert len(series["base"]["vs等权"]) == rows["base"]["n_oos"]


def test_sr_removing_edge_turns_strict_and_is_paired(tmp_path, monkeypatch):
    """拆掉动量项：埋边宇宙与对照宇宙逐格相同（配对），判定翻成「过严」。"""
    monkeypatch.setattr(synth, "SR_MOM_COEF", 0.0)
    v = run_check.check_sr(tmp_path, n_perm=N_PERM_FAST)
    assert not v["planted_passed"] and v["verdict"] == run_check.VERDICT_STRICT
    for tier in run_check.TIERS:
        for row in run_check.SR_ROWS:
            assert v["planted"][tier][row] == v["noise"][tier][row]


def test_sr_control_replaced_by_edged_universe_reports_loose(tmp_path):
    v = run_check.check_sr(tmp_path, n_perm=N_PERM_FAST,
                           noise_writer=lambda r: synth.write_sr_market(r))
    assert v["noise_leaked"] and v["verdict"] == run_check.VERDICT_LOOSE


def test_sr_insufficient_when_oos_too_short(tmp_path, monkeypatch):
    monkeypatch.setattr(run_check, "SR_MIN_OOS", 10 ** 6)
    v = run_check.check_sr(tmp_path, n_perm=N_PERM_FAST)
    assert v["verdict"] == run_check.VERDICT_INSUFF


def test_event_filter_retention_arithmetic(monkeypatch):
    """保留率 = 被过滤保留的基础率样本数 / 可执行域大小（idx ≥ 1 且 idx+1+h < n）。"""
    n = 30

    class Fake:
        GAP_DAYS = 10

        @staticmethod
        def load_symbol(path):
            return np.arange(n), np.arange(float(n))

        @staticmethod
        def event_returns(di, o, sig, h, gap):
            idx = np.arange(1, n - 2 - h)                 # 保留 n-3-h 个
            return idx, np.zeros(len(idx))

    monkeypatch.setattr(run_check, "_load_module", lambda name, path: Fake)
    h = 5
    assert run_check.event_filter_retention(Path("."), ["A", "B"], hs=(h,)) == {
        "stage-bottom": {h: (n - 3 - h) / (n - 2 - h)}, "jinniu": {h: (n - 3 - h) / (n - 2 - h)}}


# ---------------------------------------------------------------- 端到端：事件族

def test_event_planted_found_control_clean(event_baseline):
    v = event_baseline
    assert v["verdict"] == run_check.VERDICT_OK and v["planted_passed"]
    assert not v["noise_leaked"] and v["sufficient"] and v["jinniu_wiring_ok"] is True
    e = v["edge_chuji"]
    assert e["alpha_mean"] > run_check.EDGE_ALPHA_MIN and e["alpha_t"] > run_check.EDGE_T_MIN
    for arm in ("noise_chuji", "noise_jinniu"):
        assert v[arm]["n_eff"] >= run_check.NOISE_NEFF_MIN
        assert abs(v[arm]["alpha_t"]) < run_check.NOISE_T_MAX
    assert v["jinniu_positive"].startswith("未验证")
    # 既有管道的停牌过滤在零停牌合成市场上的保留率与注记一致（修好后两边同时翻）
    flagged = any("停牌过滤" in n for n in v["notes"])
    low = any(per[run_check.EVENT_H] < run_check.EVENT_FILTER_RETENTION_MIN for per in v["retention"].values())
    assert flagged == low


def test_var19_enrichment_uses_matched_window_baseline(event_baseline):
    """VAR19 点火与注入窗无富集；基准是「前瞻窗含注入日」的概率，不是单日注入占比。"""
    e = event_baseline["enrichment"]
    assert 0.7 < e["enrichment"] < 1.3
    assert e["base_rate"] > e["single_day_injection_share"] * 1.2
    assert abs(e["hit_rate"] - e["base_rate"]) < 0.1


def test_jinniu_wiring_check_has_discriminating_power(tmp_path):
    """接线核对能分清 buy 与 sell：预期样本数取自 buy 信号，绝大多数票上与 sell 不同。"""
    jn = run_check._load_module(run_check.JN_NAME, run_check.JN_PATH)
    from jinniu import icon_signals
    synth.write_cache(tmp_path, synth.event_market_tickers(600))
    differs = 0
    for sym in synth.EDGE_BOUNCE[:6] + synth.NOISE[:6]:
        di, o, c = jn.load_symbol(tmp_path / f"{sym}.jsonl")
        ib, is_ = icon_signals(c)
        ib[:jn.WARMUP] = False
        is_[:jn.WARMUP] = False
        nb = int(jn.event_returns(di, o, ib, 1, jn.GAP_DAYS)[0].size)
        ns = int(jn.event_returns(di, o, is_, 1, jn.GAP_DAYS)[0].size)
        assert run_check._jinniu_expected_n(jn, tmp_path, sym) == nb
        differs += nb != ns
    assert differs >= 10


def test_jinniu_wiring_check_raises_on_mismatch():
    run_check._check_jinniu_wiring(1234, 1234)
    with pytest.raises(ValueError):
        run_check._check_jinniu_wiring(1234, 1233)         # 差一个样本即抛
    with pytest.raises(ValueError):
        run_check._check_jinniu_wiring(0, 1234)            # 漏读整臂


def test_event_control_contaminated_with_edge_reports_loose(tmp_path):
    tickers = synth.event_market_tickers()
    for i, sym in enumerate(synth.NOISE):                      # 对照票被换成有反弹边的
        tickers[sym] = dict(seed=synth.SEED_NOISE + i, n=synth.N_EVENT_BARS, gen="bounce")
    v = run_check.check_event(tmp_path, tickers=tickers)
    assert v["noise_leaked"] and v["verdict"] == run_check.VERDICT_LOOSE


def test_event_without_control_tickers_is_insufficient(tmp_path):
    tickers = {s: kw for s, kw in synth.event_market_tickers().items()
               if s in synth.EDGE_BOUNCE or s in synth.EDGE_MOM}
    v = run_check.check_event(tmp_path, tickers=tickers)
    assert v["verdict"] == run_check.VERDICT_INSUFF and not v["noise_leaked"]


# ---------------------------------------------------------------- 端到端：rps

def test_rps_planted_found_control_silent(rps_baseline):
    v = rps_baseline
    p, n = v["arms"]["planted"]["fwd20"], v["arms"]["noise"]["fwd20"]
    assert v["verdict"] == run_check.VERDICT_OK and v["planted_passed"]
    assert not v["noise_leaked"] and v["sufficient"]
    assert abs(n["d9_d0_spread"]) < run_check.RPS_NOISE_SPREAD_MAX
    assert abs(n["ic_t"]) < run_check.RPS_NOISE_T_MAX
    # 去重叠必须真去：埋边市场上出厂 naive t 约为去重叠 t 的 √20 倍
    assert 3.0 < abs(p["ic_t_overlap"]) / abs(p["ic_t"]) < 6.0
    assert p["ic_t_phase_min"] <= p["ic_t"] <= p["ic_t_phase_max"]
    assert p["n_days"] // p["n_windows"] >= 15          # 窗数约为日数的 1/20


def test_rps_control_replaced_by_edged_market_reports_loose(tmp_path):
    v = run_check.check_rps(tmp_path, noise_writer=lambda r: synth.write_cache(r, synth.event_market_tickers()))
    assert v["noise_leaked"] and v["verdict"] == run_check.VERDICT_LOOSE


# ---------------------------------------------------------------- CLI 与装载

def test_cli_rejects_nonpositive_perm(tmp_path, capsys):
    for bad in ("0", "-5"):
        with pytest.raises(SystemExit):
            run_check.main(["sr", "--n-perm", bad, "--sr-root", str(tmp_path)])
        assert "置换数须" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []                 # 报错发生在任何写入之前


def test_cli_event_exit_code_follows_verdict(tmp_path, capsys):
    assert run_check.main(["event", "--cache-root", str(tmp_path / "a")]) == 0
    assert "planted[event] → 量具正常" in capsys.readouterr().out
    assert run_check.main(["event", "--cache-root", str(tmp_path / "a"),
                           "--strict"]) == 1            # 出厂管道带契约偏差注记：--strict 算失败
    assert "⚠" in capsys.readouterr().out


def test_load_module_cached_no_syspath_growth():
    before = len(sys.path)
    run_check._load_module(run_check.JN_NAME, run_check.JN_PATH)
    once = len(sys.path)
    run_check._load_module(run_check.JN_NAME, run_check.JN_PATH)
    run_check._load_module(run_check.SB_NAME, run_check.SB_PATH)
    assert len(sys.path) - once <= 1                     # 重复装载不再累加 sys.path
    assert once >= before
