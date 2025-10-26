from typing import Optional
from fastapi import APIRouter, Query, HTTPException
import httpx
from urllib.parse import urlencode

router = APIRouter(prefix="/azure", tags=["azure"])
BASE = "https://prices.azure.com/api/retail/prices"

async def fetch(query: str, max_pages: int):
    items = []
    url = f"{BASE}?{query}" if query else BASE
    async with httpx.AsyncClient(timeout=20.0) as client:
        pages = 0
        while url and pages < max_pages:
            r = await client.get(url)
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=r.text)
            data = r.json()
            items.extend(data.get("Items", []))
            url = data.get("NextPageLink")
            pages += 1
    return items

@router.get("/prices")
async def get_prices(
    service_name: Optional[str] = Query(None),
    arm_region_name: Optional[str] = Query(None),
    sku_name: Optional[str] = Query(None),
    meter_name: Optional[str] = Query(None),
    price_type: Optional[str] = Query(None),
    currency_code: Optional[str] = Query(None),
    max_pages: int = Query(1, ge=1, le=10),
):
    filters = []
    if service_name:    filters.append(f"serviceName eq '{service_name}'")
    if arm_region_name: filters.append(f"armRegionName eq '{arm_region_name}'")
    if sku_name:        filters.append(f"skuName eq '{sku_name}'")
    if meter_name:      filters.append(f"meterName eq '{meter_name}'")
    if price_type:      filters.append(f"priceType eq '{price_type}'")
    if currency_code:   filters.append(f"currencyCode eq '{currency_code}'")

    query = urlencode({"$filter": " and ".join(filters)}, safe=" '") if filters else ""
    items = await fetch(query, max_pages)
    return {"count": len(items), "items": items}
