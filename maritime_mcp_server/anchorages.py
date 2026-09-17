"""Finding anchorages in the data, rather than reading them off a chart.

An anchorage is not transmitted by anything. What is transmitted is a lot of
vessels reporting "At anchor" in roughly the same water, so that is what this
looks for: occupied cells that touch each other, grouped into one place.

Why derive it at all, when charted anchorage limits exist? Because the charted
limit is where ships are permitted to anchor and this is where they actually
do. For a queue, the second is the useful one. It also needs no chart licence
and no data this server does not already hold.

What it cannot do: name them. The cluster off eastern Singapore is obviously
the eastern anchorage to anyone who works there, but nothing in AIS says so,
so nothing here invents a name.
"""

from __future__ import annotations

import math

#: Minimum distinct vessels before a cluster is called an anchorage. One yacht
#: swinging on a mooring for a week is not a queue, and without a floor every
#: quiet bay in the region becomes a labelled place.
MIN_VESSELS = 3

#: Cells this far apart or closer are treated as the same anchorage.
#:
#: Two, not one, so that a single unoccupied cell bridges rather than splits.
#: Anchorages have holes in them: a channel through the middle, a shoal, or
#: simply an hour when nothing in that cell happened to be heard. At the 0.01
#: degree grid this reaches about 1.2 nautical miles, which is inside one
#: anchorage and well short of the next.
NEIGHBOUR_CELLS = 2


def _neighbours(key, cell, reach=NEIGHBOUR_CELLS):
    """Grid keys touching this one, including diagonals."""
    lat_i, lon_i = key
    for dlat in range(-reach, reach + 1):
        for dlon in range(-reach, reach + 1):
            if dlat or dlon:
                yield (lat_i + dlat, lon_i + dlon)


def cluster(cells, cell: float) -> list[dict]:
    """Group touching occupied cells into anchorages.

    `cells` are (lat, lon, vessels, positions) as the history layer returns
    them. Grid indices rather than raw degrees are used for adjacency, because
    floating point addition of 0.02 does not reliably land on the next cell.

    Returns each anchorage with the extent it actually occupies, not a circle
    fitted to it: an anchorage off a coast is usually a long thin thing and a
    radius would claim water that nobody anchors in.
    """
    index = {}
    for lat, lon, vessels, positions in cells:
        key = (int(round(lat / cell)), int(round(lon / cell)))
        # Two source cells can round to the same index at the edges; add rather
        # than overwrite so no vessel is silently dropped.
        got = index.get(key)
        index[key] = (vessels + got[0], positions + got[1]) if got else (vessels, positions)

    seen = set()
    found = []
    for start in index:
        if start in seen:
            continue
        # Breadth-first over touching cells. Iterative, not recursive: a busy
        # anchorage is hundreds of cells and Python's stack is not deep.
        group = []
        queue = [start]
        seen.add(start)
        while queue:
            key = queue.pop()
            group.append(key)
            for near in _neighbours(key, cell):
                if near in index and near not in seen:
                    seen.add(near)
                    queue.append(near)

        vessels = sum(index[k][0] for k in group)
        positions = sum(index[k][1] for k in group)
        if vessels < MIN_VESSELS:
            continue

        lats = [k[0] * cell for k in group]
        lons = [k[1] * cell for k in group]
        # Weighted by vessels, so the centre sits where the ships are rather
        # than in the middle of the bounding box.
        weight = sum(index[k][0] for k in group) or 1
        found.append({
            "lat": round(sum(k[0] * cell * index[k][0] for k in group) / weight, 4),
            "lon": round(sum(k[1] * cell * index[k][0] for k in group) / weight, 4),
            "south": round(min(lats) - cell / 2, 4),
            "north": round(max(lats) + cell / 2, 4),
            "west": round(min(lons) - cell / 2, 4),
            "east": round(max(lons) + cell / 2, 4),
            "vessels": vessels,
            "positions": positions,
            "cells": len(group),
        })

    found.sort(key=lambda a: -a["vessels"])
    return found


def area_nm2(anchorage) -> float:
    """Roughly how much water it covers, for a sense of scale."""
    lat_nm = (anchorage["north"] - anchorage["south"]) * 60
    lon_nm = (anchorage["east"] - anchorage["west"]) * 60 * math.cos(
        math.radians((anchorage["north"] + anchorage["south"]) / 2))
    return round(lat_nm * lon_nm, 1)
