#!/usr/bin/env python3
import glob
import json
import subprocess
import sys
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent / "examples"


def extract_urls():
    urls = set()
    for file in glob.glob(str(CONFIG_DIR / "*.json")):
        with open(file, "r") as f:
            try:
                data = json.load(f)
                # Traverse nested structure for 'mcpServers' and env blocks
                if "mcpServers" in data:
                    for server in data["mcpServers"].values():
                        env = server.get("env", {})
                        url = env.get("OPENAPI_SPEC_URL")
                        if url:
                            urls.add(url)
                # Also check top-level keys just in case
                for k, v in data.items():
                    if k == "OPENAPI_SPEC_URL":
                        urls.add(v)
            except Exception as e:
                print(f"Warning: Could not parse {file}: {e}")
    return sorted(urls)


def check_url(url):
    try:
        result = subprocess.run(
            ["curl", "-I", "--max-time", "15", url], capture_output=True, text=True
        )
        status = (
            result.stdout.splitlines()[0] if result.stdout else result.stderr.strip()
        )
        ok = result.returncode == 0 and "200" in status
        return ok, status
    except Exception as e:
        return False, str(e)


def main():
    urls = extract_urls()
    if not urls:
        print("No URLs found.")
        sys.exit(1)
    print(f"Found {len(urls)} URLs to validate:\n")
    failures = 0
    for url in urls:
        ok, status = check_url(url)
        print(f"{'OK' if ok else 'FAIL'}: {url}\n    {status}")
        if not ok:
            failures += 1
    print(f"\nValidation complete. {len(urls) - failures} OK, {failures} FAIL.")
    if failures:
        sys.exit(2)


if __name__ == "__main__":
    main()
