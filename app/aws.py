# app/aws.py
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Query, HTTPException
from starlette.concurrency import run_in_threadpool
import boto3, json

# Pricing API is only in us-east-1
pricing = boto3.client("pricing", region_name="us-east-1")
router = APIRouter(prefix="/aws", tags=["aws"])

# Map region codes -> AWS "location" (marketing) names used by Pricing
REGION_CODE_TO_LOCATION = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "ca-central-1": "Canada (Central)",
    "eu-central-1": "EU (Frankfurt)",
    "eu-west-1": "EU (Ireland)",
    "eu-west-2": "EU (London)",
    "eu-west-3": "EU (Paris)",
    "eu-north-1": "EU (Stockholm)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-east-1": "Asia Pacific (Hong Kong)",
    "sa-east-1": "South America (São Paulo)",
    # add more as needed
}

def to_location(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    v = val.strip()
    # accept either region code or already a marketing name
    return REGION_CODE_TO_LOCATION.get(v, v)

def build_filters(
    location: Optional[str],
    instance_type: Optional[str],
    operating_system: Optional[str],
    tenancy: Optional[str],
    pre_installed_sw: Optional[str],
    capacity_status: Optional[str],
) -> List[Dict[str, str]]:
    fs: List[Dict[str, str]] = []
    if location:
        fs.append({"Type": "TERM_MATCH", "Field": "location", "Value": location})
    if instance_type:
        fs.append({"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type})
    if operating_system:
        fs.append({"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": operating_system})
    if tenancy:
        fs.append({"Type": "TERM_MATCH", "Field": "tenancy", "Value": tenancy})
    if pre_installed_sw:
        fs.append({"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": pre_installed_sw})
    if capacity_status:
        fs.append({"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": capacity_status})
    return fs

def get_products_paginated(service_code: str, filters: List[Dict[str, str]], max_pages: int) -> List[str]:
    items: List[str] = []
    token: Optional[str] = None
    pages = 0
    while pages < max_pages:
        kwargs = {"ServiceCode": service_code, "FormatVersion": "aws_v1", "Filters": filters}
        if token:
            kwargs["NextToken"] = token
        resp = pricing.get_products(**kwargs)
        items.extend(resp.get("PriceList", []))
        token = resp.get("NextToken")
        pages += 1
        if not token:
            break
    return items

def parse_on_demand(items: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for raw in items:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        product = obj.get("product", {})
        attrs = product.get("attributes", {})
        terms = obj.get("terms", {})
        price_hr = None
        ondemand = terms.get("OnDemand", {})
        for _, term in ondemand.items():
            for _, dim in term.get("priceDimensions", {}).items():
                unit = (dim.get("unit") or "").lower()
                usd = dim.get("pricePerUnit", {}).get("USD")
                if usd and unit.startswith("hr"):
                    price_hr = float(usd)
                    break
            if price_hr is not None:
                break
        out.append(
            {
                "sku": product.get("sku"),
                "attributes": {
                    "servicecode": attrs.get("servicecode"),
                    "location": attrs.get("location"),
                    "instanceType": attrs.get("instanceType"),
                    "operatingSystem": attrs.get("operatingSystem"),
                    "tenancy": attrs.get("tenancy"),
                    "preInstalledSw": attrs.get("preInstalledSw"),
                    "capacitystatus": attrs.get("capacitystatus"),
                    "vcpu": attrs.get("vcpu"),
                    "memory": attrs.get("memory"),
                },
                "ondemand_price_hour_usd": price_hr,
            }
        )
    return out

@router.get("/prices")
async def get_prices(
    service_code: str = Query("AmazonEC2", description="e.g., AmazonEC2, AmazonS3, AmazonRDS"),
    region: Optional[str] = Query(None, description="Region code (e.g., us-west-2) or marketing name (e.g., 'US West (Oregon)')"),
    instance_type: Optional[str] = Query(None, description="EC2 instanceType, e.g., m7g.xlarge"),
    operating_system: Optional[str] = Query(None, description="Linux/Windows"),
    tenancy: Optional[str] = Query(None, description="Shared/Dedicated/Host"),
    pre_installed_sw: Optional[str] = Query(None, description="NA / SQL Server, etc."),
    capacity_status: Optional[str] = Query(None, description="Used, etc."),
    max_pages: int = Query(1, ge=1, le=10),
    raw: bool = Query(False, description="Return raw AWS PriceList elements"),
):
    # convert region code -> marketing name if needed
    location = to_location(region)
    filters = build_filters(location, instance_type, operating_system, tenancy, pre_installed_sw, capacity_status)

    # boto3 is blocking; run in a thread so FastAPI stays async-friendly
    items = await run_in_threadpool(get_products_paginated, service_code, filters, max_pages)
    if raw:
        return {"count": len(items), "items": [json.loads(i) for i in items]}
    # simplified view like Azure endpoint
    return {"count": len(items), "items": parse_on_demand(items)}
