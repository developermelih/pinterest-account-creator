# -*- coding: utf-8 -*-
import json
import os
import re
import copy
import random
import string
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from curl_cffi import requests as curl_requests
from fake_useragent import UserAgent
from faker import Faker

try:
    import colorama
    colorama.init(autoreset=True)
    HAS_COLORAMA = True
except ImportError:
    HAS_COLORAMA = False

def set_console_title(text):
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(str(text))
        except Exception:
            pass

BASE_URL = "https://tr.pinterest.com"

PINTEREST_LOCALES = {
    "AU": "en-AU", "GB": "en-GB", "IN": "en-IN", "US": "en-US",
    "AR": "es-AR", "ES": "es-ES", "MX": "es-MX", "PT": "pt-PT", "BR": "pt-BR",
    "ZA": "af-ZA", "SA": "ar-SA", "BG": "bg-BG", "CZ": "cs-CZ", "DK": "da-DK",
    "DE": "de", "GR": "el-GR", "FI": "fi-FI", "FR": "fr", "IL": "he-IL",
    "HR": "hr-HR", "HU": "hu-HU", "ID": "id-ID", "IT": "it", "JP": "ja",
    "KR": "ko-KR", "MY": "ms-MY", "NO": "nb-NO", "NL": "nl", "PL": "pl-PL",
    "RO": "ro-RO", "RU": "ru-RU", "SK": "sk-SK", "SE": "sv-SE", "TH": "th-TH",
    "PH": "tl-PH", "TR": "tr", "UA": "uk-UA", "VN": "vi-VN", "CN": "zh-CN",
    "TW": "zh-TW",
}


def random_name():
    return Faker().first_name()


def load_config():
    p = Path(__file__).parent / "config.json"
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def random_password(length=14):
    chars = string.ascii_letters + string.digits + "!@#$%"
    return "".join(random.choices(chars, k=length))


def get_country_from_proxy(session):
    try:
        r = session.get(
            "http://ip-api.com/json?fields=countryCode", timeout=4
        )
        if r.status_code == 200:
            d = r.json()
            cc = (d.get("countryCode") or "").upper()
            if len(cc) == 2:
                return cc
    except Exception:
        pass
    return "US"


def locale_for_country(country_code):
    return PINTEREST_LOCALES.get(
        (country_code or "US").upper(), "en-US"
    )


def create_tempmail_email(cfg):
    base = (cfg.get("inbox_api_base") or "").rstrip("/")
    password = cfg.get("inbox_password") or ""
    if not base or not password:
        return None
    proxies = _inbox_proxies(cfg)
    try:
        r = curl_requests.get(f"{base}/domains", timeout=15, proxies=proxies)
        if r.status_code != 200:
            return None
        data = r.json()
        members = data.get("hydra:member") or data.get("member") or []
        if not members:
            return None
        domain = members[0].get("domain") or ""
        if not domain:
            return None
        local = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=10)
        )
        address = f"{local}@{domain}"
        r2 = curl_requests.post(
            f"{base}/accounts",
            json={"address": address, "password": password},
            timeout=15,
            proxies=proxies,
        )
        if r2.status_code not in (200, 201):
            return None
        return address
    except Exception:
        return None


def get_verification_code(email, cfg):
    base = (cfg.get("inbox_api_base") or "").rstrip("/")
    password = cfg.get("inbox_password") or ""
    if not base or not password:
        return None
    proxies = _inbox_proxies(cfg)
    try:
        r = curl_requests.post(
            f"{base}/token",
            json={"address": email, "password": password},
            timeout=15,
            proxies=proxies,
        )
        if r.status_code != 200:
            return None
        token_data = r.json()
        token = token_data.get("token") or ""
        if not token:
            return None
        headers = {"Authorization": f"Bearer {token}"}
        r2 = curl_requests.get(
            f"{base}/messages", headers=headers, timeout=15, proxies=proxies
        )
        if r2.status_code != 200:
            return None
        data = r2.json()
        members = data.get("hydra:member") or data.get("member") or []
        for msg in members:
            content = (msg.get("intro") or msg.get("subject") or "")
            if isinstance(content, dict):
                content = str(content)
            match = re.search(r"\b(\d{6})\b", content)
            if match:
                return match.group(1)
        for msg in members:
            msg_id = msg.get("id")
            if not msg_id:
                continue
            r3 = curl_requests.get(
                f"{base}/messages/{msg_id}",
                headers=headers,
                timeout=15,
                proxies=proxies,
            )
            if r3.status_code != 200:
                continue
            j = r3.json()
            content = (j.get("text") or j.get("intro") or "")
            if isinstance(content, dict):
                content = str(content)
            for part in (j.get("html") or []):
                if isinstance(part, str):
                    content += " " + part
            match = re.search(r"\b(\d{6})\b", content)
            if match:
                return match.group(1)
    except Exception:
        pass
    return None


