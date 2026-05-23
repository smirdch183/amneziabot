import base64
import hashlib
import hmac
import json
import os
import secrets
from html import escape
from datetime import datetime, timedelta

from aiohttp import web

from config import ADMIN_LOGIN, ADMIN_PASS, TOKEN
from storage import get_user_status, load_users, parse_subscription_end, save_users, summarize_users
from utils import backup_json, now

SESSION_COOKIE = "amnezia_admin"
SESSION_TTL = 60 * 60 * 12


def _secret():
    return hashlib.sha256(f"{TOKEN}:{ADMIN_PASS}".encode("utf-8")).digest()


def _sign(value):
    return hmac.new(_secret(), value.encode("utf-8"), hashlib.sha256).hexdigest()


def _make_session():
    payload = {
        "login": ADMIN_LOGIN,
        "exp": int((datetime.utcnow() + timedelta(seconds=SESSION_TTL)).timestamp()),
        "nonce": secrets.token_hex(12),
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    return f"{raw}.{_sign(raw)}"


def _read_session(request):
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie or "." not in cookie:
        return None

    raw, signature = cookie.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign(raw)):
        return None

    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None

    if payload.get("login") != ADMIN_LOGIN or payload.get("exp", 0) < int(datetime.utcnow().timestamp()):
        return None

    return payload


def _require_auth(request):
    return _read_session(request) is not None


def _json_error(message, status=400):
    return web.json_response({"ok": False, "error": message}, status=status)


def _public_user(uid, user):
    end = parse_subscription_end(user.get("subscription_end"))
    status = get_user_status(user)
    days_left = None
    if end:
        days_left = (end.date() - now().date()).days

    return {
        "id": uid,
        "first_name": user.get("first_name") or "Без имени",
        "username": user.get("username") or "",
        "subscription_text": user.get("subscription_text") or "",
        "subscription_end": user.get("subscription_end"),
        "status": status,
        "days_left": days_left,
        "notified_1day": bool(user.get("notified_1day")),
        "notified_0day": bool(user.get("notified_0day")),
    }


def _normalize_datetime(value):
    if not value:
        return None

    value = value.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(microsecond=0).isoformat()
        except ValueError:
            continue
    raise ValueError("Формат даты: YYYY-MM-DD HH:MM")


def _format_broadcast_message(text):
    return f"📢 <b>ОПОВЕЩЕНИЕ</b>\n{escape(text)}"


def _get_user_or_404(uid):
    users = load_users()
    user = users.get(uid)
    if not user:
        return users, None
    return users, user


@web.middleware
async def auth_middleware(request, handler):
    public_paths = {"/login"}
    if request.path in public_paths or request.path.startswith("/assets/"):
        return await handler(request)

    if request.path.startswith("/api/") and not _require_auth(request):
        return _json_error("Требуется вход", status=401)

    if request.path != "/" and not request.path.startswith("/api/"):
        return await handler(request)

    if not _require_auth(request):
        return web.Response(text=LOGIN_HTML, content_type="text/html")

    return await handler(request)


async def index(_request):
    return web.Response(text=APP_HTML, content_type="text/html")


async def login(request):
    data = await request.json()
    login_value = str(data.get("login", ""))
    password_value = str(data.get("password", ""))

    if not ADMIN_PASS:
        return _json_error("ADMIN_PASS не задан в .env", status=403)

    login_ok = hmac.compare_digest(login_value, ADMIN_LOGIN)
    pass_ok = hmac.compare_digest(password_value, ADMIN_PASS)
    if not login_ok or not pass_ok:
        return _json_error("Неверный логин или пароль", status=401)

    response = web.json_response({"ok": True})
    response.set_cookie(
        SESSION_COOKIE,
        _make_session(),
        max_age=SESSION_TTL,
        httponly=True,
        samesite="Strict",
        path="/",
    )
    return response


async def logout(_request):
    response = web.json_response({"ok": True})
    response.del_cookie(SESSION_COOKIE, path="/")
    return response


async def api_state(_request):
    users = load_users()
    items = [_public_user(uid, user) for uid, user in users.items()]
    items.sort(key=lambda item: (item["status"] != "active", item["first_name"].lower(), item["id"]))
    return web.json_response({
        "ok": True,
        "now": now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summarize_users(users),
        "users": items,
    })


