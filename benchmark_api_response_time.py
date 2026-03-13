"""
Measure average (and p50/p95) API response time for chat.
Simulates real requests: register or login, then N chat calls; reports latency.
Usage:
  python benchmark_api_response_time.py [--base-url URL] [--requests N]
Requires the API to be running (e.g. python api.py).
"""
import argparse
import time
import urllib.request
import urllib.error
import json
import ssl

def parse():
    p = argparse.ArgumentParser(description="Benchmark API chat response time")
    p.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    p.add_argument("--requests", type=int, default=5, help="Number of chat requests to run")
    return p.parse_args()


def req(method: str, url: str, body: dict | None = None, token: str | None = None) -> tuple[dict | None, float]:
    """Return (response_json_or_None, duration_seconds)."""
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120, context=ssl.create_default_context()) as r:
            out = json.loads(r.read().decode()) if r.length else None
    except urllib.error.HTTPError as e:
        out = None
        try:
            err = e.read().decode()
            print(f"  HTTP {e.code}: {err[:200]}")
        except Exception:
            pass
    duration = time.perf_counter() - start
    return out, duration


def main():
    args = parse()
    base = args.base_url.rstrip("/")
    n = args.requests

    print(f"API base: {base}")
    print(f"Chat requests: {n}\n")

    # Register a benchmark user (or login if exists)
    username = "benchmark_user_response_time"
    password = "benchmark_pass_12345"
    reg, t_reg = req("POST", f"{base}/api/register", {
        "username": username,
        "email": "benchmark_response@example.com",
        "password": password,
    })
    if reg is None:
        login, t_login = req("POST", f"{base}/api/login", {"username": username, "password": password})
        if login is None or "token" not in login:
            print("Failed to register or login. Is the API running and DB ready?")
            return 1
        token = login["token"]
        print(f"Logged in ({t_login:.2f}s)")
    else:
        login, t_login = req("POST", f"{base}/api/login", {"username": username, "password": password})
        token = login.get("token") if login else None
        if not token:
            print("Login failed after register")
            return 1
        print(f"Registered and logged in ({t_login:.2f}s)")

    # Chat requests
    times = []
    for i in range(n):
        _, dur = req("POST", f"{base}/api/chat", {"message": "Hi, say one short sentence."}, token=token)
        times.append(dur)
        print(f"  Request {i+1}/{n}: {dur:.2f}s")

    if not times:
        print("No successful chat requests.")
        return 1

    times.sort()
    avg = sum(times) / len(times)
    p50 = times[len(times) // 2] if times else 0
    p95 = times[int(len(times) * 0.95)] if len(times) > 1 else times[0]

    print("\n--- Response time summary ---")
    print(f"  Average: {avg:.2f}s")
    print(f"  p50:     {p50:.2f}s")
    print(f"  p95:     {p95:.2f}s")
    print(f"  Min/Max: {min(times):.2f}s / {max(times):.2f}s")
    return 0


if __name__ == "__main__":
    exit(main())
