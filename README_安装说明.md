# 整理数据库V3版本

V3与“整理数据库V2版本”并存，不覆盖V2。V3使用独立插件名 `shop-report-organizer-v3` 和技能名 `operations-database-v3`。

## 安装

在Windows中右键使用PowerShell运行仓库根目录的 `安装V3.ps1`，或在PowerShell中执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\安装V3.ps1"
```

安装完成后新建Codex任务，输入 `整理数据库V3版本`。

## 默认目录

V3默认使用 `%USERPROFILE%\Desktop\运营数据库`，不会把业务数据写入插件目录。正式整理前始终先预览；政策到位价、月返价和ERP成本价的选择规则见插件技能中的 `references/cost-policy.md`。
