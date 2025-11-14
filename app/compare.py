# app/compare.py
from typing import Optional, Literal, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query
import httpx
import math

router = APIRouter(prefix="/compare", tags=["compare"])

# ---------- Region mapping (AWS code -> Azure armRegionName) ----------
AWS_TO_AZURE_REGION = {
    "us-east-1": "eastus",
    "us-east-2": "eastus2",
    "us-west-1": "westus",
    "us-west-2": "westus2",
    "ca-central-1": "canadacentral",
    "eu-west-1": "westeurope",
    "eu-west-2": "uksouth",
    "eu-west-3": "francecentral",
    "eu-north-1": "northeurope",
    "eu-central-1": "germanywestcentral",
    "ap-south-1": "centralindia",
    "ap-southeast-1": "southeastasia",
    "ap-southeast-2": "australiaeast",
    "ap-northeast-1": "japaneast",
    "ap-northeast-2": "koreacentral",
    "ap-east-1": "eastasia",
    "sa-east-1": "brazilsouth",
}

def map_azure_region(aws_region: str, azure_region: Optional[str]) -> str:
    if azure_region and azure_region.strip():
        return azure_region.strip()
    return AWS_TO_AZURE_REGION.get(aws_region.strip(), aws_region.strip())

# ---------- Helpers ----------
def _min_nonzero_or_none(vals: List[float]) -> Optional[float]:
    # Sometimes the feeds contain 0 or absurd values; pick the smallest > 0 if present
    candidates = [v for v in vals if isinstance(v, (int, float)) and v is not None and v > 0]
    if candidates:
        return min(candidates)
    # If nothing > 0, fall back to min as-is
    vals = [v for v in vals if v is not None]
    return min(vals) if vals else None

async def _min_price_from_aws(client: httpx.AsyncClient, **params) -> Optional[float]:
    # Always request raw for flexible parsing across services
    q = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
    url = f"http://127.0.0.1:8000/aws/prices?{q}&raw=true"
    r = await client.get(url)
    if r.status_code != 200:
        return None
    data = r.json()
    prices: List[float] = []
    for item in data.get("items", []):
        try:
            terms = item.get("terms", {})
            ondemand = terms.get("OnDemand", {})
            for _, term in ondemand.items():
                for _, dim in term.get("priceDimensions", {}).items():
                    usd = dim.get("pricePerUnit", {}).get("USD")
                    if usd is not None:
                        prices.append(float(usd))
        except Exception:
            continue
    return _min_nonzero_or_none(prices)

async def _min_price_from_azure(client: httpx.AsyncClient, **filters) -> Optional[float]:
    q = "&".join(f"{k}={v}" for k, v in filters.items() if v is not None)
    url = f"http://127.0.0.1:8000/azure/prices?{q}"
    r = await client.get(url)
    if r.status_code != 200:
        return None
    data = r.json()
    prices = []
    for it in data.get("items", []):
        p = it.get("retailPrice")
        if p is not None:
            try:
                prices.append(float(p))
            except Exception:
                pass
    return _min_nonzero_or_none(prices)

def _fallback_zero(v: Optional[float]) -> float:
    return float(v) if (v is not None and not math.isnan(float(v))) else 0.0

def _cheapest(a: Optional[float], z: Optional[float]) -> str:
    if a is None and z is None:
        return "Same"
    if a is None:
        return "Azure"
    if z is None:
        return "AWS"
    if a < z:
        return "AWS"
    if z < a:
        return "Azure"
    return "Same"

# ---------- 1) Unified VM/Storage compare ----------
@router.post("/service")
async def compare_service(
    service_type: Literal["vm", "storage"] = Query("vm", description="Service to compare: VM (compute) or Storage"),
    region: str = Query(..., description="AWS region code (e.g., us-west-2)"),
    # Optional override for Azure region; if omitted we map from AWS region
    azure_region: Optional[str] = Query(None, description="Azure region (e.g., westus2)"),
    # VM-only knobs
    instance_type: str = Query("t3.micro", description="AWS EC2 instance type (VM only)"),
    azure_sku: str = Query("B1s", description="Azure VM skuName (VM only). Examples: B1s, D2 v5, D2as v5"),
    max_pages: int = Query(1, ge=1, le=5, description="How many pricing pages to scan"),
):
    az_region = map_azure_region(region, azure_region)

    async with httpx.AsyncClient(timeout=30.0) as client:
        if service_type == "vm":
            aws_price = await _min_price_from_aws(
                client,
                service_code="AmazonEC2",
                region=region,
                instance_type=instance_type,
                operating_system="Linux",
                max_pages=max_pages,
            )
            # Prefer sku match; if sparse, also try generic region query
            azure_price = await _min_price_from_azure(
                client,
                service_name="Virtual%20Machines",
                arm_region_name=az_region,
                sku_name=azure_sku,
                max_pages=max_pages,
            )
            if azure_price is None:
                azure_price = await _min_price_from_azure(
                    client,
                    service_name="Virtual%20Machines",
                    arm_region_name=az_region,
                    max_pages=max_pages,
                )
        else:
            # Storage (broad min price within region)
            aws_price = await _min_price_from_aws(
                client, service_code="AmazonS3", region=region, max_pages=max_pages
            )
            azure_price = await _min_price_from_azure(
                client, service_name="Storage", arm_region_name=az_region, max_pages=max_pages
            )

    cheapest = _cheapest(aws_price, azure_price)
    return {
        "inputs": {
            "service_type": service_type,
            "region_entered": region,
            "aws_region": region,
            "azure_region": az_region,
            **({"instance_type": instance_type, "azure_sku": azure_sku} if service_type == "vm" else {})
        },
        "aws": {"price_usd": aws_price},
        "azure": {"price_usd": azure_price},
        "cheapest_provider": cheapest,
    }

