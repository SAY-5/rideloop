"""DynamoDB access layer for driver positions.

Table layout (``driver_positions``):

    partition key  cell       geohash prefix at precision 5 (about 4.9 km x 4.9 km)
    sort key       driver_id
    attributes     geohash (precision 6), lat, lng, heading, status, trip_id,
                   updated_at (ISO 8601), ttl (epoch seconds)
    GSI            by_driver (driver_id) so a driver can be found without its cell
    TTL            ttl

A nearby lookup queries the rider's cell plus its 8 neighbors, throws away
anything whose ``ttl`` has passed (DynamoDB deletes expired items lazily, so the
read side must filter too), then ranks by haversine distance.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from rideloop_common import geohash
from rideloop_common.config import Settings, get_settings
from rideloop_common.geo import haversine_m, offset_m
from rideloop_common.models import DriverPosition, DriverStatus, NearbyDriver, utcnow

GSI_BY_DRIVER = "by_driver"

# Above this many precision-6 subcells a search just reads the whole 3x3 block of
# precision-5 partitions instead of filtering (DynamoDB's IN operator caps at 100).
MAX_SUBCELL_FILTER = 64


def dynamodb_resource(settings: Settings | None = None):
    settings = settings or get_settings()
    return boto3.resource(
        "dynamodb",
        endpoint_url=settings.dynamodb_endpoint,
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        config=Config(max_pool_connections=64, retries={"max_attempts": 3}),
    )


def dynamodb_client(settings: Settings | None = None):
    """Low-level client. Unlike ``resource.meta.client`` it does not auto-convert
    Python values, so it is the right tool for ``transact_write_items``."""
    settings = settings or get_settings()
    return boto3.client(
        "dynamodb",
        endpoint_url=settings.dynamodb_endpoint,
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        config=Config(max_pool_connections=64, retries={"max_attempts": 3}),
    )


def ensure_table(settings: Settings | None = None) -> str:
    """Create the positions table with its GSI and TTL if it does not exist."""
    settings = settings or get_settings()
    resource = dynamodb_resource(settings)
    client = resource.meta.client
    name = settings.driver_positions_table
    existing = client.list_tables()["TableNames"]
    if name not in existing:
        client.create_table(
            TableName=name,
            AttributeDefinitions=[
                {"AttributeName": "cell", "AttributeType": "S"},
                {"AttributeName": "driver_id", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "cell", "KeyType": "HASH"},
                {"AttributeName": "driver_id", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": GSI_BY_DRIVER,
                    "KeySchema": [{"AttributeName": "driver_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        client.get_waiter("table_exists").wait(TableName=name)
    ttl = client.describe_time_to_live(TableName=name)["TimeToLiveDescription"]
    if ttl.get("TimeToLiveStatus") not in ("ENABLED", "ENABLING"):
        client.update_time_to_live(
            TableName=name,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
        )
    return name


def _to_decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 7)))


def _item_to_position(item: dict[str, Any]) -> DriverPosition:
    return DriverPosition(
        driver_id=item["driver_id"],
        cell=item["cell"],
        geohash=item["geohash"],
        lat=float(item["lat"]),
        lng=float(item["lng"]),
        heading=float(item.get("heading", 0)),
        status=DriverStatus(item.get("status", "available")),
        trip_id=item.get("trip_id"),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        ttl=int(item["ttl"]),
    )


class DriverPositionStore:
    """Read and write driver positions keyed by geohash cell."""

    def __init__(self, settings: Settings | None = None, resource=None):
        self.settings = settings or get_settings()
        self.resource = resource or dynamodb_resource(self.settings)
        self.table = self.resource.Table(self.settings.driver_positions_table)
        self.client = self.resource.meta.client
        self.raw_client = dynamodb_client(self.settings)
        self._pool = ThreadPoolExecutor(max_workers=9, thread_name_prefix="cellq")

    # -- writes ---------------------------------------------------------------

    def put_position(
        self,
        driver_id: str,
        lat: float,
        lng: float,
        heading: float = 0.0,
        ttl_seconds: int | None = None,
        now: datetime | None = None,
    ) -> DriverPosition:
        """Upsert a driver's position, keeping its dispatch status intact.

        When a driver crosses into a new cell the old item is removed in the same
        transaction so the driver never shows up twice. The delete is conditioned
        on the status we read, so a concurrent busy-mark makes us re-read and retry.
        """
        now = now or utcnow()
        ttl_seconds = ttl_seconds or self.settings.position_ttl_seconds
        cell = geohash.encode(lat, lng, self.settings.cell_precision)
        full_hash = geohash.encode(lat, lng, geohash.DEFAULT_PRECISION)
        base = {
            "geohash": full_hash,
            "lat": _to_decimal(lat),
            "lng": _to_decimal(lng),
            "heading": _to_decimal(heading),
            "updated_at": now.isoformat(),
            "ttl": int(now.timestamp()) + ttl_seconds,
        }
        for _ in range(3):
            current = self.get_driver(driver_id)
            if current is not None and current.cell == cell:
                self.table.update_item(
                    Key={"cell": cell, "driver_id": driver_id},
                    UpdateExpression=(
                        "SET geohash = :g, lat = :lat, lng = :lng, heading = :h, "
                        "updated_at = :u, #ttl = :ttl"
                    ),
                    ExpressionAttributeNames={"#ttl": "ttl"},
                    ExpressionAttributeValues={
                        ":g": base["geohash"],
                        ":lat": base["lat"],
                        ":lng": base["lng"],
                        ":h": base["heading"],
                        ":u": base["updated_at"],
                        ":ttl": base["ttl"],
                    },
                )
                return DriverPosition(
                    driver_id=driver_id,
                    cell=cell,
                    status=current.status,
                    trip_id=current.trip_id,
                    **{**base, "lat": lat, "lng": lng, "heading": heading, "updated_at": now},
                )

            status = current.status if current else DriverStatus.AVAILABLE
            item: dict[str, Any] = {
                "cell": cell,
                "driver_id": driver_id,
                "status": status.value,
                **base,
            }
            if current is not None and current.trip_id:
                item["trip_id"] = current.trip_id
            if current is None:
                self.table.put_item(Item=item)
                return _item_to_position(item)
            try:
                self.raw_client.transact_write_items(
                    TransactItems=[
                        {
                            "Delete": {
                                "TableName": self.table.name,
                                "Key": {
                                    "cell": {"S": current.cell},
                                    "driver_id": {"S": driver_id},
                                },
                                "ConditionExpression": "#s = :status",
                                "ExpressionAttributeNames": {"#s": "status"},
                                "ExpressionAttributeValues": {
                                    ":status": {"S": current.status.value}
                                },
                            }
                        },
                        {
                            "Put": {
                                "TableName": self.table.name,
                                "Item": _serialize(item),
                            }
                        },
                    ]
                )
                return _item_to_position(item)
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "TransactionCanceledException":
                    raise
        raise RuntimeError(f"could not update position for {driver_id} after retries")

    def try_mark_busy(self, cell: str, driver_id: str, trip_id: str) -> bool:
        """Atomically claim a driver for a trip. Returns False if someone else won."""
        try:
            self.table.update_item(
                Key={"cell": cell, "driver_id": driver_id},
                UpdateExpression="SET #s = :busy, trip_id = :trip",
                ConditionExpression="attribute_exists(driver_id) AND #s = :avail AND #ttl > :now",
                ExpressionAttributeNames={"#s": "status", "#ttl": "ttl"},
                ExpressionAttributeValues={
                    ":busy": DriverStatus.BUSY.value,
                    ":avail": DriverStatus.AVAILABLE.value,
                    ":trip": trip_id,
                    ":now": int(time.time()),
                },
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def set_status(self, driver_id: str, status: DriverStatus) -> DriverPosition | None:
        """Explicitly set a driver's status (release after a trip, go offline)."""
        current = self.get_driver(driver_id)
        if current is None:
            return None
        expression = "SET #s = :s"
        if status != DriverStatus.BUSY:
            expression += " REMOVE trip_id"
        self.table.update_item(
            Key={"cell": current.cell, "driver_id": driver_id},
            UpdateExpression=expression,
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": status.value},
        )
        return current.model_copy(
            update={"status": status, "trip_id": current.trip_id if status == "busy" else None}
        )

    def delete_driver(self, driver_id: str) -> bool:
        current = self.get_driver(driver_id)
        if current is None:
            return False
        self.table.delete_item(Key={"cell": current.cell, "driver_id": driver_id})
        return True

    # -- reads ----------------------------------------------------------------

    def get_driver(self, driver_id: str) -> DriverPosition | None:
        resp = self.table.query(
            IndexName=GSI_BY_DRIVER,
            KeyConditionExpression="driver_id = :d",
            ExpressionAttributeValues={":d": driver_id},
        )
        items = resp.get("Items", [])
        if not items:
            return None
        # A stale duplicate can exist briefly after a cell change; newest wins.
        newest = max(items, key=lambda it: it["updated_at"])
        return _item_to_position(newest)

    def _query_cell(
        self, cell: str, now_epoch: int, subcells: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Read one partition, dropping expired rows and (optionally) rows outside
        the precision-6 subcells that intersect the search area."""
        items: list[dict[str, Any]] = []
        names = {"#c": "cell", "#ttl": "ttl"}
        values: dict[str, Any] = {":c": cell, ":now": now_epoch}
        filter_expr = "#ttl > :now"
        if subcells:
            placeholders = []
            for i, sub in enumerate(subcells):
                values[f":g{i}"] = sub
                placeholders.append(f":g{i}")
            names["#g"] = "geohash"
            filter_expr += f" AND #g IN ({', '.join(placeholders)})"
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": "#c = :c",
            "FilterExpression": filter_expr,
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
        }
        while True:
            resp = self.table.query(**kwargs)
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                return items
            kwargs["ExclusiveStartKey"] = last

    def _query_plan(
        self, lat: float, lng: float, radius_m: float
    ) -> list[tuple[str, list[str] | None]]:
        """Decide which partitions to read and which subcells to keep.

        Small radii: enumerate the precision-6 cells covering the search box and
        group them by their precision-5 parent, so each partition query only
        returns rows inside the box. Large radii: read the 3x3 block of
        precision-5 partitions with no subcell filter.
        """
        precision = self.settings.cell_precision
        fine = precision + 1
        lat_lo, lng_lo = offset_m(lat, lng, -radius_m, -radius_m)
        lat_hi, lng_hi = offset_m(lat, lng, radius_m, radius_m)
        _, cell_lat_hi, _, cell_lng_hi = geohash.decode_bbox(geohash.encode(lat, lng, fine))
        cell_lat_lo, _, cell_lng_lo, _ = geohash.decode_bbox(geohash.encode(lat, lng, fine))
        step_lat = (cell_lat_hi - cell_lat_lo) * 0.999
        step_lng = (cell_lng_hi - cell_lng_lo) * 0.999

        subcells: list[str] = []
        seen: set[str] = set()
        y = lat_lo
        while y <= lat_hi + step_lat:
            x = lng_lo
            while x <= lng_hi + step_lng:
                sub = geohash.encode(max(-90.0, min(90.0, y)), max(-180.0, min(180.0, x)), fine)
                if sub not in seen:
                    seen.add(sub)
                    subcells.append(sub)
                x += step_lng
            y += step_lat

        if len(subcells) > MAX_SUBCELL_FILTER:
            center = geohash.encode(lat, lng, precision)
            return [(c, None) for c in geohash.cell_with_neighbors(center)]

        grouped: dict[str, list[str]] = {}
        for sub in subcells:
            grouped.setdefault(sub[:precision], []).append(sub)
        return [(parent, subs) for parent, subs in grouped.items()]

    def nearby(
        self,
        lat: float,
        lng: float,
        radius_m: float,
        statuses: set[DriverStatus] | None = None,
        limit: int | None = None,
        now: datetime | None = None,
    ) -> list[NearbyDriver]:
        """Drivers within ``radius_m`` of a point, nearest first, expired items excluded."""
        now_epoch = int((now or datetime.now(UTC)).timestamp())
        plan = self._query_plan(lat, lng, radius_m)
        results = list(
            self._pool.map(lambda entry: self._query_cell(entry[0], now_epoch, entry[1]), plan)
        )

        latest: dict[str, dict[str, Any]] = {}
        for items in results:
            for item in items:
                prev = latest.get(item["driver_id"])
                if prev is None or item["updated_at"] > prev["updated_at"]:
                    latest[item["driver_id"]] = item

        found: list[NearbyDriver] = []
        for item in latest.values():
            pos = _item_to_position(item)
            if statuses and pos.status not in statuses:
                continue
            dist = haversine_m(lat, lng, pos.lat, pos.lng)
            if dist <= radius_m:
                found.append(NearbyDriver(**pos.model_dump(), distance_m=round(dist, 1)))
        found.sort(key=lambda d: d.distance_m)
        return found[:limit] if limit else found


def _serialize(item: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Convert a plain item into the low-level attribute-value format."""
    out: dict[str, dict[str, str]] = {}
    for key, value in item.items():
        if isinstance(value, bool):
            out[key] = {"BOOL": value}  # type: ignore[dict-item]
        elif isinstance(value, int | float | Decimal):
            out[key] = {"N": str(value)}
        else:
            out[key] = {"S": str(value)}
    return out
