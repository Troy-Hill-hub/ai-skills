---
name: paper-download-pku
description: 在本机（北大深研院 / 深圳大学城校园网 + Chrome）按 DOI 或 Excel 清单批量下载期刊全文 PDF，并归档到分类目录。适用于 Wiley、RSC、Nature/Springer、Science、ACS、Elsevier ScienceDirect 等出版商，含 ScienceDirect 的北大 CARSI 登录流程、Cloudflare 与限流处理、PDF 完整性校验。当用户要求“下载文献 / 下全文 / 按表格下 PDF / 批量抓 paper / 补下失败的几篇”时使用。
agent_created: true
---

# 本机文献全文下载

在这台机器上把期刊论文 PDF 下全，靠三件事：**校园网机构 IP**（解决订阅权限）、**真实 Chrome 的页面导航**（解决 Cloudflare 反爬）、**持久化登录态**（解决 ScienceDirect 的机构认证）。curl / requests 直连出版商一律 403，不要尝试。

## 何时使用

- 用户给一份 Excel / CSV / DOI 清单，要求下全文并按分类归档。
- 用户要补下之前失败的若干篇。
- 用户问“为什么这篇下不了 / 怎么才能下”。

## 环境事实（先确认，别猜）

| 项 | 值 |
|---|---|
| Python 解释器 | `C:\Users\<用户名>\.workbuddy\binaries\python\envs\default\Scripts\python.exe`（已装 playwright / pypdf / openpyxl） |
| 浏览器 | Playwright `chromium-1248` 已装；优先 `channel="chrome"` 用系统 Chrome（反爬通过率明显更高） |
| 校园网出口 | IPv4 `<机构公网 IPv4>`（出版商识别为机构 IP）；IPv6 `<机构 IPv6>`（对 ScienceDirect 无用，无 AAAA 记录） |
| 默认 profile | `~/.workbuddy/cache/paper-download-profile`（存 CARSI 登录态，可复用数天） |

以上为**参考值**，不是硬编码。换机器时按下节「移植到其他机器」核对，不要照抄路径。

脚本：`scripts/fetch_papers.py`（主下载器）、`scripts/sd_login.py`（ScienceDirect 登录）。出版商细节与失败特征见 `references/publishers.md`——遇到不认识的报错先读它。

## 标准流程

1. **确认清单字段**：Excel 需「编号 / 主研究方向 / 论文题目（原文）/ 出版年（WoS）/ DOI」。缺列先与用户对齐，不要自己编列名。
2. **先试跑 1–2 篇**（`--limit 2`），确认拿到 `%PDF` 且页数正常，再全量。
3. **全量跑**：`from-xlsx` 或 `from-json`，脚本按 DOI 前缀自动选出版商与限速。
4. **收尾校验**：逐篇 `pdf_ok`（魔数 + 页数 ≥ 2 + 大小），并抽检 PDF 与题录是否对应（元数据 `/Title`、`/doi` 或首页文字）。
5. **报告差异**：成功/失败清单分开给，失败项按出版商归类说明原因与下一步，不要笼统说“下载失败”。

```bash
PY="C:/Users/<用户名>/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
SK="C:/Users/<用户名>/.workbuddy/skills/paper-download-pku/scripts"

# 全量 / 补下缺失
"$PY" "$SK/fetch_papers.py" from-xlsx \
  --xlsx "D:/AgentsLocal/无负极钠电文献_去重与重新分类.xlsx" --sheet 文献总表 \
  --out-root "D:/AgentsLocal/无负极钠电文献_分类全文"

# 只补某几篇 / 某个出版商
"$PY" "$SK/fetch_papers.py" from-xlsx --xlsx ... --sheet 文献总表 --out-root ... \
  --only AFNa-060 AFNa-079 AFNa-041
"$PY" "$SK/fetch_papers.py" from-xlsx --xlsx ... --sheet 文献总表 --out-root ... \
  --doi-prefix 10.1002 10.1039
```

`from-json` 的清单格式：`[{"id","doi","dir","title","year"}]`，方便临时拼小批。

## ScienceDirect（Elsevier，10.1016）专门流程

10.1016 开头的 DOI 不能直连，必须先建立机构会话：

