"""Novelia Web-novel metadata provider for Calibre-Web / CWA.

Version 1.3.1. Install this file in cps/metadata_provider, not Calibre plugins.
Search Chinese/Japanese titles or use a Novelia work URL / novelia:provider/id.
Web and Wenku metadata, including R18 with an authorized account token.
No chapters, automatic login, token refresh or file writes.
"""

import html
import hashlib
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urlsplit

import requests

from cps import logger
from cps.services.Metadata import Metadata, MetaRecord, MetaSourceInfo

log = logger.create()
_HOSTS = frozenset(("n.novelia.cc", "n.novelia.top"))
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_CACHE = {}
_LOCK = threading.Lock()
_TTL = 300
_MAX_BYTES = 4 * 1024 * 1024
_PROVIDERS = ("kakuyomu", "syosetu", "novelup", "hameln", "pixiv", "alphapolis")
_RESULT_LIMIT = 5


def parse_reference(query):
    """Return (provider, novel id) or None; never request arbitrary URLs."""
    if not isinstance(query, str):
        return None
    text = query.strip()
    if len(text) > 2048:
        return None
    if text.lower().startswith("novelia:") and "://" not in text:
        path = text[len("novelia:"):].strip()
        parts = path.split("/")
    elif text.startswith(("http://", "https://")):
        try:
            parsed = urlsplit(text)
            if (parsed.hostname not in _HOSTS or parsed.username or parsed.password
                    or parsed.port not in (None, 80, 443)):
                return None
            parts = unquote(parsed.path).strip("/").split("/")
            if len(parts) == 3 and parts[0] == "novel":
                parts.pop(0)
            elif len(parts) == 2 and parts[0] == "wenku":
                pass
            else:
                return None
        except ValueError:
            return None
    else:
        parts = text.split("/")
    if len(parts) != 2 or not all(_ID.fullmatch(p) for p in parts):
        return None
    return tuple(parts)


def _string(value):
    return value.strip() if isinstance(value, str) else ""


def _list(value):
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(s for v in value if (s := _string(v))))


def _text_html(value):
    return html.escape(value).replace("\n", "<br>")


