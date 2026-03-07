from mcp.server.fastmcp import FastMCP
import requests

from auth import AuthManager
from config import (
    KROGER_CLIENT_ID,
    KROGER_CLIENT_SECRET,
    KROGER_LOCATIONS_URL,
    KROGER_PRODUCTS_URL,
    KROGER_CART_API_URL,
    KROGER_REDIRECT_URI,
    KROGER_REFRESH_TOKEN,
)

mcp = FastMCP("kroger-mcp-server")

auth_manager = AuthManager(client_id=KROGER_CLIENT_ID, client_secret=KROGER_CLIENT_SECRET)
auth_manager.user_refresh_token = KROGER_REFRESH_TOKEN


@mcp.tool()
def find_stores(zip_code: str, radius_miles: int = 10, limit: int = 5) -> list | dict:
    """Find Kroger/King Soopers store locations near a ZIP code. Returns store IDs, names, and addresses."""
    token = auth_manager.get_app_token()
    if not token:
        return {"error": "Failed to obtain access token."}

    resp = requests.get(
        KROGER_LOCATIONS_URL,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params={
            "filter.zipCode.near": zip_code,
            "filter.radiusInMiles": radius_miles,
            "filter.limit": limit,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


@mcp.tool()
def search_products(query: str, location_id: str, limit: int = 10) -> list | dict:
    """Search Kroger products by keyword at a specific store. Returns product IDs, names, and prices."""
    token = auth_manager.get_app_token()
    if not token:
        return {"error": "Failed to obtain access token."}

    resp = requests.get(
        KROGER_PRODUCTS_URL,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params={
            "filter.term": query,
            "filter.locationId": location_id,
            "filter.limit": limit,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


@mcp.tool()
def get_product(product_id: str, location_id: str) -> dict:
    """Get detailed product info (price, size, stock, fulfillment) by product ID at a specific store."""
    token = auth_manager.get_app_token()
    if not token:
        return {"error": "Failed to obtain access token."}

    resp = requests.get(
        f"{KROGER_PRODUCTS_URL}/{product_id}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params={"filter.locationId": location_id},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    if isinstance(data, list):
        return data[0] if data else {}
    return data


@mcp.tool()
def add_to_cart(product_id: str, quantity: int, location_id: str) -> dict:
    """Add a product to the user's Kroger/King Soopers cart. Requires prior user authorization."""
    token = auth_manager.get_user_token()
    if not token:
        return {"error": "User not authenticated. Run setup_auth.py to authorize."}

    resp = requests.put(
        KROGER_CART_API_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={"items": [{"upc": product_id, "quantity": quantity}]},
        timeout=15,
    )
    resp.raise_for_status()

    if resp.status_code == 204:
        return {"success": True, "message": "Item added to cart successfully."}
    try:
        return {"success": True, "data": resp.json()}
    except ValueError:
        return {"success": True, "message": f"Item added (status {resp.status_code})."}


if __name__ == "__main__":
    mcp.run()
