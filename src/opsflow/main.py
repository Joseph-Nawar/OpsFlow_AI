"""FastAPI application entry point."""

from fastapi import FastAPI

app = FastAPI(title="OpsFlow AI")


@app.get("/health")
def health() -> dict[str, str]:
    """Return the process liveness response without dependency checks."""

    return {"status": "ok"}