class Novelia(Metadata):
    __name__ = "Novelia"
    __id__ = "novelia"
    DESCRIPTION = "Novelia Web / 文库：中日文书名检索；配置授权令牌后包含 R18"
    META_URL = "https://n.novelia.cc/"

    def _token(self):
        value = os.getenv("NOVELIA_ACCESS_TOKEN", "").strip()
        if value.lower().startswith("bearer "):
            value = value[7:].strip()
        if len(value) > 16384 or any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Invalid Novelia token format")
        return value

    def _base(self):
        # Restrict credentials/network to known Novelia origins. No arbitrary host.
        value = os.getenv("NOVELIA_BASE_URL", self.META_URL).rstrip("/")
        if value not in {"https://" + host for host in _HOSTS}:
            raise ValueError("NOVELIA_BASE_URL must be https://n.novelia.cc or https://n.novelia.top")
        return value

    def _fetch(self, base, provider, novel_id):
        token = self._token()
        # Never reuse authenticated metadata after credentials are removed/changed.
        key = (base, provider, novel_id, hashlib.sha256(token.encode()).hexdigest())
        with _LOCK:
            cached = _CACHE.get(key)
            if cached and time.monotonic() - cached[0] < _TTL:
                return cached[1]
        path = "/api/wenku/" + novel_id if provider == "wenku" else "/api/novel/" + provider + "/" + novel_id
        data = self._request_json(base + path, token=token)
        if not isinstance(data, dict) or not (_string(data.get("titleZh")) or _string(data.get("titleJp")) or (provider == "wenku" and _string(data.get("title")))):
            log.warning("Novelia metadata schema missing a title")
            return None
        with _LOCK:
            if len(_CACHE) >= 64:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[key] = (time.monotonic(), data)
        return data

    def _request_json(self, url, params=None, token=None):
        # Standard HTTP_PROXY / HTTPS_PROXY / NO_PROXY are honored by requests.
        # No retries: 401/403/429 must not cause a request storm or access bypass.
        origin = urlsplit(url)
        if origin.scheme != "https" or origin.hostname not in _HOSTS or origin.username or origin.password or origin.port not in (None, 443):
            raise ValueError("Refusing credentials outside Novelia HTTPS origins")
        token = self._token() if token is None else token
        headers = {"Accept": "application/json", "User-Agent": "CWA-Novelia-Metadata/1.3"}
        if token:
            headers["Authorization"] = "Bearer " + token
        with requests.get(
            url,
            headers=headers,
            params=params,
            timeout=(5, 15), allow_redirects=False, stream=True,
        ) as response:
            if response.status_code != 200:
                log.warning("Novelia metadata HTTP %s; no metadata applied", response.status_code)
                if response.status_code in (401, 403):
                    log.warning("Novelia: check token expiry and account access; restricted search requires authorization")
                return None
            if "json" not in response.headers.get("Content-Type", "").lower():
                log.warning("Novelia returned non-JSON (possibly a login/challenge page)")
                return None
            chunks, size = [], 0
            start = time.monotonic()
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > _MAX_BYTES or time.monotonic() - start > 25:
                    log.warning("Novelia metadata response exceeded size/time limit")
                    return None
                chunks.append(chunk)
            import json
            data = json.loads(b"".join(chunks))
        return data

    def _search_title(self, base, query):
        # Keep each catalog's candidates: identical names can be distinct editions.
        with ThreadPoolExecutor(max_workers=2) as pool:
            groups = list(pool.map(lambda kind: self._search_kind_safe(base, query, kind), ("web", "wenku")))
        return [record for group in groups for record in group]

    def _search_kind_safe(self, base, query, kind):
        try:
            return self._search_kind(base, query, kind)
        except (requests.RequestException, OSError, ValueError, TypeError, KeyError) as exc:
            log.warning("Novelia %s search failed (%s)", kind, type(exc).__name__)
            return []

    def _search_kind(self, base, query, kind):
        token = self._token()
        params = {
            "page": 0, "pageSize": _RESULT_LIMIT, "query": query,
            # level=0 searches all classes and requires an authorized account.
            "level": 0 if token else 1,
        }
        if kind == "web":
            params.update(provider=",".join(_PROVIDERS), type=0, translate=0, sort=2)
        data = self._request_json(base + ("/api/novel" if kind == "web" else "/api/wenku"), params=params, token=token)
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            return []
        refs = []
        for item in data["items"]:
            if not isinstance(item, dict):
                continue
            provider, novel_id = ("wenku", item.get("id")) if kind == "wenku" else (item.get("providerId"), item.get("novelId"))
            if (provider in (*_PROVIDERS, "wenku") and isinstance(novel_id, str)
                    and _ID.fullmatch(novel_id) and (provider, novel_id) not in refs):
                refs.append((provider, novel_id))
            if len(refs) == _RESULT_LIMIT:
                break
        # Search outlines lack authors/introduction; hydrate only these candidates.
        # Preserve each server list's order, regardless of detail completion order.
        with ThreadPoolExecutor(max_workers=3) as pool:
            records = list(pool.map(lambda ref: self._lookup(base, ref), refs))
        return [record for variants in records if variants for record in variants]

    def _lookup(self, base, ref):
        try:
            data = self._fetch(base, *ref)
            if not data:
                return []
            original_title = _string(data.get("title" if ref[0] == "wenku" else "titleJp"))
            variants = []
            if _string(data.get("titleZh")):
                variants.append(self._record(base, *ref, data, variant="zh"))
            if original_title:
                variants.append(self._record(base, *ref, data, variant="original"))
            return variants
        except (requests.RequestException, OSError, ValueError, TypeError, KeyError) as exc:
            log.warning("Novelia metadata failed (%s); no metadata applied", type(exc).__name__)
            return []

    def _record(self, base, provider, novel_id, data, variant="zh"):
        is_wenku = provider == "wenku"
        if is_wenku:
            # Wenku is a series-level record; latestPublishAt is NOT a volume date.
            data = dict(data, titleJp=data.get("title"), introductionZh=data.get("introductionZh", data.get("introduction")),
                        authors=[{"name": name} for name in _list(data.get("authors"))], type=None)
        title_jp = _string(data.get("titleJp"))
        title_zh = _string(data.get("titleZh"))
        intro_zh = _string(data.get("introductionZh"))
        intro_jp = _string(data.get("introductionJp"))
        status = _string(data.get("type"))
        authors_data = data.get("authors")
        authors = _list([a.get("name") for a in authors_data if isinstance(a, dict)]) if isinstance(authors_data, list) else []
        url = base + ("/wenku/" + novel_id if is_wenku else "/novel/" + provider + "/" + novel_id)
        intro = intro_zh if variant == "zh" else intro_jp
        tags = ["机翻", "轻小说机翻网", "文库版" if is_wenku else "WEB版"]
        if status:
            tags.append(status)
        tags += _list(data.get("keywords")) + _list(data.get("attentions"))
        if is_wenku and _string(data.get("level")):
            tags.append(data["level"])
        return MetaRecord(
            id="novelia:" + provider + "/" + novel_id + ":" + variant,
            title=(title_zh or title_jp) if variant == "zh" else title_jp,
            authors=authors,
            url=url,
            source=MetaSourceInfo(id=self.__id__, description="Novelia · " + ("中文翻译版" if variant == "zh" else "原文版"), link=base),
            description="<p>" + _text_html(intro) + "</p>" if intro else "",
            identifiers={"novelia": provider + "/" + novel_id},
            tags=list(dict.fromkeys(tags))[:60],
            # Work metadata cannot establish this local file's language/edition/volume.
            series=None, series_index=None, languages=[], publisher=None,
            publishedDate=None, rating=None, cover="",
        )

    def search(self, query, generic_cover="", locale="en"):
        if not self.active:
            return []
        query = _string(query)
        if not query or len(query) > 2048:
            return []
        ref = parse_reference(query)
        if ref is None and ("://" in query or query.lower().startswith("novelia:")):
            return []
        try:
            base = self._base()
            if ref is not None:
                return self._lookup(base, ref)
            return self._search_title(base, query)
        except (requests.RequestException, OSError, ValueError, TypeError, KeyError) as exc:
            # Do not log exception text: it may contain proxy credentials or query data.
            log.warning("Novelia metadata failed (%s); no metadata applied", type(exc).__name__)
            return []
