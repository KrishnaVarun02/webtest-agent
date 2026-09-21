#!/usr/bin/env python3
"""Small dependency-free website used to exercise WebTest Agent end to end."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY_BYTES = 64 * 1024


@dataclass
class Store:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    tokens: set[str] = field(default_factory=set)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def reset(self) -> None:
        with self.lock:
            self.records.clear()
            self.jobs.clear()
            self.tokens.clear()
            seeded_id = "00000000-0000-4000-8000-000000000001"
            self.records[seeded_id] = {
                "id": seeded_id,
                "name": "Seed record",
                "quantity": 1,
                "status": "ready",
                "archived": False,
                "createdAt": "2026-01-01T00:00:00Z",
            }


STORE = Store()
STORE.reset()


INDEX_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>WebTest Agent Sample</title>
<style>body{font:16px system-ui;max-width:880px;margin:2rem auto;padding:0 1rem}label{display:block;margin:.6rem 0}button{margin:.25rem}pre{background:#f4f4f4;padding:1rem;overflow:auto}.row{display:flex;gap:1rem;flex-wrap:wrap}.card{border:1px solid #ccc;border-radius:8px;padding:1rem;flex:1;min-width:300px}.danger{color:#8b0000}</style>
</head><body>
<h1>WebTest Agent sample application</h1>
<p>This intentionally small, local-only application exposes observable REST/JSON flows.</p>
<div class="row"><section class="card"><h2>Login</h2>
<label>Username <input data-testid="username" id="username" autocomplete="username" value="sample_user"></label>
<label>Password <input data-testid="password" id="password" type="password" autocomplete="current-password" value="sample_password"></label>
<button data-testid="login" id="login">Log in</button></section>
<section class="card"><h2>Create record</h2>
<label>Name <input data-testid="record-name" id="name" value="Demo record"></label>
<label>Quantity <input data-testid="record-quantity" id="quantity" type="number" value="2"></label>
<button data-testid="create-record" id="create">Create</button>
<button data-testid="list-records" id="list">Refresh list</button></section></div>
<section><h2>Records</h2><div id="records"></div></section>
<section><h2>Last response</h2><pre id="output" aria-live="polite">Log in to begin.</pre></section>
<script>
let token=''; const out=document.querySelector('#output');
async function api(path, options={}){options.headers={...(options.headers||{}),'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`}:{})};const r=await fetch(path,options);let body;try{body=await r.json()}catch{body={}};out.textContent=JSON.stringify({status:r.status,body},null,2);if(!r.ok)throw new Error(body.error||`HTTP ${r.status}`);return body}
document.querySelector('#login').onclick=async()=>{const body=await api('/api/login',{method:'POST',body:JSON.stringify({username:username.value,password:password.value})});token=body.accessToken;await listRecords()};
document.querySelector('#create').onclick=async()=>{await api('/api/records',{method:'POST',body:JSON.stringify({name:name.value,quantity:Number(quantity.value)})});await listRecords()};
document.querySelector('#list').onclick=listRecords;
async function listRecords(){const body=await api('/api/records');const root=document.querySelector('#records');root.textContent='';for(const r of body.items){const row=document.createElement('p');row.textContent=`${r.name} (${r.status}) `;const details=document.createElement('button');details.textContent='Details';details.dataset.recordId=r.id;details.onclick=()=>getRecord(r.id);const process=document.createElement('button');process.textContent='Process';process.dataset.recordId=r.id;process.onclick=()=>processRecord(r.id);const update=document.createElement('button');update.textContent='Rename';update.onclick=()=>renameRecord(r.id);const archive=document.createElement('button');archive.textContent='Archive';archive.className='danger';archive.dataset.recordId=r.id;archive.onclick=()=>archiveRecord(r.id);row.append(details,process,update,archive);root.append(row)}}
async function getRecord(id){await api(`/api/records/${id}`)}
async function renameRecord(id){await api(`/api/records/${id}`,{method:'PUT',body:JSON.stringify({name:'Updated from UI'})});await listRecords()}
async function processRecord(id){const job=await api(`/api/records/${id}/process`,{method:'POST',body:'{}'});for(let i=0;i<12;i++){const s=await api(`/api/jobs/${job.jobId}`);if(s.status==='completed')break;await new Promise(r=>setTimeout(r,100))}await listRecords()}
async function archiveRecord(id){if(!window.confirm('Archive this test record?'))return;await api(`/api/records/${id}`,{method:'DELETE',headers:{'X-Allow-Destructive':'true'}});await listRecords()}
</script></body></html>"""


