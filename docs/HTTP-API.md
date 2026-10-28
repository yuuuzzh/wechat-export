# WeChat Export HTTP API

本地 Flask 服务默认监听 `http://127.0.0.1:<port>`（CLI / 启动参数决定端口）。  
所有接口仅本机可用，**无鉴权**——请勿把端口暴露到公网。

对应产品版本 **2.12.x**（下一正式 Release 计划为 `v0.2.0`）。  
机器可读规范（从已注册的 `/api/*` 自动生成）：`GET /api/openapi.json`。浏览器可打开 `/swagger`。

SSE 进度类接口（备份、导出等）返回 `text/event-stream`，事件字段一般为 `step` / `message` / `progress` / `done`。

---

## 会话与消息

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/contacts` | 聊天会话列表 |
| GET | `/api/messages?chat_id=&page=&…` | 分页消息 |
| GET | `/api/messages/<msg_id>` | 单条消息 |
| GET | `/api/chat/<chat_id>/stats` | 会话统计 |
| GET | `/api/chat/<chat_id>/dates` | 有消息的日期 |
| GET | `/api/chat/<chat_id>/group-info` | 群信息 |
| GET | `/api/media` | 媒体文件 |
| GET | `/api/voice` | 语音 |
| GET | `/api/avatar/<username>` | 头像 |

### 示例：列会话

```http
GET /api/contacts HTTP/1.1
Host: 127.0.0.1:5000
```

---

## 搜索

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/search?q=&…` | 全文搜索 |
| GET | `/api/search/status` | 索引状态 |
| POST | `/api/search/index` | 构建 / 刷新索引 |

---

## 话题 / 事件时间线

| 方法 | 路径 | 说明 |
|------|------|------|
| POST/GET | `/api/events/timeline` | 按关键词检索并聚类为事件卡片 |

正文 / 查询参数示例：

```json
{
  "keywords": "搬家, 旅游",
  "gap_hours": 72,
  "min_messages": 1,
  "date_start": "2024-01-01",
  "date_end": "2024-12-31",
  "chat": "",
  "merge_related": true
}
```

返回 `events[]`：每张卡片含 `title` / `keywords` / 起止时间 / 会话与样例摘录，以及 `search_href`（跳转全局搜索）、样例里的 `chat_href`（定位到聊天查看器）。页面入口：`/events`。

---

## 导出

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/export/chats?kind=all\|group\|contact&q=` | 可选会话列表（含消息数） |
| POST | `/api/export/chat` | 导出会话（SSE）；可选 `privacy_redact` + `privacy` 脱敏昵称/手机/身份证 |
| GET | `/api/export/download/<filename>` | 下载导出文件 |
| POST | `/api/export/wordcloud` | 词云 |
| POST | `/api/export/report` | 综合 HTML 报告 |
| POST | `/api/export/search` | 搜索结果导出 |
| POST | `/api/export/voice` | 按人导出语音 |
| POST | `/api/export/employee` | 员工报表 |

### POST `/api/export/chat` 正文示例

```json
{
  "contacts": ["wxid_xxx"],
  "format": "md",
  "keyword": "",
  "date_start": "2026-01-01",
  "date_end": "2026-12-31",
  "merge": true,
  "include_asr": false,
  "privacy_redact": true,
  "privacy": {
    "nicknames": true,
    "phones": true,
    "id_cards": true,
    "style": "placeholder"
  }
}
```

`format` 支持：`txt` · `html` · `xlsx` · `csv` · `md` · `json` · `pgsql` · `session-pack` · `chatlab-jsonl` · `chatlab-json`。

**隐私脱敏**（`privacy_redact: true`）：仅改写导出文件，不修改本机备份。昵称可映射为「联系人甲 / 示例群聊」（`style: placeholder`）或星号打码（`asterisk`）；正文中的大陆手机号、15/18 位身份证号批量打码。文件名会加 `脱敏_` 前缀。

---

## 年度 / 双人 / 群聊报告

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/wrapped/annual?year=&account=&chat=` | 年度报告；`chat` 限定会话 → 双人/群聊画像 |
| GET | `/api/wrapped/annual/meta?year=` | 卡片清单（懒加载） |
| GET | `/api/wrapped/annual/cards/<id>?year=` | 单张卡片 |

