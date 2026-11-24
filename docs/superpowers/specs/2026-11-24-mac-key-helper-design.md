# Mac 自动提钥设计（2026-11-24）

## 决策与结论

**按 TraceMemo 已验证的路线直接实现，不再重复做可行性验证。** 产品接受「临时关闭 SIP + 管理员授权」作为**高级模式**前提；普通用户默认仍走手动密钥 / 已解密备份。

• 复刻的是 **调用契约**（`KeyServiceMac` 的链路、参数、失败码、Intel JSONL 协议、ad-hoc 签名流程），不是 helper 二进制。
• TraceMemo 仓库**无 LICENSE / NOTICE**、`package.json` 无 `license` 字段、helper 只有 Mach-O 且无源码 → **不捆绑、不下载、不再分发**；由用户用 `scripts/prepare_mac_key_helper.sh` 自备。
• 明确不做：自动关 SIP、自动联网安装 Frida 运行时、静默把账号级密钥当成功。

## 参考实现逐行核对结论

来源：`github.com/Wxw-Gu/TraceMemo`（2026-11-24 拉取，v2.7.0，Electron + TypeScript）。

| 维度 | 事实 | 本工程对应实现 |
|------|------|----------------|
| 判定顺序 | 架构快照在 SIP 之前，避免 Rosetta/x64 用户先关 SIP 才发现问题 | `resolve_mac_key_flow()` / `get_mac_arch_snapshot()`；`sysctl hw.optional.arm64` + `sysctl.proc_translated` + `platform.machine()` |
| Apple Silicon | `csrutil status` → `pgrep -x WeChat`（`-f` 兜底）→ `defaults read .../Info CFBundleShortVersionString` → `osascript ... do shell script ... with administrator privileges` | `is_sip_enabled()` / `get_wechat_pid()` / `detect_wechat_version()` / `AppleSiliconXkeyProvider._osascript()` |
| profile 分派 | `^4\.1\.13(?:\.|$)` → `xkey_helper_4_1_13`，参数 `[pid, waitMs, --profile, wechat-4.1.13, --account]`，等待下限 120 s；其余走 legacy `xkey_helper`，等待下限 30 s | `resolve_xkey_helper_mode()` / `build_apple_silicon_invocation()` |
| 输出契约 | helper stdout 内嵌 JSON `{"success":true,"key":"<64hex>","keyKind":"db","profile":"..."}`；失败为 `{"success":false,"result":"ERROR:CODE:detail"}` | `parse_xkey_helper_output()` + `contract.py` |
| 失败码 | `CAPTURE_TIMEOUT` / `SCAN_FAILED (+sink pattern not found)` / `PERMISSION_DENIED` / `AUTH_TIMEOUT` / `ERR::-128` 取消授权 / `WECHAT_NOT_RUNNING` / `HELPER_RESULT_INVALID` | `map_xkey_helper_failure()` 与 `AppleSiliconXkeyProvider.extract()` |
| Intel | 34 MB PyInstaller `intel_mac_key_helper` 的 `status` / `install` / `capture`，JSONL 逐行输出 `progress` / `result` | `IntelMacKeyProvider._run_tool()`；**不实现 `install`**（不自动联网） |
| 签名 | `after-pack.cjs` 对 helper `codesign --force --sign -`，逐架构 `--verify --strict` | `scripts/prepare_mac_key_helper.sh` |
| 版本适配 | profile 表 `4.1.8 / 4.1.9 / 4.1.13 / 4.2 reserved`；官方推荐 4.1.13.8，备选 4.1.8.100；失败建议降级 + 冷启动 + 勿连续重试 | `docs/mac-auto-key.md` 兼容矩阵与失败码表 |

**本机实测（只读）**：微信 macOS `4.2.0`，2 个账号共 39 个加密库 / 39 个 salt。macOS `MMKV` 是 16 KiB mmap 布局、首 4 字节多为 `0`，与 Windows `4B长度 + 16B IV + 密文 + 16B Tag` 不同，复用现有 AES-GCM 策略 0 命中。按本次决策**不再深挖文件侧**；该结论仅用于说明为何必须走 helper。

## 关键契约差异（已处理）

| | 本工程 | TraceMemo helper |
|---|--------|------------------|
| 密钥粒度 | 按 `{salt_hex: 64hex}` 存**每个数据库**，多账号同名库不覆盖 | Electron `safeStorage` 存单个 key |
| 4.1.13 输出 | `keyKind=account` 先当候选逐库 HMAC 试解；全不通过时提示可能需要主密钥派生层，不假成功 | 直接作为 DB key 使用 |
| 准入 | 任何候选必须过 SQLCipher page1 HMAC 才进 `key_map` | `testConnection` 单库校验 |

