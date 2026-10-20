"""Client Dropbox minimale (OAuth2 PKCE no-redirect, refresh token, upload/download).

Nessuna dipendenza dall'SDK ufficiale: solo ``requests`` (gia' presente nel
runtime). I token sono salvati in ``data/state/dropbox.json`` con permessi
``0600`` su POSIX e non vengono mai scritti nei log.

Flusso OAuth PKCE senza redirect (Dropbox "No redirect URI"):
1. ``authorize()`` genera un ``code_verifier`` casuale e restituisce l'URL di
   autorizzazione con ``code_challenge`` S256 e ``token_access_type=offline``.
2. L'utente apre l'URL, autorizza l'app e incolla il codice mostrato da Dropbox.
3. ``complete(code)`` scambia il codice con access/refresh token e legge
   l'account collegato (``users/get_current_account``).

Gli errori sono esposti come :class:`CloudError` con un codice del contratto API
(``docs/API-CONTRACT.md``); le rotte li convertono in ``ApiError``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import stat
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests

LOGGER = logging.getLogger("rvc.cloud")

AUTHORIZE_URL = "https://www.dropbox.com/oauth2/authorize"
TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
RPC_BASE = "https://api.dropboxapi.com/2/"
CONTENT_BASE = "https://content.dropboxapi.com/2/"

DEFAULT_REMOTE_PATH = "/NLTools/RVC/config.json"
DEFAULT_TIMEOUT_S = 15.0
MAX_RETRIES = 2
RETRY_STATUSES = (429, 500, 502, 503, 504)
PENDING_TTL_S = 600.0
ACCESS_TOKEN_SKEW_S = 60.0

INVALID_CLIENT_MESSAGE = (
    "App Key rifiutata da Dropbox: crea una 'Scoped App' su "
    "https://www.dropbox.com/developers/apps, abilita i permessi "
    "account_info.read, files.content.read e files.content.write, poi incolla "
    "la App Key nella sezione Cloud."
)
INVALID_CODE_MESSAGE = (
    "Codice Dropbox non valido o scaduto: premi 'Autorizza', riapri il link e "
    "incolla il nuovo codice."
)
NOT_CONNECTED_MESSAGE = (
    "Dropbox non connesso: incolla la App Key e completa l'autorizzazione."
)


class CloudError(Exception):
    """Errore cloud con codice del contratto API e stato HTTP suggerito."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 502,
        detail: str = "",
        params: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.status_code = status_code
        self.detail = detail
        self.params = params or {}


