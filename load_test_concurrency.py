#!/usr/bin/env python3
"""Load unit test: send concurrent POSTs to /webhook and report results."""
import sys
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

URL = "http://localhost:5000/webhook"

def send(i):
    payload = {
        "event": "messages.upsert",
        "instance": "load-test",
        "data": {
            "key": {"remoteJid": f"loadtest-{i}@whatsapp.net", "fromMe": False, "id": f"LOADTEST-{i}"},
            "pushName": "LoadTester",
            "message": {"conversation": f"mensaje concurrente {i}"}
        }
    }
    try:
        r = requests.post(URL, json=payload, timeout=15)
        return i, r.status_code, r.text
    except Exception as e:
        return i, None, str(e)

def main():
    total = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    concurrency = int(sys.argv[2]) if len(sys.argv) > 2 else total
    print(f"Sending {total} requests with concurrency={concurrency} to {URL}")
    start = time.time()

    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {ex.submit(send, i): i for i in range(1, total+1)}
        for fut in as_completed(futures):
            i, status, text = fut.result()
            results.append((i, status, text))
            snippet = text[:200].replace('\n',' ')
            print(f"{i:03d}: status={status} resp={snippet}")

    duration = time.time() - start
    success = sum(1 for _, s, _ in results if s and 200 <= s < 300)
    print(f"Done: {success}/{total} successful in {duration:.2f}s")

if __name__ == '__main__':
    main()
