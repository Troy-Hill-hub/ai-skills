# 环境要求与迁移

## 最小运行环境

| 能力 | 要求 | 不具备时 |
| --- | --- | --- |
| 本地文件读写 | 可读原 PDF；可写输出目录、独立状态目录；足够磁盘空间 | 先解决真实路径或权限，不把文件操作请求描述成已完成 |
| Python | Python 3.10+；推荐独立 venv；核心依赖 pypdf | 定位可用解释器或在允许的环境安装依赖 |
| 元数据/公开附件网络 | HTTPS、正常证书验证；标准 urllib 即可 | 用 agent 的联网工具发现链接；可在另一环境下载后离线 ingest |
| 浏览器备用路线 | 用户的普通 Chrome / Edge 或当前平台支持的正常浏览器，能访问目标官网和保存文件 | 用户完成机构认证、浏览器操作或下载；仍可由脚本核验归档 |
| 视觉 QA（推荐） | pypdfium2 + Pillow | 用现有 PDF 渲染器；无法渲染时准确报告该项未完成 |
| 网页检索 | 可读官方页面/链接的联网工具、连接器或浏览器 | 脚本不包含通用全站爬虫，不能凭空生成附件 href |

Python 工具跨平台；附带 PowerShell 浏览器启动器仅适用于 Windows。无需 Node.js、Playwright、Selenium、Excel、Word、管理员账号或浏览器 Cookie 导出。扫描原文可能需要已有 OCR 工具；本包不内置 OCR。脚本自动支持 PDF/DOCX；DOC、XLSX、ZIP 等交给相应解析工具核验，保留原格式后在项目记录中补充，不能声称 CLI 已自动处理这些格式。

在已有解释器中先检查，而非直接重装：

```powershell
$skillDir = '实际解压或安装后的技能目录'
$py = '当前可用的 python.exe 绝对路径'
& $py "$skillDir/scripts/si.py" doctor
# 仅当依赖缺失且环境允许安装时运行：
& $py -m pip install -r "$skillDir/scripts/requirements.txt"
& $py -m pip install -r "$skillDir/scripts/requirements-qa.txt"
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
```

macOS/Linux 使用 `python3` 或 venv 中解释器；命令参数相同，把 PowerShell 的 `&` 和变量赋值换成本地 shell 写法。不要硬编码原任务用户目录、D 盘、Codex 缓存版本或浏览器 tab ID。

## 文件与下载目录

输入应指向**原文所在目录**；`--recursive` 是显式选项。原文件名以 `SI-` 开头会被视为已有补充材料排除；若原文恰好也这样命名，应另列输入目录或调整索引规则并说明。

状态目录建议放在工作区中的独立位置，如 `.si-project`。其中含原文首页文本、文件路径、官网 URL、审核证据和 SHA-256，应随研究文件妥善保存；发布技能包时不携带该项目状态、原文全文、下载文件、Cookie 或认证令牌。

不能假定下载目录一定是 `~/Downloads`。Windows 可只读查系统已知文件夹，再核对浏览器当前实际保存位置：

```powershell
$folders = Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
$downloadDir = [Environment]::ExpandEnvironmentVariables($folders.'{374DE290-123F-4565-9164-39C4925E467B}')
```

机构会话未必能跨浏览器、跨配置文件或跨自动化工具复用。使用用户当前工作的普通浏览器，而不是新建无登录状态的临时 profile。私有机构认证需要用户提供/完成；不预设任何学校或图书馆一定能登录。

## 在其他 agent 中使用

1. 复制整个 `download-literature-si` 文件夹；`SKILL.md` 与 `scripts/`、`references/` 的相对结构必须保留。
2. 支持技能发现的产品：放进其支持的技能目录。Codex 通常放在当前用户 `CODEX_HOME/skills`（未设置时 `~/.codex/skills`）；会话需重新加载技能目录才能发现新增技能，具体行为以宿主为准。
3. 不支持技能系统的 agent：让它先读 `SKILL.md`，再按路由读需要的参考文档，使用其本身的终端、搜索和浏览器工具。CLI 不要求任何专用 MCP。
4. 在新机器定位 Python、浏览器、输入和下载目录，运行 doctor，用新的 state 路径建立项目。要迁移一个未完成项目，先备份状态，重定位 `root` 及输出/本地源路径，再用 audit 核对，不能直接把旧机器绝对路径当作有效。

本包通过当前工作流的离线回归测试；网络访问、浏览器授权和网站风控必须在目标环境现场确认。`doctor` 只验证本地依赖，不验证网络、机构权限或网页是否能下载。

创建时验证环境为 Windows、Python 3.12.14、pypdf 6.10.0、pypdfium2 5.14.0、Pillow 12.3.0；这些是实测版本，不是必须复刻的绝对依赖。macOS/Linux 的 Python 路径是可移植设计，未在本次任务中实机验证。

复核脚本可离线执行：`python scripts/selftest.py --workdir <可写测试目录>`。需要视觉 QA 依赖，生成独立的合成原文、DOCX/PDF 和 JSON 报告；不访问网络、不启动浏览器、不触碰真实论文。测试目录有意保留供查看，不打包进技能发布文件。