async def api_update_user(request):
    uid = request.match_info["uid"]
    data = await request.json()
    users, user = _get_user_or_404(uid)
    if user is None:
        return _json_error("Пользователь не найден", status=404)

    if "first_name" in data:
        user["first_name"] = str(data.get("first_name") or "").strip() or "Без имени"
    if "username" in data:
        user["username"] = str(data.get("username") or "").strip().lstrip("@") or None
    if "subscription_text" in data:
        text = str(data.get("subscription_text") or "").strip()
        user["subscription_text"] = text or None
    if "subscription_end" in data:
        try:
            user["subscription_end"] = _normalize_datetime(str(data.get("subscription_end") or ""))
        except ValueError as exc:
            return _json_error(str(exc))
        user["notified_1day"] = False
        user["notified_0day"] = False

    save_users(users)
    return web.json_response({"ok": True, "user": _public_user(uid, user)})


async def api_add_days(request):
    uid = request.match_info["uid"]
    data = await request.json()
    try:
        days = int(data.get("days"))
    except (TypeError, ValueError):
        return _json_error("Количество дней должно быть числом")

    if days <= 0:
        return _json_error("Количество дней должно быть больше нуля")

    users, user = _get_user_or_404(uid)
    if user is None:
        return _json_error("Пользователь не найден", status=404)

    base = now()
    current = parse_subscription_end(user.get("subscription_end"))
    if current and current > base:
        base = current

    user["subscription_end"] = (base + timedelta(days=days)).replace(microsecond=0).isoformat()
    user["notified_1day"] = False
    user["notified_0day"] = False
    save_users(users)

    telegram_bot = request.app["telegram_bot"]
    try:
        await telegram_bot.send_message(uid, f"✅ +{days} дней добавлено")
    except Exception:
        pass

    return web.json_response({"ok": True, "user": _public_user(uid, user)})


async def api_clear_user(request):
    uid = request.match_info["uid"]
    users, user = _get_user_or_404(uid)
    if user is None:
        return _json_error("Пользователь не найден", status=404)

    user["subscription_text"] = None
    user["subscription_end"] = None
    user["notified_1day"] = False
    user["notified_0day"] = False
    save_users(users)

    telegram_bot = request.app["telegram_bot"]
    try:
        await telegram_bot.send_message(uid, "❌ Доступ закрыт")
    except Exception:
        pass

    return web.json_response({"ok": True, "user": _public_user(uid, user)})


async def api_delete_user(request):
    uid = request.match_info["uid"]
    users = load_users()
    if uid not in users:
        return _json_error("Пользователь не найден", status=404)

    del users[uid]
    save_users(users)
    return web.json_response({"ok": True})


