from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from app import STORE, SampleHandler


class SampleApplicationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), SampleHandler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        STORE.reset()

    def request(self, method: str, path: str, body=None, token=None, headers=None):
        raw = json.dumps(body).encode() if body is not None else None
        request_headers = {"Content-Type": "application/json", **(headers or {})}
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.base + path, data=raw, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read())
            finally:
                error.close()

    def login(self):
        status, body = self.request("POST", "/api/login", {"username": "sample_user", "password": "sample_password"})
        self.assertEqual(200, status)
        return body["accessToken"]

    def test_health_and_ui(self):
        status, body = self.request("GET", "/health")
        self.assertEqual((200, "ok"), (status, body["status"]))
        with urllib.request.urlopen(self.base + "/") as response:
            page = response.read()
            self.assertIn(b"WebTest Agent sample application", page)
            self.assertIn(b"Details", page)
            self.assertIn(b"Archive", page)
            self.assertIn(b"X-Allow-Destructive", page)

    def test_unauthorized_and_validation(self):
        self.assertEqual(401, self.request("GET", "/api/records")[0])
        token = self.login()
        status, body = self.request("POST", "/api/records", {"quantity": 2}, token)
        self.assertEqual((400, "name is required"), (status, body["error"]))

    def test_create_update_get_and_async_flow(self):
        token = self.login()
        status, record = self.request("POST", "/api/records", {"name": "Created", "quantity": 2}, token)
        self.assertEqual(201, status)
        record_id = record["id"]
        status, updated = self.request("PUT", f"/api/records/{record_id}", {"name": "Updated"}, token)
        self.assertEqual((200, "Updated"), (status, updated["name"]))
        status, job = self.request("POST", f"/api/records/{record_id}/process", {}, token)
        self.assertEqual(202, status)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status, state = self.request("GET", f"/api/jobs/{job['jobId']}", token=token)
            if state["status"] == "completed":
                break
            time.sleep(0.05)
        self.assertEqual("completed", state["status"])
        status, final = self.request("GET", f"/api/records/{record_id}", token=token)
        self.assertEqual((200, "processed"), (status, final["status"]))

    def test_archive_requires_explicit_confirmation(self):
        token = self.login()
        _, record = self.request("POST", "/api/records", {"name": "Archive me"}, token)
        path = f"/api/records/{record['id']}"
        self.assertEqual(403, self.request("DELETE", path, token=token)[0])
        status, body = self.request("DELETE", path, token=token, headers={"X-Allow-Destructive": "true"})
        self.assertEqual((200, True), (status, body["archived"]))


if __name__ == "__main__":
    unittest.main()