def _inbox_proxies(cfg):
    proxy = (cfg.get("proxy") or "").strip()
    if not proxy:
        proxy_list = cfg.get("proxy_list")
        if isinstance(proxy_list, list) and proxy_list:
            proxy = (proxy_list[0] or "").strip()
    if not proxy:
        return None
    if not proxy.startswith("http"):
        proxy = "http://" + proxy
    return {"http": proxy, "https": proxy}


def inbox_configured(cfg):
    base = (cfg.get("inbox_api_base") or "").strip()
    password = (cfg.get("inbox_password") or "").strip()
    return bool(base and password)


def _ua():
    try:
        return UserAgent().chrome
    except Exception:
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
        )


class PinterestBot:
    def __init__(self, cfg, impersonate="chrome120", save_lock=None):
        self.cfg = cfg
        self.save_lock = save_lock
        self.base_url = BASE_URL.rstrip("/")
        self.session = curl_requests.Session(
            impersonate=cfg.get("impersonate") or impersonate
        )
        proxy = (cfg.get("proxy") or "").strip()
        if proxy:
            if not proxy.startswith("http"):
                proxy = "http://" + proxy
            self.session.proxies = {"http": proxy, "https": proxy}
        ua = _ua()
        self.session.headers.update({
            "User-Agent": ua,
            "Accept": "application/json, text/javascript, */*, q=0.01",
            "Origin": self.base_url,
            "Referer": self.base_url + "/",
            "x-requested-with": "XMLHttpRequest",
            "x-pinterest-appstate": "active",
            "x-pinterest-pws-handler": "www/index.js",
            "x-pinterest-source-url": "/",
        })
        self._domain = "tr.pinterest.com"

    def _ensure_csrf(self):
        jar = self.session.cookies
        for name in ("csrftoken", "csrf_token"):
            val = jar.get(name)
            if val is not None:
                token = (
                    val if isinstance(val, str)
                    else getattr(val, "value", str(val))
                )
                if token:
                    self.session.headers["X-CSRFToken"] = token
                    return
        for c in jar:
            name = c if isinstance(c, str) else getattr(c, "name", None)
            if name and (
                "csrf" in (name or "").lower() or name == "csrftoken"
            ):
                val = (
                    jar.get(name) if isinstance(c, str)
                    else getattr(c, "value", None)
                )
                if val is not None:
                    token = (
                        val if isinstance(val, str)
                        else getattr(val, "value", str(val))
                    )
                    if token:
                        self.session.headers["X-CSRFToken"] = token
                        return

    def _has_csrf(self):
        return bool(
            (self.session.headers.get("X-CSRFToken") or "").strip()
        )

    def fetch_session(self):
        for path in ("/", "/signup/"):
            try:
                self.session.get(self.base_url + path, timeout=30)
                self._ensure_csrf()
                if self._has_csrf():
                    return True
            except Exception:
                continue
        return False

    def _get(self, endpoint, params):
        url = self.base_url + endpoint
        if "data" in params and isinstance(params["data"], dict):
            params = {**params, "data": json.dumps(params["data"])}
        return self.session.get(url, params=params, timeout=30)

    def _post_form(self, endpoint, payload):
        self._ensure_csrf()
        url = self.base_url + endpoint
        self.session.headers["Content-Type"] = (
            "application/x-www-form-urlencoded"
        )
        body = {
            k: (json.dumps(v) if isinstance(v, dict) else v)
            for k, v in payload.items()
        }
        return self.session.post(url, data=body, timeout=30)

    def _post_json(self, endpoint, payload):
        self._ensure_csrf()
        url = self.base_url + endpoint
        self.session.headers["Content-Type"] = "application/json"
        return self.session.post(url, json=payload, timeout=30)

    def step1_email_exists(self, email):
        return self._get("/resource/ApiResource/get/", {
            "source_url": "/",
            "data": {
                "options": {
                    "url": "/v3/register/exists/",
                    "data": {"email": email},
                },
                "context": {},
            },
        })

    def step2_email_validation(self, email):
        return self._get("/resource/ApiResource/get/", {
            "source_url": "/",
            "data": {
                "options": {
                    "url": "/v3/email/validation/",
                    "data": {"email": email},
                },
                "context": {},
            },
        })

    def step3_sso_info(self, email):
        return self._post_json("/secure/sso_info", {"email": email})

    def step4_track(self):
        return self._post_form(
            "/resource/UserRegisterTrackActionResource/update/",
            {
                "source_url": "/",
                "data": {
                    "options": {
                        "actions": [{
                            "name": "lex.focus_password",
                            "aux_data": {"tags": {}},
                        }],
                    },
                    "context": {},
                },
            },
        )

    def step5_register(self, email, password, first_name, age, country):
        return self._post_form(
            "/resource/UserRegisterResource/create/",
            {
                "source_url": "/",
                "data": {
                    "options": {
                        "first_name": first_name,
                        "password": password,
                        "email": email,
                        "age": age,
                        "country": country,
                        "site": "pinterest",
                    },
                    "context": {},
                },
            },
        )

    def step6_settings(self, gender, country, locale):
        return self._post_form(
            "/resource/UserSettingsResource/update/",
            {
                "source_url": "/",
                "data": {
                    "options": {
                        "gender": gender,
                        "country": country,
                        "locale": locale,
                    },
                    "context": {},
                },
            },
        )

    def verification_send(self, email):
        return self._post_form("/resource/ApiResource/create/", {
            "source_url": "/settings/account-settings/",
            "data": {
                "options": {
                    "url": "/v3/verifications/send/",
                    "data": {"recipient": email, "channel": "email"},
                },
                "context": {},
            },
        })

    def verification_check(self, email, code):
        return self._post_form("/resource/ApiResource/create/", {
            "source_url": "/settings/account-settings/",
            "data": {
                "options": {
                    "url": "/v3/verifications/check/",
                    "data": {"code": code, "recipient": email},
                },
                "context": {},
            },
        })

    def _cookies_list(self):
        out = []
        jar = self.session.cookies
        domain_default = self._domain
        try:
            inner = getattr(jar, "jar", jar)
            cookies_dict = getattr(inner, "_cookies", None)
            if cookies_dict:
                for domain, by_path in cookies_dict.items():
                    if not isinstance(by_path, dict):
                        continue
                    for path, by_name in by_path.items():
                        if not isinstance(by_name, dict):
                            continue
                        for name, cookie in by_name.items():
                            val = (
                                getattr(cookie, "value", str(cookie))
                                if hasattr(cookie, "value")
                                else str(cookie)
                            )
                            out.append({
                                "name": name,
                                "value": val,
                                "domain": domain or domain_default,
                            })
                if out:
                    return out
        except Exception:
            pass
        try:
            d = jar.get_dict() if hasattr(jar, "get_dict") else None
            if d:
                for name, val in d.items():
                    out.append({
                        "name": name,
                        "value": val,
                        "domain": domain_default,
                    })
                return out
        except Exception:
            pass
        for c in jar:
            name = c if isinstance(c, str) else getattr(c, "name", None)
            val = (
                jar.get(name) if isinstance(c, str)
                else getattr(c, "value", None)
            )
            if name and val is not None:
                value_str = (
                    val if isinstance(val, str)
                    else getattr(val, "value", str(val))
                )
                out.append({
                    "name": name,
                    "value": value_str,
                    "domain": domain_default,
                })
        return out

    def _netscape(self, cookies_list):
        lines = ["# Netscape HTTP Cookie File", ""]
        for c in cookies_list:
            domain = c.get("domain", "")
            if domain and not domain.startswith("."):
                domain = "." + domain
            path = c.get("path", "/")
            secure = (
                "TRUE"
                if (c.get("name", "") or "").startswith("__Secure-")
                else "FALSE"
            )
            expiry = c.get("expiry") or 9999999999
            if expiry == 0 or expiry is None:
                expiry = 9999999999
            name = c.get("name", "")
            value = (c.get("value") or "").replace("\t", " ").replace(
                "\n", " "
            )
            lines.append("\t".join([
                domain, "TRUE", path, secure,
                str(int(expiry)), name, value,
            ]))
        return "\n".join(lines)

    def _save_account(self, email, password):
        base = Path(__file__).parent
        def _write():
            with open(base / "accounts.txt", "a", encoding="utf-8") as f:
                f.write(f"{email}:{password}\n")
            safe = email.replace("@", "_at_").replace(".", "_")
            (base / "cookies").mkdir(exist_ok=True)
            cl = self._cookies_list()
            with open(
                base / "cookies" / f"{safe}.txt", "w", encoding="utf-8"
            ) as f:
                f.write(self._netscape(cl))
        if self.save_lock:
            with self.save_lock:
                _write()
        else:
            _write()

    def run(
        self, email, password, first_name, age, country,
        gender, locale, skip_checks=False, progress_callback=None,
    ):
        results = {}
        def _prog(stage, em=None):
            if progress_callback:
                progress_callback(stage, em or email)
        if not self.fetch_session():
            return {"ok": False, "error": "session_failed", "results": results}
        if not skip_checks:
            r1 = self.step1_email_exists(email)
            results["step1"] = {"status": r1.status_code}
            try:
                rr = r1.json().get("resource_response", {})
                if rr.get("status") != "success":
                    return {
                        "ok": False,
                        "error": "email_check_failed",
                        "results": results,
                    }
                if rr.get("data") is True:
                    return {
                        "ok": False,
                        "error": "email_taken",
                        "results": results,
                    }
            except Exception:
                pass
            r2 = self.step2_email_validation(email)
            results["step2"] = {"status": r2.status_code}
            self._ensure_csrf()
            r3 = self.step3_sso_info(email)
            results["step3"] = {"status": r3.status_code}
        r4 = self.step4_track()
        results["step4"] = {"status": r4.status_code}
        r5 = self.step5_register(
            email, password, first_name, age, country
        )
        results["step5"] = {"status": r5.status_code}
        try:
            rr = r5.json().get("resource_response", {})
            if rr.get("status") != "success":
                msg = (rr.get("error") or {}).get("message") or "failed"
                return {
                    "ok": False,
                    "error": "register_failed",
                    "message": msg,
                    "results": results,
                }
        except Exception:
            return {
                "ok": False,
                "error": "invalid_response",
                "results": results,
            }
        _prog("register_ok")
        r6 = self.step6_settings(gender, country, locale)
        results["step6"] = {"status": r6.status_code}
        rs = self.verification_send(email)
        vs_data = {"status": rs.status_code}
        try:
            rs_j = rs.json()
            rr = rs_j.get("resource_response", {})
            vs_data["successful"] = (
                rr.get("data") is True
                or (
                    isinstance(rr.get("data"), dict)
                    and rr.get("data", {}).get("successful")
                )
            )
            if rr.get("error"):
                vs_data["error"] = (
                    rr["error"].get("message") or str(rr["error"])
                )
        except Exception:
            vs_data["body"] = (rs.text or "")[:300]
        results["verification_send"] = vs_data
        code = None
        has_inbox = inbox_configured(self.cfg)
        if has_inbox:
            _prog("otp_wait")
            code = get_verification_code(email, self.cfg)
            if not code:
                for _ in range(17):
                    time.sleep(4)
                    code = get_verification_code(email, self.cfg)
                    if code:
                        break
        email_verified = False
        if code:
            rc = self.verification_check(email, code)
            vc_data = {"status": rc.status_code}
            try:
                rc_j = rc.json()
                rr = rc_j.get("resource_response", {})
                vc_data["successful"] = rr.get("status") == "success"
                email_verified = vc_data["successful"]
                if rr.get("error"):
                    vc_data["error"] = (
                        rr["error"].get("message") or str(rr["error"])
                    )
            except Exception:
                vc_data["body"] = (rc.text or "")[:300]
            results["verification_check"] = vc_data
        else:
            reason = (
                "inbox not configured"
                if not has_inbox
                else (
                    "verification code not found in inbox "
                    "(wrong API format or email not from inbox service)"
                )
            )
            results["verification_check"] = {
                "skipped": True,
                "reason": reason,
            }
        if email_verified:
            self._save_account(email, password)
        return {"ok": email_verified, "results": results, "email_verified": email_verified}


