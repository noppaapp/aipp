"""In-memory Google Drive for local tests."""
import json
import re
from email.message import Message
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlparse

FOLDER_MIME = "application/vnd.google-apps.folder"

class FakeDrive:
    def __init__(self, root="root"):
        self.root = root
        self.files = {}
        self.calls = []
        self._n = 0

    def add(self, name, content="", parent=None, mime="text/markdown", file_id=None):
        self._n += 1
        file_id = file_id or f"f{self._n}"
        meta = {"id": file_id, "name": name, "mimeType": mime,
                "parents": [parent or self.root],
                "modifiedTime": "2026-10-06T00:00:00Z"}
        self.files[file_id] = {"meta": meta, "content": content.encode("utf-8") if isinstance(content, str) else content}
        return file_id

    def folder(self, name, parent=None):
        return self.add(name, "", parent, FOLDER_MIME)

    def text(self, name):
        for item in self.files.values():
            if item["meta"]["name"] == name:
                return item["content"].decode("utf-8")
        return None

    def writes_to(self, name):
        ids = {i for i, f in self.files.items() if f["meta"]["name"] == name}
        return [c for c in self.calls if c[0] in {"PATCH", "POST"} and any(i in c[1] for i in ids)]

    def _http_error(self, code, url):
        return HTTPError(url, code, "fake drive error", Message(), None)

    def request(self, url, method="GET", data=None, token=None, content_type=None):
        parsed = urlparse(url)
        path, query = parsed.path, parse_qs(parsed.query)
        self.calls.append((method, path))

        if parsed.netloc == "oauth2.googleapis.com":
            return json.dumps({"access_token": "fake-token"}).encode()

        if method == "GET" and path == "/drive/v3/files":
            match = re.match(r"'([^']+)' in parents", query.get("q", [""])[0])
            parent = match.group(1) if match else None
            kids = [dict(f["meta"]) for f in self.files.values() if parent in f["meta"]["parents"]]
            return json.dumps({"files": kids}).encode()

        match = re.fullmatch(r"/drive/v3/files/([^/]+)(/export)?", path)
        if method == "GET" and match:
            item = self.files.get(unquote(match.group(1)))
            if item is None:
                raise self._http_error(404, url)
            return item["content"]

        if method == "POST" and path == "/drive/v3/files":
            meta = json.loads(data.decode("utf-8"))
            return json.dumps({"id": self.add(meta["name"], "", meta["parents"][0], meta.get("mimeType", "text/plain"))}).encode()

        match = re.fullmatch(r"/upload/drive/v3/files/([^/]+)", path)
        if method == "PATCH" and match:
            item = self.files.get(unquote(match.group(1)))
            if item is None:
                raise self._http_error(404, url)
            item["content"] = data
            return json.dumps({"id": item["meta"]["id"]}).encode()

        raise self._http_error(404, url)

    def install(self, monkeypatch):
        import aipp_drive_runtime
        monkeypatch.setattr(aipp_drive_runtime, "_request", self.request)
        monkeypatch.setenv("GDRIVE_FOLDER_ID", self.root)
        monkeypatch.setenv("GDRIVE_CREDENTIALS", "fake-client-id fake-client-secret")
        monkeypatch.setenv("GCP_REFRESH_TOKEN", "fake-refresh")
        return self