# ---------- 2) Relational SQL (RDS vs Azure SQL) with fallback 0.0 ----------
@router.get("/db-sql")
async def compare_db_sql(
    region: str = Query(..., description="AWS region code, e.g., us-west-2"),
    azure_region: Optional[str] = Query(None, description="Azure region, e.g., westus2 (optional)"),
    database_engine: Literal["MySQL", "PostgreSQL", "MariaDB", "SQL Server", "Oracle"] = Query("MySQL"),
    deployment_option: Literal["Single-AZ", "Multi-AZ"] = Query("Single-AZ"),
    license_model: Literal["License included", "BYOL"] = Query("License included"),
    # Azure knobs
    sku_name: str = Query("GP_Gen5_2", description="Azure SQL DB SKU (e.g., GP_Gen5_2, HS_Gen5_2, etc.)"),
    max_pages: int = Query(1, ge=1, le=5)
):
    az_region = map_azure_region(region, azure_region)
    async with httpx.AsyncClient(timeout=30.0) as client:
        aws_price = await _min_price_from_aws(
            client,
            service_code="AmazonRDS",
            region=region,
            database_engine=database_engine,
            deployment_option=deployment_option,
            license_model=license_model,
            max_pages=max_pages,
        )
        azure_price = await _min_price_from_azure(
            client,
            service_name="SQL%20Database",
            arm_region_name=az_region,
            sku_name=sku_name,
            max_pages=max_pages,
        )
        if azure_price is None:
            azure_price = await _min_price_from_azure(
                client,
                service_name="SQL%20Database",
                arm_region_name=az_region,
                max_pages=max_pages,
            )

    # Fallback to 0.0 if a side is missing
    aws_out = _fallback_zero(aws_price)
    azure_out = _fallback_zero(azure_price)

    # Cheapest based on the *original* values (so 0.0 fallback doesn't bias winners)
    cheapest = _cheapest(aws_price, azure_price)

    return {
        "inputs": {
            "region": region,
            "azure_region": az_region,
            "database_engine": database_engine,
            "deployment_option": deployment_option,
            "license_model": license_model,
            "azure_sku": sku_name,
        },
        "aws": {"service": "AmazonRDS", "price_usd": aws_out},
        "azure": {"service": "SQL Database", "price_usd": azure_out},
        "cheapest_provider": cheapest,
    }

# ---------- 3) Internet Egress (Data Transfer Out) ----------
@router.get("/egress")
async def compare_egress(
    region: str = Query(..., description="AWS region code, e.g., us-west-2"),
    azure_region: Optional[str] = Query(None, description="Azure region, e.g., westus2"),
    max_pages: int = Query(1, ge=1, le=5)
):
    az_region = map_azure_region(region, azure_region)
    async with httpx.AsyncClient(timeout=30.0) as client:
        aws_price = await _min_price_from_aws(
            client, service_code="AmazonEC2", region=region, max_pages=max_pages
        )
        azure_price = await _min_price_from_azure(
            client, service_name="Bandwidth", arm_region_name=az_region, max_pages=max_pages
        )

    cheapest = _cheapest(aws_price, azure_price)
    return {
        "inputs": {"aws_region": region, "azure_region": az_region},
        "aws": {"service": "AmazonEC2 (Data Transfer)", "price_usd": aws_price},
        "azure": {"service": "Bandwidth", "price_usd": azure_price},
        "cheapest_provider": cheapest,
    }

