from mcp.server.fastmcp import FastMCP
import requests

from auth import AuthManager
from compact import compact_product
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

DEFAULT_LOCATION = "62000150"
# The products endpoint accepts up to 50 product IDs per request.
PRODUCT_BATCH = 50
CART_BATCH = 25

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
def search_products(
    query: str,
    location_id: str = DEFAULT_LOCATION,
    limit: int = 10,
    compact: bool = True,
    ingredients: bool = False,
) -> list | dict:
    """Search Kroger products by keyword at a specific store (1-2 word queries work best).

    Returns compact rows by default: upc, desc, size, price, promo, stock (stockLevel),
    delivery, in_store, key nutrients (sat_fat_g, sodium_mg, added_sugar_g, protein_g,
    fiber_g) and "flags" for banned ingredients. Set ingredients=True to include the
    ingredient statement, or compact=False for the raw API payload (~5k tokens/product).
    """
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
    data = resp.json().get("data", [])
    if not compact:
        return data
    return [compact_product(p, ingredients) for p in data]


@mcp.tool()
def get_product(
    product_id: str,
    location_id: str = DEFAULT_LOCATION,
    compact: bool = True,
    ingredients: bool = True,
) -> dict:
    """Get one product by UPC/product ID at a store. Compact row by default (with the
    ingredient statement); compact=False returns the raw payload. For more than one
    product, use check_products instead."""
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
        data = data[0] if data else {}
    if not compact or not data:
        return data
    return compact_product(data, ingredients)


@mcp.tool()
def check_products(
    product_ids: list[str],
    location_id: str = DEFAULT_LOCATION,
    ingredients: bool = False,
) -> dict:
    """Check many products at once by UPC/product ID (any number; batched 50 per request).

    Returns {"results": [compact rows in input order], "missing": [IDs the store didn't
    return]}. A missing ID usually means the store doesn't carry it. Use this to verify
    the weekly staples and recipe picks in one call instead of many get_product calls.
    """
    token = auth_manager.get_app_token()
    if not token:
        return {"error": "Failed to obtain access token."}

    ids = list(dict.fromkeys(str(pid).strip() for pid in product_ids if str(pid).strip()))
    found = {}
    for start in range(0, len(ids), PRODUCT_BATCH):
        chunk = ids[start:start + PRODUCT_BATCH]
        resp = requests.get(
            KROGER_PRODUCTS_URL,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={
                "filter.productId": ",".join(chunk),
                "filter.locationId": location_id,
                "filter.limit": len(chunk),
            },
            timeout=20,
        )
        resp.raise_for_status()
        for product in resp.json().get("data", []):
            row = compact_product(product, ingredients)
            found[row.get("upc")] = row

    return {
        "results": [found[i] for i in ids if i in found],
        "missing": [i for i in ids if i not in found],
    }


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


@mcp.tool()
def add_items_to_cart(items: list[dict], location_id: str = DEFAULT_LOCATION) -> dict:
    """Add many products to the cart in one call. items = [{"upc": "...", "quantity": 1}, ...].

    There is no delete endpoint, so the whole list is validated first: duplicate UPCs or
    bad quantities reject the call before anything is added. Items are sent in batches of
    25. A batch that times out is reported as "unknown" (it may have gone through), so
    check the app before re-sending it.
    """
    token = auth_manager.get_user_token()
    if not token:
        return {"error": "User not authenticated. Run setup_auth.py to authorize."}

    cleaned, problems, seen = [], [], set()
    for entry in items:
        upc = str(entry.get("upc") or entry.get("product_id") or "").strip()
        qty = entry.get("quantity", 1)
        if not upc:
            problems.append(f"missing upc: {entry}")
        elif upc in seen:
            problems.append(f"duplicate upc {upc}: combine the quantities into one line")
        elif not isinstance(qty, int) or qty < 1:
            problems.append(f"bad quantity for {upc}: {qty!r}")
        else:
            seen.add(upc)
            cleaned.append({"upc": upc, "quantity": qty})
    if problems:
        return {"error": "Nothing was added.", "problems": problems}

    added, failed, unknown = [], [], []
    for start in range(0, len(cleaned), CART_BATCH):
        chunk = cleaned[start:start + CART_BATCH]
        try:
            resp = requests.put(
                KROGER_CART_API_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={"items": chunk},
                timeout=30,
            )
        except requests.exceptions.Timeout:
            unknown.extend(chunk)
            continue
        except requests.exceptions.RequestException as exc:
            failed.extend({**i, "error": str(exc)} for i in chunk)
            continue
        if resp.ok:
            added.extend(chunk)
        else:
            failed.extend({**i, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"} for i in chunk)

    return {
        "added_lines": len(added),
        "added_units": sum(i["quantity"] for i in added),
        "failed": failed,
        "unknown_timed_out": unknown,
    }


if __name__ == "__main__":
    mcp.run()