async def api_broadcast(request):
    data = await request.json()
    text = str(data.get("text") or "").strip()
    if not text:
        return _json_error("Введите текст рассылки")

    telegram_bot = request.app["telegram_bot"]
    sent = 0
    failed = 0
    for uid in load_users():
        try:
            await telegram_bot.send_message(uid, _format_broadcast_message(text), parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1

    return web.json_response({"ok": True, "sent": sent, "failed": failed})


async def api_backup(_request):
    backup_path = backup_json("users.json")
    try:
        with open(backup_path, "rb") as f:
            body = f.read()
    finally:
        if os.path.exists(backup_path):
            os.remove(backup_path)

    return web.Response(
        body=body,
        headers={"Content-Disposition": f'attachment; filename="{os.path.basename(backup_path)}"'},
        content_type="application/json",
    )


def create_app(telegram_bot):
    app = web.Application(middlewares=[auth_middleware])
    app["telegram_bot"] = telegram_bot
    app.router.add_get("/", index)
    app.router.add_post("/login", login)
    app.router.add_post("/api/logout", logout)
    app.router.add_get("/api/state", api_state)
    app.router.add_patch("/api/users/{uid}", api_update_user)
    app.router.add_post("/api/users/{uid}/add-days", api_add_days)
    app.router.add_post("/api/users/{uid}/clear", api_clear_user)
    app.router.add_delete("/api/users/{uid}", api_delete_user)
    app.router.add_post("/api/broadcast", api_broadcast)
    app.router.add_get("/api/backup", api_backup)
    return app


async def start_web_admin(telegram_bot, host, port):
    app = create_app(telegram_bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"Web admin: http://{host}:{port}")
    return runner


LOGIN_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Amnezia Admin - вход</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: light-dark(#f6f7fb, #11131a);
      --panel: light-dark(#ffffff, #171a23);
      --text: light-dark(#172033, #f4f7fb);
      --muted: light-dark(#657085, #9aa6b8);
      --line: light-dark(#dfe4ee, #2a3040);
      --accent: #2f80ed;
      --accent-2: #12b886;
      --danger: #e5484d;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    body {
      min-block-size: 100dvh;
      margin: 0;
      display: grid;
      place-items: center;
      background: var(--bg);
      color: var(--text);
    }
    main {
      inline-size: min(92vw, 26rem);
      padding: 2rem;
      border: 1px solid var(--line);
      border-radius: 1.25rem;
      background: color-mix(in oklab, var(--panel) 92%, transparent);
      box-shadow: 0 1.5rem 4rem color-mix(in oklab, #000 18%, transparent);
      backdrop-filter: blur(18px);
      animation: enter .45s ease both;
    }
    h1 { margin: 0 0 .4rem; font-size: 1.8rem; letter-spacing: 0; }
    p { margin: 0 0 1.5rem; color: var(--muted); line-height: 1.5; }
    label { display: grid; gap: .45rem; margin-block: .9rem; color: var(--muted); font-size: .9rem; }
    input, button {
      font: inherit;
      min-block-size: 2.75rem;
      border-radius: .8rem;
      border: 1px solid var(--line);
    }
    input {
      padding-inline: .9rem;
      background: color-mix(in oklab, var(--panel) 88%, var(--bg));
      color: var(--text);
    }
    input:focus-visible, button:focus-visible { outline: 3px solid color-mix(in oklab, var(--accent) 45%, transparent); outline-offset: 2px; }
    button {
      inline-size: 100%;
      margin-block-start: .7rem;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: .5rem;
      border: 0;
      color: white;
      cursor: pointer;
      background: var(--accent);
      transition: transform .2s ease, filter .2s ease;
    }
    .icon { inline-size: 1rem; block-size: 1rem; flex: 0 0 auto; }
    button:hover { transform: translateY(-1px); filter: saturate(1.08); }
    .error { min-block-size: 1.3rem; color: var(--danger); font-size: .9rem; }
    @keyframes enter { from { opacity: 0; transform: translateY(1rem) scale(.98); } }
    @media (prefers-reduced-motion: reduce) { main, button { animation: none; transition: none; } }
  </style>
</head>
<body>
  <main>
    <h1>Amnezia Admin</h1>
    <form id="loginForm">
      <label>Логин<input name="login" autocomplete="username" required></label>
      <label>Пароль<input name="password" type="password" autocomplete="current-password" required></label>
      <div class="error" id="error"></div>
      <button type="submit">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><path d="m10 17 5-5-5-5"/><path d="M15 12H3"/></svg>
        Войти
      </button>
    </form>
  </main>
  <script>
    document.querySelector('#loginForm').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const response = await fetch('/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(Object.fromEntries(form))
      });
      const data = await response.json();
      if (data.ok) location.reload();
      document.querySelector('#error').textContent = data.error || '';
    });
  </script>
</body>
</html>"""


APP_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Amnezia Admin</title>
  <style>
    @layer reset, base, components;
    @layer reset {
      body, h1, h2, p { margin: 0; }
      button, input, textarea, select { font: inherit; }
      button { cursor: pointer; }
    }
    @layer base {
      :root {
        color-scheme: light;
        --bg: #f7f8fb;
        --surface: #ffffff;
        --surface-soft: #eef3f8;
        --text: #111827;
        --muted: #657085;
        --line: #dce3ee;
        --accent: #2f80ed;
        --accent-2: #12b886;
        --warn: #f08c00;
        --danger: #e03131;
        --shadow: 0 1rem 2.5rem rgb(21 31 52 / .11);
        --radius: .9rem;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      :root[data-theme="dark"] {
        color-scheme: dark;
        --bg: #10131a;
        --surface: #171b24;
        --surface-soft: #202636;
        --text: #f3f6fb;
        --muted: #99a6ba;
        --line: #2a3243;
        --shadow: 0 1rem 2.5rem rgb(0 0 0 / .32);
      }
      body {
        min-block-size: 100dvh;
        background: var(--bg);
        color: var(--text);
      }
      .app {
        inline-size: min(1440px, calc(100% - 2rem));
        margin-inline: auto;
        padding-block: 1rem 2rem;
      }
      .topbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        min-block-size: 4rem;
      }
      .brand { display: grid; gap: .15rem; }
      .brand h1 { font-size: 1.35rem; letter-spacing: 0; }
      .brand p { color: var(--muted); font-size: .9rem; }
      .toolbar { display: flex; flex-wrap: wrap; gap: .55rem; justify-content: end; }
      button, .button {
        min-block-size: 2.5rem;
        min-inline-size: 2.5rem;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: .45rem;
        border: 1px solid var(--line);
        border-radius: .75rem;
        padding-inline: .85rem;
        color: var(--text);
        background: color-mix(in oklab, var(--surface) 92%, var(--surface-soft));
        transition: transform .18s ease, border-color .18s ease, background .18s ease;
      }
      button:hover:not(:disabled), .button:hover { transform: translateY(-1px); border-color: color-mix(in oklab, var(--accent) 45%, var(--line)); }
      button:disabled { opacity: .55; cursor: not-allowed; }
      button:focus-visible, input:focus-visible, textarea:focus-visible, select:focus-visible {
        outline: 3px solid color-mix(in oklab, var(--accent) 38%, transparent);
        outline-offset: 2px;
      }
      .primary { border: 0; color: white; background: var(--accent); }
      .danger { color: #fff; border: 0; background: var(--danger); }
      .icon { inline-size: 1rem; block-size: 1rem; flex: 0 0 auto; }
      .icon-only { padding-inline: 0; }
      input, textarea, select {
        inline-size: 100%;
        box-sizing: border-box;
        border: 1px solid var(--line);
        border-radius: .75rem;
        padding: .75rem .85rem;
        color: var(--text);
        background: var(--surface);
      }
      textarea { min-block-size: 7rem; resize: vertical; }
      .layout { display: grid; grid-template-columns: 18rem minmax(0, 1fr); gap: 1rem; align-items: start; }
      .panel {
        border: 1px solid var(--line);
        border-radius: var(--radius);
        background: color-mix(in oklab, var(--surface) 94%, transparent);
        box-shadow: var(--shadow);
        backdrop-filter: blur(18px);
      }
      .side { position: sticky; top: 1rem; padding: 1rem; display: grid; gap: 1rem; }
      .stats { display: grid; grid-template-columns: 1fr 1fr; gap: .65rem; }
      .stat {
        padding: .85rem;
        border-radius: .8rem;
        background: var(--surface-soft);
      }
      .stat b { display: block; font-size: 1.3rem; }
      .stat span { color: var(--muted); font-size: .83rem; }
      .filters { display: grid; gap: .6rem; }
      .filters h2 {
        font-size: .82rem;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: .04em;
      }
      .segment { display: grid; gap: .45rem; }
      .segment button {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: .75rem;
        text-align: start;
      }
      .filter-label {
        display: inline-flex;
        align-items: center;
        gap: .45rem;
        min-inline-size: 0;
      }
      .segment button .filter-count {
        min-inline-size: 1.7rem;
        padding: .16rem .45rem;
        border-radius: 99rem;
        text-align: center;
        color: var(--muted);
        background: var(--surface-soft);
      }
      .segment button[aria-pressed="true"] { color: white; border-color: transparent; background: var(--accent); }
      .segment button[aria-pressed="true"] .filter-count {
        color: var(--accent);
        background: white;
      }
      .content { display: grid; gap: 1rem; }
      .list-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 1rem;
        padding: 1rem;
      }
      .list-tools {
        display: flex;
        flex: 1 1 22rem;
        justify-content: end;
        gap: .6rem;
      }
      .list-tools input {
        flex: 1 1 18rem;
        max-inline-size: 28rem;
      }
      .users { display: grid; gap: .65rem; padding: 0 1rem 1rem; }
      .user-card {
        display: grid;
        grid-template-columns: minmax(0, 1.4fr) minmax(10rem, .8fr) auto;
        gap: 1rem;
        align-items: center;
        padding: 1rem;
        border: 1px solid var(--line);
        border-radius: .85rem;
        background: var(--surface);
        content-visibility: auto;
        contain-intrinsic-block-size: auto 6rem;
        animation: cardIn .28s ease both;
      }
      .identity { min-inline-size: 0; }
      .identity b { display: block; overflow-wrap: anywhere; }
      .identity span, .subline { color: var(--muted); font-size: .9rem; overflow-wrap: anywhere; }
      .status {
        inline-size: max-content;
        max-inline-size: 100%;
        border-radius: 99rem;
        padding: .35rem .65rem;
        font-size: .82rem;
        background: var(--surface-soft);
      }
      .status.active { color: #087f5b; background: color-mix(in oklab, var(--accent-2) 18%, transparent); }
      .status.expired, .status.no_date { color: #b46900; background: color-mix(in oklab, var(--warn) 18%, transparent); }
      .status.empty, .status.no_access { color: #c92a2a; background: color-mix(in oklab, var(--danger) 15%, transparent); }
      .actions { display: flex; flex-wrap: wrap; justify-content: end; gap: .45rem; }
      .empty-state { padding: 3rem 1rem; text-align: center; color: var(--muted); }
      dialog {
        inline-size: min(92vw, 42rem);
        border: 1px solid var(--line);
        border-radius: 1rem;
        padding: 0;
        color: var(--text);
        background: var(--surface);
        box-shadow: var(--shadow);
      }
      dialog::backdrop { background: rgb(0 0 0 / .45); backdrop-filter: blur(4px); }
      dialog[open] {
        animation: modalIn .22s ease both;
      }
      .modal-body { padding: 1rem; display: grid; gap: 1rem; }
      .modal-head { display: flex; justify-content: space-between; gap: 1rem; align-items: start; }
      .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .85rem; }
      .form-grid label, .wide { display: grid; gap: .4rem; color: var(--muted); font-size: .88rem; }
      .wide { grid-column: 1 / -1; }
      .quick-days { display: flex; flex-wrap: wrap; gap: .45rem; }
      .toast {
        position: fixed;
        inset-block-end: 1rem;
        inset-inline: 1rem;
        margin-inline: auto;
        inline-size: max-content;
        max-inline-size: calc(100% - 2rem);
        padding: .8rem 1rem;
        border-radius: .8rem;
        background: var(--text);
        color: var(--bg);
        box-shadow: var(--shadow);
        opacity: 0;
        transform: translateY(.8rem);
        pointer-events: none;
        transition: opacity .2s ease, transform .2s ease;
      }
      .toast.show { opacity: 1; transform: translateY(0); }
      @keyframes cardIn { from { opacity: 0; transform: translateY(.5rem); } }
      @keyframes modalIn { from { opacity: 0; transform: translateY(.75rem) scale(.98); } }
      @media (max-width: 900px) {
        .layout { grid-template-columns: 1fr; }
        .side { position: static; }
        .user-card { grid-template-columns: 1fr; }
        .actions { justify-content: start; }
      }
      @media (max-width: 620px) {
        .app { inline-size: min(100% - 1rem, 1440px); }
        .topbar, .list-head { align-items: stretch; flex-direction: column; }
        .list-tools { justify-content: stretch; }
        .list-tools input { max-inline-size: none; }
        .toolbar { justify-content: stretch; }
        .toolbar button { flex: 1; }
        .form-grid { grid-template-columns: 1fr; }
      }
      @media (prefers-reduced-motion: reduce) {
        button, .user-card, dialog[open], .toast { animation: none; transition: none; }
      }
    }
  </style>
</head>
<body>
  <svg aria-hidden="true" width="0" height="0" style="position:absolute">
    <symbol id="i-theme" viewBox="0 0 24 24"><path d="M12 3a9 9 0 1 0 9 9 7 7 0 0 1-9-9Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></symbol>
    <symbol id="i-download" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M7 10l5 5 5-5M12 15V3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></symbol>
    <symbol id="i-send" viewBox="0 0 24 24"><path d="m22 2-7 20-4-9-9-4Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M22 2 11 13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></symbol>
    <symbol id="i-logout" viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="m16 17 5-5-5-5M21 12H9" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></symbol>
    <symbol id="i-refresh" viewBox="0 0 24 24"><path d="M21 12a9 9 0 0 1-15 6.7L3 16M3 12a9 9 0 0 1 15-6.7L21 8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 21v-5h5M21 3v5h-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></symbol>
    <symbol id="i-filter" viewBox="0 0 24 24"><path d="M4 6h16M7 12h10M10 18h4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></symbol>
    <symbol id="i-user" viewBox="0 0 24 24"><path d="M20 21a8 8 0 0 0-16 0" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="7" r="4" fill="none" stroke="currentColor" stroke-width="2"/></symbol>
    <symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></symbol>
    <symbol id="i-x" viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></symbol>
    <symbol id="i-save" viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M17 21v-8H7v8M7 3v5h8" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></symbol>
    <symbol id="i-trash" viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></symbol>
    <symbol id="i-check" viewBox="0 0 24 24"><path d="m20 6-11 11-5-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></symbol>
  </svg>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <h1>Amnezia Admin</h1>
        <p id="clock">Загрузка...</p>
      </div>
      <div class="toolbar">
        <button id="themeBtn" class="icon-only" type="button" title="Переключить тему"><svg class="icon"><use href="#i-theme"></use></svg></button>
        <button id="backupBtn" type="button"><svg class="icon"><use href="#i-download"></use></svg>Бэкап</button>
        <button id="broadcastBtn" type="button" class="primary"><svg class="icon"><use href="#i-send"></use></svg>Рассылка</button>
        <button id="logoutBtn" type="button"><svg class="icon"><use href="#i-logout"></use></svg>Выйти</button>
      </div>
    </header>

    <main class="layout">
      <aside class="panel side">
        <section class="stats" id="stats"></section>
        <section class="filters">
          <h2>Фильтры</h2>
          <div class="segment" id="filters"></div>
        </section>
      </aside>

      <section class="panel content">
        <div class="list-head">
          <div>
            <h2>Пользователи</h2>
            <p class="subline" id="resultCount"></p>
          </div>
          <div class="list-tools">
            <input id="search" type="search" placeholder="Поиск по имени, username или ID" autocomplete="off">
            <button id="refreshBtn" type="button"><svg class="icon"><use href="#i-refresh"></use></svg>Обновить</button>
          </div>
        </div>
        <div class="users" id="users"></div>
      </section>
    </main>
  </div>

  <dialog id="userDialog">
    <form method="dialog" class="modal-body" id="userForm">
      <div class="modal-head">
        <div>
          <h2 id="modalTitle">Пользователь</h2>
          <p class="subline" id="modalSubtitle"></p>
        </div>
        <button type="button" data-close><svg class="icon"><use href="#i-x"></use></svg>Закрыть</button>
      </div>
      <div class="form-grid">
        <label>Имя<input name="first_name"></label>
        <label>Username<input name="username"></label>
        <label class="wide">Доступ<textarea name="subscription_text" placeholder="Текст подключения Amnezia"></textarea></label>
        <label>Дата окончания<input name="subscription_end" type="datetime-local"></label>
        <label>Быстро добавить дни
          <div class="quick-days">
            <button type="button" data-days="1"><svg class="icon"><use href="#i-plus"></use></svg>1</button>
            <button type="button" data-days="7"><svg class="icon"><use href="#i-plus"></use></svg>7</button>
            <button type="button" data-days="30"><svg class="icon"><use href="#i-plus"></use></svg>30</button>
          </div>
        </label>
      </div>
      <div class="toolbar">
        <button type="submit" class="primary"><svg class="icon"><use href="#i-save"></use></svg>Сохранить</button>
        <button type="button" id="clearBtn"><svg class="icon"><use href="#i-x"></use></svg>Очистить доступ</button>
        <button type="button" id="deleteBtn" class="danger"><svg class="icon"><use href="#i-trash"></use></svg>Удалить</button>
      </div>
    </form>
  </dialog>

  <dialog id="broadcastDialog">
    <form method="dialog" class="modal-body" id="broadcastForm">
      <div class="modal-head">
        <div>
          <h2>Рассылка</h2>
          <p class="subline">Сообщение уйдет всем пользователям из базы.</p>
        </div>
        <button type="button" data-close><svg class="icon"><use href="#i-x"></use></svg>Закрыть</button>
      </div>
      <label class="wide">Текст<textarea name="text" required></textarea></label>
      <button type="submit" class="primary"><svg class="icon"><use href="#i-send"></use></svg>Отправить</button>
    </form>
  </dialog>

  <dialog id="broadcastConfirmDialog">
    <form method="dialog" class="modal-body" id="broadcastConfirmForm">
      <div class="modal-head">
        <div>
          <h2>Подтвердить рассылку</h2>
          <p class="subline" id="broadcastConfirmText"></p>
        </div>
        <button type="button" data-close><svg class="icon"><use href="#i-x"></use></svg>Закрыть</button>
      </div>
      <div class="toolbar">
        <button type="button" data-close>Отмена</button>
        <button type="submit" class="primary"><svg class="icon"><use href="#i-send"></use></svg>Отправить</button>
      </div>
    </form>
  </dialog>

  <dialog id="broadcastSuccessDialog">
    <form method="dialog" class="modal-body">
      <div class="modal-head">
        <div>
          <h2>Рассылка отправлена</h2>
          <p class="subline" id="broadcastSuccessText"></p>
        </div>
        <button type="button" data-close><svg class="icon"><use href="#i-x"></use></svg>Закрыть</button>
      </div>
      <button type="submit" class="primary"><svg class="icon"><use href="#i-check"></use></svg>Готово</button>
    </form>
  </dialog>

  <div class="toast" id="toast"></div>

  <script>
    const state = { users: [], summary: {}, filter: 'all', activeUser: null };
    const statusText = {
      all: 'Все',
      active: 'Активные',
      expired: 'Истекли',
      empty: 'Пустые',
      no_access: 'Нет доступа',
      no_date: 'Без даты'
    };
    const statusLabel = {
      active: 'Активна',
      expired: 'Истекла',
      empty: 'Пусто',
      no_access: 'Нет доступа',
      no_date: 'Без даты'
    };

    const $ = (selector) => document.querySelector(selector);
    const usersEl = $('#users');
    const toastEl = $('#toast');
    const userDialog = $('#userDialog');
    const broadcastDialog = $('#broadcastDialog');
    const broadcastConfirmDialog = $('#broadcastConfirmDialog');
    const broadcastSuccessDialog = $('#broadcastSuccessDialog');
    let pendingBroadcastText = '';

    function icon(name) {
      return `<svg class="icon" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
    }

    function setTheme(theme) {
      document.documentElement.dataset.theme = theme;
      localStorage.setItem('theme', theme);
    }

    function initTheme() {
      const saved = localStorage.getItem('theme');
      if (saved) return setTheme(saved);
      setTheme(matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    }

    function toast(message) {
      toastEl.textContent = message;
      toastEl.classList.add('show');
      clearTimeout(window.toastTimer);
      window.toastTimer = setTimeout(() => toastEl.classList.remove('show'), 2600);
    }

    async function api(path, options = {}) {
      const response = await fetch(path, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          ...(options.headers || {})
        }
      });
      if (response.status === 401) location.reload();
      const data = await response.json();
      if (!data.ok) throw new Error(data.error || 'Ошибка запроса');
      return data;
    }

    async function loadState() {
      const data = await api('/api/state');
      state.users = data.users;
      state.summary = data.summary;
      $('#clock').textContent = `Москва: ${data.now}`;
      render();
    }

    function renderStats() {
      const stats = [
        ['total', 'Всего'],
        ['active', 'Активные'],
        ['expired', 'Истекли'],
        ['empty', 'Пустые']
      ];
      $('#stats').innerHTML = stats.map(([key, label]) => `
        <div class="stat"><b>${state.summary[key] ?? 0}</b><span>${label}</span></div>
      `).join('');
    }

    function renderFilters() {
      const filters = ['all', 'active', 'expired', 'empty', 'no_access', 'no_date'];
      const counts = {
        all: state.summary.total ?? state.users.length,
        active: state.summary.active ?? 0,
        expired: state.summary.expired ?? 0,
        empty: state.summary.empty ?? 0,
        no_access: state.summary.no_access ?? 0,
        no_date: state.summary.no_date ?? 0
      };
      $('#filters').innerHTML = filters.map((filter) => `
        <button type="button" data-filter="${filter}" aria-pressed="${state.filter === filter}">
          <span class="filter-label">${icon('filter')}${statusText[filter]}</span> <span class="filter-count">${counts[filter]}</span>
        </button>
      `).join('');
    }

    function filteredUsers() {
      const query = $('#search').value.trim().toLowerCase();
      return state.users.filter((user) => {
        const statusMatch = state.filter === 'all' || user.status === state.filter;
        const text = `${user.id} ${user.first_name} ${user.username}`.toLowerCase();
        return statusMatch && (!query || text.includes(query));
      });
    }

    function renderUsers() {
      const items = filteredUsers();
      $('#resultCount').textContent = `${items.length} из ${state.users.length}`;
      if (!items.length) {
        usersEl.innerHTML = '<div class="empty-state">Ничего не найдено</div>';
        return;
      }
      usersEl.innerHTML = items.map((user) => `
        <article class="user-card">
          <div class="identity">
            <b>${escapeHtml(user.first_name)}</b>
            <span>ID ${user.id}${user.username ? ` · @${escapeHtml(user.username)}` : ''}</span>
          </div>
          <div>
            <div class="status ${user.status}">${statusLabel[user.status] || user.status}</div>
            <p class="subline">${subscriptionLine(user)}</p>
          </div>
          <div class="actions">
            <button type="button" data-open="${user.id}">${icon('user')}Открыть</button>
            <button type="button" data-add="${user.id}" data-days="7">${icon('plus')}7</button>
            <button type="button" data-add="${user.id}" data-days="30">${icon('plus')}30</button>
          </div>
        </article>
      `).join('');
    }

    function subscriptionLine(user) {
      if (!user.subscription_end) return 'Дата окончания не задана';
      const days = user.days_left;
      const suffix = days === null ? '' : ` · ${days} дн.`;
      return `${user.subscription_end.replace('T', ' ')}${suffix}`;
    }

    function render() {
      renderStats();
      renderFilters();
      renderUsers();
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[char]));
    }

    function datetimeLocal(value) {
      if (!value) return '';
      return value.slice(0, 16);
    }

    function openUser(uid) {
      const user = state.users.find((item) => item.id === uid);
      if (!user) return;
      state.activeUser = user;
      $('#modalTitle').textContent = user.first_name;
      $('#modalSubtitle').textContent = `ID ${user.id}${user.username ? ` · @${user.username}` : ''}`;
      const form = $('#userForm');
      form.first_name.value = user.first_name;
      form.username.value = user.username;
      form.subscription_text.value = user.subscription_text;
      form.subscription_end.value = datetimeLocal(user.subscription_end);
      userDialog.showModal();
    }

    async function addDays(uid, days) {
      await api(`/api/users/${uid}/add-days`, { method: 'POST', body: JSON.stringify({ days }) });
      toast(`Добавлено ${days} дней`);
      await loadState();
      if (state.activeUser?.id === uid) openUser(uid);
    }

    document.addEventListener('click', async (event) => {
      const close = event.target.closest('[data-close]');
      if (close) close.closest('dialog').close();

      const filter = event.target.closest('[data-filter]');
      if (filter) {
        state.filter = filter.dataset.filter;
        render();
      }

      const open = event.target.closest('[data-open]');
      if (open) openUser(open.dataset.open);

      const add = event.target.closest('[data-add], [data-days]');
      if (add && (add.dataset.add || state.activeUser)) {
        const uid = add.dataset.add || state.activeUser.id;
        await addDays(uid, Number(add.dataset.days));
      }
    });

    $('#search').addEventListener('input', renderUsers);
    $('#refreshBtn').addEventListener('click', loadState);
    $('#themeBtn').addEventListener('click', () => {
      const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      setTheme(next);
    });
    $('#logoutBtn').addEventListener('click', async () => {
      await api('/api/logout', { method: 'POST', body: '{}' });
      location.reload();
    });
    $('#backupBtn').addEventListener('click', () => {
      location.href = '/api/backup';
    });
    $('#broadcastBtn').addEventListener('click', () => broadcastDialog.showModal());

    $('#userForm').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      await api(`/api/users/${state.activeUser.id}`, {
        method: 'PATCH',
        body: JSON.stringify(Object.fromEntries(form))
      });
      userDialog.close();
      toast('Пользователь сохранен');
      await loadState();
    });

    $('#clearBtn').addEventListener('click', async () => {
      if (!state.activeUser) return;
      await api(`/api/users/${state.activeUser.id}/clear`, { method: 'POST', body: '{}' });
      userDialog.close();
      toast('Доступ очищен');
      await loadState();
    });

    $('#deleteBtn').addEventListener('click', async () => {
      if (!state.activeUser || !confirm('Удалить пользователя из базы?')) return;
      await api(`/api/users/${state.activeUser.id}`, { method: 'DELETE' });
      userDialog.close();
      toast('Пользователь удален');
      await loadState();
    });

    $('#broadcastForm').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      pendingBroadcastText = String(form.get('text') || '').trim();
      if (!pendingBroadcastText) return;
      $('#broadcastConfirmText').textContent = `Отправить сообщение всем пользователям (${state.summary.total ?? state.users.length})?`;
      broadcastDialog.close();
      broadcastConfirmDialog.showModal();
    });

    $('#broadcastConfirmForm').addEventListener('submit', async (event) => {
      event.preventDefault();
      const submitButton = event.submitter;
      submitButton.disabled = true;
      try {
        const result = await api('/api/broadcast', {
          method: 'POST',
          body: JSON.stringify({ text: pendingBroadcastText })
        });
        broadcastConfirmDialog.close();
        $('#broadcastForm').reset();
        $('#broadcastSuccessText').textContent = `Успешно отправлено: ${result.sent}. Ошибок: ${result.failed}.`;
        broadcastSuccessDialog.showModal();
        toast('Рассылка отправлена');
      } catch (error) {
        toast(error.message);
      } finally {
        submitButton.disabled = false;
      }
    });

    initTheme();
    loadState().catch((error) => toast(error.message));
  </script>
</body>
</html>"""
