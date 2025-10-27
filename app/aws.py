from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Query, HTTPException
from starlette.concurrency import run_in_threadpool
import boto3, json

# NOTE: AWS Pricing lives in us-east-1 only
pricing = boto3.client("pricing", region_name="us-east-1")
router = APIRouter(prefix="/aws", tags=["aws"])

# ---------- helpers ----------

def build_filters(
    location: Optional[str],
    instance_type: Optional[str],
    operating_system: Optional[str],
    tenancy: Optional[str],
    pre_installed_sw: Optional[str],
    capacity_status: Optional[str],
) -> List[Dict[str, str]]:
    """Build TERM_MATCH filters for AWS Pricing get_products."""
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


def get_products_paginated(
    service_code: str,
    filters: List[Dict[str, str]],
    max_pages: int,
) -> List[str]:
    """
    Call AWS Pricing get_products with pagination.
    Returns a list of JSON strings (each element is one 'PriceList' item).
    """
    items: List[str] = []
    token: Optional[str] = None
    pages = 0

    while pages < max_pages:
        kwargs = {
            "ServiceCode": service_code,
            "FormatVersion": "aws_v1",
            "Filters": filters,
        }
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
    """
    Parse AWS PriceList JSON strings and extract a simple on-demand hourly USD price if present.
    Keeps useful attributes for EC2. Works for other services too (attributes will differ).
    """
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
        term_code = None
        dim_code = None

        ondemand = terms.get("OnDemand", {})
        for tcode, term in ondemand.items():
            for dcode, dim in term.get("priceDimensions", {}).items():
                unit = (dim.get("unit") or "").lower()
                usd = dim.get("pricePerUnit", {}).get("USD")
                # Look for hourly prices (Hrs/Hours)
                if usd and unit.startswith("hr"):
                    price_hr = float(usd)
                    term_code, dim_code = tcode, dcode
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
                "term_code": term_code,
                "dimension_code": dim_code,
            }
        )
    return out

# ---------- route ----------

@router.get("/prices")
async def get_prices(
    service_code: str = Query("AmazonEC2", description="e.g., AmazonEC2, AmazonS3, AmazonRDS"),
    location: Optional[str] = Query(None, description="Marketing region name, e.g., 'US West (Oregon)'"),
    instance_type: Optional[str] = Query(None, description="EC2 instanceType, e.g., 'm7g.xlarge'"),
    operating_system: Optional[str] = Query(None, description="Linux/Windows"),
    tenancy: Optional[str] = Query(None, description="Shared/Dedicated/Host"),
    pre_installed_sw: Optional[str] = Query(None, description="NA / SQL Server, etc."),
    capacity_status: Optional[str] = Query(None, description="Used, etc."),
    max_pages: int = Query(1, ge=1, le=10),
    raw: bool = Query(False, description="Return raw AWS PriceList elements"),
    ):  
      return {"message": "AWS pricing route connected successfully!"}
