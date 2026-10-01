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
| Registro | SQLite (viene con Python: sin servidor ni dependencias) |

## Cómo funciona

1. Cargás la planilla de cámaras (`.xlsx`, `.xlsm` o `.csv`).
2. El backend lee sólo los encabezados y sugiere qué columna es cada cosa.
3. Confirmás el mapeo y ajustás el radio de agrupamiento.
4. DBSCAN agrupa las cámaras por cercanía geográfica real.
5. OR-Tools resuelve el orden de visita óptimo dentro de cada grupo.
6. El mapa dibuja cada recorrido y numera las paradas.
7. Exportás el Excel de seguimiento: el plan queda guardado en el **Registro**.
8. Los técnicos completan *Realizado*, *Observación* y el nodo; al subir ese
   Excel (en el paso 1 o en el Registro) se actualiza el avance de cada tarea.
9. Desde el Registro, "Planificar los próximos recorridos" lleva lo que falta
   de vuelta al paso 1.

## Registro de recorridos

Sección aparte (botón **Registro** arriba a la derecha) con todo lo planificado
y lo que informaron los técnicos:

- **Avance**: porcentaje realizado, tareas por estado y un gráfico de tareas
  por día (tocar un día lo muestra en el mapa).
- **Filtros**: período (todo, esta semana, este mes, próximos o un rango),
  plan y búsqueda por cámara, nodo, salida u observación.
- **Recorridos**: jornadas agrupadas por día, con su avance. Se marcan para
  verlas en el mapa —una, varias o todas— y al tocar una se enfoca y despliega
  sus paradas, donde se puede corregir el estado a mano.
- **Tareas**: cada cámara con su estado; "Faltan" arma el próximo plan.
- **Planes** (renombrar, filtrar, borrar) y **Cargas** (historial de
  seguimientos subidos).
- **Respaldo**: descarga la base completa como un archivo `.sqlite`.

Cada tarea está **pendiente**, **realizada**, **no realizada** (el técnico
puso "No") o **reprogramada** (quedó sin hacer y la cámara volvió a entrar en
un plan posterior). En el mapa cada estado tiene un ícono propio además del
color.

La base es un único archivo, `backend/data/recorridos.db` (se cambia con la
variable `DB_PATH`). Se crea sola al arrancar el backend, con el esquema de
`backend/app/esquema.sql`, y se puede abrir con cualquier cliente SQLite (DB
Browser for SQLite, DBeaver). Está ignorada por git: son datos de operación.

Cómo se cruza un seguimiento con el registro:

- El Excel exportado lleva el id del plan en una hoja oculta (`_registro`):
  se actualiza ese plan y no otro con la misma cámara y fecha.
- Cada fila se cruza por **cámara + fecha de planificación**; si la fecha no
  coincide (el técnico la corrigió), con la tarea más reciente de esa cámara.
- "Sí" marca realizada y "No", no realizada. **Una celda vacía no cambia
  nada**: un seguimiento parcial no deshace lo ya informado.
- Cargar dos veces el mismo archivo deja el registro igual (y lo avisa).

## Estructura

```
sistema-logistico-free/
├── backend/
│   ├── app/
│   │   ├── config.py             # OSRM, CORS, límites de subida, DB_PATH
│   │   ├── main.py               # Endpoints del planificador
│   │   ├── registro_route.py     # Endpoints del registro (/registro/...)
│   │   ├── database.py           # Conexión SQLite y aplicación del esquema
│   │   ├── esquema.sql           # Tablas, índices y vistas del registro
│   │   ├── schemas.py            # Modelos pydantic
│   │   └── services/
│   │       ├── ingest.py         # Lectura, mapeo y validación de planillas
│   │       ├── clustering.py     # DBSCAN con métrica haversine
│   │       ├── routing.py        # Proveedores de distancia (OSRM / línea recta)
│   │       ├── optimizer.py      # TSP por cluster con OR-Tools
│   │       ├── export.py         # Excel de seguimiento y de tareas
│   │       └── registro.py       # Planes, avance y carga de seguimientos
│   ├── data/                     # recorridos.db (se crea sola, ignorada por git)
│   └── tests/                    # 257 tests, 97% de cobertura
├── frontend/src/
│   ├── app/page.tsx              # Orquesta el planificador y la navegación
│   ├── components/
│   │   ├── MapView.tsx           # MapLibre: puntos, rótulos y polilíneas
│   │   ├── ControlPanel.tsx      # Los cinco pasos del planificador
│   │   └── registro/             # Sección Registro: panel, resumen, mapa
│   └── lib/{api,registro,mapStyle,vizTokens,statusIcons}.ts
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
| `POST /export/` | Excel de seguimiento del plan (con el id del registro, si se pasa) |

### Registro

| Endpoint | Qué hace |
|---|---|
| `GET/POST /registro/planes/` | Lista los planes con su avance / guarda uno nuevo |
| `PUT/PATCH/DELETE /registro/planes/{id}` | Reemplaza (si no tiene seguimiento), renombra o borra |
| `GET /registro/recorridos/` | Jornadas con su avance; filtros `desde`, `hasta`, `plan_id`, `q` |
| `GET /registro/recorridos/detalle?ids=…` | Jornadas completas con paradas y polilínea |
| `GET /registro/tareas/` | Tareas con su estado; `estado=faltan` = pendientes + no realizadas |
| `GET /registro/tareas.xlsx` | Las mismas tareas como Excel reimportable en el planificador |
| `PATCH /registro/tareas/{id}` | Corrige a mano estado, observación o nodo migrado |
| `POST /registro/seguimiento/` | Carga un Excel de seguimiento completado |
| `GET /registro/cargas/` | Historial de seguimientos cargados |
| `GET /registro/respaldo` | La base completa como `.sqlite` |

Las coordenadas pueden venir en dos columnas (`col_lat` + `col_lon`) o en una
sola columna combinada (`col_coords` + `coord_order`).

El planificador no guarda estado: el archivo se reenvía en cada llamada y
reajustar un parámetro es simplemente volver a postear. Lo único que se guarda
es el registro, en su propia base y con sus propios endpoints.

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
