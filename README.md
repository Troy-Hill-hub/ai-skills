# AI Skills

用于文献全文、Supporting Information（SI）下载、核验和归档的两个技能。

| Skill | 功能 | 入口 | 安装包 |
| --- | --- | --- | --- |
| `download-literature-si` | 为本地论文查找、下载并核验对应 SI，支持批量、续跑和审计记录 | [SKILL.md](download-literature-si/SKILL.md) | [ZIP](packages/download-literature-si.zip) |
| `paper-download-pku` | 在具备合法机构访问权限的环境中，按 DOI 或 Excel 清单下载论文全文 | [SKILL.md](paper-download-pku/SKILL.md) | [ZIP](packages/paper-download-pku.zip) |

## 使用

将所需技能的整个目录复制到所用 AI 工具的技能目录，保留 `SKILL.md`、`scripts/`、`references/` 等相对路径，再阅读对应入口文件。也可以下载 ZIP 后解压安装。

`download-literature-si` 的 Python 依赖见其 `scripts/requirements.txt`；附带 PowerShell 浏览器启动器适用于 Windows。`paper-download-pku` 依赖 Python、Playwright、pypdf、openpyxl，并主要面向 Windows / Chrome 和北大 CARSI 机构访问环境，其他机器需调整路径与访问配置。

登录由使用者本人完成。技能不提供订阅权限，也不包含账号、认证令牌、浏览器会话或论文全文。公开版本将本机用户名路径和具体校园网络地址替换为占位说明；出版商流程和案例记录具有时间与环境限制，使用前应确认当前环境。
