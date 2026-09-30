"""Clustering geográfico de cámaras con DBSCAN.

Usa la métrica haversine para que `eps` se exprese en kilómetros reales y no en
grados — un grado de longitud mide distinto según la latitud, así que agrupar
sobre coordenadas planas deforma los clusters.
"""

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

EARTH_RADIUS_KM = 6371.0088


def haversine_km(
    lat: np.ndarray, lon: np.ndarray, lat0: float, lon0: float
) -> np.ndarray:
    """Distancia sobre la esfera desde cada punto hasta (lat0, lon0)."""
    lat_r, lon_r = np.radians(lat), np.radians(lon)
    lat0_r, lon0_r = np.radians(lat0), np.radians(lon0)

    dlat = lat_r - lat0_r
    dlon = lon_r - lon0_r
    a = np.sin(dlat / 2) ** 2 + np.cos(lat0_r) * np.cos(lat_r) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def bounding_span_km(points: pd.DataFrame) -> float:
    """Distancia entre las esquinas del rectangulo que contiene a los puntos.

    Sirve como control de plausibilidad del mapeo de columnas: si lo que se
    tomo por coordenadas son en realidad otros numeros —un codigo de zona, un
    numero de cliente— los puntos se dispersan por medio continente y esta
    medida lo delata.
    """
    if len(points) < 2:
        return 0.0

    lat = points["lat"].to_numpy(dtype=float)
    lon = points["lon"].to_numpy(dtype=float)
    return float(
        haversine_km(
            np.array([lat.max()]), np.array([lon.max()]), lat.min(), lon.min()
        )[0]
    )


def reassign_noise(
    points: pd.DataFrame,
    labels: np.ndarray,
    clusters: list[dict[str, float | int]],
    max_km: float,
) -> tuple[np.ndarray, list[dict[str, float | int]]]:
    """Reasigna cada punto de ruido al cluster más cercano, dentro de max_km.

    La distancia se mide contra el miembro más cercano de cada cluster, no
    contra su centroide: un cluster elongado (una avenida larga, por ejemplo)
    tiene un centroide que no representa su forma, y un punto de ruido cerca
    de un extremo real del cluster podría parecer más lejano que otro cluster
    equivocado si se lo midiera sólo contra el centroide.

    Devuelve las etiquetas actualizadas y los clusters con `radius_km`
    recalculado —contra el centroide original, sin recentroidear— para
    reflejar los miembros reasignados. El ruido más allá de max_km conserva
    -1. En caso de empate exacto entre dos clusters, gana el de id más bajo.
    """
    if not clusters or points.empty:
        return labels, clusters

    noise_indices = np.flatnonzero(labels == -1)
    if len(noise_indices) == 0:
        return labels, clusters

    new_labels = labels.copy()
    members_by_cluster = {
        cluster["id"]: points.loc[labels == cluster["id"]] for cluster in clusters
    }

    for idx in noise_indices:
        noise_lat = float(points.iloc[idx]["lat"])
        noise_lon = float(points.iloc[idx]["lon"])

        best_id: int | None = None
        best_distance = float("inf")
        for cluster_id in sorted(members_by_cluster):
            members = members_by_cluster[cluster_id]
            distance = haversine_km(
                members["lat"].to_numpy(dtype=float),
                members["lon"].to_numpy(dtype=float),
                noise_lat,
                noise_lon,
            ).min()
            if distance < best_distance:
                best_distance = distance
                best_id = int(cluster_id)

        if best_id is not None and best_distance <= max_km:
            new_labels[idx] = best_id

    updated_clusters: list[dict[str, float | int]] = []
    for cluster in clusters:
        member_mask = new_labels == cluster["id"]
        member_count = int(member_mask.sum())
        if member_count == cluster["size"]:
            updated_clusters.append(cluster)
            continue

        lat_values = points.loc[member_mask, "lat"].to_numpy(dtype=float)
        lon_values = points.loc[member_mask, "lon"].to_numpy(dtype=float)
        radius = haversine_km(
            lat_values, lon_values, cluster["centroid_lat"], cluster["centroid_lon"]
        )
        updated_clusters.append(
            {
                **cluster,
                "size": member_count,
                "radius_km": round(float(radius.max()), 3),
            }
        )

    return new_labels, updated_clusters


def run_dbscan(
    points: pd.DataFrame, eps_km: float, min_samples: int
) -> tuple[np.ndarray, list[dict[str, float | int]]]:
    """Agrupa los puntos y resume cada cluster.

    Devuelve las etiquetas por punto (-1 = ruido) y una lista de clusters con
    su centroide y radio.
    """
    if points.empty:
        return np.array([], dtype=int), []

    coords = np.radians(points[["lat", "lon"]].to_numpy(dtype=float))

    labels = DBSCAN(
        eps=eps_km / EARTH_RADIUS_KM,
        min_samples=min_samples,
        metric="haversine",
        algorithm="ball_tree",
    ).fit_predict(coords)

    clusters: list[dict[str, float | int]] = []
    for label in sorted({int(value) for value in labels if value != -1}):
        members = points.loc[labels == label]
        lat_values = members["lat"].to_numpy(dtype=float)
        lon_values = members["lon"].to_numpy(dtype=float)

        centroid_lat = float(lat_values.mean())
        centroid_lon = float(lon_values.mean())
        radius = haversine_km(lat_values, lon_values, centroid_lat, centroid_lon)

        clusters.append(
            {
                "id": label,
                "size": int(len(members)),
                "centroid_lat": centroid_lat,
                "centroid_lon": centroid_lon,
                "radius_km": round(float(radius.max()), 3),
            }
        )

    return labels, clusters
