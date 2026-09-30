"""Lectura y validación de planillas de cámaras."""

import io
import re
from pathlib import Path

import pandas as pd

# Patrones para inferir el rol de cada columna a partir de su nombre.
_ID_PATTERNS = (
    r"^n[°º]\s*ot",  # "N° OT": numero de orden de trabajo
    r"^id$",
    r"id[_ ]?cam",
    r"cam.*id",
    r"^id",  # "ID Contrato"
    r"c[oó]digo",
    r"^nro",
    r"n[uú]mero",
    r"contrato",
    r"device\s*name",  # exportaciones de cnMaestro
    r"dispositivo",
    r"c[aá]mara",
)
_LAT_PATTERNS = (r"^lat", r"latitud", r"latitude", r"^y$")
_LON_PATTERNS = (r"^lon", r"^lng", r"longitud", r"longitude", r"^x$")
# "IP Address" contiene "address" pero no es un domicilio.
_LABEL_PATTERNS = (r"direcc", r"domicilio", r"^(?!ip\b).*address", r"nombre", r"descrip")
# Columna única que trae latitud y longitud juntas.
_COORDS_PATTERNS = (
    r"coordenada",
    r"^coords?$",
    r"lat.*lon",
    r"lon.*lat",
    r"ubicac",
    r"posici[oó]n",
    r"geo",
    r"punto",
)
# Columnas de seguimiento. "Nodo al cual se migró" es el nodo real, que carga
# el técnico; el preliminar es el planificado ("Nodo a Migrar" en cnMaestro).
_NODE_PATTERNS = (r"nodo\s*pre", r"nodo\s*a\s*migrar", r"^nodo(?!.*se\s+migr)")
_OBS_PATTERNS = (r"observ", r"coment")
_DONE_PATTERNS = (r"realizad", r"^hecho", r"^completad")
# Formas de tildar "Realizado" que cuentan como tarea hecha.
_DONE_MARKS = frozenset(
    {"si", "sí", "s", "x", "✓", "✔", "☑", "true", "verdadero", "1", "ok",
     "hecho", "hecha", "realizado", "realizada", "yes", "y"}
)
# Hasta 1e9 cubre microgrados (1e6) y las exportaciones con más precisión.
_MAX_COORD_SCALE_EXPONENT = 9


def read_dataframe(filename: str, raw: bytes) -> pd.DataFrame:
    """Carga la planilla completa a un DataFrame."""
    suffix = Path(filename).suffix.lower()
    buffer = io.BytesIO(raw)

    if suffix == ".csv":
        return pd.read_csv(buffer)
    return pd.read_excel(buffer, engine="openpyxl")


def read_headers(filename: str, raw: bytes) -> list[str]:
    """Lee únicamente la fila de encabezados, sin cargar los datos."""
    suffix = Path(filename).suffix.lower()
    buffer = io.BytesIO(raw)

    if suffix == ".csv":
        frame = pd.read_csv(buffer, nrows=0)
    else:
        frame = pd.read_excel(buffer, nrows=0, engine="openpyxl")

    return [str(column) for column in frame.columns]


def _match(columns: list[str], patterns: tuple[str, ...]) -> str | None:
    """Devuelve la primera columna cuyo nombre coincide con algún patrón."""
    for pattern in patterns:
        for column in columns:
            if re.search(pattern, column.strip().lower()):
                return column
    return None


def suggest_mapping(columns: list[str]) -> dict[str, str | None]:
    """Infiere qué columna cumple cada rol, para precargar el formulario."""
    lat = _match(columns, _LAT_PATTERNS)
    lon = _match(columns, _LON_PATTERNS)
    coords = _match(columns, _COORDS_PATTERNS)

    # Una sola columna que nombra a las dos coordenadas —"Latitud y Longitud",
    # "LAT/LONG"— no son dos columnas: es una combinada. Sin este chequeo se le
    # asignaría el mismo nombre a ambos roles y el parseo numérico daría NaN en
    # todas las filas, con un error que no explica nada.
    if lat is not None and lat == lon:
        coords = coords or lat
    if coords is not None and coords in (lat, lon):
        lat = lon = None

    # Si no hay par lat/lon pero sí una columna combinada, arrancamos en modo
    # de columna única.
    mode = "split" if lat and lon else ("single" if coords else "split")

    return {
        "id": _match(columns, _ID_PATTERNS),
        "lat": lat,
        "lon": lon,
        "coords": coords,
        "label": _match(columns, _LABEL_PATTERNS),
        "node": _match(columns, _NODE_PATTERNS),
        "observation": _match(columns, _OBS_PATTERNS),
        "done": _match(columns, _DONE_PATTERNS),
        "mode": mode,
    }


