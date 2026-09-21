from __future__ import annotations

import os

from .api import app


def run() -> None:
    import uvicorn

    uvicorn.run(
        "webtest_agent_orchestrator.api:app",
        host=os.getenv("WEBTEST_ORCHESTRATOR_HOST", "127.0.0.1"),
        port=int(os.getenv("WEBTEST_ORCHESTRATOR_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    run()
