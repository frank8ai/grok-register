# Grok 账号批量注册工具

基于 [DrissionPage](https://github.com/g1879/DrissionPage) 的 Grok (x.ai) 账号自动注册脚本，支持 CloudflareTemp Unified Pool 或 [DuckMail](https://duckmail.sbs) 临时邮箱接收验证码，通过 Chrome 扩展修复 CDP `MouseEvent.screenX/screenY` 缺陷绕过 Cloudflare Turnstile。

注册完成后自动推送 SSO token 到 [grok2api](https://github.com/chenyme/grok2api) 号池。

## 特性

- CloudflareTemp Unified Pool 临时邮箱（admin 接口随机四级子域名池）
- DuckMail 临时邮箱（`curl_cffi` TLS 指纹伪装）
- Cloudflare Turnstile 自动绕过（Chrome 扩展 patch `MouseEvent.screenX/screenY`）
- 注册资料随机化（随机名字、姓氏和密码）
- 无头服务器支持（Xvfb 虚拟显示器，自动检测 Linux 环境）
- 中英文界面自动适配
- 自动推送 SSO token 到 grok2api（支持 append 合并模式）

---

## 环境要求

- Python 3.10+
- Chromium 或 Chrome 浏览器
- CloudflareTemp Unified Pool 实例，或 [DuckMail](https://duckmail.sbs) 账号（用于创建临时邮箱）
- 可选：[grok2api](https://github.com/chenyme/grok2api) 实例（用于自动导入 SSO token）

---

## 安装

```bash
pip install -r requirements.txt
```

无头服务器（Linux）额外安装：

```bash
apt install -y xvfb
pip install PyVirtualDisplay
# 推荐用 playwright 装 chromium（避免 snap 版 AppArmor 限制）
pip install playwright && python -m playwright install chromium && python -m playwright install-deps chromium
```

---

## 配置文件（config.json）

```bash
cp config.example.json config.json
```

编辑 `config.json`：

```json
{
    "run": { "count": 10 },
    "email_provider": "cloudflare_temp_unified_pool",
    "cloudflare_temp_api_base": "https://temp-email-api.bitpowerhub.com",
    "cloudflare_temp_admin_password": "<your_admin_password>",
    "cloudflare_temp_custom_auth": "<your_custom_auth>",
    "cloudflare_temp_domains": [
        "alpha.bitfusionpay.com",
        "assets.bitfusionpay.com",
        "beta.bitfusionpay.com",
        "docs.bitfusionpay.com",
        "files.bitfusionpay.com",
        "media.bitfusionpay.com",
        "news.bitfusionpay.com",
        "status.bitfusionpay.com",
        "alpha.tokenflowpay.com",
        "beta.tokenflowpay.com",
        "files.tokenflowpay.com",
        "help.tokenflowpay.com",
        "news.tokenflowpay.com",
        "status.tokenflowpay.com",
        "support.tokenflowpay.com",
        "alpha.finchaintalk.com",
        "assets.finchaintalk.com",
        "brand.finchaintalk.com",
        "care.finchaintalk.com",
        "contact.finchaintalk.com",
        "content.finchaintalk.com",
        "docs.finchaintalk.com",
        "files.finchaintalk.com",
        "gallery.finchaintalk.com",
        "help.finchaintalk.com",
        "home.finchaintalk.com",
        "index.finchaintalk.com",
        "inside.finchaintalk.com",
        "insight.finchaintalk.com",
        "manage.finchaintalk.com",
        "market.finchaintalk.com",
        "network.finchaintalk.com",
        "orders.finchaintalk.com",
        "panel.finchaintalk.com",
        "platform.finchaintalk.com",
        "plus.finchaintalk.com",
        "portal.finchaintalk.com",
        "project.finchaintalk.com",
        "report.finchaintalk.com",
        "showcase.finchaintalk.com",
        "start.finchaintalk.com",
        "status.finchaintalk.com",
        "story.finchaintalk.com",
        "success.finchaintalk.com",
        "support.finchaintalk.com",
        "alpha.yzw.io",
        "docs.yzw.io",
        "media.yzw.io",
        "news.yzw.io",
        "status.yzw.io",
        "help.bitfusionpay.com",
        "media.tokenflowpay.com",
        "billing.finchaintalk.com",
        "design.finchaintalk.com",
        "hub.finchaintalk.com",
        "news.finchaintalk.com",
        "studio.finchaintalk.com",
        "suite.finchaintalk.com",
        "team.finchaintalk.com",
        "assets.yzw.io",
        "beta.yzw.io",
        "files.yzw.io",
        "help.yzw.io"
    ],
    "cloudflare_temp_random_subdomain_roots": [
        "alpha.yzw.io",
        "alpha.bitfusionpay.com",
        "files.bitfusionpay.com"
    ],
    "cloudflare_temp_enable_random_subdomain": false,
    "cloudflare_temp_enable_prefix": false,
    "duckmail_api_base": "https://api.duckmail.sbs",
    "duckmail_bearer": "<your_duckmail_bearer_token>",
    "proxy": "",
    "browser_proxy": "",
    "api": {
        "endpoint": "",
        "token": "",
        "append": true
    }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `run.count` | int | 注册轮数，`0` 为无限循环，可通过 `--count` 覆盖 |
| `email_provider` | string | 邮箱服务，`cloudflare_temp_unified_pool` 或 `duckmail` |
| `cloudflare_temp_api_base` | string | CloudflareTemp Worker API 地址 |
| `cloudflare_temp_admin_password` | string | CloudflareTemp admin 密码，用于 `/admin/new_address` |
| `cloudflare_temp_custom_auth` | string | CloudflareTemp custom auth，通常与 admin 密码一致 |
| `cloudflare_temp_domains` | list | CloudflareTemp Unified Pool 域名池 |
| `cloudflare_temp_random_subdomain_roots` | list | 已验证可用的随机四级子域名根域 |
| `cloudflare_temp_enable_random_subdomain` | bool | 暂时保持 `false`，直接使用 21 个基础域名轮替 |
| `cloudflare_temp_enable_prefix` | bool | 是否启用 Worker 前缀 |
| `duckmail_api_base` | string | DuckMail API 地址，默认 `https://api.duckmail.sbs` |
| `duckmail_bearer` | string | DuckMail Bearer Token（[获取方式](#获取-duckmail-bearer-token)） |
| `proxy` | string | DuckMail API 请求代理（可选） |
| `browser_proxy` | string | 浏览器代理，无头服务器需翻墙时填写（可选） |
| `api.endpoint` | string | grok2api 管理接口地址，留空跳过推送 |
| `api.token` | string | grok2api 的 `app_key` |
| `api.append` | bool | `true` 合并线上已有 token，`false` 覆盖 |

---

## 获取 DuckMail Bearer Token

1. 打开 [duckmail.sbs](https://duckmail.sbs) 并注册登录
2. 打开浏览器开发者工具 (F12) → Network
3. 刷新页面，找到任意发往 `api.duckmail.sbs` 的请求
4. 复制请求头中 `Authorization: Bearer <token>` 里的 token
5. 填入 `config.json` 的 `duckmail_bearer` 字段

---

## 启动方式

```bash
# 按 config.json 中 run.count 执行（默认 10 轮）
python DrissionPage_example.py

# 指定轮数
python DrissionPage_example.py --count 50

# 无限循环
python DrissionPage_example.py --count 0
```

无头服务器会自动启用 Xvfb，无需额外配置。

按邮箱池类型运行：

```bash
# 只跑 295 个固定域名
python run_full_620.py --pool fixed

# 只跑 25 个随机根域
python run_full_620.py --pool random

# 固定域名和随机根域都跑
python run_full_620.py --pool all
```

---

## 输出文件

```
sso/
  sso_<timestamp>.txt     ← 每行一个 SSO token
credentials/
  credentials_<timestamp>.txt  ← 每行一条账号信息：邮箱,密码,名字,姓氏
logs/
  run_<timestamp>.log     ← 每轮注册的邮箱、密码和结果
```

目录在首次运行时自动创建。

---

## 文件结构

```
├── DrissionPage_example.py     # 主脚本
├── email_register.py           # 邮箱服务封装（CloudflareTemp / DuckMail）
├── config.json                 # 配置文件（不入库）
├── config.example.json         # 配置模板
├── requirements.txt            # Python 依赖
├── turnstilePatch/             # Chrome 扩展（Turnstile patch）
│   ├── manifest.json
│   └── script.js
├── sso/                        # SSO token 输出（自动创建）
├── credentials/                # 邮箱/密码/姓名输出（自动创建）
└── logs/                       # 运行日志（自动创建）
```

---

## 账号信息格式

`credentials_<timestamp>.txt` 每行格式如下：

```text
email,password,first_name,last_name
```

示例：

```text
tmpabcd1234@story.finchaintalk.com,Ncf1f2cae!a7#wSw5MA15,Ayla,Shaw
```

---

## 无头服务器部署注意

- snap 版 chromium 在 root 下有 AppArmor 限制，推荐用 playwright 安装的 chromium
- 服务器直连 x.ai 可能被墙，需在 `browser_proxy` 填写代理地址
- 脚本自动检测 Linux 环境并启用 Xvfb + playwright chromium 路径

---

## 致谢

- [kevinr229/grok-maintainer](https://github.com/kevinr229/grok-maintainer) — 原始项目
- [grok2api](https://github.com/chenyme/grok2api) — Grok API 代理
- [DuckMail](https://duckmail.sbs) — 临时邮箱服务
