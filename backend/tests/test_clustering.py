"""Tests del agrupamiento geográfico con DBSCAN."""

import numpy as np
import pandas as pd
import pytest

from app.services.clustering import haversine_km, run_dbscan

# Tres zonas separadas entre sí por decenas de kilómetros.
ZONAS = {
    "microcentro": (-34.6037, -58.3816),
    "palermo": (-34.5780, -58.4300),
    "la_plata": (-34.9215, -57.9545),
}


def construir_puntos(por_zona: int = 8, dispersion: float = 0.003) -> pd.DataFrame:
    """Genera cámaras agrupadas alrededor de cada zona.

    `dispersion` en grados: 0.003 ≈ 300 m, bastante menos que la separación
    entre zonas, así que los clusters esperados son inequívocos.
    """
    rng = np.random.default_rng(42)
    filas = [
        {
            "id": f"{zona[:3].upper()}-{i:03d}",
            "lat": lat0 + rng.normal(0, dispersion),
            "lon": lon0 + rng.normal(0, dispersion),
        }
        for zona, (lat0, lon0) in ZONAS.items()
        for i in range(por_zona)
    ]
    return pd.DataFrame(filas)


def test_haversine_distancia_conocida() -> None:
    """Microcentro a La Plata son unos 53 km en línea recta."""
    lat0, lon0 = ZONAS["microcentro"]
    lat1, lon1 = ZONAS["la_plata"]

    distancia = haversine_km(np.array([lat1]), np.array([lon1]), lat0, lon0)[0]

    assert distancia == pytest.approx(53, abs=3)


def test_haversine_punto_consigo_mismo_es_cero() -> None:
    """Sin desplazamiento no hay distancia."""
    lat, lon = ZONAS["palermo"]

    assert haversine_km(np.array([lat]), np.array([lon]), lat, lon)[0] == pytest.approx(
        0, abs=1e-9
    )


def test_encuentra_las_tres_zonas() -> None:
    """Con eps de 2 km cada zona cae en su propio cluster."""
    points = construir_puntos()

    labels, clusters = run_dbscan(points, eps_km=2.0, min_samples=3)

    assert len(clusters) == 3
    assert all(cluster["size"] == 8 for cluster in clusters)
    assert -1 not in labels


def test_aisla_outliers_como_ruido() -> None:
    """Una cámara lejos de todo queda sin cluster (-1)."""
    points = pd.concat(
        [
            construir_puntos(),
            pd.DataFrame([{"id": "OUT-001", "lat": -38.0055, "lon": -57.5426}]),
        ],
        ignore_index=True,
    )

    labels, clusters = run_dbscan(points, eps_km=2.0, min_samples=3)

    assert len(clusters) == 3
    assert labels[-1] == -1
    assert list(labels).count(-1) == 1


def test_eps_grande_fusiona_clusters() -> None:
    """`eps_km` está en kilómetros reales: al ampliarlo las zonas se unen."""
    points = construir_puntos()

    _, apretado = run_dbscan(points, eps_km=2.0, min_samples=3)
    _, amplio = run_dbscan(points, eps_km=400.0, min_samples=3)

    assert len(apretado) == 3
    assert len(amplio) == 1


def test_radio_del_cluster_es_coherente() -> None:
    """El radio informado cubre a todos los miembros y respeta la dispersión."""
    points = construir_puntos()

    _, clusters = run_dbscan(points, eps_km=2.0, min_samples=3)

    for cluster in clusters:
        # 300 m de sigma: el miembro más lejano no debería superar ~1.5 km.
        assert 0 < cluster["radius_km"] < 1.5


def test_dataframe_vacio_no_rompe() -> None:
    """Sin puntos devuelve estructuras vacías en lugar de fallar."""
    labels, clusters = run_dbscan(
        pd.DataFrame(columns=["id", "lat", "lon"]), eps_km=1.0, min_samples=2
    )

    assert len(labels) == 0
    assert clusters == []
