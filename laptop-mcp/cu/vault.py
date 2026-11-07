"""The agent's password vault: its own Vaultwarden account, through the Bitwarden CLI.

The agent browser belongs to a throwaway identity (its own Gmail and its own vault account,
owner 2026-10-16). Agents create site accounts for that identity; the password manager makes
every password and keeps it, and the MCP tools type it into the page, so no password ever passes
through a model, a run record or deskd's log.

Configuration lives outside the repo, in ~/.config/computer-use/identity.env (mode 600):
BW_SERVER, BW_EMAIL, BW_PASSWORD (the vault account) and AGENT_EMAIL, AGENT_NAME (who signs up).
The CLI keeps its state in ~/.config/computer-use/bw, apart from any other `bw` login on the host.
"""
import base64
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import urllib.parse

CONFIG = pathlib.Path(os.environ.get("CU_IDENTITY", pathlib.Path.home() / ".config/computer-use/identity.env"))
APPDATA = pathlib.Path(os.environ.get("CU_BW_DIR") or CONFIG.parent / "bw")  # the CLI's state: writable
# Second-level labels that are part of a public suffix (example.co.uk): enough for the sites we meet.
SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu", "ne", "or"}
STATUSES = ("pending", "active", "failed")


class VaultError(RuntimeError):
    pass


def config():
    if not CONFIG.exists():
        return {}
    out = {}
    for line in CONFIG.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def base_domain(url_or_host):
    """www.example.co.uk, https://accounts.example.com/x -> example.co.uk, example.com."""
    host = urllib.parse.urlparse(url_or_host).hostname if "//" in url_or_host else url_or_host
    labels = (host or "").lower().rstrip(".").split(".")
    n = 3 if len(labels) > 2 and labels[-2] in SECOND_LEVEL and len(labels[-1]) == 2 else 2
    return ".".join(labels[-n:])


def field(item, name):
    return next((f["value"] for f in item.get("fields") or [] if f["name"] == name), None)


def summary(item):
    """An item as the agent may see it: never the password."""
    login = item.get("login") or {}
    return {"id": item["id"], "site": item["name"], "username": login.get("username"),
            "urls": [u["uri"] for u in login.get("uris") or []], "status": field(item, "status") or "active",
            "protected": is_protected(item), "notes": (item.get("notes") or "").splitlines()[-3:]}


def is_protected(item):
    """The identity's own Google account: never re-passworded or edited by an agent."""
    login = item.get("login") or {}
    email = config().get("AGENT_EMAIL", "").lower()
    return bool(email) and (login.get("username") or "").lower() == email and \
        any(base_domain(u["uri"]) == "google.com" for u in login.get("uris") or [])


class Vault:
    def __init__(self):
        self.cfg = config()
        self.session = None
        if not self.cfg.get("BW_PASSWORD"):
            raise VaultError(f"no agent vault configured ({CONFIG})")
        if not shutil.which("bw"):
            raise VaultError("the Bitwarden CLI (bw) is not installed on this host")

    def bw(self, *args, check=True):
        env = {**os.environ, "BITWARDENCLI_APPDATA_DIR": str(APPDATA), "BW_NOINTERACTION": "true"}
        env.pop("BW_SESSION", None)
        if args[0] in ("login", "unlock"):
            env["BW_PASSWORD"] = self.cfg["BW_PASSWORD"]
        if self.session:
            env["BW_SESSION"] = self.session
        r = subprocess.run(["bw", "--nointeraction", *args], capture_output=True, text=True, env=env, timeout=60)
        if check and r.returncode:
            raise VaultError(f"bw {args[0]}: {(r.stderr or r.stdout).strip()[:300]}")
        return r.stdout

    def unlock(self):
        if self.session:
            return
        APPDATA.mkdir(parents=True, exist_ok=True, mode=0o700)
        status = json.loads(self.bw("status")).get("status")
        if status == "unauthenticated":
            self.bw("config", "server", self.cfg["BW_SERVER"], check=False)
            self.session = self.bw("login", self.cfg["BW_EMAIL"], "--passwordenv", "BW_PASSWORD", "--raw").strip()
        else:
            self.session = self.bw("unlock", "--passwordenv", "BW_PASSWORD", "--raw").strip()
        self.bw("sync")

    def items(self, site=None):
        self.unlock()
        self.bw("sync")
        items = [i for i in json.loads(self.bw("list", "items")) if i.get("type") == 1]
        if site:
            want = base_domain(site)
            items = [i for i in items if base_domain(i["name"]) == want or any(
                base_domain(u["uri"]) == want for u in (i.get("login") or {}).get("uris") or [])]
        return items

    def get(self, item_id):
        self.unlock()
        return json.loads(self.bw("get", "item", item_id))

    def generate(self, length=20, uppercase=True, lowercase=True, numbers=True, special=True, append=""):
        flags = "".join(f for f, on in (("u", uppercase), ("l", lowercase), ("n", numbers), ("s", special)) if on)
        if not flags:
            raise VaultError("a password needs at least one kind of character")
        length = max(5, min(int(length), 128))
        pw = self.bw("generate", f"-{flags}", "--length", str(length - len(append))).strip() + append
        if not pw or len(pw) != length:
            raise VaultError("the generator returned an unexpected password")
        return pw

    def save(self, item):
        payload = base64.b64encode(json.dumps(item).encode()).decode()
        if item.get("id"):
            return json.loads(self.bw("edit", "item", item["id"], payload))
        return json.loads(self.bw("create", "item", payload))

    def create(self, site, url, username, password, by, purpose):
        self.unlock()
        stamp = datetime.date.today().isoformat()
        item = {"organizationId": None, "collectionIds": None, "folderId": None, "type": 1, "name": site,
                "notes": f"{stamp} created by {by}" + (f" for: {purpose}" if purpose else ""), "favorite": False,
                "fields": [{"name": "status", "value": "pending", "type": 0, "linkedId": None},
                           {"name": "created_by", "value": by, "type": 0, "linkedId": None}],
                "login": {"uris": [{"match": None, "uri": url}], "username": username, "password": password,
                          "totp": None},
                "secureNote": None, "card": None, "identity": None, "reprompt": 0}
        return self.save(item)

    def set_password(self, item, password):
        item["login"]["password"] = password
        return self.save(item)

    def note(self, item, status=None, text=""):
        if status:
            if status not in STATUSES:
                raise VaultError(f"status must be one of {', '.join(STATUSES)}")
            fields = [f for f in item.get("fields") or [] if f["name"] != "status"]
            item["fields"] = [{"name": "status", "value": status, "type": 0, "linkedId": None}, *fields]
        line = re.sub(r"\s+", " ", f"{datetime.date.today().isoformat()} {status or 'note'}: {text}").strip()
        item["notes"] = ((item.get("notes") or "") + "\n" + line).strip()
        return self.save(item)