class SampleHandler(BaseHTTPRequestHandler):
    server_version = "WebTestAgentSample/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"sample-app {self.address_string()} {fmt % args}", flush=True)

    def _headers(self, status: int, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    def send_json(self, status: int, payload: Any) -> None:
        raw = json.dumps(payload, separators=(",", ":")).encode()
        self._headers(status, "application/json; charset=utf-8", len(raw))
        self.wfile.write(raw)

    def send_html(self, status: int, html: str) -> None:
        raw = html.encode()
        self._headers(status, "text/html; charset=utf-8", len(raw))
        self.wfile.write(raw)

    def read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid content length"})
            return None
        if length > MAX_BODY_BYTES:
            self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request body too large"})
            return None
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON"})
            return None
        if not isinstance(value, dict):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "JSON object required"})
            return None
        return value

    def authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        token = header.removeprefix("Bearer ") if header.startswith("Bearer ") else ""
        with STORE.lock:
            ok = bool(token and token in STORE.tokens)
        if not ok:
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "valid bearer token required"})
        return ok

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            return self.send_html(HTTPStatus.OK, INDEX_HTML)
        if path == "/health":
            return self.send_json(HTTPStatus.OK, {"status": "ok", "environment": "local-test"})
        if path == "/api/records":
            if not self.authorized():
                return
            with STORE.lock:
                records = [dict(v) for v in STORE.records.values() if not v["archived"]]
            return self.send_json(HTTPStatus.OK, {"items": records, "count": len(records)})
        match = re.fullmatch(r"/api/records/([0-9a-f-]+)", path)
        if match:
            if not self.authorized():
                return
            with STORE.lock:
                record = STORE.records.get(match.group(1))
            return self.send_json(HTTPStatus.OK, record) if record else self.send_json(HTTPStatus.NOT_FOUND, {"error": "record not found"})
        match = re.fullmatch(r"/api/jobs/([0-9a-f-]+)", path)
        if match:
            if not self.authorized():
                return
            with STORE.lock:
                job = STORE.jobs.get(match.group(1))
            return self.send_json(HTTPStatus.OK, job) if job else self.send_json(HTTPStatus.NOT_FOUND, {"error": "job not found"})
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "route not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        body = self.read_json()
        if body is None:
            return
        if path == "/api/login":
            if body.get("username") != "sample_user" or body.get("password") != "sample_password":
                return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid credentials"})
            token = secrets.token_urlsafe(24)
            with STORE.lock:
                STORE.tokens.add(token)
            return self.send_json(HTTPStatus.OK, {"accessToken": token, "tokenType": "Bearer", "expiresIn": 3600})
        if path == "/api/records":
            if not self.authorized():
                return
            error = validate_record(body, partial=False)
            if error:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": error})
            record_id = str(uuid.uuid4())
            record = {"id": record_id, "name": body["name"], "quantity": body.get("quantity", 1), "status": "ready", "archived": False, "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            with STORE.lock:
                STORE.records[record_id] = record
            return self.send_json(HTTPStatus.CREATED, record)
        match = re.fullmatch(r"/api/records/([0-9a-f-]+)/process", path)
        if match:
            if not self.authorized():
                return
            record_id = match.group(1)
            with STORE.lock:
                if record_id not in STORE.records:
                    return self.send_json(HTTPStatus.NOT_FOUND, {"error": "record not found"})
                job_id = str(uuid.uuid4())
                STORE.jobs[job_id] = {"jobId": job_id, "recordId": record_id, "status": "pending"}
                STORE.records[record_id]["status"] = "processing"
            timer = threading.Timer(0.25, complete_job, args=(job_id, record_id))
            timer.daemon = True
            timer.start()
            return self.send_json(HTTPStatus.ACCEPTED, {"jobId": job_id, "recordId": record_id, "status": "pending"})
        if path == "/api/test/reset":
            if self.headers.get("X-Test-Environment") != "true":
                return self.send_json(HTTPStatus.FORBIDDEN, {"error": "test environment confirmation required"})
            STORE.reset()
            return self.send_json(HTTPStatus.OK, {"status": "reset"})
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "route not found"})

    def do_PUT(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        match = re.fullmatch(r"/api/records/([0-9a-f-]+)", path)
        if not match:
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "route not found"})
        body = self.read_json()
        if body is None or not self.authorized():
            return
        error = validate_record(body, partial=True)
        if error:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": error})
        with STORE.lock:
            record = STORE.records.get(match.group(1))
            if not record:
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": "record not found"})
            for key in ("name", "quantity"):
                if key in body:
                    record[key] = body[key]
            updated = dict(record)
        self.send_json(HTTPStatus.OK, updated)

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        match = re.fullmatch(r"/api/records/([0-9a-f-]+)", path)
        if not match:
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "route not found"})
        if not self.authorized():
            return
        if self.headers.get("X-Allow-Destructive") != "true":
            return self.send_json(HTTPStatus.FORBIDDEN, {"error": "destructive action confirmation required"})
        with STORE.lock:
            record = STORE.records.get(match.group(1))
            if not record:
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": "record not found"})
            record["archived"] = True
        self.send_json(HTTPStatus.OK, {"id": match.group(1), "archived": True})


def validate_record(body: dict[str, Any], partial: bool) -> str | None:
    if not partial and "name" not in body:
        return "name is required"
    if "name" in body and (not isinstance(body["name"], str) or not body["name"].strip()):
        return "name must be a non-empty string"
    if "quantity" in body and (not isinstance(body["quantity"], int) or isinstance(body["quantity"], bool) or body["quantity"] < 0 or body["quantity"] > 1000):
        return "quantity must be an integer between 0 and 1000"
    if partial and not any(key in body for key in ("name", "quantity")):
        return "at least one supported field is required"
    return None


def complete_job(job_id: str, record_id: str) -> None:
    with STORE.lock:
        job = STORE.jobs.get(job_id)
        record = STORE.records.get(record_id)
        if job and record:
            job["status"] = "completed"
            job["completedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            record["status"] = "processed"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the WebTest Agent sample application")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--ready-file", type=Path)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), SampleHandler)
    if args.ready_file:
        args.ready_file.write_text(str(server.server_port), encoding="utf-8")
    print(f"WebTest Agent sample app: http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
