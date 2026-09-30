# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

El código, los comentarios y los mensajes de commit de este repositorio están en
español. Mantené ese idioma.

## Comandos

### Backend

```powershell
cd backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

.\venv\Scripts\python.exe -m pytest                              # suite completa + cobertura
.\venv\Scripts\python.exe -m pytest tests/test_ingest.py          # un archivo
.\venv\Scripts\python.exe -m pytest -k "coma_decimal"             # por nombre
.\venv\Scripts\python.exe -m pytest tests/test_optimizer.py::test_build_route_sin_puntos
```

Usá siempre `venv\Scripts\python.exe` explícitamente: el `python` del PATH es el
de Microsoft Store y no tiene las dependencias. `pytest.ini` ya fija
`pythonpath = .` y activa cobertura, así que no hacen falta flags extra.

### Frontend

```powershell
cd frontend
npm run dev      # servidor de desarrollo en :3000
npm run build    # incluye el chequeo de TypeScript — es el type-check del proyecto
npm run lint
```

No hay tests de frontend. `npm run build` es la única verificación automática;
corrélo siempre después de tocar `.tsx`.

El panel lateral es una secuencia de pasos (`components/ui/Step.tsx`):
`ControlPanel.tsx` sólo decide estado y plegado de cada uno; el contenido está
en `components/panel/`. Las fechas del plan se calculan en `lib/planDates.ts`
como texto ISO local — no pases por `Date.toISOString()`, que es UTC y corre
el día.

### Motor de ruteo

```powershell
cd osrm
.\preparar.ps1          # una sola vez: descarga Argentina, recorta Salta, arma el grafo MLD
docker compose up -d
```

Detalles en [osrm/README.md](osrm/README.md).

## Arquitectura

El sistema optimiza los recorridos de las cuadrillas que mantienen cámaras en la
provincia de Salta. El flujo completo es:

```
planilla .xlsx → encabezados + mapeo sugerido → validación de coordenadas
              → DBSCAN (agrupa por cercanía) → VRP por cluster (jornadas)
              → fechas → Excel de seguimiento → técnicos lo completan
              → se vuelve a subir: lo realizado se aparta, lo pendiente se replanifica
```

### El Excel de seguimiento es también una planilla de entrada

`services/export.py` (endpoint en `export_route.py`) arma el Excel que
completan los técnicos, y ese mismo archivo vuelve a entrar por el paso 1.
Por eso:

- La primera hoja ("Recorridos") tiene los encabezados en la fila 1, sin
  títulos arriba: `read_dataframe` lee la primera hoja y la primera fila.
- Lleva **Latitud y Longitud** además de las columnas pedidas: sin ellas lo
  pendiente no se podría replanificar sin la planilla original.
- Los nombres de columna están elegidos para que `suggest_mapping` los mapee
  solo (id, lat/lon, nodo, observación, realizado). Si cambiás un encabezado,
  corré `test_export.py::test_ida_y_vuelta…`.
- `split_done` aparta las filas tildadas en "Realizado" (Sí, x, ✓, 1…) antes
  de validar coordenadas, conservando el número de fila original.
- openpyxl escribe como **fórmula** todo texto que empieza con `=`: los textos
  que vienen del usuario (ID, observación, nodo) pasan por `_set_text`.
- El rate limiter de `/export/` vive en su router: si agregás otro, sumalo a
  `_LIMITADORES` en `tests/conftest.py`.

La jornada con menos cámaras queda siempre última (`_lightest_day_last` en
`vrp.py`): es la que tiene lugar para sumarle lo que quede pendiente.

### El backend no guarda estado

El archivo se **reenvía completo en cada llamada** junto con el mapeo de
columnas. No hay sesión, ni temporales que limpiar, ni caché entre requests.
Reajustar `eps_km` es simplemente volver a postear. Si vas a agregar un
endpoint, mantené esa propiedad.

`_ingest_and_cluster()` en `main.py` es el tramo compartido por `/process/` y
`/optimize/`; toda lógica nueva de ingesta va ahí, no duplicada.

### La capa de ruteo está abstraída a propósito

`services/routing.py` define el protocolo `RoutingProvider` con dos
implementaciones: `OsrmProvider` (distancias reales por calle) y
`HaversineProvider` (línea recta, sin dependencias). `select_provider()` elige y
**degrada con aviso explícito** si OSRM no responde — nunca en silencio, porque
las distancias en línea recta subestiman el recorrido real cerca de un 80% en
zona urbana y no sirven para operar.

`services/optimizer.py` consume esa interfaz y no conoce OSRM. Si agregás un
motor de ruteo nuevo, implementá el protocolo; no toques el optimizador.

### Convención de coordenadas

**Hacia afuera todo es `(lat, lon)`.** OSRM espera `lon,lat`, y esa inversión
ocurre únicamente dentro de `OsrmProvider._coords()`. Es el error clásico al
integrar OSRM: si ves puntos en el océano Índico, es esto.

## Restricciones que no son obvias

