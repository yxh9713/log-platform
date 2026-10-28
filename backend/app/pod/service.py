"""Image acceptance shares the event transaction; storage is independent work."""

from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import Connection

from app.pod.prepare import PreparedImage
from app.pod.schema import shipment_images
from app.shipments.schema import shipment_events


def enqueue(
    connection: Connection,
    tenant: int,
    shipment_id: int,
    event_id: int,
    image: PreparedImage,
) -> str:
    image_id = str(uuid4())
    extension = "jpg" if image.content_type == "image/jpeg" else "png"
    connection.execute(
        shipment_images.insert().values(
            id=image_id,
            shipment_id=shipment_id,
            shipper_company_id=tenant,
            event_id=event_id,
            object_key=f"pod/{tenant}/{shipment_id}/{image_id}.{extension}",
            content_type=image.content_type,
            width=image.width,
            height=image.height,
            input_size=image.input_size,
            size_bytes=len(image.data),
            content_hash=image.digest,
            prepared_content=image.data,
        )
    )
    return image_id


def current_url(connection: Connection, tenant: int, shipment_id: int) -> str | None:
    # Rank all image-bearing accepted events before readiness filtering. A newer
    # pending/failed image must never fall back to another event's ready image.
    # Missing images leave the previous image-bearing event in this ordering.
    return connection.execute(
        sa.select(shipment_images.c.url)
        .join(
            shipment_events,
            sa.and_(
                shipment_images.c.event_id == shipment_events.c.id,
                shipment_images.c.shipment_id == shipment_events.c.shipment_id,
            ),
        )
        .where(
            shipment_images.c.shipper_company_id == tenant,
            shipment_images.c.shipment_id == shipment_id,
        )
        .order_by(
            shipment_events.c.event_time.desc(), shipment_events.c.receipt_order.desc()
        )
        .limit(1)
    ).scalar_one_or_none()
