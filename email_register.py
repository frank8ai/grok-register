
from __future__ import annotations

import json
import logging
import random
import re
import string
import time
from datetime import datetime, timezone
from email import policy
from email.header import decode_header
from email.parser import BytesParser, Parser
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================================
# 邮箱服务配置（从 config.json 加载）
# ============================================================

_config_path = Path(__file__).parent / "config.json"
_conf: Dict[str, Any] = {}
if _config_path.exists():
    with _config_path.open("r", encoding="utf-8") as _f:
        _conf = json.load(_f)

EMAIL_PROVIDER = str(_conf.get("email_provider", "duckmail"))
DUCKMAIL_API_BASE = str(_conf.get("duckmail_api_base", "https://api.duckmail.sbs"))
DUCKMAIL_BEARER = str(_conf.get("duckmail_bearer", ""))
CLOUDFLARE_TEMP_API_BASE = str(_conf.get("cloudflare_temp_api_base", "https://temp-email-api.bitpowerhub.com"))
CLOUDFLARE_TEMP_ADMIN_PASSWORD = str(_conf.get("cloudflare_temp_admin_password", ""))
CLOUDFLARE_TEMP_CUSTOM_AUTH = str(_conf.get("cloudflare_temp_custom_auth", ""))
CLOUDFLARE_TEMP_DOMAIN = str(_conf.get("cloudflare_temp_domain", "finchaintalk.com"))
CLOUDFLARE_TEMP_PREFER_RANDOM_SUBDOMAIN = bool(_conf.get("cloudflare_temp_prefer_random_subdomain", True))
CLOUDFLARE_TEMP_ENABLE_PREFIX = bool(_conf.get("cloudflare_temp_enable_prefix", False))
PROXY = str(_conf.get("proxy", ""))

DEFAULT_CLOUDFLARE_TEMP_UNIFIED_POOL: List[str] = []
DEFAULT_CLOUDFLARE_TEMP_RANDOM_SUBDOMAIN_ROOTS = [
    "alpha.bitflow.cc.cd",
    "alpha.bitflow.ccwu.cc",
    "alpha.bitfusionpay.com",
    "alpha.flowpay.cc.cd",
    "alpha.leon08.cc.cd",
    "alpha.relayon.cc.cd",
    "alpha.yzw.io",
    "assets.bitflow.cc.cd",
    "assets.bitflow.ccwu.cc",
    "assets.flowpay.cc.cd",
    "assets.leon08.cc.cd",
    "assets.relayon.cc.cd",
    "beta.bitflow.cc.cd",
    "beta.bitflow.ccwu.cc",
    "beta.flowpay.cc.cd",
    "beta.leon08.cc.cd",
    "beta.relayon.cc.cd",
    "billing.bitpowerhub.com",
    "bitflow.cc.cd",
    "bitflow.ccwu.cc",
    "bitfusionpay.com",
    "bitpowerhub.com",
    "circle.yizhiwa.com.cn",
    "club.yizhiwa.com.cn",
    "console.yizhiwa.com.cn",
]
DEFAULT_CLOUDFLARE_TEMP_EXCLUDED_DOMAINS: List[str] = []

# ============================================================
# 适配层：为 DrissionPage_example.py 提供简单接口
# ============================================================

_temp_email_cache: Dict[str, str] = {}
_verification_request_started_at: Dict[str, float] = {}


def get_email_and_token() -> Tuple[Optional[str], Optional[str]]:
    """
    创建临时邮箱并返回 (email, mail_token)。
    供 DrissionPage_example.py 调用。
    """
    email, _password, mail_token = create_temp_email()
    if email and mail_token:
        _temp_email_cache[email] = mail_token
        return email, mail_token
    return None, None


