# tools/sector-rotation/build_universe.py
"""宇宙构建（spec §3.1 point-in-time / §3.6 滞后簇 / §5 P0 数据现实曲线）。

产出一稿 config/sector-rotation-universe.md（候选集 + 簇代，status: draft）+
data/sector-rotation/coverage-curve.md（逐年可用宇宙曲线）。draft 走 review-queue。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "tools" / "daily-watch" / "scripts"))

from sector_rotation.universe import Member, UniverseSpec, write_universe  # noqa: E402
from mootdx_source import _mootdx_call  # noqa: E402

EXCLUDE = re.compile(
    r"沪深300|中证500|中证1000|中证A50|上证50|创业板|创业|双创|创50|创300|创增|创综|科创|红利|低波|"
    r"价值|成长|纳指|纳斯达克|纳100|标普|美国|日经|恒生|恒指|香港|港股|HK|H股|东证|225|QDII|MSCI|"
    r"亚洲|新兴|德国|法国|沙特|深证|深成|深100|综指|治理|超大|商品|城投|短融|国开|央企|央调|湾区|"
    r"湾创|成渝|湖北|长江|张江|共赢|增强|A500|A100|A50|A股|2000|1000|800|500|300|云50|"
    r"认购|现金|快线|快钱|保证金|质量|港|恒|AH|中概|亚太|巴西|沪港深|国企|均衡|央创|战略|"
    r"新经济|漂亮|央视|基本面|民企|中小|中创|深F|深主板|大盘|ESG|上海金|金ETF|"
    r"黄金(?!股)|豆粕|有色期货|能源化工|原油|货币|债|国债|信用|转债|添益|理财")  # M4：黄金(?!股)——黄金股 ETF 属行业票要保留
# 注 1：brief 原文为「创业板指」，对 159915「创业板ETF」不命中（brief 自带测试要求剔除），
# 按 brief 测试为准改为「创业板」并扩至创业/双创/创50 等宽基族。
# 注 2（首跑实测 2026-11-05）：TDX `stocks` 显示名是 8 字缩写，沪市 51/56/58 段 1131 只中
# 989 只名字不含「ETF」（512480 显示名就是「半导体」）——brief 的 `"ETF" not in name`
# 会把整个沪市行业 ETF 主力段剔光。改为交易所 ETF 段位白名单 + 市场标注双判，
# 511 债/货、513 跨境、518 金、519 场外、530 沪市宽基老段、551 科创债、581 主动管理
# 整段不进池；EXCLUDE 同步补首跑实测漏网的宽基/区域/策略/货基缩写名。
# 注 3（同日二跑实测）：深市 520xxx-563xxx 是债券代码段（「26伊犁02」等），与沪市
# ETF 新段 520/56x 撞号——段位判必须带市场（market=0 只认 158/159，market=1 只认沪段），
# 否则 1500+ 深市债混进候选池。

SH_ETF_SEG = re.compile(r"^(512|515|516|517|520|526|560|561|562|563|588|589)\d{3}$")
SZ_ETF_SEG = re.compile(r"^(158|159)\d{3}$")

KEYWORDS: dict[str, list[str]] = {
    # —— brief 底稿（原文保留；键须为 881 行业实名，风电/运输设备/新能源车/医药/教育
    #    五键无同名行业实际不触发，交人工复核时取舍）——
    "证券": ["证券", "券商"], "银行": ["银行"], "保险": ["保险"],
    "半导体": ["半导体", "芯片"], "软件服务": ["软件", "计算机"],
    "通信设备": ["通信", "5G"], "电子": ["电子"], "白酒": ["酒"],
    "食品饮料": ["食品饮料", "消费"], "医药": ["医药", "医疗", "创新药", "生物医药"],
    "中药": ["中药"], "煤炭": ["煤炭"], "钢铁": ["钢铁"],
    "有色": ["有色", "稀土", "黄金股"], "石油": ["石油", "油气"],
    "化工": ["化工", "碳中和"], "电力": ["电力"], "光伏": ["光伏"],
    "风电": ["风电"], "新能源车": ["新能源车", "智能汽车", "汽车"],
    "电池": ["电池"], "军工": ["军工", "国防"], "机械": ["机械", "智能制造"],
    "建筑": ["基建", "建筑材料"], "房地产": ["地产"], "家用电器": ["家电"],
    "农业": ["农业", "养殖"], "运输设备": ["高铁"], "航空": ["航空"],
    "航运": ["交运", "船舶"], "传媒": ["传媒", "游戏"], "教育": ["教育"],
    # （房地产/航运两键值按首跑实测改：TDX 缩写名只有「地产」无「房地产」、
    #   无「航运」名 ETF，用交运/船舶近邻主题 proxy，人工复核）
    # —— 首跑后按 unmatched.txt 补齐（执行注 2；关键词口径 = TDX 缩写显示名。
    #    粗 proxy（行业→近邻主题 ETF）带人工复核，review-queue 确认时逐条过目）——
    "动力煤": ["煤炭", "能源"], "炼焦煤": ["煤炭", "能源"], "焦炭加工": ["煤炭"],
    "油服工程": ["油气", "石油"], "油田服务": ["油气", "石油"], "油气工程": ["油气", "石油"],
    "石油化工": ["石化", "石油"], "炼油化工": ["石化", "石油"],
    "石油贸易": ["石化", "石油"], "其他石化": ["石化"],
    "日用化工": ["化工"],
    "其他化学": ["化工"], "化学原料": ["化工"], "煤化工": ["化工"], "钛白粉": ["化工"],
    "氯碱": ["化工"], "纯碱": ["化工"], "无机盐": ["化工"], "有机化工": ["化工"],
    "化学制品": ["化工"], "聚氨酯": ["化工"], "涂料油墨": ["化工"], "民爆制品": ["化工"],
    "纺织化学": ["化工"], "氟化工": ["化工"], "有机硅": ["化工"], "胶黏剂及": ["化工"],
    "化纤": ["化工", "新材"], "碳纤维": ["新材", "材料"],
    "塑料": ["化工", "新材"], "合成树脂": ["化工", "新材"], "塑料薄膜": ["化工", "新材"],
    "改性塑料": ["化工", "新材"], "合成革": ["化工", "新材"], "塑料助剂": ["化工", "新材"],
    "其他塑料": ["化工", "新材"], "橡胶": ["化工", "新材"], "橡胶助剂": ["化工", "新材"],
    "炭黑": ["化工", "新材"], "橡胶制品": ["化工", "新材"],
    "农用化工": ["化工", "农业", "粮食"], "农药": ["化工", "农业"],
    "氮肥": ["化工", "粮食"], "磷肥及磷": ["化工", "粮食"], "钾肥": ["化工", "粮食"],
    "复合肥": ["化工", "粮食"],
    "冶钢原料": ["钢铁"], "铁矿石": ["钢铁", "矿业"], "冶钢辅料": ["钢铁"],
    "普钢": ["钢铁"], "长材": ["钢铁"], "板材": ["钢铁"], "其他钢材": ["钢铁"], "特钢": ["钢铁"],
    "铜": ["有色", "矿业"], "铝": ["有色", "矿业"], "铅锌": ["有色", "矿业"],
    "贵金属": ["黄金股", "有色", "矿业"], "黄金": ["黄金股", "有色", "矿业"],
    "白银": ["有色", "矿业", "黄金股"],
    "能源金属": ["有色", "矿业", "稀有"], "锂": ["有色", "矿业", "稀有"], "钴": ["有色", "矿业", "稀有"],
    "钨钼": ["有色", "矿业", "稀有"], "钛": ["有色", "矿业", "稀有"],
    "其他金属": ["有色", "矿业", "新材"], "金属新材": ["有色", "新材", "材料"],
    "磁性材料": ["有色", "新材", "材料"],
    "水泥": ["建材", "材料"], "水泥制造": ["建材", "材料"], "水泥制品": ["建材", "材料"],
    "玻璃玻纤": ["建材", "材料"], "玻璃制造": ["建材", "材料"], "玻纤制造": ["建材", "材料"],
    "装饰建材": ["建材", "材料"], "陶瓷": ["建材", "材料"], "管材": ["建材", "材料"],
    "耐火材料": ["建材", "材料"], "防水材料": ["建材", "材料"], "涂料": ["建材", "材料"],
    "其他建材": ["建材", "材料"], "非金属材": ["建材", "材料"],
    "农林牧渔": ["农业", "农牧", "粮食"],
    "种植业": ["粮食", "农业"], "粮食种植": ["粮食", "农业"], "种子": ["粮食", "农业"],
    "其他种植": ["粮食", "农业"], "食用菌": ["粮食", "农业"],
    "养殖业": ["养殖", "畜牧", "农牧"], "生猪养殖": ["养殖", "畜牧", "农牧"],
    "肉鸡养殖": ["养殖", "畜牧", "农牧"], "其他养殖": ["养殖", "畜牧", "农牧"],
    "饲料": ["养殖", "农牧", "农业"], "畜禽饲料": ["养殖", "农牧", "农业"],
    "水产饲料": ["养殖", "农牧", "农业"],
    "农产品加": ["粮食", "食品", "农业"], "粮油加工": ["粮食", "食品"],
    "果蔬加工": ["粮食", "食品"], "其他农产": ["粮食", "食品", "农业"],
    "酿酒": ["酒"], "啤酒": ["酒", "食品"], "葡萄酒": ["酒"], "黄酒": ["酒"],
    "其他酒类": ["酒"],
    "饮料乳品": ["食品", "饮料", "消费"], "软饮料": ["食品", "饮料"],
    "乳制品": ["食品", "饮料"], "调味品": ["食品", "消费"],
    "休闲食品": ["食品"], "零食": ["食品"], "烘焙食品": ["食品"], "熟食": ["食品"],
    "肉制品": ["食品"], "预加工食": ["食品"], "其他食品": ["食品"], "制糖业": ["食品"],
    "保健品": ["保健", "食品"],
    "白色家电": ["家电", "家居"], "空调": ["家电"], "冰洗": ["家电"],
    "黑色家电": ["家电"], "电视": ["家电"], "其他黑色": ["家电"], "小家电": ["家电"],
    "厨房小家": ["家电"], "清洁小家": ["家电"], "个护小家": ["家电"],
    "厨卫电器": ["家电"], "厨房电器": ["家电"], "卫浴电器": ["家电"], "家电零部": ["家电"],
    "文化用品": ["文娱"], "娱乐用品": ["文娱"],
    "家具": ["家居", "家电"], "其他家居": ["家居", "家电"],
    "商贸": ["消费"], "一般零售": ["消费"], "超市及便": ["消费"], "百货": ["消费"],
    "多业态零": ["消费"], "商业物业": ["消费"], "专业连锁": ["消费"], "贸易": ["消费"],
    "综合电商": ["线上", "在线", "互联网", "消费"], "跨境电商": ["线上", "在线", "互联网"],
    "电商服务": ["线上", "在线", "互联网"],
    "乘用车": ["汽车", "电动汽车", "智能车", "新能"], "电动乘用": ["汽车", "电动汽车", "新能"],
    "综合乘用": ["汽车", "电动汽车"], "商用车": ["汽车"], "商用载货": ["汽车"],
    "商用载客": ["汽车"],
    "汽车零部": ["汽车", "汽零"], "车身附件": ["汽车", "汽零"], "底盘与发": ["汽车", "汽零"],
    "轮胎轮毂": ["汽车", "汽零"], "其他汽车": ["汽车", "汽零"],
    "摩托车及": ["汽车"], "摩托车": ["汽车"],
    "化学制药": ["医药", "制药"], "化学制剂": ["医药", "制药"], "原料药": ["医药"],
    "生物制品": ["生物", "生物医药"], "血液制品": ["生物", "医药"],
    "抗体": ["生物", "创新药", "医药"], "诊断试剂": ["医疗", "医药"],
    "体外诊断": ["医疗", "医药"], "基因药物": ["生物", "创新药"], "其他生物": ["生物"],
    "家用器械": ["器械"], "医疗设备": ["医疗", "器械"], "医疗耗材": ["器械", "医疗"],
    "制药装备": ["制药", "机械"], "诊断服务": ["医疗", "医药"],
    "医疗研发": ["医疗", "创新药"], "医院": ["医疗", "医药"], "其他医疗": ["医疗"],
    "医药商业": ["医药"], "医药流通": ["医药"], "线下药店": ["医药"],
    "医疗美容": ["医疗", "医药"], "医美耗材": ["医疗", "医药"],
    "电机制造": ["机械", "电力"], "燃料电池": ["电池"], "其他电池": ["电池"],
    "电池化学": ["电池"], "锂电设备": ["电池"],
    "电网设备": ["电网"], "电网自动": ["电网"], "输变电设": ["电网"],
    "配电设备": ["电网"], "线缆部件": ["电网"], "电工仪器": ["电网"],
    "光伏设备": ["光伏"], "光伏硅料": ["光伏"], "光伏硅片": ["光伏"],
    "光伏电池": ["光伏"], "光伏逆变": ["光伏"], "光伏辅材": ["光伏"],
    "光伏加工": ["光伏"],
    "其他发电": ["电力", "绿电"], "水力发电": ["电力", "绿电"], "火力发电": ["电力", "绿电"],
    "热力服务": ["电力", "绿电"], "风力发电": ["电力", "绿电"], "光伏发电": ["电力", "光伏", "绿电"],
    "核力发电": ["电力", "绿电"], "电能综合": ["电力", "绿电"],
    "燃气": ["公用", "电力"], "水务": ["公用", "电力"], "公用事业": ["公用", "电力", "绿电"],
    "地面兵装": ["军工", "国防"], "航空装备": ["军工", "航空", "航天"],
    "航天装备": ["航天", "军工", "卫星"], "航海装备": ["船舶", "军工"],
    "军工电子": ["军工"], "电力设备": ["电力", "电网", "电池", "光伏"],
    "机械设备": ["机械", "装备", "智能制造"], "机床制造": ["机床", "母机", "机械"],
    "通用设备": ["机械", "装备"], "机械基础": ["机械", "装备"], "金属制品": ["机械", "装备"],
    "内燃机": ["机械", "装备"], "制冷空调": ["机械", "装备"], "磨具磨料": ["机械", "装备"],
    "其他通用": ["机械", "装备"], "专用设备": ["机械", "装备"], "能源及重": ["机械", "装备"],
    "印刷包装": ["机械", "装备"], "农用机械": ["机械", "装备"], "楼宇设备": ["机械", "装备"],
    "其他专用": ["机械", "装备"], "自动化设": ["机器人", "智能制造", "机械"],
    "机器人": ["机器人", "ROBOT"], "工业控制": ["机器人", "智能制造", "工业互联"],
    "激光设备": ["机械", "装备"], "其他自动": ["机器人", "机械"],
    "消费电子": ["消费电子", "电子消费", "消电"], "光学光电": ["电子", "消电"],
    "光学元件": ["电子", "消电"], "面板": ["电子", "消电"], "LED": ["电子"],
    "元器件": ["电子"], "被动元件": ["电子"], "其他电子": ["电子"],
    "电子化学": ["电子", "化工", "材料"],
    "半导体材": ["半导体", "半导材料"], "半导体设": ["半导体", "半导设备"],
    "集成电路": ["集成电路", "半导体", "芯片"], "功率半导": ["半导体", "芯片"],
    "半导体制": ["半导体"], "半导体封": ["半导体", "芯片"],
    "光纤光缆": ["通信"], "网络接配": ["通信", "网络"], "系统设备": ["通信", "计算机"],
    "其他通信": ["通信"], "电信服务": ["电信"], "电信运营": ["电信"], "电信增值": ["电信"],
    "网络规划": ["网络", "通信", "计算机"], "网络工程": ["网络", "通信", "计算机"],
    "网络优化": ["网络", "通信", "计算机"],
    "IT设备": ["计算机", "信创", "信息技术"], "安防设备": ["信息安全", "信创", "计算机"],
    "其他IT设": ["计算机", "信创"], "基础软件": ["软件", "信创"], "新兴软件": ["软件", "信创"],
    "行业应用": ["软件", "计算机"], "云服务": ["云", "云计算"], "云基础设": ["云", "云计算"],
    "云平台服": ["云", "云计算"], "云软件服": ["云", "云计算"], "其他云服": ["云", "云计算"],
    "产联网信": ["工业互联", "物联网"], "产联网平": ["工业互联", "物联网"],
    "产联网综": ["工业互联", "物联网"],
    "广告营销": ["传媒", "互联网"], "其他广告": ["传媒", "互联网"],
    "数字媒体": ["传媒", "文娱"], "视频音频": ["传媒", "文娱"], "文字图片": ["传媒", "文娱"],
    "出版业": ["传媒", "文娱"], "教育出版": ["传媒", "文娱"], "大众出版": ["传媒", "文娱"],
    "其他出版": ["传媒", "文娱"], "广播电视": ["传媒"], "发行院线": ["影视", "传媒"],
    "非银金融": ["证券", "保险"], "多元金融": ["金融", "金科"], "信托": ["金融"],
    "期货": ["金融"], "租赁": ["金融"], "投资管理": ["金融", "金科"],
    "金融控股": ["金融", "金科"], "其他金融": ["金融", "金科"],
    "全国性银": ["银行"], "国有大型": ["银行"], "股份制银": ["银行"], "地方性银": ["银行"],
    "城商行": ["银行"], "农商行": ["银行"], "非货币银": ["银行"],
    "房地产开": ["地产"], "住宅开发": ["地产"], "商业地产": ["地产"],
    "产业地产": ["地产"], "房产服务": ["地产"], "物业管理": ["地产"], "租赁经纪": ["地产"],
    "房屋建设": ["基建", "建筑"], "基础建设": ["基建", "建筑"], "园林工程": ["基建", "建筑"],
    "专业工程": ["基建", "建筑"], "化学工程": ["基建", "建筑", "化工"],
    "钢结构": ["基建", "建筑", "钢铁"], "国际工程": ["基建", "建筑"],
    "其他专业": ["基建", "建筑"], "工程咨询": ["基建", "建筑"], "装修装饰": ["基建", "建筑"],
    "社会服务": ["消服", "消费"], "酒店餐饮": ["饮食", "消费"], "酒店": ["饮食", "消费"],
    "餐饮": ["饮食", "消费"], "休闲综合": ["文娱", "消费"],
    "公路铁路": ["交运", "基建"], "铁路运输": ["交运", "基建"], "高速公路": ["交运", "基建"],
    "公共交通": ["交运"], "机场": ["航空", "交运"], "航运港口": ["交运", "船舶"],
    "港口": ["交运", "船舶"], "其他交通": ["交运", "汽车"],
    "供应链服": ["物流", "交运"], "跨境物流": ["物流", "交运"], "仓储物流": ["物流", "交运"],
    "公路货运": ["物流", "交运"],
    "环境治理": ["环保", "低碳", "双碳"], "大气治理": ["环保", "低碳"],
    "水治理": ["环保", "低碳"], "固废治理": ["环保", "低碳"],
    "生态修复": ["环保", "低碳"], "环境监测": ["环保", "低碳"],
}

CLUSTER_GENERATIONS = [2017, 2019, 2021, 2023, 2025]   # 代 g 聚类窗 [g, g+1]


def filter_etf_candidates(listing: list[dict]) -> list[str]:
    """行业/主题 ETF 候选池（宽基/跨境/商品/货币/债整段剔除；56 = 沪市新 ETF 段）。

    段位白名单 + 市场双判：market=0（深）只认 158/159，market=1（沪）只认沪段
    （见模块头注 2/3——TDX 缩写名不可作 ETF 判据，深市 52x-56x 是债）。listing
    项无 market 标注时（测试夹具）按段位推断：158/159 视为深市，其余按沪段。
    """
    kept = []
    for item in listing:
        code, name = item["code"], (item.get("name") or "")
        mkt = item.get("market")
        if mkt == 0:
            seg_ok = bool(SZ_ETF_SEG.match(code))
        elif mkt == 1:
            seg_ok = bool(SH_ETF_SEG.match(code))
        else:
            seg_ok = bool(SZ_ETF_SEG.match(code) or SH_ETF_SEG.match(code))
        if not seg_ok or EXCLUDE.search(name):
            continue
        kept.append(f"{code}.SZ" if code.startswith("15") else f"{code}.SH")
    return sorted(set(kept))


def load_bars(data_root: Path, symbol: str) -> list[dict]:
    path = data_root / "market" / "series" / f"{symbol}.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def point_in_time_pick(candidates: list[str], bars: dict[str, list[dict]],
                       week_end: str, *, min_list_years: int = 2,
                       min_amount_wan: float = 10000.0) -> str | None:
    """当时达标者：上市满 2 年 + trailing 20 日均额 ≥ 1 亿；多只取均额最大
    （规模 proxy 近似，spec §8 待验证——README 声明；上市年满 2 年按年整数差
    近似，误差 ±数日，评审 M2 注记）。"""
    best, best_amt = None, 0.0
    for sym in candidates:
        rows = [r for r in bars.get(sym, []) if r["date"] <= week_end]
        if len(rows) < 20:
            continue
        first, recent = rows[0]["date"], rows[-20:]
        listed_years = (int(week_end[:4]) - int(first[:4]))
        if listed_years < min_list_years:
            continue
        amt = sum(r["amount"] for r in recent) / 20
        if amt >= min_amount_wan * 1e4 and amt > best_amt:
            best, best_amt = sym, amt
    return best


def cluster_by_correlation(returns: np.ndarray, codes: list[str],
                           *, threshold: float = 0.75) -> dict[str, str]:
    corr = np.corrcoef(returns, rowvar=False)
    n = len(codes)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if np.isfinite(corr[i, j]) and corr[i, j] > threshold:
                parent[find(j)] = find(i)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return {codes[i]: f"cluster-{codes[min(g)]}" for g in groups.values() for i in g}


def _index_daily(data_root: Path, code: str) -> dict[str, float]:
    path = data_root / "sector" / "series" / f"{code}.jsonl"
    out: dict[str, float] = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                row = json.loads(ln)
                out[row["date"]] = float(row["close"])
    return out


def _match(cands: list[str], idx_name: str, listing: list[dict]) -> list[str]:
    """行业名 → ETF 候选集（执行注 1 拆名）：KEYWORDS 命中 ETF 显示名任一关键词，
    KEYWORDS 未登记的行业回退行业名前两字。语义与 brief 内嵌推导一致。"""
    name_by_code = {x["code"]: (x.get("name") or "").replace("\x00", "")
                    for x in listing}
    keywords = KEYWORDS.get(idx_name, [idx_name[:2]])
    return sorted({sym for sym in cands
                   if any(kw in name_by_code.get(sym.split(".")[0], "")
                          for kw in keywords)})


def build(data_root: Path, out_config: Path) -> dict[str, int]:
    listing = []
    for market in (0, 1):                  # 0=深 1=沪（注 3：段位判必须带市场）
        df = _mootdx_call("stocks", market=market)
        listing += [{"code": str(c).zfill(6), "name": str(n).replace("\x00", ""),
                     "market": market} for c, n in zip(df["code"], df["name"])]
    candidates = filter_etf_candidates(listing)
    (data_root / "sector-rotation").mkdir(parents=True, exist_ok=True)
    (data_root / "sector-rotation" / "etf-candidates.txt").write_text(
        "\n".join(candidates) + "\n", encoding="utf-8")
    # 评审 M5：ETF 显示名缓存（signal.py 信号表用），随候选池一起落盘
    name0 = {x["code"]: x["name"].replace("\x00", "") for x in listing}
    (data_root / "sector-rotation" / "etf-names.json").write_text(
        json.dumps({s: name0.get(s.split(".")[0], "") for s in candidates},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    bars = {sym: load_bars(data_root, sym) for sym in candidates}

    sector_list = json.loads((data_root / "sector" / "sector-list.json").read_text())
    lv2 = [x for x in sector_list if x["category"] == "二级行业"]
    members: list[Member] = []
    unmatched: list[str] = []
    for sec in lv2:
        idx_name = sec["name"].replace("\x00", "")
        cands = _match(candidates, idx_name, listing)
        if not cands:                       # 今日一票未中 → 无候选集，出 unmatched 人工补
            unmatched.append(f"{sec['code']} {idx_name}")
            continue
        limit = 0.20 if any(k in idx_name for k in ("半导体", "芯片", "创新药", "生物")) \
            and any(s.startswith(("58", "15")) for s in cands) else 0.10
        members.append(Member(sec["code"], idx_name, tuple(cands), limit))

    # 滞后滚动簇：代 g 用 [g, g+1] 年指数日收益聚类（spec §3.6 禁全样本）
    clusters: dict[int, dict[str, str]] = {}
    codes = [m.index_code for m in members]
    series = {c: _index_daily(data_root, c) for c in codes}
    for g in CLUSTER_GENERATIONS:
        lo, hi = f"{g}-01-01", f"{g + 1}-12-31"
        dates = sorted(d for d in
                       (set().union(*(set(series[c]) for c in codes)))
                       if lo <= d <= hi)
        if len(dates) < 40:                 # 该代数据不足（指数未上线）→ 无簇代
            continue
        mat = np.array([[series[c].get(d, np.nan) for d in dates] for c in codes])
        rets = np.diff(np.log(mat), axis=1)
        keep = ~np.isnan(rets).all(axis=1)
        usable = rets[keep][:, ~np.isnan(rets[keep]).any(axis=0)]
        if usable.shape[1] < 40 or keep.sum() < 3:
            continue
        clusters[g] = cluster_by_correlation(usable.T, [c for c, k in zip(codes, keep) if k])

    # point-in-time 逐年覆盖曲线（每年末快照，spec §5 P0）
    cov_lines = ["| 年 | 覆盖率 | 可用行业数 |", "|---|---|---|"]
    for year in range(2017, 2027):
        week_end = f"{year}-12-31"
        n_ok = sum(point_in_time_pick(list(m.etf_candidates), bars, week_end) is not None
                   and len([d for d in series[m.index_code] if d <= week_end]) > 100
                   for m in members)
        cov_lines.append(f"| {year} | {n_ok / len(members):.0%} | {n_ok} |")
    (data_root / "sector-rotation" / "coverage-curve.md").write_text(
        "\n".join(cov_lines) + "\n", encoding="utf-8")
    (data_root / "sector-rotation" / "unmatched.txt").write_text(
        "\n".join(unmatched) + "\n", encoding="utf-8")
    write_universe(out_config, UniverseSpec(members, clusters), status="draft")
    return {"members": len(members), "unmatched": len(unmatched),
            "candidates": len(candidates), "cluster_generations": len(clusters)}


def main() -> int:
    stats = build(REPO_ROOT / "data", REPO_ROOT / "config" / "sector-rotation-universe.md")
    print(stats)
    print("草稿：config/sector-rotation-universe.md；曲线：data/sector-rotation/coverage-curve.md")
    print("unmatched.txt 人工补 KEYWORDS 后重跑；候选集含多只 ETF 供 point-in-time 引擎择一")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
