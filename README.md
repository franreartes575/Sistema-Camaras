# Sistema Logístico Free

Optimización de rutas de mantenimiento de cámaras para la **provincia de Salta**,
sobre un stack 100% libre y self-hosted. Sin Google Maps, sin API keys, sin
servicios pagos: ninguna coordenada de las cámaras sale del equipo.

## Stack

| Capa | Tecnología |
|---|---|
| Frontend | Next.js 16 (TypeScript, App Router) + TailwindCSS 4 |
| Mapa | MapLibre GL JS + react-map-gl, tiles raster de OpenStreetMap |
| Backend | FastAPI (Python 3.14) |
| Agrupamiento | scikit-learn — DBSCAN con métrica haversine |
| Optimización | Google OR-Tools — un TSP por cluster |
| Ruteo | OSRM local en Docker, grafo de Salta |
| Planillas | pandas + openpyxl |

## Cómo funciona

1. Cargás la planilla de cámaras (`.xlsx`, `.xlsm` o `.csv`).
2. El backend lee sólo los encabezados y sugiere qué columna es cada cosa.
3. Confirmás el mapeo y ajustás el radio de agrupamiento.
4. DBSCAN agrupa las cámaras por cercanía geográfica real.
5. OR-Tools resuelve el orden de visita óptimo dentro de cada grupo.
6. El mapa dibuja cada recorrido y numera las paradas.

## Estructura

```
sistema-logistico-free/
├── backend/
│   ├── app/
│   │   ├── config.py             # OSRM, CORS, límites de subida
│   │   ├── main.py               # Endpoints HTTP
│   │   ├── schemas.py            # Modelos pydantic
│   │   └── services/
│   │       ├── ingest.py         # Lectura, mapeo y validación de planillas
│   │       ├── clustering.py     # DBSCAN con métrica haversine
│   │       ├── routing.py        # Proveedores de distancia (OSRM / línea recta)
│   │       └── optimizer.py      # TSP por cluster con OR-Tools
│   └── tests/                    # 90 tests, 96% de cobertura
├── frontend/src/
│   ├── app/page.tsx              # Orquesta carga → mapeo → optimización
│   ├── components/
│   │   ├── MapView.tsx           # MapLibre: puntos, rótulos y polilíneas
│   │   └── ControlPanel.tsx      # Mapeo, parámetros y lista de recorridos
│   └── lib/{api,mapStyle,vizTokens}.ts
└── osrm/                         # Motor de ruteo — ver osrm/README.md
    ├── docker-compose.yml
    └── preparar.ps1
```

## Cómo correrlo

### Backend

```powershell
cd backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Documentación interactiva en <http://127.0.0.1:8000/docs>

### Frontend

```powershell
cd frontend
npm run dev
```

Aplicación en <http://localhost:3000>

### Motor de ruteo

Sin OSRM el sistema funciona, pero con distancias en línea recta que subestiman
el recorrido real. Instrucciones completas en [osrm/README.md](osrm/README.md).

```powershell
cd osrm
.\preparar.ps1        # una sola vez: descarga, recorta Salta y arma el grafo
docker compose up -d
```

### Tests

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest
```

## API

| Endpoint | Qué hace |
|---|---|
| `GET /health` | Estado del servicio y URL de OSRM configurada |
| `POST /upload-excel/` | Devuelve los encabezados y sugiere el mapeo de columnas |
| `POST /process/` | Ingesta + validación + agrupamiento DBSCAN |
| `POST /optimize/` | Todo lo anterior más el recorrido optimizado de cada cluster |

Las coordenadas pueden venir en dos columnas (`col_lat` + `col_lon`) o en una
sola columna combinada (`col_coords` + `coord_order`).

El archivo se reenvía en cada llamada en lugar de guardarse entre requests: el
backend queda sin estado y reajustar un parámetro es simplemente volver a
postear.

## Notas de implementación

**Agrupamiento.** DBSCAN corre con métrica `haversine` sobre coordenadas en
radianes, así que `eps_km` son kilómetros reales. Agrupar sobre grados planos
deformaría los clusters, porque un grado de longitud mide distinto según la
latitud — y en Salta, que abarca del Chaco a la puna, esa diferencia importa.

**Coordenadas.** El parser tolera coma decimal y separador de miles, que es
como Excel exporta en configuración regional es-AR. También acepta las dos
coordenadas en una sola celda; el caso difícil es `-24,7859,-65,4117`, que trae
cuatro comas y obliga a probar todas las agrupaciones posibles descartando las
que no den un par geográfico válido.

El **orden** dentro de la celda sólo se puede inferir cuando uno de los valores
excede ±90, porque entonces sólo puede ser longitud. En Salta ambos valores
caben en el rango de latitud, así que la lectura es ambigua: `auto` asume
`lat,lon` —la convención de Google Maps y de la mayoría de los GPS— y la
interfaz permite forzar el orden.

**Ruteo.** El optimizador no depende de OSRM: consume la interfaz
`RoutingProvider`. Si el motor no responde, el sistema degrada a distancias en
línea recta y lo informa explícitamente en la interfaz, en vez de entregar
números que parecen de manejo y no lo son.

**Tramos sin conexión vial.** Si OSRM no puede conectar dos cámaras por calle,
ese tramo se reporta como `null` y el recorrido se marca con
`has_unreachable_legs`. Contarlo como cero haría parecer que las paradas son
contiguas cuando el recorrido no es transitable.

**Color en el mapa.** La identidad de cada cluster la lleva el número impreso
sobre el punto, no el matiz. Una paleta categórica sólo sostiene tres colores
simultáneos sobre el fondo de los tiles OSM antes de que pares como
naranja/amarillo caigan por debajo del piso de distinguibilidad, y la cantidad
de clusters no está acotada. El color queda para un estado binario
—seleccionado vs. en reposo— que sí escala.

**pandas 3.0.** Dos cambios de comportamiento que ya nos mordieron: las
columnas de texto usan un dtype `str` dedicado, así que comparar contra
`object` para detectarlas ya no funciona; y `astype(str)` sobre esa columna
conserva los `NaN` como float en lugar de convertirlos a la cadena `"nan"`.

## Antes de exponerlo a la red

Hoy el sistema corre en `localhost` y no tiene autenticación, lo cual es
razonable para una herramienta interna de escritorio. Si en algún momento se
publica en red, hay que resolver primero:

- Autenticación y rate limiting en `/optimize/`, que corre OR-Tools hasta 30 s
  por cluster y es un blanco fácil de saturación.
- Sanitizar los mensajes de error: hoy incluyen la URL interna de OSRM.
- Fijar las versiones en `requirements.txt` y auditar con `pip-audit`.
