# 平台支持说明

## 结论先说

- **Windows**：完整能力（自动密钥提取、一键备份、计划任务、打包 exe）。
- **macOS / Linux**：分析与导出核心可用；**自动提取密钥不可用**（与 TraceMemo 不同，本项目尚未捆绑 macOS 原生 helper）。
- **移动端**：不做 iOS/Android 提取 App；窄屏 Web + 导出 HTML 可在手机浏览器打开。

## 为什么 TraceMemo 能适配 Mac，而我们原先不行？

TraceMemo 不是「Electron 一写就能跨端」，而是额外做了：

1. 按架构打包的 **WCDB 动态库**（`.dylib` / `.dll`）
2. **macOS 专用密钥 helper**（`xkey_helper` / Frida，常需关闭 SIP、管理员授权）
3. Full Disk Access 文档与权限引导
4. 可选的 macOS 发送运行时（与「读库」无关）

WeChat Export 的查看 / 搜索 / 导出是纯 Python + Flask，本来就可移植；卡在：

| 阻塞点 | 说明 |
|--------|------|
| `key_scan` / `config_cipher_extract` | 绑定 `ctypes.windll`（Win32 进程内存） |
| 数据目录探测 | 原先只扫 `%APPDATA%` / 盘符 |
| 打包与工具 | `wechat_exp.exe`、`silk_decoder.exe`、计划任务 bat |
| V2 密钥收割 | Windows 进程 API |

## 本仓库已做的 Phase 1

- 平台能力探测：`engine/platform_info.py`，`GET /api/health` → `platform`
- 密钥 HMAC / 扫库与 Win32 提取解耦：`engine/db_key_crypto.py`（手动密钥在 Mac 可用）
- macOS `xwechat_files` 路径探测 + Full Disk Access 提示
- 非 Windows 跳过 V2 收割 / 自动 key_scan，并给出明确错误
- `ffmpeg` / `silk_decoder` / 打开 tools 目录跨平台
- 窄屏 CSS（聊天侧栏、仪表盘、表单）

## 后续 Phase（未做）

1. macOS 原生密钥提取 helper（工作量最大，需按微信版本维护）
2. PyInstaller `.app` / DMG、签名公证
3. `launchd` 定时备份
4. 编译各架构 `silk_decoder`
5. 可选：桌面服务 + 局域网 Token，让手机浏览器只读查看（仍非原生 App）
