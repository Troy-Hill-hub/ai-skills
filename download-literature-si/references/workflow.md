# 命令、项目状态与核验流程

## 1. 索引和确认原文

运行 `inventory --folder <原文目录> --state <状态目录>`。只读取 PDF，默认不递归，排除 `SI-` 前缀。`project.json` 保存原文哈希、首页文本、嵌入链接、DOI 候选和相对路径；**不会默认选中第一个 DOI**。

查看每篇首页及候选，确认 DOI。可按篇更新，也可由 agent 写 JSON 一次更新，避免 130 次工具往返：

```powershell
& $py "$skillDir/scripts/si.py" set-paper --state $stateDir --id 0001 --doi '10.1002/adfm.202210206'
& $py "$skillDir/scripts/si.py" set-paper --state $stateDir --records "$stateDir/confirmed-papers.json"
& $py "$skillDir/scripts/si.py" metadata --state $stateDir --ids 0001,0002
```

批量 JSON 结构为 `[{"id":"0001","doi":"10.xxxx/实际 DOI","title":"核实后的完整标题","note":"可选的核对依据"}]`；示意值不是合法 DOI，使用真实内容。`metadata` 只请求已确认 DOI 的 Crossref，精确核对返回 DOI 后补标题和官网入口，不从相似标题自动认领文献。Crossref 标题仍应与实际原文一致；错误、缺失或截断时用 `set-paper --title` 修正。

## 2. 发现并登记附件

从官方论文页、原 PDF 的超链接、官方 SI / 开放仓储提取附件。记录所处证据页、最终 href、准确文件名、角色和归属论文。读网页时不要只查 `-sup-`，也要查 `-supp-`、`Supporting Information`、`Supplementary information`、`Appendix`。

```powershell
& $py "$skillDir/scripts/si.py" add-job --state $stateDir --ids 0001,0002 --url $siUrl --filename $actualFile --evidence-url $paperUrl --role main
# 同 DOI 的两个原始 PDF 可以共用一个 job；不同 DOI 会被拒绝。
& $py "$skillDir/scripts/si.py" add-job --state $stateDir --ids 0001 --url $checklistUrl --filename $checklistFile --evidence-url $paperUrl --role checklist
```

默认所有登记的文档都是必需附件。只有用户范围或实际用途明确不需要时才加 `--optional`。`--role extra --label ReportingSummary` 可给附加文件稳定后缀。主 SI 默认无后缀；Checklist 默认 `-Checklist`；不同内容发生文件名冲突时用 `-02`、`-03`，不会覆盖。

批量可写 UTF-8 JSON，然后执行 `add-job --state <状态目录> --records <JSON文件>`。JSON 是记录列表，键为 `ids`（逗号分隔字符串或 ID 字符串列表）、`url`、`filename`、`evidence_url`，可选 `role`、`label`、`optional`。只写已核实的实际附件，不将搜索猜测批量导入。单批登记发生验证错误时不会保存部分改动。

新官方仓储/CDN 不在白名单时，用已经认可的官方页证明来源，再登记主机：

```powershell
& $py "$skillDir/scripts/si.py" allow-host --state $stateDir --host $verifiedHost --evidence-url $knownOfficialPage
```

这只登记已核实的精确主机，不通配域名、不放开任意 URL。代码也检查 HTTPS 重定向目的主机；遇到新的官方 CDN，应核实再添加，不能为通过下载而盲目放宽。

## 3. 下载与整理

`fetch --state ... --jobs J0001,J0002` 每个选中 job 尝试一次；默认只尝试 planned。401/403/429 等进入 `access_unverified`；格式/身份不符进入 `review`。不会自动退避后无限重试。只有证据表明路线变化时才显式 `--retry`。默认单次读取上限 256 MiB、总时限约 180 秒（单次 socket 读还受 20 秒超时影响）；可明确调整 `--max-mb`、`--deadline`。大文件通常转浏览器。

浏览器路线：

```powershell
& $py "$skillDir/scripts/si.py" export --state $stateDir
& "$skillDir/scripts/launch-browser.ps1" -Ledger "$stateDir/browser-jobs.json" -Browser chrome -DownloadDir $downloadDir -Max 2 -DryRun
# 检查 dry-run 后，去掉 -DryRun 才真正打开已核实的附件 URL。
& $py "$skillDir/scripts/si.py" ingest --state $stateDir --downloads $downloadDir
```

