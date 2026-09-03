"""Create the DynamoDB driver_positions table (with GSI and TTL) if it is missing."""

from __future__ import annotations

import sys

from rideloop_common.config import get_settings
from rideloop_common.dynamo import dynamodb_resource, ensure_table


def main() -> int:
    settings = get_settings()
    name = ensure_table(settings)
    client = dynamodb_resource(settings).meta.client
    ttl = client.describe_time_to_live(TableName=name)["TimeToLiveDescription"]
    print(f"table {name} ready at {settings.dynamodb_endpoint or 'aws'}; ttl={ttl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
