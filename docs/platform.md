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

## macOS 低风险用法（推荐）

本工具在 Mac 上**不会**自动挂接微信进程取密钥（不做注入 / Frida / 关 SIP）。  
这比「每次扫描进程」更不容易触发微信环境异常，但**不能保证永不风控**。

推荐流程：

1. **密钥只准备一次**：粘贴到「手动输入密钥」，或直接打开已解密备份。
2. **日常只碰本地文件**：备份 / 导出 / 搜索；分析阶段可先退出微信。
3. **读沙盒目录**：系统设置 → 隐私与安全性 → **完全磁盘访问权限**，允许 Terminal / Python / 本程序。
4. **不要做**：关 SIP、chmod 整个微信目录、装发送/注入类插件、反复调试附着微信进程。

路径示例：

```text
~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<账号>/db_storage
```

界面：仪表盘 / 备份页 / 手动密钥页会在检测到 macOS 时显示引导条（可点「知道了」收起）。

## 本仓库已做的 Phase 1

- 平台能力探测：`engine/platform_info.py`，`GET /api/health` → `platform`
- 密钥 HMAC / 扫库与 Win32 提取解耦：`engine/db_key_crypto.py`（手动密钥在 Mac 可用）
- macOS `xwechat_files` 路径探测 + Full Disk Access 提示
- 非 Windows 跳过 V2 收割 / 自动 key_scan，并给出明确错误
- `ffmpeg` / `silk_decoder` / 打开 tools 目录跨平台
- 窄屏 CSS（聊天侧栏、仪表盘、表单）
- macOS 低风险引导条（`static/js/mac_guide.js`）

## macOS `.app` / DMG 打包（已支持，未公证）

在本机（Apple Silicon / Intel）执行：

```bash
chmod +x quick_build_macos.sh start.command
./quick_build_macos.sh
```

产物：

| 文件 | 说明 |
|------|------|
| `dist/WeChat Export.app` | 双击启动本地 Web 服务（控制台可见日志） |
| `dist/WeChatExport-v*-macos-arm64.dmg`（或 `x86_64`） | 拖到「应用程序」安装 |

说明：

- **未做 Apple 公证 / Developer ID 签名**（需付费账号）。首次打开请 **右键 → 打开**。
- 备份与配置写在 `~/Library/Application Support/WeChatExport/`（避免 `/Applications` 不可写）。
- 能力边界与源码模式相同：**无自动提密钥**；建议手动密钥或已解密备份。
- 可选：`brew install ffmpeg`；`tools/silk_decoder` 需自行编译后放入 Application Support 的 `tools/` 或仓库 `tools/` 再打包。

也可以不打包，双击 `start.command` 用源码启动。

## 后续 Phase（未做）

1. macOS 原生密钥提取 helper（工作量最大，需按微信版本维护）
2. Apple Developer ID 签名 + 公证（公证后可双击打开）
3. `launchd` 定时备份
4. 编译各架构 `silk_decoder` 并打进 `.app`
5. 可选：桌面服务 + 局域网 Token，让手机浏览器只读查看（仍非原生 App）