页面入口：`/wrapped` · `/duo` · `/group`。

---

## 备份与密钥

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/backup/scan` | 扫描微信数据目录 |
| POST | `/api/backup/run` | 一键备份流水线（SSE）；成功后登记版本并可选返回相对上次的差分摘要 |
| POST | `/api/backup/decrypt` | 解密 |
| POST | `/api/backup/keyscan` | 密钥扫描 |
| GET | `/api/backup/versions` | 列出备份版本（`base_dir` / `wxid` / `limit` 可选） |
| GET/POST | `/api/backup/versions/diff` | 对比两版：`old` + `new` 路径 → 新增/消失会话与消息增量 |
| POST | `/api/backup/versions/activate` | 将工作集切换到指定备份（回滚），body: `{ "path": "..." }` |
| GET | `/api/backup/schedule/status` | 定时备份状态（计划任务 / 模板路径 / 命令预览 / 最近日志） |
| POST | `/api/backup/schedule/install` | 启用每天增量：`{ "time":"02:00", "days":0, "db_dir":"..." }` |
| POST | `/api/backup/schedule/uninstall` | 停用计划任务 |
| GET/POST | `/api/backup/schedule/template` | 仅生成 bat/xml，不注册 |
| POST | `/api/backup/schedule/run-now` | 立即触发一次（已安装则 `schtasks /Run`，否则后台跑 bat） |
| GET | `/api/backup/schedule/download/bat\|xml` | 下载模板 |
| GET/POST | `/api/media/integrity` | 媒体完整性体检：缺失图片/视频/语音清单（可恢复 / 已丢失） |
| POST | `/api/media/integrity/remigrate` | 一键补迁可恢复项（SSE） |
| GET/POST | `/api/keys/*` | 密钥目录 / 校验 / 保存 |

---

## ChatLab Pull

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/pull/status` | Pull 服务状态 |
| POST | `/api/pull/start` | 启动（默认另开端口） |
| POST | `/api/pull/stop` | 停止 |

---

## 朋友圈（离线）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sns/status` | 是否已解密 `sns.db` |
| GET | `/api/sns/posts?q=&username=&start=&end=&limit=&offset=` | 时间线列表 |
| GET | `/api/sns/media?url=&token=&key=&video=` | 本地缓存或 CDN+ISAAC 解密 |
| POST | `/api/sns/export` | 导出 JSON/HTML（SSE） |
| GET | `/api/sns/download/<filename>` | 下载导出文件 |
| GET | `/api/specials/status` | 收藏库与文件传输助手是否可用 |
| GET | `/api/specials/favorites?q=&limit=&offset=` | 收藏预览 |
| POST | `/api/specials/favorites/export` | 导出收藏 JSON/HTML/MD（SSE） |
| POST | `/api/specials/filehelper/export` | 导出文件传输助手（SSE） |
| GET | `/api/specials/download/<filename>` | 下载专项导出文件 |

页面入口：`/sns`。聊天实况图：图片消息 XML 含 `livePhoto` / `islive` 时，`xml_parsed.is_live_photo=true`。

---

## 通讯录

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/address-book?kind=contacts\|official\|orphan\|groups\|all` | 联系人列表（含公众号 / 可能的历史好友） |
| GET | `/api/address-book/labels` | 标签 |
| GET | `/api/address-book/<wxid>` | 详情 |
| GET | `/api/address-book/groups` | 群 |
| GET | `/api/address-book/export` | 导出 |

---

## 说明

- 本页文档随版本更新；完整行为以源码 `src/web/routes/` 为准。
- 二次开发建议：先调 `GET /api/export/chats` 拿到 `username`，再调导出或 Wrapped。
