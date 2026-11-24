# Mac 自动提钥执行计划（2026-11-24）

配套设计：`docs/superpowers/specs/2026-11-24-mac-key-helper-design.md`
用户手册：`docs/mac-auto-key.md`

## 决策

**直接按 TraceMemo 路线实现，不做重复可行性验证。** 高级模式接受「临时关 SIP + 管理员授权」前提；helper 二进制自备，不捆绑、不下载。

判定原则：Windows 主路径零回归；默认 Mac 体验仍指向手动密钥 / 已解密备份；高级模式只在 helper 就绪时显现。

## Task 1 — 调研（已完成）

• 拉取并逐行核对 `Wxw-Gu/TraceMemo`：`key-service-mac.ts`、`shared/macos-arch.ts`、`main/macos-arch.ts`、`connection-diagnostics.ts`、`resource-paths.ts`、`index.ts` IPC 段、`database-key-store.ts`、`after-pack.cjs`。
• 结论：架构判定 → SIP → 版本/PID → profile → `osascript` 提权 → JSON → 失败码；Intel 走 Frida JSONL；helper 闭源无 LICENSE。
• 本机只读实测：微信 4.2.0、2 账号 / 39 加密库 / 39 salt；macOS MMKV 布局与 Windows 不同，文件侧 0 命中 → 按决策关闭该路线。

## Task 2 — 契约与 provider 抽象（已完成）

• 新增 `engine/services/mac_key/`：`contract.py`、`providers.py`、`adapter.py`、`diagnostics.py`、`cli.py`、`__main__.py`。
• `wechat_key_extract._extract_all_keys_macos()`：macOS 独立策略链，Windows 分支不变。
• `platform_info.mac_key_capabilities()` / `mac_auto_key_ready()`；`auto_key_extract_supported()` 保持 Windows-only。

## Task 3 — TraceMemo 链路移植（已完成）

• 新增 `engine/services/mac_key/tracememo.py`：`resolve_mac_key_flow` / `get_mac_arch_snapshot` / `parse_sip_enabled` / `is_sip_enabled` / `detect_wechat_version` / `get_wechat_pid` / `resolve_xkey_helper_mode` / `build_apple_silicon_invocation` / `map_xkey_helper_failure` / `parse_xkey_helper_output`。
• `AppleSiliconXkeyProvider`：osascript 管理员授权执行 `xkey_helper` / `xkey_helper_4_1_13`，含 `ERR::-128`、超时、失败码处理。
• `IntelMacKeyProvider`：`status` / `capture` JSONL；不实现联网 `install`。
• `contract.parse_helper_output` 接受 `keyKind=account`（4.1.13 helper 的实际输出），由 adapter 逐库 HMAC 裁决。
• `diagnostics` / CLI 增加架构流程、SIP、helper 清单、profile、capture_ready。

## Task 4 — 向导与 API 接入（已完成）

• `backup_api.py`：新增 `_mac_keyscan_sse()`；`/api/backup/keyscan` 在 darwin 早分派，新增别名 `/api/backup/mac-keyscan`。
• `setup_api.py`：新增 `mac_keys_advanced`、`mac_auto_key` 字段并调整 keys 步骤标题/提示。
• `setup.html` / `dashboard.html` / `keyscan.html`：helper 就绪时显示「Mac 高级提钥」入口、前置条件说明与 SSE 进度。
• `mac_keys_guide.html` / `mac_guide.js`：文案改为「默认路线不附加进程；高级模式需自备 helper + 临时关 SIP」。
• `README.md` / `docs/platform.md`：平台能力表、FAQ、后续 Phase 更新。
• `scripts/prepare_mac_key_helper.sh`：放置 helper + `codesign --force --sign -` + 逐架构 `--verify --strict`。
• `docs/mac-auto-key.md`：前置条件、操作步骤、失败码表、安全边界。

## Task 4b — Mac 使用新手指引补齐（v0.6.0 发版后补漏，发布为 v0.6.1，2026-11-24）

发版复核发现：交互式指引只有手动密钥三条路线，高级模式只有 Markdown 文档与页内提示，用户第一次用无从下手。已补齐：

• `mac_keys_guide.html`：新增第 4 条路线 `mac_advanced`，6 步向导（前提总览 → 放 helper → 临时关 SIP → 微信版本/登录页 → 执行提钥 → 失败排查与收尾），含错误码表、完成后重开 SIP、末尾「打开高级提钥页」CTA。
• `docs/mac-keys-guide.html` 离线版同步新增高级路线与执行/排障步骤；保留原有 3 条手动路线。
• 入口统一改为「Mac 使用新手指引」：首次向导（含高级模式）、仪表盘 Mac 卡片与 `keysMacAdvanced`、提取密钥页高级区块、手动密钥页、引导条；`docs/mac-auto-key.md` 与 `docs/platform.md` 顶部指向应用内向导。
• 新增 4 个静态/路由契约测试（分步函数齐全、离线版覆盖、路由渲染、入口文案）；定向 58 个用例通过。

## Task 5 — 测试与回归（本次交付）

• 新增 `tests/test_tracememo_provider.py`：架构判定、`build_apple_silicon_invocation` profile 分派、失败码映射、JSON 解析、osascript 命令构造、SIP / helper 缺失路径、Intel JSONL、HMAC 裁决闭环、UI/API 静态契约。
• 更新 `tests/test_mac_key_provider.py`：账号级密钥作为候选、推荐文案按新决策。
• 回归：`.venv/bin/python -m pytest -q`（对比 `git archive HEAD` 干净快照基线，区分既有失败）。

## Task 6 — 后续（未做，按依赖排序）

- [x] helper 放置与签名（2026-11-24 本机已完成）：源用参考仓库 `resources/` 目录，工作区根转发脚本 → `src/resources/mac/`，3 个 Mach-O 均逐架构 `--verify --strict` 通过，`.gitignore` 已排除；CLI 显示「高级模式就绪：是」。
- [ ] 用户按需换成官方 TraceMemo 发行包里的 helper（脚本支持 `.app` / DMG 挂载路径）。
- [ ] 在微信 4.1.13.8 / 4.1.8.100 上做真机闭环验证；本机 4.2.0 预计 `SCAN_FAILED`。
- [ ] 若账号级密钥逐库 HMAC 全不通过：逆向并实现「主密钥 + DB salt → 每库密钥」派生层。
- [ ] 微信新版本 profile / 特征码适配（4.2.x reserved）。
- [ ] Apple Developer ID 签名 + 公证（当前 `.app` 未公证，helper 为 ad-hoc 签名）。
- [ ] 每次微信升级后的兼容矩阵回归清单。

## 验证清单

```bash
cd /Users/yuuu/code/wechat-export/src
.venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m engine.services.mac_key --db-dir "<db_storage>"
PYTHONPATH=src .venv/bin/python -m engine.services.mac_key --db-dir "<db_storage>" --probe
```

• 禁止事项：任何测试/脚本打印完整 64 hex 密钥、写入 `.wechat_exp_config.json`、修改 SIP、自动联网安装运行时。
• 真实微信环境验证只能在用户本机手工进行；CI 只覆盖契约与接线。
