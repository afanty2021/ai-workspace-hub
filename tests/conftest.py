import _test_paths  # noqa: F401

# Windows 本地跑测试的编码兜底：runner 缺省 locale（cp1252）会让脚本 print 中文
# 在捕获的 stdio 上 Unicode 炸（首跑 9 红）。CI 由 ci.yml 的 PYTHONUTF8=1 兜；
# 这里对裸跑 `pytest tests` 的本地 Windows 再兜一层，机制同源（stdio 归 UTF-8）。
import sys

if sys.platform == "win32":  # pragma: no cover - 仅 Windows 生效
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure") and _stream.encoding.lower().replace("-", "") != "utf8":
            _stream.reconfigure(encoding="utf-8", errors="replace")