def get_oai_code(dev_token: str, email: str, timeout: int = 30) -> Optional[str]:
    """
    轮询临时邮箱获取 OTP 验证码。
    供 DrissionPage_example.py 调用。

    Returns:
        验证码字符串（去除连字符，如 "MM0SF3"）或 None
    """
    code = wait_for_verification_code(mail_token=dev_token, timeout=timeout)
    if code:
        code = code.replace("-", "")
    return code


def mark_verification_request_started(mail_token: str, started_at: Optional[float] = None) -> None:
    normalized = str(mail_token or "").strip()
    if not normalized:
        return
    _verification_request_started_at[normalized] = (
        float(started_at) if started_at is not None else time.time()
    )


# ============================================================
# 服务选择与 HTTP 工具
# ============================================================


def _provider_key(provider: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(provider or "").lower())


def _use_cloudflare_temp_provider() -> bool:
    return _provider_key(EMAIL_PROVIDER) in {
        "cloudflaretemp",
        "cloudflaretempunifiedpool",
        "tempmail",
        "tempemail",
        "cloudflareworker",
    }


def _create_http_session():
    """创建请求会话（优先 curl_cffi 绕 TLS 指纹）"""
    if curl_requests:
        session = curl_requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        if PROXY:
            session.proxies = {"http": PROXY, "https": PROXY}
        return session, True

    # fallback to requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    if PROXY:
        s.proxies = {"http": PROXY, "https": PROXY}
    return s, False


def _create_duckmail_session():
    return _create_http_session()


def _do_request(session, use_cffi, method, url, **kwargs):
    """统一请求，curl_cffi 加 impersonate 参数"""
    if use_cffi:
        kwargs.setdefault("impersonate", "chrome131")
    return getattr(session, method)(url, **kwargs)


def _generate_password(length=14):
    lower = string.ascii_lowercase
    upper = string.ascii_uppercase
    digits = string.digits
    special = "!@#$%"
    pwd = [random.choice(lower), random.choice(upper),
           random.choice(digits), random.choice(special)]
    all_chars = lower + upper + digits + special
    pwd += [random.choice(all_chars) for _ in range(length - 4)]
    random.shuffle(pwd)
    return "".join(pwd)


def _generate_cloudflare_temp_name() -> str:
    letters = "".join(random.choices(string.ascii_lowercase, k=5))
    digits = "".join(random.choices(string.digits, k=random.randint(1, 3)))
    suffix = "".join(random.choices(string.ascii_lowercase, k=random.randint(1, 3)))
    return letters + digits + suffix


def create_temp_email() -> Tuple[str, str, str]:
    if _use_cloudflare_temp_provider():
        return create_cloudflare_temp_email()
    return create_duckmail_temp_email()


# ============================================================
# CloudflareTemp Unified Pool 核心函数
# ============================================================


def _normalize_domain(domain: str) -> str:
    return str(domain or "").strip().lower().strip(".")


