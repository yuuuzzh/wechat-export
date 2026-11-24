# macOS 高级一键提钥（参考 TraceMemo）

> 面向已经决定使用「原生 helper」路线的用户。**默认路线仍然是手动输入密钥或打开已解密备份**；本文描述的是可选的高级模式，会调整系统安全设置。

## 它是什么

本工程按 `Wxw-Gu/TraceMemo` 的 `KeyServiceMac` 复刻了 macOS 提钥的**调用契约**：架构判定 → SIP 检查 → 微信版本/PID → helper profile 分派 → `osascript` 管理员授权执行 → JSON 输出 → 失败码映射。

| 复刻了 | 没有复刻 |
|--------|----------|
| 调用顺序、参数、profile 分派、超时、失败码、Intel JSONL 协议、ad-hoc 签名流程 | helper 二进制本身（TraceMemo 仓库无 LICENSE / NOTICE、无源码，本项目不捆绑、不下载、不再分发） |

⇒ **helper 需要你自己提供**：`xkey_helper`、`xkey_helper_4_1_13`、`macos-key-tool/intel_mac_key_helper`。**不需要安装 TraceMemo.app**——参考仓库的 `resources/` 目录本身就是随包分发的原始文件，直接用它即可：

```bash
# 在工作区根 /Users/yuuu/code/wechat-export 下（根目录有转发脚本）
./scripts/prepare_mac_key_helper.sh /tmp/tracememo-study/resources

# 或在仓库根 /Users/yuuu/code/wechat-export/src 下
cd src && ./scripts/prepare_mac_key_helper.sh /tmp/tracememo-study/resources

# 已安装 TraceMemo.app 时也可以
./scripts/prepare_mac_key_helper.sh "/Applications/TraceMemo.app"
```

脚本接受 **resources 目录 / `.app` / git clone 根目录**三种形态，会校验可用的 `.sha256`、把文件放到 `src/resources/mac/`（已被 `.gitignore` 排除）、`chmod 755`、逐个架构 ad-hoc 签名并 `--verify --strict`。也可设 `WECHAT_EXPORT_MAC_RESOURCES` 指向其它目录。

路径提示：仓库根是 `wechat-export/src/`，脚本实际在 `src/scripts/`；工作区根 `wechat-export/scripts/` 放的是转发脚本，两种入口都能用。

## 三条路线怎么选

| 路线 | 前置条件 | 适合谁 |
|------|----------|--------|
| 已解密备份 | 无 | 最省事，直接用本工具打开 |
| 手动输入密钥 | 有 64 位 hex / Windows 扫描日志 | 不想改系统设置 |
| **高级一键提钥** | 自备 helper + 临时关 SIP + 管理员授权 + 微信停在登录页 | 只有一台 Mac、愿意按向导操作 |

## 前置条件（缺一不可）

• **架构**：Apple Silicon 请用 arm64 版 Python / `.app`；Apple 芯片上跑 x86_64 会直接返回 `ARCH_MISMATCH_X64_ON_ARM`。Intel Mac 走 `intel_mac_key_helper`（Frida 运行时）。
• **SIP**：需在恢复模式（Apple 芯片长按开机键 / Intel `Command+R`）打开终端执行 `csrutil disable`，重启后 `csrutil status` 显示 `disabled.`。**拿到密钥后请按 Apple 官方方式重新开启**；macOS 大版本更新会把 SIP 重置回开启。
• **微信版本**：参考实现已适配 **4.1.13.8**，备选 **4.1.8.100**。其它版本（含本机实测的 4.2.0）可能 `SCAN_FAILED`，其 profile 表里 4.2 仍是 reserved。不要连续重试，以免触发微信安全模式。
• **微信状态**：退出当前账号，**停留在未登录界面**（只关闭窗口不算）。
• **权限**：点击后会弹出 macOS 管理员授权框；完成授权、看到提示后再回微信点「登录」。
• **完全磁盘访问权限**：只影响读取微信沙盒数据目录，与提钥本身无关。

## 操作步骤

1. 按上文放置并签名 helper。
2. 临时关闭 SIP 并重启。
3. 启动微信，退出账号，停在登录页。
4. 打开本工具的「提取密钥」页 → 「一键提取密钥（高级）」；或在向导里点「Mac 高级提钥」。
5. 完成管理员授权 → 看到提示后回微信点「登录」→ 等待结果。
6. 成功后密钥写入 `.wechat_exp_config.json`（按数据库 salt 区分多账号），**重新开启 SIP**。

诊断命令（只读，不打印密钥）：

```bash
PYTHONPATH=src .venv/bin/python -m engine.services.mac_key --db-dir "<db_storage>"
PYTHONPATH=src .venv/bin/python -m engine.services.mac_key --db-dir "<db_storage>" --probe
```

## 失败码

| 码 | 含义 / 处理 |
|----|-------------|
| `SIP_ENABLED` | SIP 仍开启，按上文临时关闭并重启 |
| `ARCH_MISMATCH_X64_ON_ARM` | Apple 芯片上跑了 Intel 版运行时，换 arm64 包 |
| `WECHAT_NOT_RUNNING` | 启动微信并停在登录界面 |
| `CAPTURE_TIMEOUT` | 登录时机不对；退出账号重来，授权后再点登录 |
| `SCAN_FAILED` | 版本未适配（常见「Sink pattern not found」）；降级微信 4.1.8 / 冷启动，**不要连续重试** |
| `PERMISSION_DENIED` | 管理员授权不足 |
| `AUTH_CANCELLED` / `AUTH_TIMEOUT` | 取消或超时未完成系统授权 |
| `HELPER_NOT_FOUND` / `HELPER_EXEC_FAILED` | helper 没放好或没签名 |
| `KEY_TOOL_*` | Intel 运行时缺失 / 超时 / 未返回结果 |
| `NO_VERIFIED_KEY` | helper 给了密钥但逐个数据库 HMAC 都没过（可能需要主密钥派生层） |

## 安全与隐私

• helper 只在本机执行；不上传、不联网下载、不自动发现二进制。
• 任何候选密钥都要先通过数据库首页 **HMAC 校验**才会写进配置，错误密钥不会污染备份。
• 日志与诊断只输出脱敏密钥（`1111…1111` 形式）与计数，不打印完整 64 位 hex、MMKV 明文或聊天内容。
• `--probe` 只报告 HMAC 命中数，**不写配置文件**。
• 反复附加微信进程可能触发安全模式；失败后先按失败码排查，不要连续重试。
• 关闭 SIP 会降低系统防护，**请勿长期保持关闭状态**。

## 与 TraceMemo 的已知差异

• TraceMemo 用 Electron `safeStorage` 存单个密钥；本工程按 `{salt_hex: 64hex}` 存**每个数据库**的密钥，兼容多账号与同名库。
• 4.1.13 helper 的 `keyKind=account` 会被本工程当作候选，先逐库 HMAC 试解；若全不通过会提示可能需要「主密钥 + DB salt → 每库密钥」派生层，而不是显示成功。
• 参考项目的 Intel 分支会联网 `install` Frida 运行时；本工程**不自动安装**，仅调用 `status` / `capture`，运行时需自行准备。
