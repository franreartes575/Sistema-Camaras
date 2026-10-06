# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

El código, los comentarios y los mensajes de commit de este repositorio están en
español. Mantené ese idioma.

## Comandos

### Backend

```powershell
cd backend
.\venv\Scripts\python.exe -m app.auth.cli inicializar        # una vez: clave maestra + base de seguridad
.\venv\Scripts\python.exe -m app.auth.cli crear-usuario --usuario admin --nombre "Admin" --rol admin
.\venv\Scripts\python.exe -m app.catalogo_cli preparar-municipios  # una vez: límites del IGN para la localidad
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --no-proxy-headers --port 8000

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

Todo pasa por `components/auth/AuthGate.tsx`: sin sesión no se monta nada de
la aplicación, y al perderla (logout, inactividad, revocación) se desmonta
entera. Dentro, tres secciones, Inicio (la que abre), Planificar y Registro,
que se eligen en el encabezado (`app/page.tsx`); quedan montadas y se ocultan
con CSS, así que ir y volver no pierde el estado de ninguna. El catálogo y las
sedes se leen una vez en `page.tsx` y los comparten Inicio y el paso 1;
`catalogVersion` / `registroVersion` fuerzan a releer después de un cambio.

Las lecturas de datos usan `lib/useJson.ts`, que reintenta una vez un GET
que falla por algo pasajero (status 0 o 5xx): el rewrite `/api` de Next
devuelve un 500 sin llegar al backend si se le cae la conexión, y el Inicio
dispara varias lecturas juntas al entrar.

Toda llamada al backend pasa por `lib/http.ts` (`apiFetch`): va a `/api/...`
en el mismo origen, agrega `X-CSRF-Token` en los métodos que modifican y avisa
a AuthGate ante un 401. No uses `fetch` directo.

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

exportar guarda el plan en el registro (SQLite) → subir el seguimiento
              actualiza el estado de cada tarea → "lo que falta" vuelve al paso 1
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

### El planificador no guarda estado; el registro sí

En `/upload-excel/`, `/process/`, `/optimize/` y `/export/` el archivo se
**reenvía completo en cada llamada** junto con el mapeo de columnas. No hay
sesión, ni temporales que limpiar, ni caché entre requests. Reajustar `eps_km`
es simplemente volver a postear. Si vas a agregar un endpoint al planificador,
mantené esa propiedad.

Lo único con estado es el **registro** (`registro_route.py`, prefijo
`/registro/`): una base SQLite en `DB_PATH` (por defecto
`backend/data/recorridos.db`, ignorada por git). No toques la base desde los
endpoints del planificador: el frontend guarda el plan llamando a
`/registro/planes/` antes de `/export/`.

### Autenticación (`app/auth/`)

Modelo: sesiones opacas de servidor (no JWT, para poder revocarlas al
instante), contraseña Argon2id (sin segundo factor), auditoría de sólo agregado.
Todo endpoint que no sea `/auth/*` ni `/health` depende de `requiere_sesion`
(`dependencias.py`); los de administración, de `requiere_admin`. Un endpoint
nuevo tiene que llevarla: en `main.py` va en `dependencies=[...]`, y los
routers se incluyen con `dependencies=[Depends(requiere_sesion)]`.

- **Base separada** (`AUTH_DB_PATH`, `seguridad.db`) del registro: el respaldo
  del registro no se lleva hashes ni la auditoría. Transacciones explícitas
  (`db.transaccion`, `BEGIN IMMEDIATE`) porque la auditoría encadena cada fila
  con la anterior.
- **Los servicios devuelven el error, no lo lanzan, dentro de la
  transacción**: un intento fallido tiene que quedar auditado y contado aunque
  el pedido termine en 401. Las funciones públicas lo lanzan después del
  COMMIT. Si agregás un flujo, respetá ese patrón (`_paso()` + `isinstance`).
- **Argon2 fuera de la transacción**: tarda decenas de ms y no debe retener
  el lock de escritura.
- **Mensajes al cliente siempre genéricos** (`servicio.ErrorAuth.mensaje`); el
  motivo real va a `auditoria.registrar(..., motivo=...)`. No agregues
  mensajes que distingan usuario inexistente, contraseña incorrecta o bloqueo.
- **Cookies**: se programan en `request.state` y las aplica
  `SeguridadMiddleware` sobre la respuesta que sea (también las `Response`
  directas de las descargas). `__Host-` exige `Secure` y `Path=/`.
- **Reloj**: todo pasa por `reloj.ahora()` (UTC); los tests lo mueven.
- **Clave maestra**: derivadas por propósito con HKDF (`cripto.subclave`). Sin
  ella el backend no arranca (lifespan).

`ingest_points()` en `app/ingesta.py` es el tramo compartido "archivo →
puntos válidos" de `/process/`, `/optimize/` (vía `_ingest_and_cluster()` en
`main.py`, que además agrupa) y `/catalogo/importar/`; toda lógica nueva de
ingesta va ahí, no duplicada.

### Registro de recorridos

- El esquema vive en `app/esquema.sql` (todo `IF NOT EXISTS`) y lo aplica
  `database.connect()` al abrir la base; `SCHEMA_VERSION` va a
  `PRAGMA user_version`. Si cambiás una tabla existente, subí la versión y
  escribí la migración: `IF NOT EXISTS` no altera tablas ya creadas.
- Las columnas de la base están en castellano (es lo que ve quien la abre con
  un cliente SQL) y la API mantiene los nombres en inglés del resto del
  backend: la traducción está en los alias de los SELECT de
  `services/registro.py`.
- **"Reprogramada" no se guarda, se deriva** en la vista `v_paradas`: una
  tarea no realizada cuya cámara aparece en un plan con id mayor. Así borrar o
  reemplazar un plan nunca deja marcas viejas. El estado guardado sólo puede
  ser `pendiente`, `realizada` o `no_realizada` (hay un CHECK).
- Al cargar un seguimiento, **una celda vacía en "Realizado" no cambia el
  estado** (`reported_status` devuelve None): un Excel parcial no deshace lo ya
  informado. "No" marca `no_realizada`. Cargar dos veces el mismo archivo es
  idempotente; el sha256 sólo sirve para avisarlo.
- El Excel exportado lleva el id del plan en la hoja oculta `_registro`
  (`read_plan_id`). Sin ella, el cruce es por cámara + fecha, prefiriendo el
  plan más nuevo.
- `PUT /registro/planes/{id}` reemplaza un plan **sólo si no tiene
  seguimiento** (409 si no). El frontend (`persistPlan` en `page.tsx`) lo usa
  mientras se siga trabajando sobre la misma planilla —mover fechas,
  recalcular— para no duplicar el plan; ante 409 o 404 guarda uno nuevo. Si el
  nombre era el automático, sigue a las fechas nuevas.
- El respaldo usa `VACUUM INTO`, no `conn.serialize()`: la base está en modo
  WAL y serializarla copia esa marca en el encabezado, y el archivo resultante
  no abre sin su `-wal`.
- Los tests escriben en una base temporal por test (fixture autouse
  `_base_temporal` en `conftest.py`). El limitador del registro está en
  `_LIMITADORES`.
- Los tests corren con una sesión de administrador simulada
  (`_sesion_simulada` en `conftest.py`). Los de autenticación llevan
  `pytestmark = pytest.mark.auth_real` y usan el flujo real; su cliente es
  `https://testserver` (sin https, httpx no manda las cookies `Secure`).

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

### Los clusters con la misma sede se resuelven juntos

`_solve_routes` agrupa los clusters por punto de partida (`_group_clusters_by_start`)
cuando `merge_clusters` está activo, y resuelve cada grupo como un solo problema
de ruteo: una jornada puede mezclar cámaras de varios clusters, y `ClusterRoute.cluster_ids`
los lista (`cluster_id` es el menor). Un vehículo sale y vuelve a una sola sede, por eso
sedes distintas nunca comparten día. La API lo deja apagado por defecto (conserva el
comportamiento anterior); el frontend lo manda activado. El frontend renumera
`vehicle_day` de corrido en todo el plan (`optimize()` en `lib/api.ts`).

### `--max-table-size` de OSRM debe coincidir

`OSRM_MAX_TABLE_SIZE` en `routing.py` (1000) tiene que ser igual al flag del
`docker-compose.yml`. Para clusters más grandes hay que subir **los dos**; el
costo de la matriz crece al cuadrado.

### Un tramo sin conexión vial vale `None`, no cero

Si OSRM no puede unir dos paradas por calle, `distance_from_previous_m` es
`null` y el recorrido se marca con `has_unreachable_legs`. Contarlo como cero
haría parecer que las paradas son contiguas cuando el recorrido no es
transitable.

### Catálogo de cámaras y sedes (`catalogo_route.py`, prefijo `/catalogo/`)

- Tablas `camaras`, `sedes` y `cargas_catalogo` en la **misma base del
  registro** (esquema v2): el catálogo se cruza con `paradas` por el texto del
  ID, sin clave foránea, y el respaldo se lo lleva. Leer es para cualquier
  sesión; escribir, `requiere_admin`. El limitador del catálogo está en
  `_LIMITADORES`.
- Importar **combina por ID y nunca borra**; una celda vacía no pisa lo que
  había. Cada importación recalcula la localidad de todo el catálogo.
- **La localidad es el municipio, calculado por coordenadas** con los límites
  del IGN en `app/data/municipios_salta.geojson` (`config.MUNICIPIOS_PATH`),
  que genera `python -m app.catalogo_cli preparar-municipios`. Punto en
  polígono vectorizado con numpy (`services/localidades.py`): en Python puro
  miles de cámaras tardan segundos. Sin el archivo la localidad es "Sin
  calcular" — nunca se inventa. Fuera de todo municipio pero a menos de 5 km,
  el más cercano (la simplificación deja huecos en los bordes); si no, "Fuera
  de Salta". `localidad_manual = 1` (corrección de un admin) no la pisa
  ninguna importación. Los tests usan polígonos inventados
  (`tests/municipios_de_prueba.py`) y `conftest.py` apunta
  `MUNICIPIOS_PATH` a un archivo temporal que no existe.
- **Planificar desde el catálogo no toca el planificador**: `POST
  /catalogo/planilla` devuelve un .xlsx con las cámaras elegidas y encabezados
  que `suggest_mapping` reconoce solos, y el frontend lo pasa a `handleFile`
  como si se hubiera subido. Es .xlsx y no CSV porque `read_csv` convierte
  "00123" en 123 y el ID deja de coincidir con el catálogo y el registro.
- Las sedes viven en el servidor (antes, en `localStorage`). La primera vez
  que entra un admin con el servidor sin sedes, `page.tsx` sube las del
  navegador y borra la clave (`migrateLegacyDepots`).

### El color del mapa identifica días, no clusters

La cantidad de clusters no está acotada, así que el color nunca identifica un
cluster. Sí identifica la **jornada** (día) de cada recorrido, con
`DAY_PALETTE` en `lib/vizTokens.ts`: cinco colores validados contra el fondo
de los tiles OSM comparando todos los pares. Es el máximo que pasa — sumar un
sexto rompe el piso de distinguibilidad. Con más de cinco días el color se
repite, por eso la identidad la sigue llevando el rótulo ("Día N" en la línea,
"día·orden" en cada parada), y al elegir un día se dibuja solo (las demás
capas se filtran, no se atenúan).

**La excepción es el mapa del Inicio** (`components/inicio/CatalogMap.tsx`),
donde se pide distinguir clusters: usa los mismos cinco colores
(`CLUSTER_PALETTE`) y el backend asigna el índice (`assign_colors`) para que
los clusters cercanos no lo compartan; la identidad la lleva el rótulo "C n".
Las sedes van debajo de las cámaras (están en medio de un cluster y lo
taparían) y sus nombres arriba de todo.

Ojo con las expresiones de MapLibre, que rechazan la capa entera en silencio
para el usuario (sólo queda un error en consola):

- `["case", valor]` es **inválido**: `case` exige condición, resultado y
  fallback.
- `filter={undefined}` es **inválido**: react-map-gl lo pasa tal cual. Para
  "sin filtro" usá una expresión que siempre dé verdadero (`["has", "cluster"]`).
- `["at", i, ["literal", [colores]]]` como color es **inválido**: el literal se
  tipa como `array<string>`. Usá `match` sobre el índice.

### El mapa del registro no colorea por día

En el registro conviven jornadas de días y planes distintos: los cinco colores
de `DAY_PALETTE` no alcanzan y su verde y su rojo chocarían con los estados.
Ahí todas las líneas van en `ROUTE_LINE` con su rótulo de fecha, la jornada
enfocada en `ROUTE_LINE_FOCUS` y las demás atenuadas.

El **estado** de cada tarea (`STATUS_INK` en `lib/vizTokens.ts`) nunca va sólo
con color: verde y rojo no se distinguen con deuteranopía (medido). En el panel
lleva ícono + rótulo (`StatusBadge`); en el mapa, un ícono dibujado en canvas
(`lib/statusIcons.ts`) porque el servidor de glifos no trae ✓ ni ✕; en las
barras apiladas, lo pendiente va entre lo realizado y lo no realizado. La capa
de íconos se monta recién después de `addStatusIcons` (en `onLoad`), así nunca
pide una imagen que todavía no está registrada.

### El rewrite `/api` de Next tiene dos trampas

- `:path*` **descarta la barra final**: `/api/upload-excel/` llegaba como
  `/upload-excel`, FastAPI redirigía (307) a `http://127.0.0.1:8000/...` y el
  navegador recibía la dirección interna. Por eso hay dos reglas en
  `next.config.ts` (la de la barra primero) y `redirect_slashes=False` en la
  app: una ruta mal escrita da 404, nunca un Location interno.
- **No agrega `X-Forwarded-For`** y reenvía el que mande el cliente. Sin un
  proxy delante, todos los pedidos llegan como 127.0.0.1; con Next expuesto a
  la red, la IP sería falsificable. Por eso Next escucha sólo en 127.0.0.1
  (`-H 127.0.0.1` en los scripts) y en producción va detrás de un proxy TLS
  que reescribe la cabecera (`deploy/`).

uvicorn, por su lado, reescribe la IP del cliente desde `X-Forwarded-For`
cuando el par es 127.0.0.1 (`--proxy-headers`, activo por defecto): la
auditoría perdería la IP de conexión. Corrélo con `--no-proxy-headers`; la IP
la resuelve `red.py` según `TRUSTED_PROXIES`.

### La CSP lleva nonce, y eso obliga a renderizar por pedido

`src/proxy.ts` genera un nonce por pedido y Next lo aplica a sus scripts. Una
página estática no puede llevarlo: `layout.tsx` llama a `connection()`. Si
agregás un dominio externo (tiles, fuentes), sumalo a la CSP del proxy o el
navegador lo bloquea en silencio (queda sólo un error en la consola). El
matcher excluye `/api`: si el proxy corriera ahí, Next retendría en memoria
los cuerpos de las subidas (tope de 10 MB por defecto).

### El radio de agrupamiento arranca en 20 km

En Salta los pueblos que atiende una misma sede quedan a más de 5 km entre sí
(Orán, Pichanal, Yrigoyen): con el radio viejo de 5 km cada uno era un cluster
aparte, mientras que en Tartagal varios quedaban encadenados en uno solo. Por
eso el planificador (`params.eps_km` en `page.tsx`) y el mapa del Inicio
arrancan en 20 km, y `GET /catalogo/clusters` usa el mismo valor por defecto.

### Un `sr-only` necesita un ancestro `relative`

`sr-only` es `position: absolute`. Sin un ancestro posicionado, el input se
ubica respecto del documento, en su lugar dentro de un panel con scroll, y
estira la página más allá de `h-dvh`: aparece un hueco abajo y el encabezado
se va de la vista. Las zonas para soltar archivos (`<label>` con un `<input
type="file" className="sr-only">`) llevan `relative`, y `<main>` lleva
`overflow-hidden` para que la página nunca se desplace entera.

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
  `NEXT_PUBLIC_API_BASE_URL` (o `BACKEND_URL`, el nombre nuevo). Ahora lo lee
  sólo el rewrite de `next.config.ts`: el navegador siempre llama a `/api`. Se
  creó porque el 8000 quedó retenido por un socket huérfano; se libera al
  reiniciar Windows, y ahí conviene borrar el archivo.
- `backend/data/seguridad.db` (usuarios, sesiones, auditoría) y
  `backend/data/clave_maestra.key`. **Perder la clave deja inservible la
  verificación de la auditoría**: respaldala aparte.
- `osrm/data/` pesa cientos de MB y está ignorado por git: se reconstruye con
  `preparar.ps1`.
- `backend/data/recorridos.db` es la base del registro (más sus `-wal` y
  `-shm` mientras el backend corre). Para respaldarla, copiala con el backend
  detenido o usá el botón **Respaldo** de la sección Registro.
- El lint usa las reglas del React Compiler (`react-hooks` 7): no se puede
  llamar a `setState` sincrónicamente dentro de un `useEffect` (hacelo en el
  `.then` de la promesa o en un timer), y un `useMemo` cuyo cálculo muta
  objetos falla con `preserve-manual-memoization`.

## Despliegue

Fuera de `localhost` va detrás de un proxy HTTPS (`deploy/Caddyfile` o
`deploy/nginx.conf`): sin TLS el navegador descarta las cookies `Secure` y nadie
puede entrar. Ver "Despliegue en red" en el README para lo que no se puede
omitir (reescribir `X-Forwarded-For`, `ALLOWED_ORIGINS`, la clave maestra).