def c(t, color):
    if not HAS_COLORAMA:
        return t
    from colorama import Fore, Style
    colors = {"green": Fore.GREEN, "red": Fore.RED, "yellow": Fore.YELLOW, "cyan": Fore.CYAN, "white": Fore.WHITE}
    return colors.get(color, "") + t + Style.RESET_ALL


def get_worker_config(cfg, worker_id):
    out = copy.deepcopy(cfg)
    proxy_list = cfg.get("proxy_list")
    if isinstance(proxy_list, list) and len(proxy_list) > 0:
        proxy = proxy_list[worker_id % len(proxy_list)]
        if proxy and not str(proxy).startswith("http"):
            proxy = "http://" + str(proxy)
        out["proxy"] = proxy or out.get("proxy", "")
    return out


def run_single_account(worker_id, cfg_base, stats, file_lock, print_lock, skip_checks, stop_event):
    cfg = get_worker_config(cfg_base, worker_id)
    use_inbox = inbox_configured(cfg)
    if not use_inbox:
        with stats["lock"]:
            stats["fail"] += 1
        return
    with print_lock:
        print(c(f"  [T{worker_id}] Requesting mail...", "cyan"))
    email = None
    for attempt in range(5):
        email = create_tempmail_email(cfg)
        if email:
            break
        time.sleep(0.5)
    if not email:
        with stats["lock"]:
            stats["fail"] += 1
        with print_lock:
            print(c(f"  [T{worker_id}] Mail request failed (inbox API).", "red"))
        return
    pre = email[:16] + ".." if len(email) > 16 else email
    with print_lock:
        print(c(f"  [{pre}] Mail created, registering...", "cyan"))
    password = random_password(cfg.get("password_length", 14))
    bot = PinterestBot(cfg, save_lock=file_lock)

    def progress_callback(stage, em=None):
        with print_lock:
            p = (em or email)[:16] + (".." if len(em or email) > 16 else "")
            if stage == "register_ok":
                print(c(f"  [{p}] Registered.", "cyan"))
            elif stage == "otp_wait":
                print(c(f"  [{p}] Waiting for OTP...", "yellow"))

    try:
        country = get_country_from_proxy(bot.session)
    except Exception:
        country = "US"
    locale = locale_for_country(country)
    gender = random.choice(("male", "female"))
    age = str(random.randint(18, 65))
    first_name = random_name()
    out = bot.run(
        email=email,
        password=password,
        first_name=first_name,
        age=age,
        country=country,
        gender=gender,
        locale=locale,
        skip_checks=skip_checks,
        progress_callback=progress_callback,
    )
    with stats["lock"]:
        if out.get("ok"):
            stats["success"] += 1
            stats["success_times"].append(time.time())
            with print_lock:
                print(c(f"  [{pre}] Success: {email}:{password}", "green"))
        else:
            stats["fail"] += 1
            with print_lock:
                print(c(f"  [{pre}] Failed.", "red"))


