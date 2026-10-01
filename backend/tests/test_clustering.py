"""Tests del agrupamiento geográfico con DBSCAN."""

import numpy as np
import pandas as pd
import pytest

from app.services.clustering import haversine_km, reassign_noise, run_dbscan

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


# --------------------------------------------------------------------------
# reassign_noise
# --------------------------------------------------------------------------


def test_reasigna_ruido_a_cluster_cercano() -> None:
    """Un punto de ruido a pocos km de un cluster se reasigna a ese cluster."""
    cluster_pts = pd.DataFrame(
        [{"id": f"C-{i}", "lat": 0.0 + i * 0.001, "lon": 0.0} for i in range(4)]
    )
    # A ~3 km del cluster: fuera de eps=1km (queda ruido) pero dentro de
    # max_km=6km (se reasigna).
    ruido = pd.DataFrame([{"id": "RUIDO", "lat": 0.027, "lon": 0.0}])
    points = pd.concat([cluster_pts, ruido], ignore_index=True)

    labels, clusters = run_dbscan(points, eps_km=1.0, min_samples=3)
    assert labels[-1] == -1  # confirma que arranca como ruido

    new_labels, new_clusters = reassign_noise(points, labels, clusters, max_km=6.0)

    assert new_labels[-1] == clusters[0]["id"]
    assert new_clusters[0]["size"] == 5


def test_ruido_mas_alla_del_limite_no_se_reasigna() -> None:
    """Un punto fuera de max_km de todos los clusters sigue en -1."""
    cluster_pts = pd.DataFrame(
        [{"id": f"C-{i}", "lat": 0.0 + i * 0.001, "lon": 0.0} for i in range(4)]
    )
    lejos = pd.DataFrame([{"id": "LEJOS", "lat": -38.0055, "lon": -57.5426}])
    points = pd.concat([cluster_pts, lejos], ignore_index=True)

    labels, clusters = run_dbscan(points, eps_km=1.0, min_samples=3)
    new_labels, new_clusters = reassign_noise(points, labels, clusters, max_km=6.0)

    assert new_labels[-1] == -1
    assert new_clusters == clusters  # nada cambió: ningún cluster creció


def test_reasignacion_recalcula_radius_km() -> None:
    """El radio del cluster que absorbe ruido refleja al nuevo miembro."""
    cluster_pts = pd.DataFrame(
        [{"id": f"C-{i}", "lat": 0.0 + i * 0.001, "lon": 0.0} for i in range(4)]
    )
    ruido = pd.DataFrame([{"id": "RUIDO", "lat": 0.027, "lon": 0.0}])
    points = pd.concat([cluster_pts, ruido], ignore_index=True)

    labels, clusters = run_dbscan(points, eps_km=1.0, min_samples=3)
    radio_original = clusters[0]["radius_km"]

    _, new_clusters = reassign_noise(points, labels, clusters, max_km=6.0)

    assert new_clusters[0]["radius_km"] > radio_original
    # El punto reasignado está a ~3 km del centroide original.
    assert new_clusters[0]["radius_km"] == pytest.approx(3.0, abs=0.3)


def test_reasignacion_usa_miembro_mas_cercano_no_centroide() -> None:
    """Un cluster elongado atrae ruido cercano a un extremo, no a su centroide.

    El cluster "avenida" es tan elongado que su centroide queda más lejos del
    punto de ruido que el centroide de un cluster compacto vecino — pero el
    miembro más cercano de la avenida sigue estando mucho más cerca que
    cualquier miembro del cluster compacto. La reasignación por miembro más
    cercano debe elegir la avenida; por centroide habría elegido el compacto.
    """
    avenida = pd.DataFrame(
        [
            {"id": f"AV-{i}", "lat": 0.0, "lon": lon}
            for i, lon in enumerate([-0.05, -0.04, -0.03, -0.02, -0.01, 0.0])
        ]
    )
    compacto = pd.DataFrame(
        [
            {"id": f"CO-{i}", "lat": 0.0, "lon": 0.03 + i * 0.0002}
            for i in range(4)
        ]
    )
    # A 1.34 km del extremo de la avenida (fuera de eps, así que no lo suma
    # directamente al cluster) y a 2.0 km del cluster compacto.
    ruido = pd.DataFrame([{"id": "RUIDO", "lat": 0.0, "lon": 0.012}])
    points = pd.concat([avenida, compacto, ruido], ignore_index=True)

    labels, clusters = run_dbscan(points, eps_km=1.2, min_samples=3)
    assert len(clusters) == 2
    assert labels[-1] == -1  # el punto de ruido no entra solo por DBSCAN

    avenida_cluster = next(c for c in clusters if c["size"] == 6)

    new_labels, _ = reassign_noise(points, labels, clusters, max_km=5.0)

    assert new_labels[-1] == avenida_cluster["id"]


def test_reasignacion_empate_elige_id_mas_bajo() -> None:
    """Con dos clusters exactamente equidistantes, gana el de id más chico."""
    izquierda = pd.DataFrame(
        [{"id": f"I-{i}", "lat": 0.0, "lon": -0.03 - i * 0.001} for i in range(3)]
    )
    derecha = pd.DataFrame(
        [{"id": f"D-{i}", "lat": 0.0, "lon": 0.03 + i * 0.001} for i in range(3)]
    )
    ruido = pd.DataFrame([{"id": "RUIDO", "lat": 0.0, "lon": 0.0}])
    points = pd.concat([izquierda, derecha, ruido], ignore_index=True)

    labels, clusters = run_dbscan(points, eps_km=0.5, min_samples=3)
    assert len(clusters) == 2
    assert labels[-1] == -1

    new_labels, _ = reassign_noise(points, labels, clusters, max_km=10.0)

    assert new_labels[-1] == min(cluster["id"] for cluster in clusters)
