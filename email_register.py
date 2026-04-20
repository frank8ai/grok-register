
from __future__ import annotations

import json
import logging
import random
import re
import string
import time
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
CLOUDFLARE_TEMP_DOMAIN = str(_conf.get("cloudflare_temp_domain", "finchaintalk.com"))
CLOUDFLARE_TEMP_PREFER_RANDOM_SUBDOMAIN = bool(_conf.get("cloudflare_temp_prefer_random_subdomain", True))
PROXY = str(_conf.get("proxy", ""))

# ============================================================
# 适配层：为 DrissionPage_example.py 提供简单接口
# ============================================================

_temp_email_cache: Dict[str, str] = {}


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


def create_temp_email() -> Tuple[str, str, str]:
    if _use_cloudflare_temp_provider():
        return create_cloudflare_temp_email()
    return create_duckmail_temp_email()


# ============================================================
# CloudflareTemp Unified Pool 核心函数
# ============================================================


def _normalize_domain(domain: str) -> str:
    return str(domain or "").strip().lower().strip(".")


def _as_domain_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [_normalize_domain(item) for item in value if _normalize_domain(item)]


def _is_subdomain_of_root(domain: str, root_domain: str) -> bool:
    domain = _normalize_domain(domain)
    root_domain = _normalize_domain(root_domain)
    return bool(domain and root_domain and domain != root_domain and domain.endswith(f".{root_domain}"))


def _build_cloudflare_temp_domain_candidates(
    settings: Dict[str, Any],
    preferred_root_domain: str,
    prefer_random_subdomain: bool = True,
) -> List[str]:
    preferred_root_domain = _normalize_domain(preferred_root_domain)
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
    candidates = _build_cloudflare_temp_domain_candidates(
        settings=settings,
        preferred_root_domain=CLOUDFLARE_TEMP_DOMAIN,
        prefer_random_subdomain=CLOUDFLARE_TEMP_PREFER_RANDOM_SUBDOMAIN,
    )
    if not candidates:
        raise Exception("邮箱池没有可用域名")

    root = _normalize_domain(CLOUDFLARE_TEMP_DOMAIN)
    subdomains = [domain for domain in candidates if _is_subdomain_of_root(domain, root)]
    return random.choice(subdomains or candidates)


def create_cloudflare_temp_email() -> Tuple[str, str, str]:
    """创建 CloudflareTemp 邮箱，返回 (email, password, jwt)"""
    api_base = CLOUDFLARE_TEMP_API_BASE.rstrip("/")
    settings = _fetch_cloudflare_temp_settings()
    domain = _choose_cloudflare_temp_domain(settings)
    session, use_cffi = _create_http_session()

    res = _do_request(
        session,
        use_cffi,
        "post",
        f"{api_base}/api/new_address",
        json={"name": "", "domain": domain, "cf_token": ""},
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


def wait_for_verification_code(mail_token: str, timeout: int = 120) -> Optional[str]:
    """轮询临时邮箱等待验证码邮件"""
    start = time.time()
    seen_ids = set()

    while time.time() - start < timeout:
        messages = fetch_emails(mail_token)
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            msg_id = msg.get("id") or msg.get("@id")
            if not msg_id or msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)

            detail = fetch_email_detail(mail_token, str(msg_id))
            if detail:
                content = (
                    detail.get("text")
                    or detail.get("message")
                    or detail.get("html")
                    or detail.get("raw")
                    or detail.get("subject")
                    or ""
                )
                code = extract_verification_code(content)
                if code:
                    print(f"[*] 从临时邮箱提取到验证码: {code}")
                    return code
        time.sleep(3)
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
