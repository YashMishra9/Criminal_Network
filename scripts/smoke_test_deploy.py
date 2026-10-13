#!/usr/bin/env python3
"""
H2 Deployment Smoke Test — Criminal Network Analysis System
============================================================

Manual or CI-driven smoke test that verifies:
  1. The Docker image builds successfully from backend/Dockerfile.
  2. The container starts and the FastAPI /docs endpoint responds 200 OK.
  3. LIVE_ADAPTER_ENABLED defaults to "false" in the running container
     (Contract Invariant 7 — DOC3).
  4. The container shuts down cleanly.

Usage (local):
    python scripts/smoke_test_deploy.py

Usage (CI — e.g. GitHub Actions step):
    python scripts/smoke_test_deploy.py

Requirements:
    - Docker daemon must be running.
    - Run from the repository root.
    - No additional Python packages beyond the standard library are required.

Exit codes:
    0 — all checks passed
    1 — one or more checks failed
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

IMAGE_TAG = "criminal-network-backend-smoke:latest"
CONTAINER_NAME = "cn-smoke-test"
HOST_PORT = 18080           # Use a high port to avoid conflicts
CONTAINER_PORT = 8000
STARTUP_WAIT_SECONDS = 15   # Max seconds to wait for the container to be ready
POLL_INTERVAL_SECONDS = 1

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
DOCKERFILE = os.path.join(BACKEND_DIR, "Dockerfile")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    """Run a subprocess command and return the result."""
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def check(condition: bool, message: str) -> bool:
    """Print PASS/FAIL for a check and return the result."""
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"  {status} — {message}")
    return condition


def wait_for_http(url: str, timeout: int) -> bool:
    """Poll url until it returns 2xx or timeout expires. Return True on success."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if 200 <= resp.status < 300:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(POLL_INTERVAL_SECONDS)
    return False


# ---------------------------------------------------------------------------
# Smoke test steps
# ---------------------------------------------------------------------------


def step_build_image() -> bool:
    print("\n[Step 1] Build Docker image")
    result = run(
        [
            "docker", "build",
            "-t", IMAGE_TAG,
            "-f", DOCKERFILE,
            BACKEND_DIR,
        ]
    )
    ok = result.returncode == 0
    check(ok, f"Docker build exits 0 (got {result.returncode})")
    if not ok:
        print("  --- docker build stdout ---")
        print(result.stdout[-2000:])
        print("  --- docker build stderr ---")
        print(result.stderr[-2000:])
    return ok


def step_start_container() -> bool:
    print("\n[Step 2] Start container")
    # Remove any leftover container from a previous run
    run(["docker", "rm", "-f", CONTAINER_NAME])

    result = run(
        [
            "docker", "run",
            "--name", CONTAINER_NAME,
            "--detach",
            "-p", f"{HOST_PORT}:{CONTAINER_PORT}",
            # Override NEO4J settings so the app starts without a real DB
            "-e", "ENVIRONMENT=production",
            "-e", "NEO4J_URI=bolt://localhost:7687",
            "-e", "NEO4J_USER=neo4j",
            "-e", "NEO4J_PASSWORD=smoketest",
            # Verify Contract Invariant 7: LIVE_ADAPTER_ENABLED must remain false
            # (no override here — we rely on the image default)
            IMAGE_TAG,
        ]
    )
    ok = result.returncode == 0
    check(ok, f"docker run exits 0 (got {result.returncode})")
    if not ok:
        print(result.stderr[-2000:])
    return ok


def step_health_check() -> bool:
    print(f"\n[Step 3] Wait for /docs to respond (up to {STARTUP_WAIT_SECONDS}s)")
    url = f"http://localhost:{HOST_PORT}/docs"
    ok = wait_for_http(url, STARTUP_WAIT_SECONDS)
    check(ok, f"GET {url} returns 2xx within {STARTUP_WAIT_SECONDS}s")
    return ok


def step_invariant7_check() -> bool:
    """Check LIVE_ADAPTER_ENABLED is 'false' inside the running container."""
    print("\n[Step 4] Verify Contract Invariant 7: LIVE_ADAPTER_ENABLED=false in container")
    result = run(
        ["docker", "exec", CONTAINER_NAME, "sh", "-c", "echo $LIVE_ADAPTER_ENABLED"]
    )
    value = result.stdout.strip()
    ok = value == "false"
    check(ok, f"LIVE_ADAPTER_ENABLED in container = {value!r} (expected 'false')")
    return ok


def step_stop_container() -> bool:
    print("\n[Step 5] Stop and remove container")
    stop = run(["docker", "stop", CONTAINER_NAME])
    rm = run(["docker", "rm", CONTAINER_NAME])
    ok = stop.returncode == 0 and rm.returncode == 0
    check(ok, "Container stopped and removed cleanly")
    return ok


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 60)
    print("H2 Deployment Smoke Test")
    print("Criminal Network Analysis System")
    print("=" * 60)

    # Check Docker is available
    docker_check = run(["docker", "info"])
    if docker_check.returncode != 0:
        print("\n❌ Docker daemon is not running or not accessible.")
        print("   Start Docker Desktop (Windows/macOS) or the Docker service (Linux).")
        return 1

    results = []

    results.append(step_build_image())
    if not results[-1]:
        print("\n⛔ Build failed — skipping runtime checks.")
        return 1

    results.append(step_start_container())
    if not results[-1]:
        print("\n⛔ Container failed to start — skipping runtime checks.")
        return 1

    results.append(step_health_check())
    results.append(step_invariant7_check())
    results.append(step_stop_container())

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    if all(results):
        print(f"✅ All {total} checks passed — deployment smoke test PASSED.")
        return 0
    else:
        print(f"❌ {total - passed}/{total} checks failed — deployment smoke test FAILED.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