Cada una costó un bug difícil de diagnosticar.

### maplibre-gl tiene que quedarse en v5

`react-map-gl` 8.x está construido contra `maplibre-gl` **5.x**, pero declara su
peer dependency como `>=1.13.0`. Con ese rango npm instala la v6 sin advertir
nada, y entonces **las fuentes GeoJSON quedan vacías**: las capas se crean, el
mapa base se dibuja, no hay ningún error en consola, y simplemente no aparece
ningún punto ni recorrido. Está fijado en `^5.24.0`. No lo subas sin verificar
que react-map-gl haya declarado soporte.

### pandas 3.0 cambió dos comportamientos

- Las columnas de texto usan un dtype `str` dedicado: comparar contra `object`
  para detectarlas **ya no funciona**. Usá `pd.api.types.is_numeric_dtype()`.
- `astype(str)` sobre esas columnas **conserva los `NaN` como float** en lugar
  de convertirlos a la cadena `"nan"`. Todo lo que reciba celdas sueltas tiene
  que tolerar no-strings (ver `parse_coord_cell`).

### El trabajo bloqueante va a un hilo

`/optimize/` es `async def` pero adentro corre `requests` y OR-Tools, que son
sincrónicos. Se despachan con `anyio.to_thread.run_sync()`. Sin eso, un request
con varios clusters congela el event loop y con él todo el servidor.

### `--max-table-size` de OSRM debe coincidir

`OSRM_MAX_TABLE_SIZE` en `routing.py` (100) tiene que ser igual al flag del
`docker-compose.yml`. Para clusters más grandes hay que subir **los dos**; el
costo de la matriz crece al cuadrado.

### Un tramo sin conexión vial vale `None`, no cero

Si OSRM no puede unir dos paradas por calle, `distance_from_previous_m` es
`null` y el recorrido se marca con `has_unreachable_legs`. Contarlo como cero
haría parecer que las paradas son contiguas cuando el recorrido no es
transitable.

### El color del mapa identifica días, no clusters

La cantidad de clusters no está acotada, así que el color nunca identifica un
cluster. Sí identifica la **jornada** (día) de cada recorrido, con
`DAY_PALETTE` en `lib/vizTokens.ts`: cinco colores validados contra el fondo
de los tiles OSM comparando todos los pares. Es el máximo que pasa — sumar un
sexto rompe el piso de distinguibilidad. Con más de cinco días el color se
repite, por eso la identidad la sigue llevando el rótulo ("Día N" en la línea,
"día·orden" en cada parada), y al elegir un día se dibuja solo (las demás
capas se filtran, no se atenúan).

Ojo con las expresiones de MapLibre, que rechazan la capa entera en silencio
para el usuario (sólo queda un error en consola):

- `["case", valor]` es **inválido**: `case` exige condición, resultado y
  fallback.
- `filter={undefined}` es **inválido**: react-map-gl lo pasa tal cual. Para
  "sin filtro" usá una expresión que siempre dé verdadero (`["has", "cluster"]`).
- `["at", i, ["literal", [colores]]]` como color es **inválido**: el literal se
  tipa como `array<string>`. Usá `match` sobre el índice.

### Avisos de plausibilidad

`bounding_span_km()` mide cuánto abarcan los puntos válidos. Si supera
`MAX_SPAN_PLAUSIBLE_KM` (800 km, contra los ~600 de Salta) o si menos de la
mitad de las filas dieron coordenadas, la respuesta trae un `warning`. Es lo que
distingue "la planilla está mal mapeada" de "el sistema no anda".

### El encuadre del mapa ignora el ruido

`MapView` encuadra sólo las paradas que pertenecen a algún recorrido. Una sola
orden aislada a cientos de kilómetros obligaría a alejar tanto el mapa que los
recorridos quedarían de un píxel.

## Entorno

- **Python 3.14** en `backend/venv`. OR-Tools y scikit-learn tienen wheels para
  cp314; no bajes de versión sin necesidad.
- **`frontend/AGENTS.md`** lo regenera `next dev` en cada arranque y advierte que
  esta versión de Next.js difiere de lo que el modelo tiene memorizado. Ante una
  duda de API, consultá `node_modules/next/dist/docs/`.
- **`frontend/.env.local`** (si existe) redirige el backend a otro puerto vía
  `NEXT_PUBLIC_API_BASE_URL`. Se creó porque el 8000 quedó retenido por un
  socket huérfano; se libera al reiniciar Windows, y ahí conviene borrar el
  archivo.
- `osrm/data/` pesa cientos de MB y está ignorado por git: se reconstruye con
  `preparar.ps1`.

## Antes de exponerlo a la red

Hoy corre en `localhost` sin autenticación, lo cual es razonable para una
herramienta interna. Publicarlo exige resolver primero: autenticación y rate
limiting en `/optimize/` (corre OR-Tools hasta 30 s por cluster), sanitizar los
mensajes de error —hoy incluyen la URL interna de OSRM— y fijar las versiones de
`requirements.txt`.
