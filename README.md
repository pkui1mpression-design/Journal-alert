# 大气环境文献日报（journal-alert）

把「期刊定期推送」变成**按关键词筛选后的微信推送 + 本地 Markdown 每日阅读报**，全自动、每天定时运行。

它**不依赖你的邮箱**：直接抓取期刊官网 RSS，并用 OpenAlex / Crossref 官方 API 兜底和补充摘要，因此不受邮箱改版、RSS 邮件格式、Outlook 客户端类型的任何影响。**只用 Python 标准库，不需要 pip 安装任何东西。**

**目录**

| | |
|---|---|
| [1. 它做什么](#1-它做什么) | [2. 快速开始](#2-快速开始) |
| [3. 常用命令](#3-常用命令) | [4. 目录结构 / 在线卡片墙 / 学科分区](#4-目录结构) |
| [5. 用 Obsidian 管理日报](#5-用-obsidian-管理日报) | [6. 配置](#6-配置) |
| [7. 微信推送](#7-微信推送) | [8. 每天自动运行](#8-每天自动运行) |
| [9. 换电脑迁移](#9-换电脑迁移) | [10. 数据源](#10-数据源) |
| [11. 故障排查](#11-故障排查) | [12. 维护备忘](#12-维护备忘) |

---

## 1. 它做什么

```
24 本目标期刊 ──┬─ RSS（官网推送源）
                ├─ OpenAlex API（按 ISSN + 日期）
                └─ Crossref API（按 ISSN + 日期）
                        │
                        ▼
        合并去重（DOI 优先）→ 时间窗过滤
                        │
                        ▼
   关键词打分（标题 ×3 / 摘要 ×1，同义词扩展）
                        │
                        ▼
    排除规则（撤稿/勘误/社论/Nature 新闻稿）
                        │
                        ▼
   SQLite 历史库去重 ──► 只保留「从未见过」的新文献
                        │
                        ├─► Markdown 每日阅读报（必读 / 值得一读 / 其他相关）
                        │     └─ 按学科分流：主学科进当天日报，其他学科各写一个子目录
                        ├─► 在线卡片墙 docs/index.html（GitHub Pages，见 4.1）
                        └─► 微信推送摘要（Server酱 / PushPlus / Bark）
```

**分级规则**（可在 `config.json` 的 `tiers` 里改）：

| 级别 | 条件 | 含义 |
|---|---|---|
| 🔥 必读 | 得分 ≥ 12 | 至少一个关键词命中标题，且另有命中 |
| 值得一读 | 得分 ≥ 6 | 一个关键词命中标题 |
| 其他相关 | 得分 ≥ 3 | 仅摘要命中 |
| 丢弃 | 得分 < 3 | 不进入报告 |

得分 = Σ（关键词权重 × 字段倍数）。默认权重 3，标题倍数 3，摘要倍数 1。所以「标题命中一个关键词」= 9 分。

---

## 2. 快速开始

### 2.1 装 Python

需要 **3.10 或更高版本**，从 <https://www.python.org/downloads/> 下载，安装时**务必勾选 `Add python.exe to PATH`**。

`run_daily.cmd` 会自己找 Python，**你不用改脚本**。查找顺序：`py -3` 启动器 → PATH 里的 `python.exe` → `%LOCALAPPDATA%\Programs\Python`、`C:\Program Files\Python`、`C:\Python` 等常见位置 → `%USERPROFILE%\.dsh\dsh-runtimes\*`（如果装了 DSH）。每一步都会实测能否 `import sqlite3, urllib.request`，所以会自动挡掉微软商店那个「假的 python」。

全都没找到时，`logs\runner.log` 会写 `ERROR: no usable Python 3 found.` 并返回退出码 2。

### 2.2 环境自检（先做这一步）

```powershell
<项目目录>\run_daily.cmd --doctor
```

这一步能提前发现 90% 的部署问题（权限、Python、网络代理）。它会检查并打印：Python 版本与路径、标准库是否齐全、三个目录是否可写、期刊/关键词数量、推送渠道是否已配、以及 Nature RSS / OpenAlex / Crossref 三个海外站点的连通性。

> ⚠️ **浏览器能打开网页 ≠ Python 能联网。** 代理、防火墙或安全软件可能只放行特定程序。本项目所有网络访问都由 Python 完成——**不要试图用 `curl` / PowerShell 复现**，很多机器上这些客户端被挡住而 Python 能通。

确认环境没问题后，再逐本刊验证全部数据源：

```powershell
<项目目录>\run_daily.cmd --check
```

### 2.3 跑一次

```powershell
<项目目录>\run_daily.cmd --once
```

第一次建议放大时间窗，先看一批历史文献：

```powershell
<项目目录>\run_daily.cmd --once --days 14
```

### 2.4 让它每天自动跑

三条路，**只开一条**：

| 方式 | 电脑要开机吗 | 去哪配 |
|---|---|---|
| **GitHub Actions（推荐）** | ❌ 不用 | [第 8.1 节](#8-每天自动运行) |
| Windows 计划任务 | ✅ 要 | [第 8.2 节](#8-每天自动运行) |
| 开机自启 | ✅ 要 | [第 8.3 节](#8-每天自动运行) |

---

## 3. 常用命令

在**项目根目录**下（把 `<项目目录>` 换成实际路径）：

```powershell
# 完整跑一次：抓取 → 筛选 → 写报告 → 推送
run_daily.cmd --once

# 只检查 24 本刊 × 3 个数据源的连通性，不写任何文件
run_daily.cmd --check

# 试运行：不写库、不写报告、不推送，直接把报告打到屏幕上
run_daily.cmd --dry-run --print

# 放大时间窗到 14 天（适合第一次使用，先看一批历史文献）
run_daily.cmd --once --days 14

# 只用 RSS，不用 API（更快）
run_daily.cmd --once --sources rss

# 不要推送
run_daily.cmd --once --no-push

# 自检推送通道（配好密钥后立刻验证，不用等第二天）
run_daily.cmd --test-push

# 环境自检：Python 版本、目录写入权限、配置完整性、三个海外站点连通性
run_daily.cmd --doctor

# 改完关键词/分级阈值后，重排今天的日报，不必重新联网抓取
run_daily.cmd --rerender

# 只重建在线卡片墙（读 reports/，不联网、不动台账、不推送）
run_daily.cmd --cards
```

`run_daily.cmd` 的两种模式：**不带参数**（计划任务用）输出写进 `logs\run-last.log`；**带参数**输出直接打在屏幕上，方便交互排查。

> ⚠️ `--rerender` 的结果**不要直接往外发**。它是「快照重放」，报告表头的「抓取 N 篇 / 新增 M 篇 / 0 篇已读」不反映真实运行，只用于把之前被 `output.max_entries` 截掉的条目补回报告。

---

## 4. 目录结构

| 路径 | 作用 |
|---|---|
| `config.json` | **唯一需要你改的文件**：期刊、关键词、分级阈值 |
| `run.py` | 主程序（命令行入口） |
| `jalert/fetch.py` | 三源抓取与解析（RSS/Atom/RDF、OpenAlex、Crossref） |
| `jalert/score.py` | 关键词打分、同义词匹配、排除规则 |
| `jalert/state.py` | SQLite 历史库（跨天去重 + 累积文献台账） |
| `jalert/report.py` | Markdown 报告与推送文案生成 |
| `jalert/push.py` | Server酱 / PushPlus / Bark 推送 |
| `jalert/cards.py` | 把 `reports/` 渲染成单文件卡片墙 HTML（见 [4.1](#41-在线卡片墙)） |
| `jalert/config.py` | 配置分层加载（默认值 → `config.json` → `config.local.json` → 环境变量） |
| `reports/YYYY-MM-DD.md` | **每日阅读报**（正文）——只收录标了 `"main": true` 的学科 |
| `reports/<学科>/YYYY-MM-DD.md` | 非主学科的专属日报，每个学科一个子目录（见 [4.2](#42-按学科分流的子目录)） |
| `reports/YYYY-MM-DD.json` | 同日结构化数据（可再导入 Excel/Obsidian）。**不入库** |
| `docs/index.html` | 在线卡片墙，GitHub Pages 直接发布这一份文件 |
| `state/daily/YYYY-MM-DD.json` | 当日报表快照。**不入库**，只上传为 artifact |
| `state/seen.sqlite` | 历史库：`articles` 表是累积文献台账，`runs` 表是运行日志 |
| `logs/` | 运行日志（日报库那边另有一份 `.sync.log`） |
| `run_daily.cmd` | 启动脚本（自动寻找可用的 Python） |
| `make_package.py` | 打包成可移植 zip，供复制到另一台电脑 |
| `.github/workflows/daily.yml` | 云端定时任务定义（每天 07:30 东八区跑 `run.py --once`） |
| `config.local.json` | **不入库**的本机覆盖层，推送密钥写这里 |
| `tools/obsidian-sync/` | 把日报同步进 Obsidian 库的脚本（复制到库根目录用，见 [第 5 节](#5-用-obsidian-管理日报)） |
| `.gitattributes` | 行尾统一声明：文本文件一律 LF，批处理保持 CRLF |
| `.gitignore` / `LICENSE` | 入库清单 / MIT 许可证 |

**打包到另一台电脑**（完整清单见 [第 9 节](#9-换电脑迁移)）：

```powershell
run_daily.cmd  # 直接用 Python 也行：
python make_package.py                 # 生成便携 zip（自动排除日志/旧日报/缓存，并清空推送密钥）
python make_package.py --fresh         # 不要已读台账，新电脑从零开始
python make_package.py --keep-secrets  # 保留密钥：只在自己电脑之间用 U 盘直接拷时才用
```

包里会自动放一份 `先读我-安装三步.txt`（内容由 `make_package.py` 里的 `QUICKSTART` 生成，所以仓库里不放这个文件）。已实测：解压到**含空格的任意路径**后 `run_daily.cmd --doctor` 返回「一切正常」。

### 4.1 在线卡片墙

日报之外，每次运行还会把**全部历史日报**渲染成一张卡片墙网页：

```
https://pkui1mpression-design.github.io/Journal-alert/
```

小红书式瀑布流，**一张卡片就是一篇文献**，按学科分组，点卡片弹出完整摘要、作者、DOI 和原文链接。顶部可以按学科 / 分级筛选，也能搜标题、摘要、作者、期刊。

| 特性 | 说明 |
|---|---|
| 收录范围 | `reports/` 下**所有**日报（含各学科子目录），跨天按 DOI 去重 |
| 篇数 | 等于日报里实际列出的篇数。受 `output.max_entries` 限制，所以日报列多少，页面就有多少 |
| 依赖 | **零外部资源**——没有 CDN、没有网络字体、没有图片请求。断网、`file://` 双击打开都正常 |
| 更新时机 | `run.py --once` 末尾自动重建并提交，Pages 随即重新发布。也可单独跑 `run.py --cards` |

配置项（都有默认值，不写也能跑）：

```jsonc
"output": {
  "cards": true,                    // 关掉就完全不生成卡片墙
  "cards_html": "docs/index.html"   // 输出路径，相对项目根目录
}
```

部署到 GitHub Pages 只需一次：仓库 **Settings → Pages → Source** 选 `Deploy from a branch`，分支 `main`、目录 **`/docs`**。`docs/.nojekyll` 已经放好，跳过 Jekyll 处理。

### 4.2 按学科分流的子目录

学科越加越多时，全塞进一个日报会变得臃肿。所以每个学科组在 `config.json` 里有一个 `main` 标记，决定它的文献写到哪里：

```jsonc
"keywords": [
  { "label": "空气污染", "main": true, "weight": 3, "terms": [ ... ] },   // → reports/2026-10-10.md
  { "label": "城市地理信息系统",           "weight": 3, "terms": [ ... ] } // → reports/城市地理信息系统/2026-10-10.md
]
```

实际长这样：

```
reports/
  2026-10-10.md                   ← 主日报：空气污染 / 遥感 / 大气化学 / 生物地球化学
  2026-10-09.md
  城市地理信息系统/
    2026-10-10.md                 ← 该学科专属日报
    2026-10-09.md
```

要点：

* **默认是「没有 `main` 就自己开一个子目录」**。所以加新学科只需要往 `keywords` 里加一组词，不用改代码、也不用记得补标记。
* **一篇文献只落一个文件**。同时命中多个学科时，只要**其中任意一个**是主学科就留在主日报；否则按它命中的第一个学科归档。子目录之间是**划分**关系，不是重叠的索引。
* **限流按文件独立**。主日报和每个学科日报各自吃满 `output.max_entries`，新学科再热闹也挤不掉主日报的位置。
* **子目录日报带 `scope` 属性**，Obsidian 里可以直接 `scope: 城市地理信息系统` 筛出来：

  ```yaml
  ---
  date: 2026-10-10
  scope: "城市地理信息系统"
  topics: ["城市地理信息系统"]
  tags: ["journal-alert", "城市地理信息系统"]
  ---
  ```

* **清理是递归的**。`output.keep_days` 到期的子目录日报一并删除，清空后的学科目录会被回收（不会留下空壳）。
* 想把某个学科在主日报和子目录之间搬家，改 `main` 一个字段即可，不用动别的。

---

## 5. 用 Obsidian 管理日报

`reports/` 下每天一篇 Markdown，天生适合 Obsidian：文件名就是日期，正文是标准语法（标题、引用块、表格、外链），头部还带 YAML 属性。

**推荐：单独建一个只含 `reports/` 的库**，不要混进主笔记库。整个库不到 100 KB。

### 5.1 建库

两种方式，按你的网络情况选：

**方式 A：git sparse clone**（git 通道正常时用）

```bash
git clone --filter=blob:none --sparse https://github.com/<用户名>/Journal-alert.git journal-alert-reports
cd journal-alert-reports
git config core.sparseCheckoutCone false
printf '/reports/\n' > .git/info/sparse-checkout
git read-tree -mu HEAD
```

**方式 B：只镜像文件，不用 git**（git 通道被掐时用，本机走的就是这条）

新建一个空文件夹当库就行（不用装 git，也不用 `git init`），同步脚本会自己创建 `reports/`。
适合 `git fetch` 走不通、但 `api.github.com` 可达的环境（见 [第 12.2 节](#122-本机推拉代码拉取用-git推送走-rest-api)）。
仓库是公开的，因此**不需要任何 token**，也就不必担心密钥存在哪。

两种方式都用 Obsidian 的「打开文件夹作为库」选中该目录。

> **两个坑**：① 不隔离的话，`jalert/*.py`、`state/seen.sqlite`、`README.md` 也会被索引，搜索和图谱里全是噪音；② `sparse-checkout` 的 **cone 模式总是保留根目录文件**，所以上面显式关掉 cone 模式、直接写规则文件。若在 Git Bash 里执行 `sparse-checkout set`，`/reports/` 会被 MSYS 当成绝对路径展开，那一步务必照上面写成规则文件。

### 5.2 每天同步

把 `tools/obsidian-sync/` 下的两个文件复制到**库根目录**，双击 `同步.cmd` 即可。

| 文件 | 作用 |
|---|---|
| `同步.cmd` | 双击运行。自己找 Python（PATH → 托管安装 → 版本目录），找到后调 `sync_reports.py` |
| `auto_sync.cmd` | 给[计划任务](#53-自动同步windows-计划任务)用。不发 `pause`，输出写进 `.sync.log` |
| `sync_reports.py` | 同步引擎。用 GitHub API 列出 `reports/`，逐个比对 git blob sha，只写有变化的文件 |

> `同步.cmd` 里**一个中文都没有**，这不是洁癖：批处理文件按系统 OEM 代码页解析，
> 混进中文就可能在别的机器上报「不是内部或外部命令」。所有中文提示都放在 Python
> 侧输出，脚本名用 ASCII，这样这两个文件放哪台 Windows 上都能跑。

只用 Python 标准库，不需要 pip 装任何东西。命令行的用法：

```bash
python sync_reports.py            # 同步（幂等：没更新时一个文件都不碰）
python sync_reports.py --list     # 只看远端有哪些日报，不下载
python sync_reports.py --stamp    # 额外打一行运行时间戳（计划任务用）
```

> 为什么不用 git 同步：本机到 `github.com:443` 的通道不稳定（代理 502、TLS 握手失败、
> 传输中途断流轮着来），而镜像只读、用不着提交历史。走 API 还顺带避开了行尾问题 ——
> 写进来的是仓库里的原始字节（LF），不会被 `core.autocrlf` 在检出时改成 CRLF。
>
> 脚本按 **git blob 的 sha** 判断是否需要更新，而不是比时间戳或文件大小。这样没更新的日子
> 文件 mtime 不变，Obsidian 不会白重载一遍；内容对不上但只是行尾差异时也只静默修正行尾。

### 5.3 自动同步（Windows 计划任务）

不想每天手动双击的话，挂一个计划任务。本机已注册：

| 项目 | 值 |
|---|---|
| 任务名 | `JournalAlertObsidianSync` |
| 触发时刻 | 每天 **08:00 / 11:00 / 14:00 / 17:00 / 20:00**（共 5 次） |
| 执行 | `cmd.exe /c "D:\journal-alert-reports\auto_sync.cmd"` |
| 日志 | 库根目录 `.sync.log`（**以点开头，Obsidian 不会显示它**） |
| 配置备份 | `C:\Users\wangs\JournalAlertObsidianSync-task-backup.xml` |

**为什么要跑 5 次**：云端 CI 的 cron 定的是 07:30，但 GitHub 的定时任务在高负载时会明显延迟
—— 实测有一天的 `schedule` 事件是 **11:16** 才落地的。只跑一次的话，那天就会整天看不到新日报。
同步脚本幂等（没更新时一个文件都不碰），多跑几次的成本约等于零。

**几个刻意的选择**：

* `StartWhenAvailable = true` —— 该跑的时刻电脑关着，开机后会补跑一次。
* `DisallowStartIfOnBatteries = false` —— 笔记本用电池时也照跑（漏了这个设置就不会执行）。
* `LogonType = InteractiveToken` —— 只在登录状态下运行，**不存密码**。
* 任务不会跟着文件夹走。换了电脑或挪了库的位置，得重新注册一次（见下）。

**常用操作**（本机 `schtasks.exe` 被安全策略拉黑，只能用 PowerShell 的 ScheduledTasks 模块）：

```powershell
# 看状态 / 下次运行时间
Get-ScheduledTaskInfo -TaskName JournalAlertObsidianSync

# 立刻跑一次
Start-ScheduledTask -TaskName JournalAlertObsidianSync

# 临时停用 / 重新启用
Disable-ScheduledTask -TaskName JournalAlertObsidianSync
Enable-ScheduledTask  -TaskName JournalAlertObsidianSync

# 彻底删掉
Unregister-ScheduledTask -TaskName JournalAlertObsidianSync -Confirm:$false

# 在新电脑上重建（先改 $vault，并确认 auto_sync.cmd 里的 Python 路径）
$vault = 'D:\journal-alert-reports'
$triggers = '08:00','11:00','14:00','17:00','20:00' | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
Register-ScheduledTask -TaskName JournalAlertObsidianSync `
  -Action (New-ScheduledTaskAction -Execute 'C:\Windows\System32\cmd.exe' -Argument ('/c "{0}\auto_sync.cmd"' -f $vault) -WorkingDirectory $vault) `
  -Trigger $triggers `
  -Principal (New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited) `
  -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew)
```

> `auto_sync.cmd` 与 `同步.cmd` 的分工：前者给计划任务用（**没有 `pause`**，否则任务会永远挂住；
> 输出写进 `.sync.log`），后者给人双击用（有 `pause`，能在窗口里看结果）。两个文件都放在
> `tools/obsidian-sync/` 下，复制到库根目录使用。

### 5.4 日报头部的属性

由 `output.frontmatter` 控制（默认开）：

| 字段 | 含义 |
|---|---|
| `date` / `generated` | 日报日期 / 生成时刻 |
| `fetched` / `matched` / `new_count` | 抓取 / 命中 / 新增篇数 |
| `must_read` / `worth_reading` / `other` | 三个级别各多少篇 |
| `topics` | 关注方向（取自 `keywords` 的 `label`） |
| `sources_failed` | 本次抓取失败的数据源条数 |

装了 **Dataview** 插件后，一张索引页就能把这些日报汇总成表：

````markdown
```dataview
TABLE WITHOUT ID file.link AS 日报, must_read AS 必读, worth_reading AS 值得一读
FROM "reports"
WHERE must_read > 0
SORT file.name DESC
```
````

**注意**：别在 Obsidian 里编辑 `reports/` 下的文件 —— 下次同步会按远端内容覆盖回去（内容或行尾只要对不上就会被重写）；库内其他位置随便加自己的笔记。

---

## 6. 配置

### 6.1 改关键词与期刊

编辑 `config.json`：

```jsonc
"keywords": [
  {
    "label": "空气污染",              // 报告里显示的中文名
    "main": true,                     // 进当天主日报；不写则单独开一个子目录（见 4.2）
    "weight": 3,                      // 权重，越大越优先
    "terms": [                        // 命中的英文写法，全部小写、不分大小写匹配
      "air pollution", "pm2.5", "particulate matter", "aerosol", "ozone"
    ]
  }
]
```

要点：

* **`terms` 是召回率的关键**。同一个概念要列出各种英文写法（`pm2.5` / `pm25`；复数不用写，匹配时已按字母数字边界处理）。
* 匹配使用「字母数字边界」，所以 `no2` 不会误命中 `no2something`，`soa` 也不会命中 `soap`。
* **加一个新学科**：往 `keywords` 里追加一组 `{ "label": ..., "terms": [...] }` 就行。不写 `main` 时它的日报会自动落到 `reports/<学科>/` 子目录，主日报不受影响，见 [4.2](#42-按学科分流的子目录)。
* **一篇文献可能同时命中多个学科**。日报的「匹配」行会把它们全部列出（用 `、` 分隔），卡片墙据此把这篇归入每个命中的学科。
* 想临时屏蔽某类内容，加到 `exclude_terms`（命中即整条丢弃，默认已屏蔽撤稿/勘误/社论）。
* `exclude_doi_prefixes` 默认屏蔽 `10.1038/d41586`（Nature 新闻/评论/播客），只保留研究论文。
* 增删期刊：`journals` 数组里加 `{ "name": ..., "issn": ..., "rss": ... }`。`issn` 必须准确，OpenAlex/Crossref 靠它取数。
* **只想每天看最重要的几篇**：`output.max_entries`（默认 `0` = 不限，当前设为 `10`）。超过就只列得分最高的 N 篇，按「必读 → 值得一读 → 其他相关」的层级截取；**全部命中仍会进历史库和 `reports/YYYY-MM-DD.json`**，所以把数值调大后执行 `--rerender` 即可把其余几篇补回报告，不用重新联网抓取。
* **报告末尾的数据源表太长**：`output.source_status` 三档 —— `full`（完整表格，排查数据源时用，是默认值）、`summary`（一切正常时只留一行，有失败才列短表，`config.json` 里用的是这个）、`none`（一个字都不提）。每篇日报后面都跟着 47 行表格实在没必要。
* **要不要 YAML 属性**：`output.frontmatter`（默认 `true`）决定日报头部是否写 `date` / `must_read` / `topics` 等属性。用 Obsidian 看日报就保持开着，见 [第 5 节](#5-用-obsidian-管理日报)。

### 6.2 配置的分层（`config.json` vs `config.local.json`）

`config.json` 是**可以公开分享**的那一份：期刊、关键词、阈值、分级规则。**里面不放任何密钥。**

密钥放 `config.local.json`（与 `config.json` 同目录，已被 `.gitignore` 排除）。它会被深合并到 `config.json` 之上，写多少层覆盖多少层，不用把整个 `push` 段抄一遍：

```jsonc
// config.local.json —— 只写要覆盖的部分
{
  "push": {
    "channels": {
      "serverchan": { "enabled": true, "sendkey": "SCT..." }
    }
  }
}
```

完整优先级，从下往上覆盖：

```
DEFAULTS（代码里的默认值）
  → config.json           ← 入库。只放期刊、关键词、阈值。sendkey 留空 ""
    → config.local.json   ← 不入库（已在 .gitignore）。本机密钥写这里
      → 环境变量           ← 最高优先级。CI 用这个
```

在 GitHub Actions 里则完全不碰文件，用仓库 Secrets 通过环境变量注入。`run_daily.cmd --doctor` 会打印「本机覆盖层」路径和密钥最终来源（`Server酱（环境变量 ...）` 或 `Server酱（配置文件）`）。

### 6.3 环境变量总表

| 环境变量 | 覆盖的字段 |
|---|---|
| `JALERT_SERVERCHAN_SENDKEY` | `push.channels.serverchan.sendkey` |
| `JALERT_PUSHPLUS_TOKEN` | `push.channels.pushplus.token` |
| `JALERT_BARK_KEY` | `push.channels.bark.key` |
| `JALERT_BARK_SERVER` | `push.channels.bark.server` |
| `JALERT_PUSH_ENABLED` | `push.enabled`（设成 `0` 可以整体关掉推送） |
| `JALERT_MAILTO` | OpenAlex / Crossref 的「礼貌池」联系邮箱 |
| `JALERT_USER_AGENT` | 抓取时用的 UA |
| `JALERT_CONFIG` / `JALERT_CONFIG_LOCAL` | 配置文件路径（默认就是项目根目录那两个） |

只要变量非空，程序会自动把该渠道 `enabled` 设为 `true`——**填了密钥就代表意图是要用**，不用再改两处。

### 6.4 入库 / 不入库清单

`config.local.json` 和 `.gitignore` 已经配好。原则是**代码 + 可分享的配置 + 每天的日报入库；运行痕迹、机器本地状态、密钥不入库**。

| 不入库 | 原因 |
|---|---|
| `logs/` | 运行日志，含本机 Python 路径；云端改成 Actions artifact |
| `state/daily/` | 每日快照，每天 ~90 KB。本地跑同一天第二次时靠它合并，但 CI 每次都全新检出、拿不到它，所以不入库；缺失时程序会改从当天日报回读，见 [第 8.1 节](#8-每天自动运行) |
| `state/*.bak-*` | 数据库备份 |
| `reports/*.json` | 与日报同内容的机器可读版，每天 ~90 KB，会无限堆积 |
| `config.local.json` | 密钥 |
| `.workbuddy/` | 助手工具的项目数据 |
| `__pycache__/` | 字节码 |

被跟踪的有：`state/seen.sqlite`（去重台账）、`reports/YYYY-MM-DD.md`（主日报正文）、`reports/<学科>/YYYY-MM-DD.md`（各学科子目录日报）、`docs/index.html`（在线卡片墙），以及其余源码与文档。

> 注意上面第 2、4 条：**「同一天多次运行自动合并」依据的快照文件恰好是不入库的**。本机连续跑没问题，CI 上补跑同一天则会走「从日报回读」的降级路径。详见 [8.1 节](#8-每天自动运行) 的说明。

> **注意**：`.gitignore` 对**已跟踪**文件无效。如果某个文件已经被提交过，需要先取消跟踪：
> ```powershell
> git rm -r --cached logs state/daily reports/*.json
> git commit -m "chore: stop tracking run artifacts"
> ```

---

## 7. 微信推送

推送**不是必须**的：不做这一步，你依然每天有本地 Markdown 日报。但只要花三分钟配一次，就能在微信里直接收到「今天有哪些新文献」的卡片，点开即是论文链接。

为什么需要你自己申请：推送要靠第三方服务把你的微信和电脑连起来，密钥等同于密码，只能你自己在手机上扫码领取。

### 7.1 方案 A：Server酱（推荐，最省事）

**第 1 步：拿到 SendKey**
1. 电脑或手机浏览器打开 <https://sct.ftqq.com>
2. 点右上角「登录」，用**微信扫码**（不需要注册账号，扫码即注册）
3. 登录后进入「SendKey」页面，复制那串 **SendKey**，形如 `SCT341234Txxxxxxxxxxxxxxxxxxxxxxxxxxxx`

**第 2 步：关注服务号（否则收不到）**
在刚才那个页面点「**点此关注**」，或在微信里搜索并关注服务号「**Server酱**」。没关注的话消息会被服务端直接丢弃。

**第 3 步：填进配置文件**
新建或打开项目根目录下的 **`config.local.json`**（不是 `config.json`——那个要提交到 Git，不能放密钥）：

```jsonc
{
  "push": {
    "channels": {
      "serverchan": {
        "enabled": true,                             // 改成 true
        "sendkey": "SCT341234Txxxxxxxxxxxxxxxxxxxx"  // 粘贴你的 SendKey
      }
    }
  }
}
```

保存时注意**编码选 UTF-8**（记事本默认即可），文件必须仍是合法 JSON：不要少逗号、不要多逗号。

> 如果你是在 **GitHub Actions** 上跑，这一步改成填仓库 Secrets：`SERVERCHAN_SENDKEY`，**不要新建任何文件**。见 [第 8.1 节](#8-每天自动运行)。

**第 4 步：立刻自检（不用等第二天）**

```powershell
<项目目录>\run_daily.cmd --test-push
```

看到这样就是成功：

```
  serverchan   成功  code=0 SUCCESS
```

同时手机上应该马上收到一条「推送通道自检」。免费版每天有额度，本工具每天只推 1 条，够用。

### 7.2 方案 B：PushPlus

1. 打开 <https://www.pushplus.plus>，微信扫码登录。
2. 复制「一对一推送」里的 **token**。
3. 填进 `config.local.json`：
   ```jsonc
   { "push": { "channels": { "pushplus": { "enabled": true, "token": "你的token" } } } }
   ```
4. 运行 `--test-push` 自检。

### 7.3 方案 C：Bark（仅 iPhone，无需关注公众号）

1. App Store 安装「Bark」。
2. 打开 App，首页那串地址 `https://api.day.app/xxxxxxxx` 里的 **xxxxxxxx** 就是 key。
3. 填进 `config.local.json`：
   ```jsonc
   { "push": { "channels": { "bark": { "enabled": true, "key": "xxxxxxxx", "server": "https://api.day.app", "sound": "bird" } } } }
   ```
4. 运行 `--test-push` 自检。

**三个渠道互不冲突，都填了就会都发。** 建议先只用 Server酱，跑通了再说。

推送内容是**摘要卡片**：标题为「大气环境文献日报 YYYY-MM-DD：新增 N 篇，必读 M 篇」，正文列出最多 `push.max_items`（默认 6）条，格式为「标题（可点击）+ 期刊 · 日期 · 命中关键词」。完整内容在本地 Markdown 日报里。

每条文献**自成一段**（条目之间留空行，条目内用 Markdown 硬换行分行）。这是有意为之：如果条目之间不空行，Markdown 会把它们合并成同一个段落，在微信里就显示成一大串连着排的文字。总长超过 `push.max_chars`（默认 1800）时，会在**段落边界**截断，不会把某一条切成一半。

### 7.4 排查表

| 现象 | 原因与处理 |
|---|---|
| `serverchan 失败  code=...` | SendKey 抄错或已失效，回 <https://sct.ftqq.com> 重新复制 |
| 自检显示成功，但手机上没消息 | **没有关注「Server酱」服务号**。这是最常见的原因 |
| `失败 未配置 sendkey` | `config.local.json`（或 Actions 的 Secrets）里 `serverchan.sendkey` 还是空的，或 `enabled` 不是 `true` |
| 提示 JSON 解析错误 | 编辑 `config.local.json` 时破坏了格式（中文逗号、漏引号、多逗号） |
| 一切正常但当天没有推送 | 设计行为：只有**有新增文献**时才推送（`skip_when_empty: true`），避免每天发空消息打扰你 |
| 不知道密钥最终从哪来的 | 跑一次 `--doctor`，会打印「本机覆盖层」路径和密钥来源 |

### 7.5 安全

密钥**只**写进 `config.local.json`（已 git-ignore）或 GitHub 仓库 Secrets。`config.json` 是要提交到 Git 的，里面必须保持 `sendkey: ""`。

万一密钥已经泄露（比如曾经被提交进 Git 历史），**改文件是没用的**——去对应网站「重置」一下，让旧密钥立即作废，这是唯一彻底的办法。删掉提交、`--force` 推送都不能真正清除旧对象，Git 保存的是全部历史。

---

## 8. 每天自动运行

### 8.1 方式 A：GitHub Actions（推荐，电脑不用开机）

仓库里已经带了一份 `.github/workflows/daily.yml`：**云端每天 07:30（北京时间）跑一次**，推送照发，日报和去重台账自动提交回仓库。免费、不用挂机、不受「笔记本睡眠 / 关机 / 未登录」影响。

#### 运行频次与北京时间

工作流里写的是：

```yaml
on:
  schedule:
    - cron: "30 23 * * *"
```

| 项目 | 值 |
|---|---|
| **运行频次** | **每天一次** |
| 触发时刻（本地） | **07:30（北京时间 UTC+8）** |
| 触发时刻（GitHub 视角） | **23:30 UTC，前一天** |
| 为什么差一天 | **GitHub 的 cron 一律按 UTC 解释**。北京 07:30 时，UTC 还是前一天的 23:30。所以「23:30 UTC」和「次日 07:30 北京」是同一时刻 |
| 实际延迟 | 整点高峰期 GitHub 会排队，**延迟 5–30 分钟是常态**。对日报无影响 |

> 工作流里还设了 `TZ: Asia/Shanghai`。这一步不能省：`run.py` 用 `date.today()` 命名日报，容器默认是 UTC，不设就会生成「昨天」文件名的日报。

**改成只跑工作日**（如果就是想贴着原来本机任务的节奏）：

```yaml
    - cron: "30 23 * * 0-4"   # UTC 的周日~周四 == 北京时间的周一~周五 07:30
```

注意 day-of-week 要按 **UTC 视角**填：23:30 UTC 的周日，在北京已经是周一了，所以是 `0-4`（0 = 周日）而**不是** `1-5`。

> 其实**不必**特意改成工作日：周六周日的文献会在周一被自适应时间窗（`max(配置的 3 天, 距上次运行的天数 + 1)`）一起捞回来，不会漏。

#### 它做四件事

1. `python run.py --doctor` —— 先自检（Python 版本、目录写入、三个海外站点连通性），失败原因一眼可见。这一步标了 `continue-on-error`，偶发超时不会把整个任务判失败。
2. `python run.py --once` —— 跑完整管线：抓取 → 筛选 → 写日报（主日报 + 各学科子目录）→ 重建 `docs/index.html` → 推送
3. `git commit && git push` —— 把 `state/seen.sqlite`、当日日报（含学科子目录）和卡片墙写回仓库（标了 `if: always()`，即使抓取失败也保住台账）。Pages 随后自动重新发布
4. 上传 `logs/` 为 artifact（保留 90 天）+ 把当日日报渲染到运行页面的 Summary 里

#### 一次性配置（3 分钟）

仓库页 → **Settings** → **Secrets and variables** → **Actions** → **Secrets** 标签 → **New repository secret**：

| Name | Value |
|---|---|
| `SERVERCHAN_SENDKEY` | 你的 SendKey |
| `PUSHPLUS_TOKEN` | 可选，不用就整个不要建 |
| `BARK_KEY` | 可选 |

再切到 **Variables** 标签建一个（可选，但推荐）：

| Name | Value |
|---|---|
| `JALERT_MAILTO` | 你的邮箱。OpenAlex/Crossref 对提供了真实联系方式的调用者给「礼貌池」优先权，成功率更高 |

没配的 Secret 会展开成空字符串，程序把「空密钥」当作「该渠道未启用」直接跳过，**不会报错**，所以只建 `SERVERCHAN_SENDKEY` 一个也能跑。

#### 手动触发与验收

**Actions** → 左侧 `journal-alert daily` → **Run workflow**。可以填两个输入框：

* `days` —— 覆盖时间窗，第一次建议填 `14`，先看一批历史文献
* `sources` —— 例如填 `openalex,crossref` 先只跑 API

也可以不点鼠标，用 API 直接触发：

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/<owner>/<repo>/actions/workflows/daily.yml/dispatches \
  -d '{"ref":"main","inputs":{"days":"14"}}'
# HTTP 204 = 已受理
```

**怎么判断推送成功没有**：看运行日志里的 `push results`：

```
push serverchan   OK   code=0
push results: [{"channel": "serverchan", "ok": true, "detail": "code=0 "}]
```

`code=0` 是 Server酱的成功码。取日志的办法见 [第 12.2 节](#12-维护备忘) —— `GET .../actions/jobs/<id>/logs` 会 302 到 blob 存储，**直接跟会 401**（因为 `Authorization` 被一起转发，把目标的 SAS 令牌顶掉了），要手动跟重定向且不带授权头。

#### 状态怎么跨运行存活

Actions 每次运行都是**全新容器**，`state/seen.sqlite`（「已读台账」）不会自己留下。丢了就会把时间窗内的文献全部当新的重推一遍。三个方案：

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| **A. 写回仓库（当前实现）** | 每次运行 `git add -A && commit && push` | 稳。台账和日报都在仓库里，随时可见、可回滚；天然规避「60 天不活动被停用」的坑 | 每天 1 个提交，一年 365 个 |
| B. Actions cache | `actions/cache` + 滚动 key | 不污染提交历史 | 缓存**连续 7 天无人访问就被清理**；工作流挂掉超过一周，台账丢失，下次会把时间窗内全部文献当新的重推 |
| C. 外部存储 | Release asset / 对象存储 / 数据库 | 不污染历史 | 要额外凭证和维护成本 |

**推荐 A，就是现在这份。** 想彻底不要这些提交？把 `reports/` 和 `state/` 都 gitignore，改用方案 B——**不建议**，省下的只是几十个提交，换来一个会静默失效的去重机制。

> **关于「同一天多次运行会合并」**：`state/daily/` 和 `reports/*.json` 都在 `.gitignore` 里（见 [第 6.4 节](#64-入库--不入库清单)），CI 又每次都是全新检出，所以**快照并不会跟着运行走**。平时每天只跑一次，当天从零开始，这个差异无所谓；但**手动补跑同一天**时要留意：
>
> * 程序发现没有快照，会退而从**磁盘上已经写好的当天日报**里把条目读回来当合并基础，再叠加本次新增，所以补跑是**累加**而不是覆盖。
>   从日报回读是有损的（摘要回来只有 700 字截断、命中词的分值丢失），但只用于重新排版，不会写回去重库。
> * 另有兜底：万一确实无内容可渲染、而当天日报已有内容，程序会保留原文件而不是把它清空。
>
> 这两个行为是 2026-10-10 补上的。在那之前，一次「0 篇新增」的补跑会把当天日报直接覆盖成空文件。

#### 其他注意事项

| 现象 | 说明 |
|---|---|
| 定时任务「跑了 60 天后自己停了」 | GitHub 会停用**连续 60 天无仓库活动**的定时工作流。方案 A 每天都有提交，天然不触发 |
| `permissions: contents: write` 安全吗 | 安全。**用自动 `GITHUB_TOKEN` 推送的提交不会触发工作流**，不存在自己触发自己的死循环 |
| Actions 分钟数 | 公开仓库用 GitHub 托管 runner **免费且不计费**。私有仓库走免费额度（2000 分钟/月），本工作流一次约 4–6 分钟，每天一次 ≈ 150 分钟/月，也够 |
| `reports/*.md` 会公开 | 内容是论文标题、DOI、作者、摘要片段——都是公开学术信息。但它同时暴露了**你的研究方向和关键词**，介意就把 `reports/` 也 gitignore 掉 |
| `keep_days: 365` | 自动清理一年前的日报（`.md` 和 `.json` 都清），仓库体积不会无限增长 |

### 8.2 方式 B：Windows 计划任务

先注册（在**要运行它的这台电脑上**执行）：

```powershell
$action   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c <项目目录>\run_daily.cmd"
$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 07:30
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "JournalAlertDaily" -Action $action -Trigger $trigger -Settings $settings -Force
```

**`$settings` 那一行不能省。** Windows 默认是「电池供电时不启动、切换到电池就停止」，笔记本上会让 07:30 这次运行根本不发生：

| 开关 | 作用 |
|---|---|
| `-AllowStartIfOnBatteries` | 电池供电时也允许启动 |
| `-DontStopIfGoingOnBatteries` | 中途拔电源不掐断 |
| `-StartWhenAvailable` | 睡着了错过 07:30，唤醒后补跑 |
| `-MultipleInstances IgnoreNew` | 上一次没跑完不会叠着跑 |

如果 `Register-ScheduledTask` 报「拒绝访问」，用**管理员身份**打开 PowerShell 再执行一次。

> 提示：`Get-ScheduledTask` 读回来的 `AllowStartIfOnBatteries` / `DontStopIfGoingOnBatteries` 会显示为空值，那是 PowerShell 的显示怪癖（这两个属性名是反向命名）。**验证要看真实 XML**：
> ```powershell
> (Export-ScheduledTask -TaskName "JournalAlertDaily") -split "`n" | Select-String "Batteries"
> ```
> 应输出 `<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>` 与 `<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>`。

日常操作：

```powershell
Get-ScheduledTask -TaskName "JournalAlertDaily"                    # 查看状态
Start-ScheduledTask -TaskName "JournalAlertDaily"                  # 立刻手动跑一次
Disable-ScheduledTask -TaskName "JournalAlertDaily"                # 临时停用
Unregister-ScheduledTask -TaskName "JournalAlertDaily" -Confirm:$false   # 彻底删除
```

改时间：重跑上面的 `Register-ScheduledTask`，把 `-At` 改掉即可。

#### 07:30 时电脑处于不同状态，会发生什么

| 状态 | 结果 |
|---|---|
| 开机且已登录 | 准时运行，准时推送 |
| 睡眠 / 休眠 | **不会唤醒**（未开 `WakeToRun`，且电池供电下 Windows 的唤醒定时器本身也是禁用的）；下次开机登录后由 `StartWhenAvailable` 补跑 |
| 完全关机 | 同上，下次开机登录后补跑 |
| 开着但没人登录（锁屏/注销） | 不会运行（任务是 InteractiveToken，要求已登录会话）；登录后补跑 |

**补跑不会漏文献。** 时间窗是自适应的：`max(配置的 3 天, 距上次成功运行的天数 + 1)`，上限为 `max_catchup_days`（默认 30 天）。所以电脑关了两周也不会漏掉中间的文献。用 `--days N` 手动指定时关闭该自适应。

#### 想让睡眠中的电脑也在 07:30 自动醒来跑（可选）

```powershell
# 1) 打开任务的唤醒开关
$t = Get-ScheduledTask -TaskName "JournalAlertDaily"
$t.Settings.WakeToRun = $true
Set-ScheduledTask -TaskName "JournalAlertDaily" -Settings $t.Settings

# 2) 关键补充：默认只在插电时允许唤醒，电池下要单独打开
powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
powercfg /setactive SCHEME_CURRENT
```

第 2 步不能省——Windows 默认「交流电启用 / 电池禁用」唤醒定时器，不然拔了电源照样叫不醒。代价是 07:30 电脑会短暂亮起或转一下风扇；电脑完全关机时仍无法唤醒（只有极少数机型支持关机定时开机）。

### 8.3 方式 C：开机自启

把 `run_daily.cmd` 的快捷方式放进启动文件夹：`Win+R` → `shell:startup` → 把快捷方式粘进去。缺点是每次开机才跑，不是固定时间。

### 8.4 三种方式怎么选

| | GitHub Actions | Windows 计划任务 | 开机自启 |
|---|---|---|---|
| 电脑要开机 | ❌ | ✅ | ✅ |
| 固定时间 | ✅ 07:30 | ✅ | ❌ 开机时间 |
| 免费 | ✅ 公开仓库完全不花钱 | ✅ | ✅ |
| 适合 | **长期、省心（推荐）** | 想完全本地、不联网到 GitHub | 临时 |

> ⚠️ **本机计划任务和云端 Actions 请只开一个。** 两边各有独立的去重台账，同时开会把同一批文献推两次。

---

## 9. 换电脑迁移

**代码可以直接复制**（纯标准库、无绝对路径、无注册表依赖），但有 **1 件事必须先删、2 件事必须重做、1 件事必须决策**。

### 第 1 步：复制时排除这些（都是本机运行痕迹）

推荐用 `robocopy`，它会自动跳过被排除的目录：

```powershell
robocopy "D:\journal-alert" "E:\apps\journal-alert" /E ^
  /XD __pycache__ logs reports _probe
```

> `robocopy` 的返回码 1–7 都表示成功（1 = 复制了文件），只有 ≥8 才是出错。所以别被它的退出码吓到。

注意上面**刻意没有排除 `state/`**——这是唯一需要你决策的一项（见下）。

| 排除项 | 原因 |
|---|---|
| `logs/` | 旧日志；`runner.log` 里还写着旧电脑的 Python 路径 |
| `reports/` | 旧日报，纯占地方 |
| `_probe/` | 排查数据源时的临时脚本 |
| `__pycache__/` | Python 字节码缓存 |

**需要你决策的一项：`state/` 要不要一起复制？**

* **一起复制**（推荐）→ 两台电脑共享已读历史，新电脑不会重复推送你在旧电脑上已看过的文献。
* **排除掉** → 新电脑从零开始，第一次运行会把时间窗内所有文献都当成新的。

> 反过来提醒：如果两台电脑都注册了每日任务，各自维护独立台账，那么同一批新文献会在两台机器上各推送一次。要么只在一台机器上开任务，要么定期同步 `state/`。

### 第 2 步：装 Python

见 [第 2.1 节](#2-快速开始)。装完新开一个 PowerShell 窗口，输入 `python -V` 验证。

### 第 3 步：环境自检

```powershell
E:\apps\journal-alert\run_daily.cmd --doctor
```

### 第 4 步：重新注册计划任务（必须重做）

**计划任务存在每台电脑自己的任务计划程序里，不会跟着文件夹走。** 在**新电脑上**按 [第 8.2 节](#8-每天自动运行) 的命令重跑一次。

> 如果新电脑就是用 GitHub Actions，这一步可以跳过——那边与机器无关。

### 第 5 步：推送密钥

密钥**跟人不跟机器**，同一串 SendKey 在新电脑上照样推到你的微信。照 [第 7 节](#7-微信推送) 填一次 `config.local.json`，然后：

```powershell
E:\apps\journal-alert\run_daily.cmd --test-push
```

### 第 6 步：立即验证一次完整运行

```powershell
E:\apps\journal-alert\run_daily.cmd
```

无参数运行 = 计划任务模式：不往屏幕上打印，全部输出写进 `logs\run-last.log`。跑完后检查：

```powershell
Get-Content "E:\apps\journal-alert\logs\runner.log" -Tail 3   # 应看到 exit=0
Get-ChildItem "E:\apps\journal-alert\reports"                 # 应生成当天的 .md
```

也可以直接触发计划任务来验证（这才是真正的生产路径）：

```powershell
Start-ScheduledTask -TaskName "JournalAlertDaily"
```

### 需要整套照抄的改动清单

复制到新电脑后，只有这几处与路径有关，且都**不需要手工改**：

| 位置 | 是否硬编码路径 | 说明 |
|---|---|---|
| `run.py` / `jalert\*.py` | ❌ 无 | 项目根目录由 `__file__` 推导，放哪都行 |
| `run_daily.cmd` | ❌ 无 | 用 `%~dp0` 定位自身，自动搜索 Python |
| `config.json` | ❌ 无 | `reports`/`logs` 都是相对路径 |
| 计划任务 | ✅ 有 | 必须用新路径重新注册（第 4 步） |

### 日志在哪

| 文件 | 内容 |
|---|---|
| `logs\jalert-YYYY-MM.log` | **最详细**：每次抓取、每本刊每个数据源的条数与耗时、失败原因。按月分文件 |
| `logs\run-last.log` | 最近一次运行的完整控制台输出（含崩溃 traceback），**每次运行覆盖**，不会无限增长 |
| `logs\runner.log` | 只记启动时间、选中的 Python 路径、退出码。便于快速看「昨天到底跑没跑」 |

---

## 10. 数据源

**结论：24 本刊里 20 本有可用 RSS；ACS 的 ES&T 与三本 GIS/城市类刊（IJGIS、Transactions in GIS、EPB）没有 RSS，由 OpenAlex + Crossref 双保险；每一本刊都至少有两个独立数据源覆盖，所以任何单一源失效都不会漏掉整本刊。**

| 期刊 | RSS | OpenAlex | Crossref |
|---|---|---|---|
| Nature | ✅ 75 | ⏱ 偶发超时 | ✅ 5 |
| Science | ✅ 45 | ✅ 42 | ✅ 46 |
| Nature Climate Change | ✅ 8 | ✅ | ✅ 1 |
| Nature Geoscience | ✅ 8 | ⏱ 偶发超时 | ✅ 1 |
| Nature Sustainability | ✅ 8 | ✅ | ✅ |
| Nature Cities | ✅ 8 | ✅ 1 | ✅ 1 |
| Nature Communications | ✅ 8 | ✅ 34 | ✅ 61 |
| Science Advances | ✅ 83 | ⏱ 偶发超时 | ✅ 83 |
| Earth's Future | ✅ 9 | ✅ 4 | ✅ 30 |
| Atmospheric Chemistry and Physics | ✅ 20 | ✅ 5 | ✅ 5 |
| Environmental Science & Technology | ❌ ACS 已停 RSS | ✅ 23 | ✅ 25 |
| Environmental Research Letters | ✅ 10 | ✅ 5 | ✅ 14 |
| Geophysical Research Letters | ✅ 26 | ✅ 5 | ✅ 13 |
| Journal of Geophysical Research: Atmospheres | ✅ 14 | ✅ 5 | ✅ 6 |
| Atmospheric Environment | ✅ 55 | ✅ 1 | ✅ 60 |
| Remote Sensing of Environment | ✅ 86 | ✅ 7 | ✅ 60 |
| Computers, Environment and Urban Systems | ✅ 37 | ✅ 1 | ✅ 37 |
| Landscape and Urban Planning | ✅ 34 | ✅ 9 | ✅ 65 |
| Urban Climate | ✅ 93 | ✅ 7 | ✅ 37 |
| Cities | ✅ 100 | ✅ 29 | ✅ 294 |
| ISPRS Journal of Photogrammetry and Remote Sensing | ✅ 60 | ✅ 10 | ✅ 79 |
| International Journal of Geographical Information Science | ❌ 无 RSS | ✅ 0 | ✅ 1 |
| Transactions in GIS | ❌ 无 RSS | ✅ 3 | ✅ 4 |
| Environment and Planning B: Urban Analytics and City Science | ❌ 无 RSS | ✅ 2 | ✅ 2 |

数字是实测某一天时间窗内的条数，仅代表量级。⏱ 表示海外 API 偶发连接超时（重试后多数会成功，即便一直失败也有另外两个源兜底）。

> 表格下半的 8 本刊是 2026-10-10 为「城市地理信息系统」学科新增的（Elsevier 的 5 本走 ScienceDirect RSS，三家 GIS/城市类刊没有 RSS）。它们的数字按**近 7 天**窗口实测，和上半的窗口长度不同，只看量级即可。三家纯 API 的刊物本身出版频率就低（一周 1–4 篇），量少属正常。

**云端实测（2026-10-05）**：Actions 上 16 刊 × 3 源 = 48 次调用，**成功 46 次**。失败的 2 次是 Nature Cities 与 Nature Climate Change 的 RSS 报 XML 解析错误（`not well-formed (invalid token)`），0.2 秒即返回，属瞬时问题——本机抓同一地址正常。**因为每刊都有多源兜底，覆盖没有缺口。**

**云端实测（2026-10-10，扩到 24 刊后）**：24 刊 × 3 源 = 72 次调用，**成功 69 次**，抓取 772 篇（去重后）。失败的 3 次全部是 Nature 系 RSS 的同一个 XML 解析错误（Nature Geoscience / Nature Sustainability / Nature Cities），与新增的 8 本刊无关——**新增的 5 个 ScienceDirect RSS 全部一次成功**。

踩坑记录（以后加期刊时有用）：

* **Wiley / AGU 的 RSS 地址必须用「不带横线」的 ISSN**：`https://agupubs.onlinelibrary.wiley.com/feed/19448007/most-recent`。带横线的 `1944-8007` 一律 404，这一条卡了很久。
* **ACS（ES&T）已停止提供 RSS**，落地页里也没有 feed 链接，只能靠 OpenAlex + Crossref。
* **ScienceDirect（Elsevier）的 RSS 可用**：`https://rss.sciencedirect.com/publication/science/<不带横线的ISSN>`，而且条数很多（Atmospheric Environment 55 条、RSE 86 条）。2026-10-10 又验证了 5 本城市/GIS 类刊同样可用：CEUS、Landscape and Urban Planning、Urban Climate、Cities、ISPRS J. Photogrammetry。
* **不是所有刊都有 RSS**。三家 GIS/城市类刊（IJGIS、Transactions in GIS、EPB）在 Taylor & Francis / SAGE 上，feed 地址不稳定，索性留 `"rss": ""` 走 OpenAlex + Crossref——**空 RSS 是合法配置，不会报错**，和 ES&T 一个待遇。
* **Copernicus（ACP）**：`https://acp.copernicus.org/xml/rss2_0.xml`。
* **IOP（ERL）**：`https://iopscience.iop.org/journal/rss/1748-9326`。
* **Nature 的 RSS 里混有大量新闻/评论/播客**（DOI 前缀 `10.1038/d41586`），已由 `exclude_doi_prefixes` 过滤掉，只留研究论文。
* **Elsevier 的日期是「期号日期」，可能在未来**（例如今天 10-04，条目显示 12-01）。报告里这类条目会自动标注「在线预发表」，排序时也按今天处理，不会顶到最前面。
* **Crossref 的日期字段可能只有年份**（`date-parts: [[2026]]`），早期版本会因此崩溃，现已容错。
* **OpenAlex/Crossref 对国内网络偶发超时**，所以设了 45 秒超时 + 重试，并把抓取做成 6 路并发（顺序抓取要 16 分钟，并发后约 4 分钟）。

---

## 11. 故障排查

| 现象 | 原因与处理 |
|---|---|
| 报告里「数据源状态」出现 ❌ | 正常现象，单个源失败不影响整体。常见原因：出版商反爬（ACS/IOP/ScienceDirect 常见 403）、对方临时故障。会靠 OpenAlex/Crossref 兜底 |
| 一次运行时间很长 | OpenAlex 大刊（如 Science、Nature Communications）返回条数多，加上失败重试会慢。可以 `--sources rss` 只用 RSS 提速，或在 `window.max_items_per_journal` 调小 |
| 推送没收到 | 看 `logs/jalert-YYYY-MM.log` 里 `push ... FAIL` 那行。最常见是 SendKey 填错，或微信没关注服务号。详见 [第 7.4 节](#7-微信推送) |
| 报告里空空的 | 看日志里 `keyword matched X/Y`。若 Y 很大而 X=0，说明关键词 `terms` 没覆盖到实际用词，去 `config.json` 加词 |
| 想重看某天 | 直接打开 `reports\YYYY-MM-DD.md`；历史台账查 `state\seen.sqlite` 的 `articles` 表 |
| 想重新推送一次 | 删掉 `state/seen.sqlite` 里对应行即可（或简单删库重来，会重新报告时间窗内所有文献） |
| `runner.log` 里写 `no usable Python 3 found` | 装 Python 并勾选 `Add python.exe to PATH`，或让 DSH 装一份运行时 |
| `--doctor` 显示写入权限不可写 | 别放在 `C:\Program Files` 等受保护目录，换 `D:\`、`E:\` 或用户目录 |
| `--doctor` 显示海外站点全部 FAIL | 这台机器的网络策略挡住了 Python。检查代理设置与安全软件白名单 |
| 计划任务显示「就绪」但从没执行过 | 检查是否勾了「只在交流电下运行」；用 [第 8.2 节](#8-每天自动运行) 的 `$settings` 重注册一次 |
| 日报是空的（刚换电脑） | 正常——`state/` 是从旧电脑复制过来的，所有文献都算已读。删掉 `state\seen.sqlite` 再跑一次 |
| 想换回全新开始 | 删掉 `state\` 和 `reports\` 整个目录，下次运行会重新报告时间窗内全部文献 |
| 云端日报文件名日期差一天 | 说明 `TZ` 没生效。确认工作流的 job 级 `env:` 里有 `TZ: Asia/Shanghai` |
| 本地和 Actions 同时跑 | 会各自基于自己那份台账判断「新增」，可能重复推送。只开一边，或跑完先同步 |
| 同一天手动重跑，日报条目变少 | 设计行为：报告只含**本次运行**的新增，同一天第二次运行会把当天报告覆盖成只剩第二次的新增。每天只跑一次定时任务不会遇到 |

---

## 12. 维护备忘

本节是给**本机这个工作副本**用的运维记录，普通使用者可以跳过。

### 12.1 现状（2026-10-10）

| 项目 | 状态 |
|---|---|
| 仓库 | `pkui1mpression-design/Journal-alert`（**大小写敏感**），默认分支 `main`，公开 |
| 运行方式 | GitHub Actions 每天 07:30（北京），本机计划任务 `JournalAlertDaily` **已注销**（XML 备份在 `C:\Users\wangs\JournalAlertDaily-task-backup.xml`） |
| 仓库 Secret | `SERVERCHAN_SENDKEY` 已建（**建议轮换**，见下方） |
| 仓库变量 | `JALERT_MAILTO = pkui1mpression@gmail.com` |
| 推送验证 | ✅ run #2 日志 `push serverchan OK code=0` |
| 期刊 | 24 本（20 本有 RSS，4 本纯 API：ES&T、IJGIS、Transactions in GIS、EPB） |
| 日报格式 | 2026-10-06 起头部带 YAML 属性，数据源状态段压成一行摘要（`output.source_status = summary`）；历史三篇已按同格式回填 |
| 学科分区 | 2026-10-10 起：`main: true` 的四个学科留在主日报，`城市地理信息系统` 等新学科写进 `reports/<学科>/` 子目录（见 [4.2](#42-按学科分流的子目录)） |
| 在线卡片墙 | 2026-10-10 上线：<https://pkui1mpression-design.github.io/Journal-alert/>，Pages 源 = `main` / `/docs`（见 [4.1](#41-在线卡片墙)） |
| 日报库 | `D:\journal-alert-reports\` —— 只镜像 `reports/` 的 Obsidian 库（**不带 git**）；同步走 `api.github.com`，双击 `同步.cmd` 或由计划任务 `JournalAlertObsidianSync` 每天跑 5 次（见 [第 5.3 节](#53-自动同步windows-计划任务)） |

**历史提交里的明文 SendKey**：这个坑踩过两次。`config.json` 一旦被本地旧副本覆盖，明文密钥就会跟着进公开仓库。`--force` 或后续提交都**不能**真正撤回——Git 对象还在，按 SHA 直取照样能读到未登录内容。

| commit | 时间 | 情况 |
|---|---|---|
| `4d6a1224` | 2026-10-05 前 | 已轮换处理 |
| `4a95fb79` | 2026-10-10 | 推送方误用过期工作副本带进去，暴露约 20 分钟；`ce264f2b` 已从分支顶端移除，**但对象仍在历史里** |

**唯一可靠的补救是把密钥作废（轮换）**，然后写进 GitHub 仓库 Secrets，`config.json` 里的 `sendkey` 永远留空 `""`。要真正清掉历史对象只能删库重建（需 PAT 带 `delete_repo` 权限）或找 GitHub Support。

> 教训：**推送前先 `GET contents/config.json` 拿远端真实版本**，不要在本地旧副本上改完直接覆盖。这两个 commit 都是这么来的。

### 12.2 本机推拉代码：拉取用 git，推送走 REST API

**2026-10-06 更正**：早先记的「git 通道完全不通」只对了一半。

| 操作 | 实测结果 |
|---|---|
| `git fetch origin` / `git ls-remote`（走代理） | ✅ 通，几秒返回 |
| `git push`（走代理） | ❌ 认证已通过（`HTTP 200`），但**发送数据阶段进程被 SIGTERM 掐断**，远端 ref 不动 |
| `https://api.github.com`（直连） | ✅ 200 OK |

所以分成两条路：**拉取用 git**（快、完整、不怕签名提交），**推送仍走 REST API**。

| 脚本 | 作用 |
|---|---|
| `.workbuddy/push-to-github.sh` | 统一入口。直接跑 = 推送 |
| `.workbuddy/api-push.py` | 把本地提交**原样重建**到远端（含作者、时间、完整提交信息） |
| `.workbuddy/api-pull.py` | **已不推荐**，拉取改用 git（原因见下方坑 6） |
| `.workbuddy/check-ci.py` | 验收 Actions 运行：列步骤结论 + 取日志关键行。**无 token 也能判定成败** |

推送时逐层校验 sha——blob、tree、commit、ref 全部相等才收工。看到 `tree ... [OK]` 和末尾 `完全一致 : YES` 就是成功。

**日常顺序：先同步 → 改代码 → 再推送。**

```bash
git fetch origin && git rebase origin/main   # 拉取；CI 每天都会往 main 追加一个 chore(state) 提交
bash .workbuddy/push-to-github.sh            # 推送
```

**不要在分叉状态下强推**，那会冲掉云端积累的去重台账。

**踩过的坑（都已修进脚本）**

1. commit 信息必须取自 `git cat-file commit` 的**原始字节**——`%b` 的 body 没有尾部换行，差一字节 sha 就变了。
2. 增量推送的 `base_tree` 必须取**远端父提交的树**。漏了会把整个仓库替换成一个文件；现在移动 ref 前会逐层校验，任何 tree 对不上就中止。
3. 全量重建时**根提交不能挂 parent**，否则整条链 sha 全变。
4. 路径含中文时 `git diff-tree --name-status` 要加 `-z`，否则路径被转义，`rev-parse` 报 not exist。
5. `api-pull.py` 会 `git reset --hard`，工作区里**未提交**的改动会被冲掉（已加保护：有未提交的已跟踪改动时直接拒绝执行）。
6. **`api-pull.py` 重建不了网页上编辑出来的提交**。GitHub 网页改文件会产生**签名提交**（`verification.verified = true`，对象里多一段 `gpgsig` 头），而且 author 是 `+0800`、committer 是 GitHub 的 `+0000`——两个变量叠加，重建必然 sha 不符。作者/committer 偏移已改成分别试，签名那段仍是死结。**既然 `git fetch` 能用，就别跟它较劲了。**
7. `sparse-checkout` 的 **cone 模式总是保留根目录文件**。想只留 `reports/` 必须 `git config core.sparseCheckoutCone false` 再手写 `.git/info/sparse-checkout`。另外在 Git Bash 里 `sparse-checkout set /reports/` 会被 MSYS 当成绝对路径展开，务必用规则文件那套写法。

详细的排查与用法见本机技能 `~/.workbuddy/skills/github-push-via-api/`。

### 12.3 取 Actions 日志

```python
import urllib.request, urllib.error

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None

# 直接跟重定向会 401：Authorization 被一起转发，把目标的 SAS 令牌顶掉了
op = urllib.request.build_opener(NoRedirect)
req = urllib.request.Request(
    "https://api.github.com/repos/<owner>/<repo>/actions/jobs/<job_id>/logs",
    headers={"Authorization": "Bearer " + TOKEN, "User-Agent": "logfetch"})
try:
    data = op.open(req, timeout=60).read()
except urllib.error.HTTPError as e:
    # 关键：这一步千万别带 Authorization
    data = urllib.request.urlopen(
        urllib.request.Request(e.headers["Location"], headers={"User-Agent": "logfetch"}),
        timeout=120).read()
```

也可以直接跑 `.workbuddy/check-ci.py --logs`。

---

## 许可证

MIT，见 [LICENSE](LICENSE)。
