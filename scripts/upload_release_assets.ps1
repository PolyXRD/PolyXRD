# ⚠️ 已废弃 (DEPRECATED) —— 请勿使用本脚本
#
# 历史: 这是 v0.9.0 时期的附件上传脚本, 把工作目录硬编码成 `d:\TEMP\PolyXRD`。
# 2026-09 重装系统后盘符变更为 E:, 该路径已失效; 附件命名规则也已从
# `PolyXRD_COD_*_v0.9.x.zip` 改为 `PolyXRD-v<ver>-Databases-*.zip`。
#
# 现行做法 —— 创建 Release 与上传附件合一, 按版本命名:
#     scripts/create_github_release_v0.10.0.ps1
#
# ★ 政策提醒: PDF2-2004 为 ICDD 版权库, 任何上传脚本都不得包含该库。
#   现行脚本内已内置 Assert-NotBanned 守卫与上传后自检。

param()
Write-Host "本脚本已废弃，不再执行任何上传动作。" -ForegroundColor Yellow
Write-Host "请改用: pwsh -NoProfile -File scripts\create_github_release_v0.10.0.ps1" -ForegroundColor Yellow
exit 1