def _is_done(value: object) -> bool:
    """True si la celda de "Realizado" marca la tarea como hecha."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1  # NaN != 1: una celda vacía no está hecha
    if not isinstance(value, str):
        return False
    return value.strip().lower() in _DONE_MARKS


def split_done(frame: pd.DataFrame, col_done: str | None) -> tuple[pd.DataFrame, int]:
    """Aparta las filas marcadas como realizadas; devuelve las pendientes y cuántas se apartaron.

    Conserva el índice original, así las filas que después se descarten por
    coordenadas siguen informando su número de fila real en la planilla.
    """
    if not col_done:
        return frame, 0
    if col_done not in frame.columns:
        raise ValueError(f"Columnas inexistentes en la planilla: {col_done}")
    done = frame[col_done].map(_is_done).astype(bool)
    return frame.loc[~done], int(done.sum())


def _optional_text(frame: pd.DataFrame, column: str | None) -> list[str | None]:
    """Texto limpio de una columna opcional; vacíos y NaN quedan en None."""
    if not column:
        return [None] * len(frame)
    values: list[str | None] = []
    for value in frame[column]:
        # pandas 3 conserva NaN como float en columnas de texto: no basta astype(str).
        text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value).strip()
        values.append(text or None)
    return values


def _to_float_series(series: pd.Series) -> pd.Series:
    """Convierte a float tolerando coma decimal y separadores de miles."""
    # No basta con comparar contra `object`: pandas 3.0 usa un dtype `str`
    # dedicado para las columnas de texto.
    if not pd.api.types.is_numeric_dtype(series):
        series = (
            series.astype(str)
            .str.strip()
            .str.replace(r"\.(?=\d{3}\b)", "", regex=True)  # miles: 1.234,56
            .str.replace(",", ".", regex=False)
        )
    return pd.to_numeric(series, errors="coerce")


def _rescale_integer_coords(
    lat: pd.Series, lon: pd.Series
) -> tuple[pd.Series, pd.Series]:
    """Reinterpreta coordenadas exportadas como enteros escalados.

    cnMaestro y varios GPS guardan microgrados sin punto decimal: -24845092 es
    -24.845092. Sólo se reescala cuando *todos* los valores de ambas columnas
    son enteros fuera de rango; un valor suelto fuera de rango entre grados
    normales sigue siendo un error de carga. Se usa una única escala para las
    dos columnas, la menor que las vuelve válidas: la longitud, que admite tres
    dígitos enteros, desempata cuando la latitud sola sería ambigua.
    """
    values = pd.concat([lat, lon]).dropna()
    if values.empty or not (values == values.round()).all():
        return lat, lon
    if (lat.dropna().abs() <= 90).any() or (lon.dropna().abs() <= 180).any():
        return lat, lon

    for exponent in range(1, _MAX_COORD_SCALE_EXPONENT + 1):
        factor = 10.0**exponent
        if (lat.dropna().abs() / factor <= 90).all() and (
            lon.dropna().abs() / factor <= 180
        ).all():
            return lat / factor, lon / factor
    return lat, lon


def _to_float(text: str) -> float | None:
    """Convierte un escalar suelto, tolerando coma decimal."""
    cleaned = re.sub(r"\.(?=\d{3}\b)", "", text.strip()).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _candidate_pairs(text: str) -> list[tuple[float, float]]:
    """Devuelve las lecturas plausibles de una celda con ambos valores.

    El caso difícil es la coma decimal: "-34,6037,-58,3816" trae cuatro comas y
    hay que reagrupar los pares. Cuando la partición es ambigua se prueban todas
    las agrupaciones y más adelante se descarta la que no dé coordenadas válidas.
    """
    cleaned = text.strip().strip("()[]{}").replace("|", ";")

    # Punto y coma o espacio separan sin ambigüedad: la coma queda como decimal.
    for separator in (";", None):
        parts = cleaned.split(";") if separator == ";" else cleaned.split()
        if len(parts) == 2:
            first, second = _to_float(parts[0]), _to_float(parts[1])
            if first is not None and second is not None:
                return [(first, second)]

    parts = [part for part in cleaned.split(",") if part.strip()]

    if len(parts) == 2:  # "-34.6037,-58.3816"
        groupings = [(parts[:1], parts[1:])]
    elif len(parts) == 4:  # "-34,6037,-58,3816" — coma decimal en ambos
        groupings = [(parts[:2], parts[2:])]
    elif len(parts) == 3:  # coma decimal en uno solo de los dos
        groupings = [(parts[:2], parts[2:]), (parts[:1], parts[1:])]
    else:
        return []

    pairs: list[tuple[float, float]] = []
    for left, right in groupings:
        first = _to_float(",".join(left))
        second = _to_float(",".join(right))
        if first is not None and second is not None:
            pairs.append((first, second))
    return pairs


def _valid_coords(lat: float, lon: float) -> bool:
    """Rango geográfico válido, excluyendo la isla nula."""
    return -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0)


def parse_coord_cell(text: object, order: str) -> tuple[float, float] | None:
    """Extrae (lat, lon) de una celda que trae ambos valores juntos.

    `order` acepta "latlon", "lonlat" o "auto". En "auto" se resuelve por rango
    cuando uno de los valores excede ±90 —sólo puede ser longitud—; si ambos
    caben en el rango de latitud la lectura es genuinamente ambigua y se asume
    lat,lon, que es la convención de Google Maps y de la mayoría de los GPS.
    """
    # Las celdas vacías llegan como NaN: pandas 3.0 ya no las convierte a la
    # cadena "nan" al hacer astype(str).
    if text is None or pd.isna(text):
        return None

    for first, second in _candidate_pairs(str(text)):
        if order == "lonlat":
            candidates = [(second, first)]
        elif order == "latlon":
            candidates = [(first, second)]
        else:
            # Un valor fuera de ±90 sólo puede ser longitud.
            if abs(first) > 90 and abs(second) <= 90:
                candidates = [(second, first)]
            elif abs(second) > 90 and abs(first) <= 90:
                candidates = [(first, second)]
            else:
                candidates = [(first, second)]

        for lat, lon in candidates:
            if _valid_coords(lat, lon):
                return lat, lon

    return None


def _split_coord_column(series: pd.Series, order: str) -> tuple[pd.Series, pd.Series]:
    """Parte una columna de coordenadas combinadas en dos series numéricas."""
    parsed = series.map(lambda text: parse_coord_cell(text, order))
    lat = parsed.map(lambda pair: pair[0] if pair else None)
    lon = parsed.map(lambda pair: pair[1] if pair else None)
    return (
        pd.to_numeric(lat, errors="coerce"),
        pd.to_numeric(lon, errors="coerce"),
    )


def extract_points(
    frame: pd.DataFrame,
    col_id: str,
    col_lat: str | None = None,
    col_lon: str | None = None,
    col_label: str | None = None,
    col_coords: str | None = None,
    coord_order: str = "auto",
    col_node: str | None = None,
    col_obs: str | None = None,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Normaliza y valida las filas geográficas.

    Acepta las coordenadas en dos columnas separadas (`col_lat`/`col_lon`) o en
    una sola columna combinada (`col_coords`).

    Devuelve el DataFrame de puntos válidos (columnas id/lat/lon/label/node/
    observation) y la lista de filas descartadas con su motivo. El número de
    fila sale del índice del DataFrame, así sobrevive a un `split_done` previo.
    """
    single = bool(col_coords)
    if not single and not (col_lat and col_lon):
        raise ValueError(
            "Indique una columna combinada de coordenadas o las columnas de "
            "latitud y longitud por separado."
        )

    if not single and col_lat == col_lon:
        raise ValueError(
            f"Latitud y longitud apuntan a la misma columna ('{col_lat}'). "
            f"Si esa columna trae los dos valores juntos, elija el modo de "
            f"columna única."
        )

    needed = [col_id, col_coords] if single else [col_id, col_lat, col_lon]
    needed += [column for column in (col_label, col_node, col_obs) if column]

    missing = [name for name in needed if name and name not in frame.columns]
    if missing:
        raise ValueError(f"Columnas inexistentes en la planilla: {', '.join(missing)}")

    if single:
        lat_series, lon_series = _split_coord_column(frame[col_coords], coord_order)
    else:
        lat_series, lon_series = _rescale_integer_coords(
            _to_float_series(frame[col_lat]), _to_float_series(frame[col_lon])
        )

    work = pd.DataFrame(
        {
            "row": (frame.index + 1).to_numpy(),
            "id": frame[col_id].astype(str).str.strip().to_numpy(),
            "lat": lat_series.to_numpy(),
            "lon": lon_series.to_numpy(),
            # dtype object: con el dtype `str` de pandas 3 los None vuelven como NaN.
            "label": pd.Series(_optional_text(frame, col_label), dtype=object),
            "node": pd.Series(_optional_text(frame, col_node), dtype=object),
            "observation": pd.Series(_optional_text(frame, col_obs), dtype=object),
        }
    )

    discarded: list[dict[str, object]] = []

    def drop(mask: pd.Series, reason: str) -> None:
        """Registra y elimina las filas marcadas por `mask`."""
        nonlocal work
        if not mask.any():
            return
        for row in work.loc[mask, "row"]:
            discarded.append({"row": int(row), "reason": reason})
        work = work.loc[~mask]

    drop(
        work["lat"].isna() | work["lon"].isna(),
        "No se pudo interpretar el par de coordenadas"
        if single
        else "Coordenada vacía o no numérica",
    )
    drop(
        ~work["lat"].between(-90, 90) | ~work["lon"].between(-180, 180),
        "Coordenada fuera de rango válido",
    )
    drop((work["lat"] == 0) & (work["lon"] == 0), "Coordenada nula (0,0)")
    drop(work["id"].isin(["", "nan", "None"]), "Identificador vacío")

    return work.reset_index(drop=True), discarded
