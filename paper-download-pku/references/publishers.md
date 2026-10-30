# 出版商下载策略与失败特征（本机实测，2026-10）

## 一、本机网络环境

| 项 | 值 |
|---|---|
| 公网 IPv4 | `<机构公网 IPv4>`（深圳大学城图书馆 / 北大深研院出口，被多数出版商识别为机构 IP） |
| IPv6 | `<机构 IPv6>`（CERNET2，可直连但 ScienceDirect 无 AAAA 记录，绕不过去） |
| DNS | `<校内 DNS>`（校内 DNS） |
| 代理 | 环境变量 `http_proxy=http://127.0.0.1:1595`（WorkBuddy 沙箱代理）；Playwright / Chromium **不走**这个代理 |

机构 IP 只解决“订阅权限”，解决不了“反爬”。Cloudflare 拦截与权限是两回事，必须区分。

## 二、各出版商

### Wiley（10.1002）
- 直连：`https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true`
- 会 302 到 `advanced.onlinelibrary.wiley.com` 等子域，正常。
- 实测 42 篇一次跑通，间隔 4–8 秒即可；不需要 landing 页。
- 失败特征：`403 text/html`（curl 或 `ctx.request` 直发）；浏览器导航不受影响。

### RSC（10.1039）
- 直连：`https://pubs.rsc.org/en/content/articlepdf/{年}/{刊代码}/{doi后缀}`
  例：`10.1039/d5ee03213j` → `/articlepdf/2025/ee/d5ee03213j`，会 301 到正式地址。
- 之后走 `SilentOIDCLogin`，靠 IP 自动完成机构认证，页面会显示 `UNIVERSITY TOWN LIBRARY OF SHENZHEN`。
- 落地页首次加载要 6–9 秒（SSO 往返），等太短会抓不到 PDF 链接。
- 实测 6/6 成功。

### Nature / Springer（10.1038）
- `https://link.springer.com/content/pdf/{doi}.pdf`（备用 `https://www.nature.com/articles/{后缀}.pdf`）
- 元数据里 `/doi`、`/Subject` 字段可直接核对，适合做正确性校验。

### Science / AAAS（10.1126）
- `https://www.science.org/doi/pdf/{doi}?download=true`
- Cloudflare 会给 “Performing security verification”，等待上限必须 ≥ 90 秒，偶尔才放行；短超时会误判失败。
- 兜底：Science Advances 全 OA，走 Europe PMC。
  - 查 PMCID：Europe PMC REST `search?query=DOI:"<doi>"&format=json&resultType=core`（`hasPDF=Y`）
  - 下载：`https://pmc.ncbi.nlm.nih.gov/articles/{PMCID}/pdf/`（`www.ncbi.nlm.nih.gov/pmc/...` 与 `europepmc.org/articles/{PMCID}?pdf=render` 都不稳）
  - 注意：该 API 用 curl 请求会 503/被拦，要在**浏览器上下文里 `fetch`** 才行。

### ACS（10.1021）
- `https://pubs.acs.org/doi/pdf/{doi}?download=true`，Cloudflare 同样存在，靠浏览器导航 + 较长等待。

### Elsevier / ScienceDirect（10.1016）——最麻烦
- **不要**用“深圳大学城图书馆”机构登录（Elsevier 会记住这个机构名，其权益/流程不同）。
- 正确姿势：机构登录页选 **Peking University** → `idp.pku.edu.cn` → `iaaa.pku.edu.cn` 学号+密码。
  登录成功后文章页顶部出现 `Brought to you by: Peking University`，Cloudflare Turnstile 也不再拦。
- 自动化入口：`https://www.sciencedirect.com/user/institution/login?targetURL=%2F`
  点「取消」→ 在 `input[type=text]` 填 `Peking` → 点 `text=Peking University` → 人工登录（脚本只轮询等结果，不碰密码）。
- 登录态存在持久化 profile 里，可复用数天；过期重跑 `sd-login` 即可。
- 下载：进文章页（`/science/article/pii/{PII}`）→ 点 `a:has-text('View PDF')`。
  - PII 可从 Crossref 拿：`api.crossref.org/works/{doi}` 的 `alternative-id`（S 开头）。
  - 必须让 Chrome 直接把 PDF 当下载处理，否则会内嵌预览、抓不到文件：
    在 profile 的 `Default/Preferences` 里写 `plugins.always_open_pdf_externally = true`。
- **限流**：`/pdfft` 端点密集请求会返回 HTTP 429，页面文案仍是
  “There was a problem providing the content you requested”，极易误判成“没权限/封 IP”。
  判别方法：把响应存下来看文件头，是 `<!doctype html>`（约 52KB）而不是 `%PDF`。
  触发后要冷却 **15–30 分钟以上**，继续重试只会延长封禁。正常节奏 25–40 秒/篇。
- 无效的绕行手段（都试过，别浪费时间）：`ctx.request.get` 直取 pdfft（403）；签名 CDN
  `pdf.sciencedirectassets.com/...main.pdf`（curl 403，浏览器内也被 CF 判为脚本）；
  `europepmc` CDP `Network.getResponseBody`（PDF 插件文档拿不到 body）；
  给 `<a>` 加 `download` 属性再 click（会把 52KB 的 HTML 中间页当 PDF 存下来）；
  手机 UA、referer 链、`linkinghub.elsevier.com` 入口（同样拦截）。

## 三、通病与对策

| 现象 | 原因 | 对策 |
|---|---|---|
| `403 text/html` 5–6KB | Cloudflare 拦非浏览器客户端 | 一律用 Chromium 页面导航，禁用 curl / `ctx.request` |
| 文件正好 262144 字节 | 响应流被截断（response 分支） | 优先 `page.on("download")`，并用 pypdf 校验页数 |
| 文件是 `<!doctype html>` 开头 | 拿到的是错误页/挑战页/429 页 | 落盘前对比 `%PDF` 魔数 + 页数 ≥ 2 |
| `Page.goto: Download is starting` | 导航触发下载，属正常 | try/except 吞掉，用 download 事件取文件 |
| `expect_page` 报 AttributeError | 异步 API 叫 `expect_popup` | 用 `page.expect_popup()` |
| Chrome 启动即 “Target closed” / 在已有会话中打开 | profile 被上次残留进程占用 | 先 `taskkill /F /IM chrome.exe` |
| Turnstile 一直 “Verifying…” | 自动化特征 / 新 profile 无历史 | 用真实 Chrome（`channel="chrome"`）+ 已登录 profile；别折腾复制用户 profile |
| Chrome 136+ 默认 profile 开不了调试端口 | 安全限制 | 别用用户默认 `User Data`；用独立 profile 目录 + CARSI 登录 |

## 四、命名与归档约定

```
<根目录>/<主研究方向>/<编号>_<年份>_<标题前 116 字符>.pdf
例：无负极钠电文献_分类全文/液态电解液设计/AFNa-008_2026_Data-Driven KnowledgeDiscovery....pdf
```
标题里的 `/:*?"<>|` 替换成空格，连续空白折叠，末尾不保留空格。