def title_updater_loop(stats, stop_event):
    while not stop_event.is_set():
        try:
            with stats["lock"]:
                s, f = stats["success"], stats["fail"]
                now = time.time()
                stats["success_times"] = [t for t in stats["success_times"] if now - t < 60]
                cpm = len(stats["success_times"])
            title = f"Success: {s} | Failed: {f} | CPM: {cpm}/min | Pinterest Account Maker"
            set_console_title(title)
        except Exception:
            pass
        stop_event.wait(1.0)


def worker_loop(worker_id, cfg_base, stats, file_lock, print_lock, skip_checks, stop_event):
    while not stop_event.is_set():
        try:
            run_single_account(worker_id, cfg_base, stats, file_lock, print_lock, skip_checks, stop_event)
        except Exception as e:
            with stats["lock"]:
                stats["fail"] += 1
            with print_lock:
                print(c(f"[X] {e}", "red"))


def main():
    cfg = load_config()

    if not inbox_configured(cfg):
        print('config.json: "inbox_api_base" and "inbox_password" (mail.gw) required.')
        return 1

    while True:
        try:
            raw = input("Thread count: ").strip()
            threads = int(raw) if raw else 20
            threads = max(1, min(500, threads))
            break
        except (ValueError, EOFError):
            print("Enter a number (e.g. 25)")
            continue
        except KeyboardInterrupt:
            os._exit(0)
    stats = {
        "success": 0,
        "fail": 0,
        "success_times": [],
        "lock": threading.Lock(),
    }
    file_lock = threading.Lock()
    print_lock = threading.Lock()
    stop_event = threading.Event()

    print(c("  Mail service: mail.gw | Stop: Ctrl+C\n", "cyan"))
    title_thread = threading.Thread(target=title_updater_loop, args=(stats, stop_event), daemon=True)
    title_thread.start()

    try:
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = [
                executor.submit(
                    worker_loop,
                    i,
                    cfg,
                    stats,
                    file_lock,
                    print_lock,
                    False,
                    stop_event,
                )
                for i in range(threads)
            ]
            for f in futures:
                f.result()
    except KeyboardInterrupt:
        stop_event.set()
        with stats["lock"]:
            s, f = stats["success"], stats["fail"]
        if HAS_COLORAMA:
            print(c(f"\nSuccess: {s} | Failed: {f}", "yellow"))
        else:
            print(f"\nSuccess: {s} | Failed: {f}")
        os._exit(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
