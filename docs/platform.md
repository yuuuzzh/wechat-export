# 平台支持说明

## 结论先说

- **Windows**：完整能力（自动密钥提取、一键备份、计划任务、打包 exe）。
- **macOS**：分析与导出核心可用；默认走手动密钥 / 已解密备份；**高级一键提钥**参考 TraceMemo 实现，需自备 helper、临时关 SIP、管理员授权（见 `docs/mac-auto-key.md`）。
- **Linux**：分析与导出核心可用；无微信官方桌面客户端提钥。
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

## macOS 默认路线（推荐给普通用户）

默认路线**不挂接**微信进程取密钥，比「每次扫描进程」更不容易触发微信环境异常，但**不能保证永不风控**。

推荐流程：

1. **密钥只准备一次**：粘贴到「手动输入密钥」，或直接打开已解密备份。
2. **日常只碰本地文件**：备份 / 导出 / 搜索；分析阶段可先退出微信。
3. **读沙盒目录**：系统设置 → 隐私与安全性 → **完全磁盘访问权限**，允许 Terminal / Python / 本程序。
4. **默认不要做**：chmod 整个微信目录、装注入类插件、反复调试附着微信进程。
5. **高级模式才需要**：临时关闭 SIP + 管理员授权 + 微信停在登录页；完成后重新开启 SIP。

路径示例：

```text
~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<账号>/db_storage
```

界面：仪表盘 / 备份页 / 手动密钥页会在检测到 macOS 时显示引导条（可点「知道了」收起）。

**Mac 密钥新手指引（推荐发给卡住的用户）**：

- 应用内分步向导：`http://127.0.0.1:5000/mac-keys-guide`
- 离线可单独打开：`docs/mac-keys-guide.html`

核心说明：Mac 默认需已有密钥文本 / Windows 扫描日志，或已解密备份，再到「手动输入密钥」粘贴校验；自备 helper 时可切到高级一键提钥。

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
- 能力边界与源码模式相同：默认手动密钥或已解密备份；helper 需放到 `resources/mac/` 后才有高级提钥。
- 可选：`brew install ffmpeg`；`tools/silk_decoder` 需自行编译后放入 Application Support 的 `tools/` 或仓库 `tools/` 再打包。

也可以不打包，双击 `start.command` 用源码启动。

## macOS 高级提钥（2026-11-24 已按 TraceMemo 路线实现）

设计 / 计划 / 使用说明：
`docs/superpowers/specs/2026-11-24-mac-key-helper-design.md`、
`docs/superpowers/plans/2026-11-24-mac-key-helper-plan.md`、
`docs/mac-auto-key.md`。

• **决策**：不再重复验证文件侧 (MMKV) 路线，直接按 TraceMemo 已验证的 helper 链路实现；接受「临时关闭 SIP + 管理员授权」作为高级模式前提。
• **实现**：`engine/services/mac_key/tracememo.py` 复刻架构判定（`resolve_mac_key_flow`）、`csrutil` SIP 检查、版本/PID 探测、`buildAppleSiliconXkeyInvocation` profile 分派、`osascript with administrator privileges`、失败码映射、Intel `status/capture` JSONL 协议。
• **接入**：`/api/backup/keyscan` 在 macOS 分派到高级链路（新增别名 `/api/backup/mac-keyscan`）；首次向导 / 仪表盘 / 提取密钥页按 `platform.mac_key.auto_extract_ready` 显示「Mac 高级提钥」入口。
• **不回归**：`auto_key_extract_supported()` 仍为 Windows-only（`backup/pipeline.py` 依赖它导入 `key_scan`），另设 `mac_auto_key_ready()`；Windows 策略链零改动。
• **不捆绑二进制**：TraceMemo 仓库无 LICENSE / NOTICE 且 helper 无源码，本项目只实现调用契约；用 `scripts/prepare_mac_key_helper.sh` 把你已有的 helper 放进 `resources/mac/`（已 gitignore）并 ad-hoc 签名。脚本接受 resources 目录 / `.app` / git clone 根目录三种来源，**不需要安装 TraceMemo.app**；工作区根 `wechat-export/scripts/` 另有转发脚本，仓库根 `src/scripts/` 是实际脚本。
• **安全**：候选密钥一律过 page1 HMAC 才写配置；日志脱敏；`--probe` 不写配置；不自动联网安装 Frida 运行时。
• **诊断**：`PYTHONPATH=src .venv/bin/python -m engine.services.mac_key --db-dir <db_storage>`。
• **已知限制**：参考实现适配微信 4.1.13.8 / 4.1.8.100；本机实测为 4.2.0，可能 `SCAN_FAILED`。helper 返回的账号级密钥需逐库 HMAC 试解。

## 后续 Phase（未做）

1. Apple Developer ID 签名 + 公证（公证后可双击打开）
2. 微信新版本 profile / 特征码适配（4.2.x 尚未验证）
3. 主密钥 → 每库密钥派生层（若账号级密钥 HMAC 全不通过）
4. `launchd` 定时备份
5. 编译各架构 `silk_decoder` 并打进 `.app`
6. 可选：桌面服务 + 局域网 Token，让手机浏览器只读查看（仍非原生 App）