# ---------- 4) Block Storage (EBS vs Managed Disks) ----------
@router.get("/block-storage")
async def compare_block_storage(
    region: str = Query(..., description="AWS region code, e.g., us-west-2"),
    azure_region: Optional[str] = Query(None, description="Azure region, e.g., westus2"),
    # Optional hint filters
    volume_type: Optional[str] = Query("gp3", description="AWS EBS volumeType hint (gp3/gp2/io1/io2/st1/sc1)"),
    sku_name: Optional[str] = Query(None, description="Azure disk SKU (e.g., P10, E10, S10)"),
    max_pages: int = Query(1, ge=1, le=5)
):
    az_region = map_azure_region(region, azure_region)
    async with httpx.AsyncClient(timeout=30.0) as client:
        aws_price = await _min_price_from_aws(
            client, service_code="AmazonEC2", region=region, volume_type=volume_type, max_pages=max_pages
        )
        azure_price = await _min_price_from_azure(
            client, service_name="Storage", arm_region_name=az_region,
            **({"sku_name": sku_name} if sku_name else {}),
            max_pages=max_pages
        )

    if aws_price is None and azure_price is None:
        raise HTTPException(status_code=404, detail="No block storage pricing found")

    cheapest = _cheapest(aws_price, azure_price)
    return {
        "inputs": {
            "aws_region": region, "azure_region": az_region,
            "aws_volume_type": volume_type, "azure_disk_sku": sku_name
        },
        "aws": {"service": "Amazon EBS (via EC2 pricing)", "price_usd": aws_price},
        "azure": {"service": "Managed Disks (via Storage)", "price_usd": azure_price},
        "cheapest_provider": cheapest,
    }

# ---------- 5) Load Balancer (ELB vs Azure LB) with fallback 0.0 ----------
@router.get("/load-balancer")
async def compare_load_balancer(
    region: str = Query(..., description="AWS region code, e.g., us-west-2"),
    azure_region: Optional[str] = Query(None, description="Azure region, e.g., westus2"),
    max_pages: int = Query(1, ge=1, le=5)
):
    az_region = map_azure_region(region, azure_region)
    async with httpx.AsyncClient(timeout=30.0) as client:
        aws_price = await _min_price_from_aws(
            client, service_code="AWSELB", region=region, max_pages=max_pages
        )
        azure_price = await _min_price_from_azure(
            client, service_name="Load%20Balancer", arm_region_name=az_region, max_pages=max_pages
        )

    # Fallback to 0.0 if missing
    aws_out = _fallback_zero(aws_price)
    azure_out = _fallback_zero(azure_price)

    cheapest = _cheapest(aws_price, azure_price)
    return {
        "inputs": {"aws_region": region, "azure_region": az_region},
        "aws": {"service": "Elastic Load Balancing", "price_usd": aws_out},
        "azure": {"service": "Load Balancer", "price_usd": azure_out},
        "cheapest_provider": cheapest,
    }

# ---------- 6) DNS (Route 53 vs Azure DNS) ----------
@router.get("/dns")
async def compare_dns(
    region: str = Query(..., description="AWS region code (pricing still varies by product), e.g., us-west-2"),
    azure_region: Optional[str] = Query(None, description="Azure region, e.g., westus2"),
    max_pages: int = Query(1, ge=1, le=5)
):
    az_region = map_azure_region(region, azure_region)
    async with httpx.AsyncClient(timeout=30.0) as client:
        aws_price = await _min_price_from_aws(
            client, service_code="AmazonRoute53", region=region, max_pages=max_pages
        )
        azure_price = await _min_price_from_azure(
            client, service_name="DNS", arm_region_name=az_region, max_pages=max_pages
        )

    cheapest = _cheapest(aws_price, azure_price)
    return {
        "inputs": {"aws_region": region, "azure_region": az_region},
        "aws": {"service": "Amazon Route 53", "price_usd": aws_price},
        "azure": {"service": "Azure DNS", "price_usd": azure_price},
        "cheapest_provider": cheapest,
    }

# ---------- 7) Availability zone coverage (heuristic) ----------
@router.get("/az-coverage")
async def az_coverage(
    region: str = Query(..., description="AWS region code, e.g., us-west-2"),
    azure_region: Optional[str] = Query(None, description="Azure region, e.g., westus2"),
    max_pages: int = Query(1, ge=1, le=2)
):
    """
    Heuristic: if pricing results exist for VM/Storage in a region, we assume service availability there.
    """
    az_region = map_azure_region(region, azure_region)
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Check AWS VM & Storage presence
        aws_vm = await _min_price_from_aws(client, service_code="AmazonEC2", region=region, max_pages=max_pages)
        aws_s3 = await _min_price_from_aws(client, service_code="AmazonS3", region=region, max_pages=max_pages)
        # Check Azure VM & Storage presence
        az_vm = await _min_price_from_azure(client, service_name="Virtual%20Machines", arm_region_name=az_region, max_pages=max_pages)
        az_st = await _min_price_from_azure(client, service_name="Storage", arm_region_name=az_region, max_pages=max_pages)

    return {
        "inputs": {"aws_region": region, "azure_region": az_region},
        "available": {
            "aws_vm": aws_vm is not None,
            "aws_storage": aws_s3 is not None,
            "azure_vm": az_vm is not None,
            "azure_storage": az_st is not None,
        }
    }
