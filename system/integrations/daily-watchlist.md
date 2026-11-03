# daily-watch 内部接线说明

> daily-watch 工具（原 daily-watchlist）的代码在 `tools/daily-watch/`。
> 独立项目：[daily-watchlist](https://github.com/Benboerba620/daily-watchlist)

## 接线

```text
config/daily-watchlist-watchlist.md（股票池）
config/daily-watchlist.yaml（配置）
  → tools/daily-watch/scripts/generate_daily_report.py
  → output/daily-watch/YYYY/MM/YYYY-MM-DD.md（日报）
  → evidence/YYYY/MM/E-*.md（证据账本）
  → hypothesis/H*.md（只追加证据引用）
  → data/（市场数据持久化层：日报钩子快照级追加；每日 16:30 批量权威写，详见 tools/daily-watch/README.md「本地持久化」）
```

## 文件契约

| 动作 | 路径 |
|------|------|
| 读取股票池 | `config/daily-watchlist-watchlist.md` |
| 读取知识库 | `wiki/entities/` / `wiki/concepts/` |
| 写入日报 | `output/daily-watch/YYYY-MM/YYYY-MM-DD.md` |
| 写入证据 | `evidence/YYYY-MM/E-*.md` |
| 引用证据 | `hypothesis/H*.md` |
| 持久化市场数据 | `data/`（market/sector/finance/custom/news + .state/.locks，整目录 gitignore；spec：`docs/superpowers/specs/2026-11-02-market-data-persistence-design.md`） |
| 可选沉淀 | `wiki/explorations/` |

## workspace-config 记录

```markdown
### daily-watch
- status: enabled
- project_path: ./tools/daily-watch
- reads_from: config/daily-watchlist-watchlist.md, wiki/entities/, wiki/concepts/
- writes_to: output/daily-watch/, evidence/, hypothesis/（引用）, data/（持久化层）
```

`config/daily-watchlist-watchlist.md` 是唯一执行股票池。`workspace/monitoring/` 是用户看板，不作为脚本的第二输入源。
