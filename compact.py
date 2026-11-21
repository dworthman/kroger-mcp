"""Compact product rows for the Kroger MCP server.

Raw Kroger product payloads are ~5k tokens each (images, aisle data, every
nutrient). The weekly cart workflow only needs a handful of fields, so these
helpers turn a product into one small dict, and flag ingredients the household
avoids.
"""

import re

# Ingredients the household never buys. Matched case-insensitively against the
# ingredient statement; a hit is reported in "flags", never silently dropped.
BANNED_PATTERNS = {
    "carrageenan": r"carrageenan",
    "mono/diglycerides": r"mono\s*-?\s*(and|&)?\s*-?\s*diglycerides|monoglycerides|diglycerides",
    "stevia": r"stevia|rebaudioside|reb[\s-]?a\b",
    "monk fruit": r"monk\s*fruit|luo han guo",
    "erythritol": r"erythritol",
    "sucralose": r"sucralose",
    "xylitol": r"xylitol",
    "allulose": r"allulose",
    "aspartame": r"aspartame",
    "acesulfame": r"acesulfame",
    "artificial color": r"\b(red|yellow|blue|green)\s*(no\.?\s*)?\d+\b|artificial colou?rs?",
}

# Nutrients worth surfacing, keyed by the API's displayName.
NUTRIENTS = {
    "Saturated Fat": "sat_fat_g",
    "Sodium": "sodium_mg",
    "Added Sugar": "added_sugar_g",
    "Protein": "protein_g",
    "Dietary Fiber": "fiber_g",
}


def _nutrition(product):
    info = product.get("nutritionInformation") or []
    return info[0] if info else {}


def ingredient_flags(statement):
    if not statement:
        return []
    text = statement.lower()
    return [name for name, pattern in BANNED_PATTERNS.items() if re.search(pattern, text)]


def compact_product(product, ingredients=False):
    item = (product.get("items") or [{}])[0]
    price = item.get("price") or {}
    fulfillment = item.get("fulfillment") or {}
    nutrition = _nutrition(product)
    statement = nutrition.get("ingredientStatement") or ""

    row = {
        "upc": product.get("upc") or product.get("productId"),
        "desc": product.get("description"),
        "size": item.get("size"),
        "price": price.get("regular"),
        "promo": price.get("promo") or None,
        # No stockLevel usually means the item is unavailable; fresh seafood,
        # bananas and a few others never report one.
        "stock": (item.get("inventory") or {}).get("stockLevel"),
        "delivery": fulfillment.get("delivery"),
        "in_store": fulfillment.get("inStore"),
    }

    serving = nutrition.get("servingSize") or {}
    if serving:
        unit = (serving.get("unitOfMeasure") or {}).get("name", "")
        row["serving"] = f"{serving.get('quantity', '')} {unit}".strip()
    for nutrient in nutrition.get("nutrients") or []:
        key = NUTRIENTS.get(nutrient.get("displayName"))
        if key and nutrient.get("quantity") is not None:
            row[key] = nutrient["quantity"]

    flags = ingredient_flags(statement)
    if flags:
        row["flags"] = flags
    if ingredients:
        row["ingredients"] = statement[:400] or None

    return {k: v for k, v in row.items() if v not in (None, "")}
