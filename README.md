# Pinterest Account Maker

[![Pinterest Account Maker Demo](https://img.youtube.com/vi/hTzrKVIIgXk/maxresdefault.jpg)](https://www.youtube.com/watch?v=hTzrKVIIgXk)

Multi-threaded Pinterest account creator. Creates **email-verified** accounts using temporary mail (mail.gw), saves credentials and session cookies.

## Features

- **Multi-threaded** — Run many accounts in parallel (1–500 threads). Thread count is asked at startup.
- **Email-verified only** — Uses mail.gw for temp email, completes Pinterest verification, and only saves accounts that pass OTP.
- **Auto-save** — Successful accounts appended to `accounts.txt` as `email:password`. Session cookies saved under `cookies/` (Netscape format).
- **Proxy support** — All requests (Pinterest + mail.gw) go through your proxy. Optional `proxy_list` in config for per-thread proxies.
- **Live stats** — Console shows progress (requesting mail, registering, waiting for OTP, success/fail). On Windows, window title shows total success/fail and **CPM** (accounts per minute).
- **Clean exit** — Press **Ctrl+C** to stop; you get a short summary and the process exits immediately.

## Requirements

- Python 3.8+
- `config.json` with mail.gw and (optionally) proxy settings

## Setup

1. Clone the repo and install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy and edit config:

   - Create `config.json` in the project root (see **Config** below).
   - Set `inbox_api_base` and `inbox_password` for [mail.gw](https://api.mail.gw).
   - Add `proxy` (or `proxy_list`) if you use a proxy.

3. Run:

   ```bash
   python main.py
   ```

   When prompted, enter thread count (e.g. `20`) or leave empty for default 20.

## Config

`config.json` in the project root:

| Key               | Description |
|-------------------|-------------|
| `inbox_api_base`  | mail.gw API base URL, e.g. `https://api.mail.gw`. |
| `inbox_password`  | Password used when creating temp mail accounts on mail.gw. |
| `proxy`           | Optional. HTTP/HTTPS proxy URL (e.g. `http://user:pass@host:port`). |
| `proxy_list`      | Optional. Array of proxy URLs; threads use them in round-robin. |
| `password_length` | Length of generated account passwords (default 14). |
| `impersonate`     | Optional. Browser fingerprint (e.g. `chrome120`). |

Example (no proxy):

```json
{
  "inbox_api_base": "https://api.mail.gw",
  "inbox_password": "YourMailGwPassword",
  "password_length": 14
}
```

## Output

- **accounts.txt** — One line per successful account: `email:password`.
- **cookies/** — One Netscape-format cookie file per account, named from the email (e.g. `user_at_domain_com.txt`).

## Disclaimer

This tool is for educational purposes. Automated account creation may violate Pinterest's Terms of Service. Use at your own risk.
