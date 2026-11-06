# tests/test_sr_repro.py
import numpy as np
import pytest

pytest.importorskip("torch")            # repro_paper 顶部 import models

from repro_paper import (PREREG_CONFIG, YEARS, _paper_cell,  # noqa: E402
                         alpha_vs_paper, annual_group_returns, exec_iso_year,
                         verdict)


def test_years_window_frozen():
    assert list(YEARS) == list(range(2012, 2023))     # 尾段 2023+ 处女，硬编码


def test_paper_cell_renders():
    # 终审修复波：旧守卫 `"{}" in fmt` 对 "{:+.2%}" 恒 False，论文列误渲染「—」
    assert _paper_cell(0.1263, "{:+.2%}") == "+12.63%"   # PAPER mean_alpha 格式
    assert _paper_cell(None, "{:+.2%}") == "—"           # 论文无此口径（净 α 行）
    assert _paper_cell(10, "{}/11") == "10/11"           # 正年数行格式串本身含字面量


def test_prereg_config_frozen():
    # 计划评审 M-4：预注册三处载体（spec §6.3 行 / PREREG_CONFIG / 报告注入）
    # 的关键 token 集合——含两项用户已拍板方向决策（偏差⑦⑨）与归年/择格规则。
    for token in ("N∈{13,26,52}", "seed=20261106", "2012-01-01:2022-12-31",
                  "open→close", "trailing 52", "执行周 ISO 年", "最强格",
                  "SPY", "等权"):
        assert token in PREREG_CONFIG


def test_annual_group_returns_by_exec_year():
    keys = [2012, 2012, 2013, 2013]
    weekly = np.array([0.10, 0.10, -0.5, 0.0])
    got = annual_group_returns(keys, weekly)
    assert abs(got[2012] - 0.21) < 1e-12 and abs(got[2013] - (-0.5)) < 1e-12


def test_exec_iso_year_boundaries():
    # 计划评审 I-7：年归属 = 执行周 ISO 年——跨年决策周（W52/W53）归下一 ISO 年
    assert exec_iso_year("2019-06-07") == 2019
    assert exec_iso_year("2016-12-30") == 2017     # W52 周五 → 执行周 W1-2017
    assert exec_iso_year("2020-12-31") == 2021     # W53 周四（Good Friday 型短周）


def test_verdict_domains():
    assert verdict(0.10, 8).startswith("A")
    assert verdict(0.03, 5).startswith("B")
    assert "不预指派" in verdict(0.03, 5)          # 计划评审 I-5：并列归因
    assert verdict(-0.02, 3).startswith("C")
    assert verdict(0.10, 5).startswith("B")        # 均值够但正年数不足


def test_alpha_arithmetic():
    a = alpha_vs_paper({2022: 0.1029}, {2022: -0.1811})
    assert abs(a[2022] - 0.284) < 1e-9             # 论文 2022 α=+28.4% 同口径