```bash
"$PY" "$SK/sd_login.py"          # 打开有头 Chrome，自动选 Peking University
```

窗口里由**用户本人**输入北大 IAAA 学号 + 密码（脚本只轮询 `Brought to you by` 是否出现，不接触密码）。看到该字样即成功，登录态写入 profile，后续批量直接复用。

对用户的沟通要点：
- 只需他点一次登录（或扫码），之后不用再管；几天后会话过期时重跑一次。
- 机构要选 **Peking University**，不要选“深圳大学城图书馆”（Elsevier 会记成另一个机构，权益与流程不同）。

## 硬约束（踩过的坑，务必遵守）

- **只用浏览器导航取 PDF**：优先 `page.on("download")`，其次 `page.on("response")` 中 content-type 含 pdf 的 body。禁止用 `ctx.request.get` 抓出版商 PDF（403）。
- **落盘前必须校验**：`%PDF` 魔数 + `pypdf` 页数 ≥ 2 + 大小 > 60KB。实测出现过 262144 字节的截断文件、以及 52KB 的 HTML 错误页；不校验就会把垃圾当论文存进库里。
- **限速**：Wiley 4–8s、RSC 8–12s、Science 12–18s、ScienceDirect **25–40s**。ScienceDirect 触发 429 后必须冷却 15–30 分钟，期间重试只会延长封禁。
- **不要**：curl/requests 直连出版商；给 `<a>` 加 `download` 属性强下 ScienceDirect（存下的是中间页 HTML）；复制用户默认 Chrome profile 冒充登录（照样卡 Turnstile）；用 Chrome 136+ 的默认 `User Data` 开远程调试（被禁）。
- **PDF 内嵌预览**：Chrome 默认在标签页渲染 PDF，不产生 download 事件。需把 profile 的 `Default/Preferences` 中 `plugins.always_open_pdf_externally` 设为 `true`（脚本已自动处理）。
- **残留进程**：报 `Target closed` 或“已在已有会话中打开”时，先 `taskkill /F /IM chrome.exe` 再重试。
- 浏览器默认**有头**运行（通过率更高）。批量期间提醒用户别关窗口。

## 命名与归档

```
<根目录>/<主研究方向>/<编号>_<年份>_<标题前 116 字符>.pdf
```

标题中 `/:*?"<>|` 换空格、折叠连续空白。若目标目录里已有别的截断长度，**以已有文件为准**，不要为了统一重命名用户已归档的文件。

## 收尾

- 给成功/失败统计；失败项列编号、DOI、原因（无权限 / 验证码 / 限流 / 该刊不在订阅内）。
- 仍可救的（限流冷却后重试、OA 走 PMC）说明做法与时间窗，让用户决定是否继续。
- 提醒用户：某个分类目录为空，可能只是那几篇恰好都在失败清单里，不是漏归档。

## 移植到其他机器

本 skill 的方法论通用，只有四处与机器/账号绑定，换环境时逐条核对：

1. **Python 解释器**：换成目标机的 python，并确认 `pip install playwright pypdf openpyxl` + `playwright install chromium`。
2. **浏览器**：`fetch_papers.py` 用 `channel="chrome"`，目标机需装 Chrome；没有就删掉该参数改用 Playwright 自带 chromium（反爬通过率会低一些）。
3. **网络**：必须能出校园网机构 IP。先用浏览器打开任一订阅期刊文章页，页面顶部出现机构名（如 `Brought to you by: Peking University`）才说明权益生效。校外需先连学校 VPN/WebVPN。
4. **账号**：CARSI 登录用**使用者本人**的北大 IAAA 账号，不要共用会话；profile 目录默认在 `~/.workbuddy/cache/paper-download-profile`，每人各自一份。

验证方法：随便挑一篇已知可下的 Wiley/Elsevier 文章跑 `--limit 1`，能拿到 `%PDF` 且页数 ≥ 2 即环境就绪。

给不支持 skill 的 AI（网页版对话模型）使用时，把本文件正文和 `references/publishers.md` 直接作为提示词/知识库投喂，脚本让对方自己执行；此时只能提供方法与判断依据，无法代为操作浏览器。
