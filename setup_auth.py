"""
One-time Kroger OAuth setup script.
Run this to authorize with your Kroger account and save the refresh token.
"""
import threading
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests

from config import (
    KROGER_CLIENT_ID,
    KROGER_CLIENT_SECRET,
    KROGER_REDIRECT_URI,
    KROGER_AUTHORIZE_URL,
    KROGER_TOKEN_URL,
)

AUTH_CODE = None
SERVER_DONE = threading.Event()


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global AUTH_CODE
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            AUTH_CODE = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Authorization successful! You can close this tab.</h2>")
        else:
            error = params.get("error", ["unknown"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<h2>Authorization failed: {error}</h2>".encode())

        SERVER_DONE.set()

    def log_message(self, format, *args):
        pass  # suppress request logs


def build_auth_url():
    params = {
        "client_id": KROGER_CLIENT_ID,
        "redirect_uri": KROGER_REDIRECT_URI,
        "response_type": "code",
        "scope": "cart.basic:write profile.compact",
    }
    return f"{KROGER_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(code):
    resp = requests.post(
        KROGER_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": KROGER_REDIRECT_URI,
        },
        auth=(KROGER_CLIENT_ID, KROGER_CLIENT_SECRET),
    )
    resp.raise_for_status()
    return resp.json()


def save_refresh_token(refresh_token):
    config_path = "config.py"
    with open(config_path, "r") as f:
        content = f.read()

    if "KROGER_REFRESH_TOKEN" in content:
        import re
        content = re.sub(
            r'KROGER_REFRESH_TOKEN\s*=\s*"[^"]*"',
            f'KROGER_REFRESH_TOKEN = "{refresh_token}"',
            content,
        )
    else:
        content += f'\nKROGER_REFRESH_TOKEN = "{refresh_token}"\n'

    with open(config_path, "w") as f:
        f.write(content)


if __name__ == "__main__":
    parsed = urllib.parse.urlparse(KROGER_REDIRECT_URI)
    port = parsed.port or 80

    server = HTTPServer(("localhost", port), CallbackHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()

    auth_url = build_auth_url()
    print(f"Opening browser for Kroger login...")
    print(f"URL: {auth_url}\n")
    webbrowser.open(auth_url)

    SERVER_DONE.wait(timeout=120)
    thread.join()

    if not AUTH_CODE:
        print("No authorization code received. Did the browser open?")
        raise SystemExit(1)

    print("Authorization code received. Exchanging for tokens...")
    token_data = exchange_code(AUTH_CODE)

    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        print("No refresh token in response:", token_data)
        raise SystemExit(1)

    save_refresh_token(refresh_token)
    print("Refresh token saved to config.py.")
    print("\nSetup complete! You can now run server.py.")