@dataclass
class _HttpResponse:
    status: int
    content: bytes
    headers: Any

    @property
    def payload(self) -> Any:
        if not self.content:
            return None
        try:
            return json.loads(self.content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None


# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------


def generate_code_verifier() -> str:
    """Verifier PKCE (43-128 caratteri, alfabeto ``unreserved``)."""
    return base64.urlsafe_b64encode(os.urandom(64)).rstrip(b"=").decode("ascii")


def code_challenge(verifier: str) -> str:
    """Challenge S256 = BASE64URL(SHA256(verifier)) senza padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ---------------------------------------------------------------------------
# Helper su header/JSON
# ---------------------------------------------------------------------------


def _header_value(headers: Any, name: str) -> str:
    if not headers:
        return ""
    target = name.lower()
    try:
        items = headers.items()
    except AttributeError:
        items = []
    for key, value in items:
        if str(key).lower() == target:
            return str(value)
    try:
        value = headers.get(name)
    except Exception:  # pragma: no cover - header esotici
        return ""
    return str(value) if value is not None else ""


def _json_header(headers: Any, name: str) -> Any:
    raw = _header_value(headers, name)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _retry_delay(headers: Any, attempt: int) -> float:
    value = _header_value(headers, "Retry-After")
    if value:
        try:
            return max(0.0, min(float(value), 10.0))
        except (TypeError, ValueError):
            pass
    return min(0.5 * (2 ** attempt), 4.0)


def _account_label(payload: Dict[str, Any]) -> str:
    name = payload.get("name")
    if isinstance(name, dict):
        label = str(name.get("display_name") or "").strip()
        if label:
            return label
    return str(payload.get("email") or "").strip()


def _is_not_found(response: _HttpResponse) -> bool:
    payload = response.payload
    if not isinstance(payload, dict):
        return False
    summary = str(payload.get("error_summary") or "")
    if "not_found" in summary:
        return True
    error = payload.get("error")
    if isinstance(error, dict):
        tag = str(error.get(".tag") or "")
        if tag in ("not_found", "path/not_found"):
            return True
        path = error.get("path")
        if isinstance(path, dict) and str(path.get(".tag") or "") == "not_found":
            return True
    return False


def _connected(state: Dict[str, Any]) -> bool:
    if str(state.get("refresh_token") or ""):
        return True
    if not str(state.get("access_token") or ""):
        return False
    try:
        expires_at = float(state.get("expires_at") or 0.0)
    except (TypeError, ValueError):
        expires_at = 0.0
    return expires_at > time.time()


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _content_digest(content: bytes) -> str:
    return hashlib.sha256(content or b"").hexdigest()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class DropboxClient:
    """Client Dropbox con stato persistente e session factory iniettabile."""

    def __init__(
        self,
        paths,
        settings_manager,
        session_factory: Optional[Callable[[], Any]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        timeout: float = DEFAULT_TIMEOUT_S,
    ):
        self.paths = paths
        self.settings_manager = settings_manager
        self._session_factory = session_factory or requests.Session
        self._sleep = sleep or time.sleep
        self.timeout = float(timeout)
        self._lock = threading.RLock()
        self._pending: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------- stato
    @property
    def state_path(self) -> str:
        return self.paths.dropbox_state_path

    def _load_state(self) -> Dict[str, Any]:
        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        path = self.state_path
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            payload = json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True)
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except OSError as exc:
            try:
                if os.path.exists(path + ".tmp"):
                    os.remove(path + ".tmp")
            except OSError:
                pass
            raise CloudError(
                "cloud_error",
                "Impossibile salvare lo stato Dropbox in %s" % path,
                500,
                str(exc),
            ) from exc
        if os.name == "posix":
            try:
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass

    def _remove_state(self) -> None:
        try:
            os.remove(self.state_path)
        except OSError:
            pass

    def _app_key(self) -> str:
        try:
            return str(self.settings_manager.settings.cloud.dropbox.app_key or "").strip()
        except Exception:  # pragma: no cover - configurazione non caricata
            return ""

    def _remote_path(self) -> str:
        path = ""
        try:
            path = str(
                self.settings_manager.settings.cloud.dropbox.remote_path or ""
            ).strip()
        except Exception:  # pragma: no cover
            path = ""
        if not path:
            path = str(self._load_state().get("remote_path") or "").strip()
        path = path or DEFAULT_REMOTE_PATH
        if not path.startswith("/"):
            path = "/" + path
        return path

    def _local_path(self) -> str:
        try:
            configured = str(
                self.settings_manager.settings.cloud.local_path or ""
            ).strip()
        except Exception:  # pragma: no cover
            configured = ""
        return configured or self.paths.config_path

    # ------------------------------------------------------------ HTTP
    def _new_session(self) -> Any:
        return self._session_factory()

    def _http(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Any = None,
        json_body: Any = None,
    ) -> _HttpResponse:
        """Esegue la richiesta con timeout e 2 retry su 429/5xx."""
        last_status = 0
        for attempt in range(MAX_RETRIES + 1):
            session = self._new_session()
            try:
                try:
                    response = session.request(
                        method,
                        url,
                        headers=headers or {},
                        data=data,
                        json=json_body,
                        timeout=self.timeout,
                    )
                except requests.RequestException as exc:
                    raise CloudError(
                        "network_error",
                        "Impossibile raggiungere Dropbox: controlla la connessione a Internet",
                        502,
                        repr(exc),
                    ) from exc
                result = _HttpResponse(
                    status=int(getattr(response, "status_code", 0) or 0),
                    content=bytes(getattr(response, "content", b"") or b""),
                    headers=getattr(response, "headers", None) or {},
                )
                last_status = result.status
                if result.status in RETRY_STATUSES and attempt < MAX_RETRIES:
                    delay = _retry_delay(result.headers, attempt)
                    LOGGER.warning(
                        "Dropbox: HTTP %s, nuovo tentativo tra %.1fs (%d/%d)",
                        result.status,
                        delay,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    self._sleep(delay)
                    continue
                return result
            finally:
                close = getattr(session, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:  # pragma: no cover
                        pass
        raise CloudError(
            "network_error",
            "Dropbox non raggiungibile (ultimo stato HTTP %s)" % last_status,
            502,
        )

    @staticmethod
    def _auth_headers(
        token: str, extra: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        headers = {"Authorization": "Bearer %s" % token}
        if extra:
            headers.update(extra)
        return headers

    def _api_error(self, response: _HttpResponse, message: str) -> CloudError:
        payload = response.payload
        summary = ""
        if isinstance(payload, dict):
            summary = str(payload.get("error_summary") or "")
        if response.status == 409:
            if _is_not_found(response):
                return CloudError(
                    "not_found", "File remoto non trovato su Dropbox", 404, summary
                )
            return CloudError(
                "dropbox_conflict",
                "Conflitto con il file su Dropbox: scarica la versione remota "
                "oppure usa 'forza' per sovrascrivere",
                409,
                summary,
            )
        if response.status == 401:
            return CloudError(
                "cloud_error",
                "Autorizzazione Dropbox scaduta o revocata: riconnetti l'account",
                401,
                summary,
            )
        return CloudError(
            "cloud_error",
            message,
            502,
            summary or ("HTTP %s" % response.status),
        )

    # ------------------------------------------------------------ OAuth
    def _oauth_token(self, form: Dict[str, str]) -> Dict[str, Any]:
        response = self._http("POST", TOKEN_URL, data=form)
        payload = response.payload if isinstance(response.payload, dict) else {}
        if response.status == 200 and payload.get("access_token"):
            return payload
        error = str(payload.get("error") or "")
        description = str(payload.get("error_description") or "")
        if error == "invalid_client" or response.status == 401:
            raise CloudError(
                "dropbox_invalid_client", INVALID_CLIENT_MESSAGE, 400, description
            )
        if error in ("invalid_grant", "invalid_request"):
            raise CloudError(
                "dropbox_invalid_code", INVALID_CODE_MESSAGE, 400, description
            )
        raise CloudError(
            "cloud_error",
            "Risposta inattesa dal servizio OAuth Dropbox (HTTP %s)"
            % response.status,
            502,
            error or description,
        )

    def _apply_token_payload(
        self, state: Dict[str, Any], payload: Dict[str, Any]
    ) -> None:
        state["access_token"] = str(payload.get("access_token") or "")
        refresh_token = payload.get("refresh_token")
        if refresh_token:
            state["refresh_token"] = str(refresh_token)
        try:
            expires_in = int(payload.get("expires_in") or 0)
        except (TypeError, ValueError):
            expires_in = 0
        state["expires_at"] = time.time() + expires_in if expires_in > 0 else 0.0
        state["token_type"] = str(payload.get("token_type") or "bearer")
        account_id = payload.get("account_id")
        if account_id:
            state["account_id"] = str(account_id)

    def _refresh_access_token(self) -> str:
        with self._lock:
            state = self._load_state()
            refresh_token = str(state.get("refresh_token") or "")
            if not refresh_token:
                raise CloudError("dropbox_not_configured", NOT_CONNECTED_MESSAGE, 400)
            app_key = self._app_key()
            if not app_key:
                raise CloudError(
                    "dropbox_not_configured",
                    "App Key Dropbox mancante: incolla la App Key nella sezione Cloud",
                    400,
                )
            payload = self._oauth_token(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": app_key,
                }
            )
            state = self._load_state()
            self._apply_token_payload(state, payload)
            self._save_state(state)
            return str(state.get("access_token") or "")

    def _access_token(self, force_refresh: bool = False) -> str:
        state = self._load_state()
        token = str(state.get("access_token") or "")
        try:
            expires_at = float(state.get("expires_at") or 0.0)
        except (TypeError, ValueError):
            expires_at = 0.0
        if token and not force_refresh and expires_at > time.time() + ACCESS_TOKEN_SKEW_S:
            return token
        if state.get("refresh_token"):
            return self._refresh_access_token()
        if token:
            return token
        raise CloudError("dropbox_not_configured", NOT_CONNECTED_MESSAGE, 400)

    def _fetch_account(self, state: Dict[str, Any]) -> None:
        token = str(state.get("access_token") or "")
        if not token:
            return
        try:
            response = self._http(
                "POST",
                RPC_BASE + "users/get_current_account",
                headers=self._auth_headers(token),
                data=b"",
            )
        except CloudError:
            return
        payload = response.payload
        if response.status != 200 or not isinstance(payload, dict):
            return
        label = _account_label(payload)
        if label:
            state["account"] = label
        account_id = payload.get("account_id")
        if account_id:
            state["account_id"] = str(account_id)
        state["account_checked_at"] = time.time()
        self._save_state(state)

    # ------------------------------------------------------------ API pub
    def status(self) -> Dict[str, Any]:
        with self._lock:
            state = self._load_state()
            app_key = self._app_key()
            return {
                "configured": bool(app_key),
                "connected": _connected(state),
                "account": str(state.get("account") or "") or None,
                "last_sync": _safe_float(state.get("last_sync")),
                "remote_path": self._remote_path(),
                "rev": str(state.get("rev") or "") or None,
            }

    def set_app_key(self, app_key: str) -> Dict[str, Any]:
        key = (app_key or "").strip()
        if not key:
            raise CloudError(
                "validation_error",
                "App Key Dropbox non valida: incolla la App Key della Scoped App",
                422,
                params={"field": "app_key"},
            )
        with self._lock:
            manager = self.settings_manager
            settings = manager.settings
            previous = str(settings.cloud.dropbox.app_key or "").strip()
            settings.cloud.dropbox.app_key = key
            try:
                manager.save(settings)
            except Exception as exc:
                raise CloudError(
                    "settings_write_failed",
                    "Impossibile salvare la App Key nella configurazione",
                    500,
                    str(exc),
                ) from exc
            if previous and previous != key:
                # I token appartengono alla vecchia app: vanno rimossi.
                state = self._load_state()
                for field in (
                    "access_token",
                    "refresh_token",
                    "expires_at",
                    "account",
                    "account_id",
                    "token_type",
                ):
                    state.pop(field, None)
                self._pending = None
                self._save_state(state)
            return self.status()

    def authorize(self) -> Dict[str, Any]:
        with self._lock:
            app_key = self._app_key()
            if not app_key:
                raise CloudError(
                    "dropbox_not_configured",
                    "Configura prima la App Key Dropbox: crea una Scoped App e "
                    "incolla la App Key nella sezione Cloud",
                    400,
                )
            verifier = generate_code_verifier()
            challenge = code_challenge(verifier)
            params = [
                ("client_id", app_key),
                ("response_type", "code"),
                ("code_challenge", challenge),
                ("code_challenge_method", "S256"),
                ("token_access_type", "offline"),
            ]
            self._pending = {
                "verifier": verifier,
                "expires_at": time.time() + PENDING_TTL_S,
            }
            return {
                "auth_url": AUTHORIZE_URL + "?" + urlencode(params),
                "expires_in_s": int(PENDING_TTL_S),
            }

    def complete(self, code: str) -> Dict[str, Any]:
        code = (code or "").strip()
        if not code:
            raise CloudError(
                "dropbox_invalid_code",
                "Incolla il codice di autorizzazione mostrato da Dropbox",
                400,
            )
        with self._lock:
            pending = self._pending
            expires_at = float((pending or {}).get("expires_at") or 0.0)
            if not pending or expires_at < time.time():
                self._pending = None
                raise CloudError(
                    "dropbox_invalid_code",
                    "Autorizzazione Dropbox scaduta: premi 'Autorizza' e riprova",
                    400,
                )
            app_key = self._app_key()
            if not app_key:
                raise CloudError(
                    "dropbox_not_configured",
                    "Configura prima la App Key Dropbox",
                    400,
                )
            payload = self._oauth_token(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": str(pending.get("verifier") or ""),
                    "client_id": app_key,
                }
            )
            state = self._load_state()
            self._apply_token_payload(state, payload)
            state["app_key"] = app_key
            state["remote_path"] = self._remote_path()
            self._save_state(state)
            self._pending = None
            self._fetch_account(state)
            return self.status()

    def _get_remote_rev(self) -> Optional[str]:
        response = self._http(
            "POST",
            RPC_BASE + "files/get_metadata",
            headers=self._auth_headers(
                self._access_token(), {"Content-Type": "application/json"}
            ),
            data=json.dumps({"path": self._remote_path()}).encode("utf-8"),
        )
        if response.status == 200:
            payload = response.payload
            if isinstance(payload, dict):
                rev = payload.get("rev")
                if rev:
                    return str(rev)
            return None
        if _is_not_found(response):
            return None
        raise self._api_error(
            response, "Impossibile leggere i metadati del file remoto Dropbox"
        )

    def upload(self, force: bool = False) -> Dict[str, Any]:
        with self._lock:
            local_path = self._local_path()
            if not os.path.isfile(local_path):
                raise CloudError(
                    "input_missing",
                    "File di configurazione locale non trovato: %s" % local_path,
                    404,
                    params={"path": local_path},
                )
            try:
                with open(local_path, "rb") as handle:
                    content = handle.read()
            except OSError as exc:
                raise CloudError(
                    "cloud_error",
                    "Impossibile leggere il file locale da caricare",
                    500,
                    str(exc),
                ) from exc
            remote_path = self._remote_path()
            state = self._load_state()
            if not force:
                known_rev = str(state.get("rev") or "")
                remote_rev = self._get_remote_rev()
                if known_rev and remote_rev and remote_rev != known_rev:
                    raise CloudError(
                        "dropbox_conflict",
                        "Il file remoto e' cambiato da un altro dispositivo: scarica "
                        "la versione remota oppure usa 'forza' per sovrascrivere",
                        409,
                        params={"local_rev": known_rev, "remote_rev": remote_rev},
                    )
            argument = {
                "path": remote_path,
                "mode": "overwrite",
                "autorename": False,
                "mute": True,
            }
            response = self._http(
                "POST",
                CONTENT_BASE + "files/upload",
                headers=self._auth_headers(
                    self._access_token(),
                    {
                        "Dropbox-API-Arg": json.dumps(argument),
                        "Content-Type": "application/octet-stream",
                    },
                ),
                data=content,
            )
            if response.status != 200:
                raise self._api_error(response, "Caricamento su Dropbox non riuscito")
            payload = response.payload if isinstance(response.payload, dict) else {}
            rev = str(payload.get("rev") or "")
            state = self._load_state()
            if rev:
                state["rev"] = rev
            state["last_sync"] = time.time()
            state["remote_path"] = remote_path
            state["local_sha256"] = _content_digest(content)
            self._save_state(state)
            return {
                "ok": True,
                "rev": rev,
                "message": "Configurazione caricata su Dropbox (%s)" % remote_path,
            }

    def download(self, force: bool = False) -> Dict[str, Any]:
        with self._lock:
            remote_path = self._remote_path()
            response = self._http(
                "POST",
                CONTENT_BASE + "files/download",
                headers=self._auth_headers(
                    self._access_token(),
                    {"Dropbox-API-Arg": json.dumps({"path": remote_path})},
                ),
            )
            if response.status != 200:
                if _is_not_found(response):
                    raise CloudError(
                        "not_found",
                        "File remoto non trovato su Dropbox: esegui prima un "
                        "caricamento",
                        404,
                        params={"path": remote_path},
                    )
                raise self._api_error(response, "Download da Dropbox non riuscito")
            content = response.content or b""
            metadata = _json_header(response.headers, "Dropbox-API-Result")
            remote_rev = ""
            if isinstance(metadata, dict):
                remote_rev = str(metadata.get("rev") or "")
            local_path = self._local_path()
            existing = b""
            try:
                with open(local_path, "rb") as handle:
                    existing = handle.read()
            except OSError:
                existing = b""
            state = self._load_state()
            known_rev = str(state.get("rev") or "")
            local_digest = str(state.get("local_sha256") or "")
            local_changed = (
                bool(existing) and bool(local_digest) and _content_digest(existing) != local_digest
            )
            remote_changed = bool(remote_rev) and remote_rev != known_rev
            if not force and local_changed and remote_changed:
                raise CloudError(
                    "dropbox_conflict",
                    "Sia la configurazione locale sia quella remota sono cambiate: "
                    "usa 'forza' per sovrascrivere la copia locale",
                    409,
                    params={"local_path": local_path, "remote_rev": remote_rev},
                )
            if not force and not remote_changed:
                # Nessuna novita' remota: non toccare eventuali modifiche locali.
                state["last_sync"] = time.time()
                self._save_state(state)
                return {
                    "ok": True,
                    "changed": False,
                    "message": "Configurazione remota invariata: nessuna modifica",
                }
            changed = existing != content
            if changed or force:
                self._write_local(local_path, content)
            if remote_rev:
                state["rev"] = remote_rev
            state["last_sync"] = time.time()
            state["remote_path"] = remote_path
            state["local_sha256"] = _content_digest(content)
            self._save_state(state)
            if changed:
                message = "Configurazione scaricata da Dropbox (%s)" % remote_path
            else:
                message = "Configurazione gia' aggiornata: nessuna modifica"
            return {"ok": True, "changed": changed, "message": message}

    @staticmethod
    def _write_local(local_path: str, content: bytes) -> None:
        try:
            parent = os.path.dirname(os.path.abspath(local_path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp = local_path + ".tmp"
            with open(tmp, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, local_path)
        except OSError as exc:
            try:
                if os.path.exists(local_path + ".tmp"):
                    os.remove(local_path + ".tmp")
            except OSError:
                pass
            raise CloudError(
                "cloud_error",
                "Impossibile scrivere il file di configurazione locale",
                500,
                str(exc),
            ) from exc

    def disconnect(self) -> Dict[str, Any]:
        with self._lock:
            state = self._load_state()
            for field in (
                "access_token",
                "refresh_token",
                "expires_at",
                "account",
                "account_id",
                "token_type",
            ):
                state.pop(field, None)
            self._pending = None
            if state:
                self._save_state(state)
            else:
                self._remove_state()
            return {"ok": True}


def pkce_pair() -> Tuple[str, str]:
    """Coppia (verifier, challenge S256) per test e strumenti esterni."""
    verifier = generate_code_verifier()
    return verifier, code_challenge(verifier)
