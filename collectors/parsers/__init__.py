"""One module per source family. Each defines ``list_items(ctx, source)`` and optionally
``fetch_detail(ctx, source, item)``; see docs/CONTRACTS.md. Modules may also set
``STRUCTURED_FIELDS`` (dotted paths in ``Item.structured`` matched with confidence 'high')."""
