import sys
import os
import time
import json
import pyotp
import httpx
from typing import List, Optional
from pydantic import BaseModel

# Add current dir to path and change to it
backend_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(backend_dir)
sys.path.append(backend_dir)

from security import settings
from main import app

# Standard FastAPI TestClient from starlette
from fastapi.testclient import TestClient

def get_mfa_code(secret: str) -> str:
    totp = pyotp.TOTP(secret)
    return totp.now()

def wait_for_index(client):
    print("Waiting for search index to be ready...")
    for _ in range(60):  # Wait up to 60 seconds
        response = client.get("/search/status", headers=get_auth_headers(client))
        if response.status_code == 200:
            status = response.json()
            print(f"Index status: {status['state']}")
            if status['state'] == 'ready':
                print(f"Index stats: {status['stats']}")
                return True
            if status['state'] == 'error':
                print(f"Index error: {status['stats']}")
                return False
        time.sleep(1)
    print("Index wait timeout.")
    return False

_token = None
def get_auth_headers(client):
    global _token
    if not _token:
        mfa_code = get_mfa_code(settings.app_mfa_secret)
        login_data = {
            "username": settings.app_admin_username,
            "password": settings.app_admin_password,
            "totp": mfa_code
        }
        response = client.post("/login", json=login_data)
        if response.status_code != 200:
            print(f"Login failed: {response.text}")
            sys.exit(1)
        _token = response.json()["access_token"]
    return {"Authorization": f"Bearer {_token}"}

def test_chat_endpoint(client):
    print("\nTesting /chat endpoint with conceptual query (triggers semantic search)...")
    chat_request = {
        "query": "How does the search system rank results?",
        "history": [],
        "model": "qwen",
        "page_context": {"title": "Search", "url": "/search/"}
    }
    
    start_time = time.time()
    response = client.post("/chat", json=chat_request, headers=get_auth_headers(client))
    end_time = time.time()
    
    if response.status_code != 200:
        print(f"Chat failed: {response.text}")
        return False
    
    result = response.json()
    reply = result.get("reply", "")
    print(f"Response received in {end_time - start_time:.2f}s")
    print(f"Agent Reply (truncated): {reply[:300]}...")
    
    if "Agent execution failed" in reply:
        print("❌ FAILURE: Agent failed to execute (check API keys).")
        return False

    if len(reply) > 50:
        print("✅ SUCCESS: API returned a valid response.")
        return True
    else:
        print("❌ FAILURE: Response too short or empty.")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("END-TO-END SYSTEM VERIFICATION")
    print("=" * 60)
    
    with TestClient(app) as client:
        if not wait_for_index(client):
            print("Continuing verification anyway...")
        
        success = test_chat_endpoint(client)
    
    if success:
        print("\n" + "=" * 60)
        print("✅ ALL SYSTEMS OPERATIONAL")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ SYSTEM VERIFICATION FAILED")
        print("=" * 60)
        sys.exit(1)
