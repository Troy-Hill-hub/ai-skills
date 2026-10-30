# 官方附件发现路线

下面是路线和 2026-10-30 的实测示例，**不是可按编号批量猜测的 URL 生成器**。每篇都应核对当前官网真实 href。元数据 API 可帮助找 DOI、PII 或 PMCID，但不能替代 SI 内容核验。主机和 API 可能变化；失效时查官方页面，不循环尝试成百上千个候选。

## Wiley：重点路线

1. 打开 DOI 对应的 `onlinelibrary.wiley.com` 或 `advanced.onlinelibrary.wiley.com` 官方论文页。
2. 查找 `Supporting Information`，展开折叠区，收集每个属于范围的文档文件名和链接。摘要入口 `/doi/abs/<DOI>` 有时也列 SI；它是另一种官网入口，不保证能解除验证。
3. 真实附件常用 `/action/downloadSupplement?doi=<URL编码DOI>&file=<准确文件名>`。不要依靠旧 `/doi/suppl/.../supinfo/...` 规律；该路线在本批不少论文返回 404。
4. 通过搜索工具点击附件后，即便抓取返回 403，错误结果里暴露的**实际 href**可作为浏览器下载地址；只能说“已找到链接”，不能说“已下载”。以正常浏览器下载并完成落盘核验。

真实例子：

| DOI | 官网列出的附件 | 经验 |
| --- | --- | --- |
| 10.1002/adfm.202210206 | adfm202210206-sup-0001-SuppMat.pdf | Chrome 预览曾正常显示 43 页；控制接口失败不等于 PDF 未打开 |
| 10.1002/adfm.202526995 | adfm74060-sup-0001-SuppMat.docx | 文件编号与 DOI 不一致；正文从 Methods 开始，无标题页 |
| 10.1002/anie.202503691 | anie202503691-supp-0001-SuppMat.docx | `-supp-` 两个 p |
| 10.1002/anie.202503864 | anie202503864-supp-0001-SuppMat.docx；另有 -supp-0002-SuppMat.pdf | 第二份是电池数据核对表，不能当作主 SI |
| 10.1002/anie.2602693 | anie73976-sup-0001-SuppMat.docx | 官网标注约 58.9 MB，完成要等实际传输 |
| 10.1002/adfm.77962 | adfm77962-sup-0001-SuppMat.docx | 官网标注约 121.1 MB，不能用固定短超时推断文件不存在 |

示例已公开的 Chen 附件地址：

`https://advanced.onlinelibrary.wiley.com/action/downloadSupplement?doi=10.1002%2Fadfm.202210206&file=adfm202210206-sup-0001-SuppMat.pdf`

这些示例是说明“如何读实际链接”；不要向用户重新下载今天已停止的论文，除非收到恢复请求。

## ACS

官网论文的 Supporting Information 区、PDF 嵌入链接及 ACS 官方 Figshare 是优先入口。传统形式如 `https://pubs.acs.org/doi/suppl/<DOI>/suppl_file/<准确文件名>_si_001.pdf` 只在官方实际给出时使用。期刊前缀与论文编码的映射并不通用；只凭 DOI 拼出 `_si_001.pdf` 是未核实候选。

若官网转到 `acs.figshare.com`，从其页面/API 返回的文件记录读取下载链接；不能使用其他论文的 SI。跳转到新 CDN 时先确认官方关联并登记新主机。ACS/Figshare 403 仍是访问未核实，不能写“无权限”或“无 SI”。本次已有 32 个原文对应的 ACS SI 核验成功，不代表今后每条直链都能访问。

## Elsevier / ScienceDirect

从官网 DOI/PII 对应页面的 `Appendix A. Supplementary data`、`Supplementary material` 或附件区取链接；Crossref `link[]` / resource 可辅助确认 PII。已在官网观察到的附件常形如：

`https://ars.els-cdn.com/content/image/1-s2.0-<PII>-mmc1.pdf`

编号、扩展名和附件数量以官网为准，不能默认都是 mmc1.pdf。多个 404 不证明没有 SI。综述也可能有 SI，研究论文也可能没有独立文档。

本次 DOI `10.1016/j.ensm.2024.103753` 的 26 页原文未发现 SI 提示/附件链接，官方检索内容未见独立 SI 入口，但完整官网访问受限、官方 API 返回 429；最终保留“未找到，是否提供尚未确认”，没有伪造一个 SI 文件。

## RSC

在官网文章 landing page 查 Supplementary information / Electronic supplementary information，或使用原 PDF 中的链接。真实 href 可能位于 `pubs.rsc.org/.../suppdata/...`。不要按大小写、年份和文章代码猜测完整路径。逐个保存文档；其他数据/视频按用户范围。

## Nature / Springer Nature

在官网文章 Supplementary information 区读取具体附件链接，常见官方 CDN 包括 `static-content.springer-cdn.com`、`media.springernature.com` 及 `MediaObjects` 路径。Supplementary information、Reporting Summary、Peer review file、Source Data 不是同一角色。用户只要 SI 文档时，至少保证主 Supplementary information，不把其他文件误计为主 SI。

## PMC / Europe PMC 与机构仓储

只有 DOI 精确匹配的记录才可认领 PMCID。Europe PMC 检索可提供 `pmcid`、`hasSuppl`，但 metadata 的缺失不能作无 SI 证据。根据当前记录和官方文件列表读取真实附件：

- Europe PMC 官方 REST：`https://www.ebi.ac.uk/europepmc/webservices/rest/`
- PMC OA 文件或官方开放数据对象；本次曾成功用已列出的 `pmc-oa-opendata.s3.amazonaws.com/...` SI 地址。
- 作者大学/实验室、OSTI 等正式仓储：精确 DOI、标题和版本对应，附件是否真是 SI 必须检查。

不要假定 OA 对象版本永远是 `.1` 或每个 PMCID 都有可用 supplementaryFiles ZIP。读当前元数据/下载列表后再取实际文件。ZIP 必须先检查条目路径、大小及格式，不把网页错误或路径穿越条目直接解压到论文目录。该包 CLI 不自动解包。

当搜索工具不返回真实 href，转到可用浏览器读取页面；不要把无关论文引用列表里的“Supporting Information”认领给当前论文。