def _dedupe_domains(domains: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for domain in domains:
        normalized = _normalize_domain(domain)
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def _filter_excluded_domains(domains: List[str], excluded_domains: List[str]) -> List[str]:
    excluded = {_normalize_domain(domain) for domain in excluded_domains if _normalize_domain(domain)}
    return [domain for domain in _dedupe_domains(domains) if domain not in excluded]


_configured_cloudflare_temp_domains = _conf.get("cloudflare_temp_domains", DEFAULT_CLOUDFLARE_TEMP_UNIFIED_POOL)
if _configured_cloudflare_temp_domains is None:
    _configured_cloudflare_temp_domains = DEFAULT_CLOUDFLARE_TEMP_UNIFIED_POOL

CLOUDFLARE_TEMP_DOMAINS = [
    _normalize_domain(domain)
    for domain in _configured_cloudflare_temp_domains
    if _normalize_domain(domain)
]
CLOUDFLARE_TEMP_EXCLUDED_DOMAINS = _dedupe_domains(
    [
        _normalize_domain(domain)
        for domain in (_conf.get("cloudflare_temp_excluded_domains") or DEFAULT_CLOUDFLARE_TEMP_EXCLUDED_DOMAINS)
        if _normalize_domain(domain)
    ]
)
CLOUDFLARE_TEMP_DOMAINS = _filter_excluded_domains(CLOUDFLARE_TEMP_DOMAINS, CLOUDFLARE_TEMP_EXCLUDED_DOMAINS)
CLOUDFLARE_TEMP_RANDOM_SUBDOMAIN_ROOTS = [
    _normalize_domain(domain)
    for domain in (_conf.get("cloudflare_temp_random_subdomain_roots") or DEFAULT_CLOUDFLARE_TEMP_RANDOM_SUBDOMAIN_ROOTS)
    if _normalize_domain(domain)
]
CLOUDFLARE_TEMP_RANDOM_SUBDOMAIN_ROOTS = _dedupe_domains(CLOUDFLARE_TEMP_RANDOM_SUBDOMAIN_ROOTS)
_cloudflare_temp_domain_index = 0


def _as_domain_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [_normalize_domain(item) for item in value if _normalize_domain(item)]


def _filter_supported_random_subdomain_roots(
    settings: Dict[str, Any],
    configured_roots: Optional[List[str]] = None,
) -> List[str]:
    roots = _dedupe_domains(configured_roots or CLOUDFLARE_TEMP_RANDOM_SUBDOMAIN_ROOTS)
    supported_random_domains = _as_domain_list(settings.get("randomSubdomainDomains"))
    if not supported_random_domains:
        return roots

    supported_set = set(supported_random_domains)
    return [domain for domain in roots if domain in supported_set]


def _unsupported_random_subdomain_roots(
    settings: Dict[str, Any],
    configured_roots: Optional[List[str]] = None,
) -> List[str]:
    roots = _dedupe_domains(configured_roots or CLOUDFLARE_TEMP_RANDOM_SUBDOMAIN_ROOTS)
    supported_random_domains = _as_domain_list(settings.get("randomSubdomainDomains"))
    if not supported_random_domains:
        return []

    supported_set = set(supported_random_domains)
    return [domain for domain in roots if domain not in supported_set]


def _is_subdomain_of_root(domain: str, root_domain: str) -> bool:
    domain = _normalize_domain(domain)
    root_domain = _normalize_domain(root_domain)
    return bool(domain and root_domain and domain != root_domain and domain.endswith(f".{root_domain}"))


def _build_cloudflare_temp_domain_candidates(
    settings: Dict[str, Any],
    preferred_root_domain: str,
    prefer_random_subdomain: bool = True,
    configured_domains: Optional[List[str]] = None,
) -> List[str]:
    preferred_root_domain = _normalize_domain(preferred_root_domain)
    explicit_domains = [_normalize_domain(domain) for domain in (configured_domains or []) if _normalize_domain(domain)]
    if explicit_domains:
        seen = set()
        ordered = []
        for domain in explicit_domains:
            if domain not in seen:
                seen.add(domain)
                ordered.append(domain)
        return ordered

    random_domains = _as_domain_list(settings.get("randomSubdomainDomains"))
    domains = _as_domain_list(settings.get("domains")) or _as_domain_list(settings.get("defaultDomains"))

    candidates: List[str] = []

    def add_once(domain: str):
        domain = _normalize_domain(domain)
        if domain and domain not in candidates:
            candidates.append(domain)

    if prefer_random_subdomain:
        for domain in random_domains:
            if _is_subdomain_of_root(domain, preferred_root_domain):
                add_once(domain)

    for domain in domains:
        if _is_subdomain_of_root(domain, preferred_root_domain):
            add_once(domain)

    for domain in domains:
        if domain == preferred_root_domain:
            add_once(domain)

    if not candidates and preferred_root_domain:
        add_once(preferred_root_domain)

    return candidates


def _fetch_cloudflare_temp_settings() -> Dict[str, Any]:
    api_base = CLOUDFLARE_TEMP_API_BASE.rstrip("/")
    session, use_cffi = _create_http_session()
    res = _do_request(session, use_cffi, "get", f"{api_base}/open_api/settings", timeout=15)
    if res.status_code != 200:
        raise Exception(f"获取邮箱池配置失败: HTTP {res.status_code} {res.text[:200]}")
    data = res.json()
    if not isinstance(data, dict):
        raise Exception("获取邮箱池配置失败: 返回格式异常")
    return data


def _choose_cloudflare_temp_domain(settings: Dict[str, Any]) -> str:
    global _cloudflare_temp_domain_index
    candidates = _build_cloudflare_temp_domain_candidates(
        settings=settings,
        preferred_root_domain=CLOUDFLARE_TEMP_DOMAIN,
        prefer_random_subdomain=CLOUDFLARE_TEMP_PREFER_RANDOM_SUBDOMAIN,
        configured_domains=CLOUDFLARE_TEMP_DOMAINS,
    )
    if not candidates:
        raise Exception("邮箱池没有可用域名")
    domain = candidates[_cloudflare_temp_domain_index % len(candidates)]
    _cloudflare_temp_domain_index += 1
    return domain


def _build_cloudflare_temp_domain_entries(settings: Optional[Dict[str, Any]] = None) -> List[Tuple[str, bool]]:
    entries: List[Tuple[str, bool]] = []
    seen = set()
    settings = settings or {}

    for domain in CLOUDFLARE_TEMP_DOMAINS:
        key = (domain, False)
        if domain and key not in seen:
            seen.add(key)
            entries.append(key)

    for domain in _unsupported_random_subdomain_roots(settings):
        key = (domain, False)
        if domain and key not in seen:
            seen.add(key)
            entries.append(key)

    for domain in _filter_supported_random_subdomain_roots(settings):
        key = (domain, True)
        if domain and key not in seen:
            seen.add(key)
            entries.append(key)

    return entries


def _choose_cloudflare_temp_domain_entry(settings: Dict[str, Any]) -> Tuple[str, bool]:
    global _cloudflare_temp_domain_index
    entries = _build_cloudflare_temp_domain_entries(settings)
    if not entries:
        raise Exception("邮箱池没有可用域名")
    domain, enable_random_subdomain = entries[_cloudflare_temp_domain_index % len(entries)]
    _cloudflare_temp_domain_index += 1
    return domain, enable_random_subdomain


def create_cloudflare_temp_email() -> Tuple[str, str, str]:
    """创建 CloudflareTemp 邮箱，返回 (email, password, jwt)"""
    api_base = CLOUDFLARE_TEMP_API_BASE.rstrip("/")
    admin_auth = CLOUDFLARE_TEMP_CUSTOM_AUTH or CLOUDFLARE_TEMP_ADMIN_PASSWORD
    if not admin_auth:
        raise Exception("cloudflare_temp_admin_password / cloudflare_temp_custom_auth 未设置")
    settings = _fetch_cloudflare_temp_settings()
    domain, enable_random_subdomain = _choose_cloudflare_temp_domain_entry(settings)
    session, use_cffi = _create_http_session()

    res = _do_request(
        session,
        use_cffi,
        "post",
        f"{api_base}/admin/new_address",
        json={
            "name": _generate_cloudflare_temp_name(),
            "domain": domain,
            "enablePrefix": CLOUDFLARE_TEMP_ENABLE_PREFIX,
            "enableRandomSubdomain": enable_random_subdomain,
        },
        headers={"x-admin-auth": admin_auth, "x-custom-auth": admin_auth},
        timeout=15,
    )
    if res.status_code != 200:
        raise Exception(f"创建 CloudflareTemp 邮箱失败: HTTP {res.status_code} {res.text[:200]}")

    data = res.json()
    email = data.get("address")
    mail_token = data.get("jwt")
    password = data.get("password") or ""
    if not email or not mail_token:
        raise Exception(f"创建 CloudflareTemp 邮箱失败: 返回格式异常 {str(data)[:200]}")

    print(f"[*] CloudflareTemp 邮箱创建成功: {email}")
    return str(email), str(password), str(mail_token)


def fetch_cloudflare_temp_emails(mail_token: str) -> List[Dict[str, Any]]:
    try:
        api_base = CLOUDFLARE_TEMP_API_BASE.rstrip("/")
        headers = {"Authorization": f"Bearer {mail_token}"}
        session, use_cffi = _create_http_session()
        res = _do_request(
            session,
            use_cffi,
            "get",
            f"{api_base}/api/mails?limit=20&offset=0",
            headers=headers,
            timeout=15,
        )
        if res.status_code == 200:
            data = res.json()
            return data.get("results") or []
    except Exception:
        pass
    return []


def fetch_cloudflare_temp_email_detail(mail_token: str, msg_id: str) -> Optional[Dict]:
    try:
        api_base = CLOUDFLARE_TEMP_API_BASE.rstrip("/")
        headers = {"Authorization": f"Bearer {mail_token}"}
        session, use_cffi = _create_http_session()
        res = _do_request(
            session,
            use_cffi,
            "get",
            f"{api_base}/api/mail/{msg_id}",
            headers=headers,
            timeout=15,
        )
        if res.status_code == 200:
            data = res.json()
            return data if isinstance(data, dict) else None
    except Exception:
        pass
    return None


# ============================================================
# DuckMail 核心函数
# ============================================================


def create_duckmail_temp_email() -> Tuple[str, str, str]:
    """创建 DuckMail 临时邮箱，返回 (email, password, mail_token)"""
    if not DUCKMAIL_BEARER:
        raise Exception("duckmail_bearer 未设置，无法创建临时邮箱")

    chars = string.ascii_lowercase + string.digits
    length = random.randint(8, 13)
    email_local = "".join(random.choice(chars) for _ in range(length))
    email = f"{email_local}@duckmail.sbs"
    password = _generate_password()

    api_base = DUCKMAIL_API_BASE.rstrip("/")
    bearer_headers = {"Authorization": f"Bearer {DUCKMAIL_BEARER}"}
    session, use_cffi = _create_duckmail_session()

    try:
        # 1. 创建账号
        res = _do_request(session, use_cffi, "post",
                          f"{api_base}/accounts",
                          json={"address": email, "password": password},
                          headers=bearer_headers, timeout=15)
        if res.status_code not in (200, 201):
            raise Exception(f"创建邮箱失败: {res.status_code} - {res.text[:200]}")

        # 2. 获取 mail token
        time.sleep(0.5)
        token_res = _do_request(session, use_cffi, "post",
                                f"{api_base}/token",
                                json={"address": email, "password": password},
                                timeout=15)
        if token_res.status_code == 200:
            mail_token = token_res.json().get("token")
            if mail_token:
                print(f"[*] DuckMail 临时邮箱创建成功: {email}")
                return email, password, mail_token

        raise Exception(f"获取邮件 Token 失败: {token_res.status_code}")
    except Exception as e:
        raise Exception(f"DuckMail 创建邮箱失败: {e}")


def fetch_emails(mail_token: str) -> List[Dict[str, Any]]:
    if _use_cloudflare_temp_provider():
        return fetch_cloudflare_temp_emails(mail_token)

    """获取 DuckMail 邮件列表"""
    try:
        api_base = DUCKMAIL_API_BASE.rstrip("/")
        headers = {"Authorization": f"Bearer {mail_token}"}
        session, use_cffi = _create_duckmail_session()
        res = _do_request(session, use_cffi, "get",
                          f"{api_base}/messages",
                          headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return data.get("hydra:member") or data.get("member") or data.get("data") or []
    except Exception:
        pass
    return []


def fetch_email_detail(mail_token: str, msg_id: str) -> Optional[Dict]:
    if _use_cloudflare_temp_provider():
        return fetch_cloudflare_temp_email_detail(mail_token, msg_id)

    """获取 DuckMail 单封邮件详情"""
    try:
        api_base = DUCKMAIL_API_BASE.rstrip("/")
        headers = {"Authorization": f"Bearer {mail_token}"}
        session, use_cffi = _create_duckmail_session()

        if isinstance(msg_id, str) and msg_id.startswith("/messages/"):
            msg_id = msg_id.split("/")[-1]

        res = _do_request(session, use_cffi, "get",
                          f"{api_base}/messages/{msg_id}",
                          headers=headers, timeout=15)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None


def _parse_mail_timestamp(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric / 1000.0 if numeric > 10**12 else numeric

    text = str(value or "").strip()
    if not text:
        return 0.0
    if text.isdigit():
        numeric = float(text)
        return numeric / 1000.0 if numeric > 10**12 else numeric

    normalized = text.replace("Z", "+00:00")
    for parser in (
        lambda raw: datetime.fromisoformat(raw),
        lambda raw: datetime.strptime(raw, "%Y-%m-%d %H:%M:%S"),
        lambda raw: datetime.strptime(raw, "%Y/%m/%d %H:%M:%S"),
        lambda raw: datetime.strptime(raw, "%Y/%m/%d %H:%M"),
        parsedate_to_datetime,
    ):
        try:
            parsed = parser(normalized)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc).timestamp()
            return parsed.timestamp()
        except Exception:
            continue
    return 0.0


def _mail_timestamp(item: Dict[str, Any]) -> float:
    for key in (
        "createdAt",
        "created_at",
        "created",
        "date",
        "sentAt",
        "sent_at",
        "receivedAt",
        "received_at",
        "timestamp",
    ):
        parsed = _parse_mail_timestamp(item.get(key))
        if parsed:
            return parsed
    return 0.0


def _mail_sort_key(item: Dict[str, Any]) -> Tuple[int, float, int]:
    timestamp = _mail_timestamp(item)
    numeric_id = 0
    try:
        numeric_id = int(str(item.get("id") or item.get("@id") or "").split("/")[-1])
    except Exception:
        numeric_id = 0
    return (0 if timestamp else 1, timestamp, numeric_id)


def _mail_content(item: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in (
        "subject",
        "intro",
        "text",
        "message",
        "html",
        "raw",
        "body",
        "content",
    ):
        value = item.get(key)
        if value:
            if key == "raw":
                decoded = _decode_raw_email(value)
                if decoded:
                    parts.extend(decoded)
                    continue
            parts.append(str(value))
    return "\n".join(parts)


def _decode_mime_header(value: str) -> str:
    decoded_parts: List[str] = []
    for chunk, encoding in decode_header(str(value or "")):
        if isinstance(chunk, bytes):
            decoded_parts.append(chunk.decode(encoding or "utf-8", errors="replace"))
        else:
            decoded_parts.append(str(chunk))
    return "".join(decoded_parts)


def _decode_raw_email(raw_value: Any) -> List[str]:
    raw_text = str(raw_value or "").strip()
    if not raw_text:
        return []

    if ":" not in raw_text.partition("\n")[0]:
        return [raw_text]

    try:
        message = BytesParser(policy=policy.default).parsebytes(raw_text.encode("utf-8", errors="replace"))
    except Exception:
        try:
            message = Parser(policy=policy.default).parsestr(raw_text)
        except Exception:
            return [raw_text]

    parts: List[str] = []
    subject = _decode_mime_header(message.get("Subject", ""))
    if subject:
        parts.append(f"Subject: {subject}")

    if message.is_multipart():
        for part in message.walk():
            if part.is_multipart():
                continue
            content_type = part.get_content_type()
            if content_type not in ("text/plain", "text/html"):
                continue
            try:
                payload = part.get_content()
            except Exception:
                payload_bytes = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                payload = payload_bytes.decode(charset, errors="replace")
            if payload:
                parts.append(str(payload))
    else:
        try:
            payload = message.get_content()
        except Exception:
            payload_bytes = message.get_payload(decode=True) or b""
            charset = message.get_content_charset() or "utf-8"
            payload = payload_bytes.decode(charset, errors="replace")
        if payload:
            parts.append(str(payload))

    return [part for part in parts if part]


def _mail_debug_summary(item: Dict[str, Any]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    for key in ("id", "@id", "subject", "createdAt", "created_at", "date", "sentAt", "receivedAt"):
        value = item.get(key)
        if value:
            summary[key] = value

    content = _mail_content(item)
    if content:
        normalized = " ".join(content.split())
        summary["content_preview"] = normalized[:160]

    return summary


def wait_for_verification_code(mail_token: str, timeout: int = 120) -> Optional[str]:
    """轮询临时邮箱等待验证码邮件"""
    start = time.time()
    requested_at = _verification_request_started_at.get(str(mail_token or "").strip(), start)
    min_mail_timestamp = max(0.0, requested_at - 5.0)
    last_debug_summaries: List[Dict[str, Any]] = []

    while time.time() - start < timeout:
        messages = sorted(
            [msg for msg in fetch_emails(mail_token) if isinstance(msg, dict)],
            key=_mail_sort_key,
        )
        last_debug_summaries = [_mail_debug_summary(msg) for msg in messages[:5]]
        for msg in messages:
            mail_timestamp = _mail_timestamp(msg)
            if mail_timestamp and mail_timestamp < min_mail_timestamp:
                continue
            msg_id = msg.get("id") or msg.get("@id")
            if not msg_id:
                continue

            detail = fetch_email_detail(mail_token, str(msg_id))
            candidates = [detail, msg] if detail else [msg]
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                content = _mail_content(candidate)
                code = extract_verification_code(content)
                if code:
                    print(f"[*] 从临时邮箱提取到验证码: {code}")
                    return code
        time.sleep(3)
    if last_debug_summaries:
        print(f"[Debug] 验证码轮询超时，最近邮件摘要: {last_debug_summaries}")
    else:
        print("[Debug] 验证码轮询超时，邮箱列表为空。")
    return None


def extract_verification_code(content: str) -> Optional[str]:
    """
    从邮件内容提取验证码。
    Grok/x.ai 格式：MM0-SF3（3位-3位字母数字混合）或 6 位纯数字。
    """
    if not content:
        return None

    # 模式 1: Grok 格式 XXX-XXX
    m = re.search(r"(?<![A-Z0-9-])([A-Z0-9]{3}-[A-Z0-9]{3})(?![A-Z0-9-])", content)
    if m:
        return m.group(1)

    # 模式 2: 带标签的验证码
    m = re.search(r"(?:verification code|验证码|your code)[:\s]*[<>\s]*([A-Z0-9]{3}-[A-Z0-9]{3})\b", content, re.IGNORECASE)
    if m:
        return m.group(1)

    # 模式 3: HTML 样式包裹
    m = re.search(r"background-color:\s*#F3F3F3[^>]*>[\s\S]*?([A-Z0-9]{3}-[A-Z0-9]{3})[\s\S]*?</p>", content)
    if m:
        return m.group(1)

    # 模式 4: Subject 行 6 位数字
    m = re.search(r"Subject:.*?(\d{6})", content)
    if m and m.group(1) != "177010":
        return m.group(1)

    # 模式 5: HTML 标签内 6 位数字
    for code in re.findall(r">\s*(\d{6})\s*<", content):
        if code != "177010":
            return code

    # 模式 6: 独立 6 位数字
    for code in re.findall(r"(?<![&#\d])(\d{6})(?![&#\d])", content):
        if code != "177010":
            return code

    return None