`ingest` 可传多个目录，识别大小写差异及 Chrome 的 `name (1).pdf` / `name (2).docx`；依次核验候选，不因一个坏副本而忽略另一个好副本。不会接受临时扩展名。已完成任务幂等跳过；同 DOI 新增原文别名时，会为新原文补副本。不要并发运行同一 state 的 writer；`.writer.lock` 记录 PID，异常遗留时先确认进程已结束，再删除这个**明确的锁文件**，不删除整个目录。

需要等待时由 agent 小间隔检查，不默认创建无人管理的后台下载监视。可每 20–30 秒重新 ingest，关注输入消息和实际增长，按宿主要求汇报进度。启动器记录 `browser-launch-events.jsonl`，重复运行默认不会重发同一链接。仅经判断确需重试后，指定 `-Ids J0001 -Retry`；文件已落盘但被判错时先检查，确需重新请求可另加 `-Force`。`-Force` 不改变浏览器任何安全保护。

## 人工核对

常见情况：只有 Methods、Supporting Text、Figure S1–S14、Table of Contents；PDF 文本把 Supporting 拆成碎片；核对表没有论文标题。先验证结构完整，再核对官网实际链接与原文中的至少几项具体对应关系，不能只看电池主题或文件名。

```powershell
& $py "$skillDir/scripts/si.py" review --state $stateDir --job J0001 --file $completedFile --note 'Official article attachment; Figures S1-S3 and the PFPN/EC/DEC formulation match the original paper page 2; DOCX CRC passes.'
& $py "$skillDir/scripts/si.py" ingest --state $stateDir --downloads $downloadDir
```

审核记录绑定当前 URL、官方证据页和完整文件 SHA-256；更换文件、URL 或证据页后不会自动沿用。`review` 自身不复制文件。它不绕过 PDF/DOCX 结构校验。Checklist 必须人工确认其官方归属和内容后才接收，且始终不能独自使原文 complete。

自动身份核对要求 SI 特征，加**完整标题规范化后匹配**或精确 DOI；相似关键词只能帮助人工检查，不自动放行。原文标题不完整、OCR 缺字或无 SI 标题时，可能产生保守的 review，这是有意保留的核验界限。

## 4. 状态、停止和交付

`project.json` 为唯一续跑状态，`status` 派生报表。不要手动修改汇总数字。

| 层次 | 字段/状态 | 含义 |
| --- | --- | --- |
| paper | DOI 候选、确认 DOI、原文哈希 | 身份与原文保护 |
| job | planned | 已登记的真实附件，尚未尝试 |
| job | access_unverified | HTTP 访问失败，不能推导没有 SI |
| job | review | 已有候选文件，需要内容或格式核验 |
| job | verified + outputs[] | 具体附件及每份原文的输出路径/哈希 |
| paper | complete | 有已核验主 SI，且所有必需 job 都已为该原文生成输出 |
| paper | si_availability_unverified | 尚未发现/确认独立附件，不等于没有 |
| paper/job | skipped_user_request | 用户明确停止或跳过 |
| paper | no_si_confirmed | 官方明确说明不提供，或 agent 已有足以确认的完整官方证据 |

```powershell
& $py "$skillDir/scripts/si.py" mark --state $stateDir --ids 0003 --status skipped_user_request --note 'User explicitly asked to stop this remaining paper.'
# 仅当官方确实确认无 SI，不能只因 403/404 或“这是综述”而使用：
& $py "$skillDir/scripts/si.py" mark --state $stateDir --ids 0004 --status no_si_confirmed --note $officialEvidence
# 用户后续要求恢复时，清除原文 disposition 并恢复关联 job：
& $py "$skillDir/scripts/si.py" mark --state $stateDir --ids 0003 --status planned --note 'User requested resuming this paper.'
& $py "$skillDir/scripts/si.py" mark --state $stateDir --jobs J0003 --status planned --note 'Resume its attachment job if previously skipped.'
& $py "$skillDir/scripts/si.py" status --state $stateDir
& $py "$skillDir/scripts/si.py" audit --state $stateDir --render
```

实际查看 `qa/contact-*.jpg`，检查首末页内容、空白页是否为原件本身、有没有错误/登录页。`audit.json` 中 `visual_review` 提醒 agent 查看，不自动声称通过。原文哈希改变、输出缺失或内容被改都会使 audit 失败。状态目录若非交付目录，把最终清单/记录复制到用户指定交付处；链接使用当前真实绝对路径。

最终说明完成原文数、附件数、重复 DOI 处理和每类例外；不能把部分完成写成全部成功。保留 URL 证据和审核记录，不删除用户下载目录中的文件。CLI 脚本不取消浏览器中的下载，也不修改 PDF 偏好；若曾改变偏好，按用户约定恢复或准确说明仍待用户恢复。