⇒ helper 返回单 key 时，adapter 会把它对所有未解 salt 逐个验证；同一 raw key 配不同 DB salt 的场景可一次全解。

## 架构

```
POST /api/backup/keyscan (或 /api/backup/mac-keyscan)   ← macOS 分派
  └─ _mac_keyscan_sse()  →  SSE 进度
       └─ wechat_key_extract.extract_all_keys()
            └─ _extract_all_keys_macos()
                 ├─ load_from_config / extract_keys_from_mmkv（复用，跨平台）
                 ├─ mac_key.adapter.extract_keys_via_mac_provider()
                 │    └─ providers.available_providers()
                 │         ├─ AppleSiliconXkeyProvider  ← tracememo.py
                 │         │    ├─ arch snapshot → SIP → 版本/PID → profile
                 │         │    └─ osascript 管理员授权 → helper → JSON
                 │         ├─ IntelMacKeyProvider      ← tracememo.py (JSONL)
                 │         └─ ExternalHelperProvider  ← 用户显式配置的 BYO helper
                 │              └─ contract.parse_helper_output → KeyCandidate
                 │                   └─ verify_enc_key(page1 HMAC) → key_map
                 ├─ cross_verify_keys（复用）
                 └─ save_key_results（唯一写点，复用）
```

Windows 的 `/api/backup/keyscan` 分支完全不变；`auto_key_extract_supported()` 保持 Windows-only（`backup/pipeline.py` 依赖它导入 `key_scan`），另设 `mac_auto_key_ready()` 供 UI 使用。

## 模块清单

| 文件 | 职责 |
|------|------|
| `engine/services/mac_key/tracememo.py` | 架构判定、SIP/版本/PID 探测、profile 分派、osascript 提权、失败码映射、两个 first-party provider |
| `engine/services/mac_key/contract.py` | helper 输出 v1、`KeyCandidate` / `ProviderResult`、错误码、`mask_key`、TraceMemo 风格 JSON 解析 |
| `engine/services/mac_key/providers.py` | provider 注册表 + BYO helper（`shell=False`、可选 SHA-256、超时/输出上限） |
| `engine/services/mac_key/adapter.py` | 同构策略签名，HMAC 裁决，不落盘 |
| `engine/services/mac_key/diagnostics.py` / `cli.py` | 只读环境快照与 `--probe` |
| `web/routes/backup_api.py` | macOS SSE 提钥端点 |
| `web/routes/setup_api.py` / `templates/{setup,dashboard,keyscan,mac_keys_guide}.html` / `static/js/mac_guide.js` | 高级模式入口与文案 |
| `scripts/prepare_mac_key_helper.sh` | helper 放置 + ad-hoc 签名 + 逐架构校验 |
| `docs/mac-auto-key.md` | 用户可见操作手册与失败码表 |

## 安全与合规边界

• helper 路径只认用户显式放置的 `resources/mac/` 或 `WECHAT_EXPORT_MAC_RESOURCES`；不自动发现、不下载、不捆绑。
• `osascript ... with administrator privileges` 是**用户可见的系统授权弹窗**，由用户手动确认；本工程不静默提权、不修改 SIP 状态。
• BYO helper 仍用 `shell=False` + 可选 SHA-256 + 超时 + stdout 1 MiB / 候选 256 上限。
• 日志与诊断只输出脱敏密钥与计数；`--probe` 不写配置；不打印 MMKV 明文或聊天内容。
• 明确告知：关闭 SIP 降低系统防护，拿到密钥后须重新开启；勿连续重试以免触发微信安全模式。

## 验收标准

• Windows 策略链行为不变；macOS 提钥不 import 任何 Win32 绑定模块。
• 架构不匹配 / SIP 开启 / 微信未运行 / helper 缺失 / 取消授权 / 超时 / `SCAN_FAILED` 均有明确错误码与可操作文案。
• helper 返回的 64 hex 必须通过真实 page1 HMAC 才写入 `key_map`；账号级密钥全不通过时给出派生层提示。
• 诊断 CLI 与 `--probe` 输出不含完整密钥、不写配置。
• 新增测试覆盖 profile 分派、失败码映射、osascript 命令构造、架构判定、UI 契约。

## 已知限制与风险

• **版本脆弱**：本机 4.2.0 超出参考实现适配范围，profile 表中 4.2 为 reserved；每个微信版本可能需重新适配特征码。
• **许可证**：helper 二进制无 LICENSE / 源码，只实现调用契约；分发前需自行确认授权。
• **主密钥派生**：若账号级密钥逐库 HMAC 全不通过，需补「主密钥 + DB salt → 每库密钥」派生层。
• **非技术用户门槛**：关 SIP、恢复模式、管理员授权、微信停在登录页、锁版本，这些仍是高级模式的固有成本；默认路线不指向它。
• **风控**：反复附加微信进程可能触发安全模式。
