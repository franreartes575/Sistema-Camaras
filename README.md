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
| Acceso | Argon2id, sesiones de servidor, auditoría encadenada con HMAC |

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
│   │   ├── red.py                # IP real del cliente detrás de proxies
│   │   ├── auth/                 # Login, sesiones, auditoría y CLI
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
│   ├── data/                     # recorridos.db, seguridad.db y la clave maestra (ignorada por git)
│   └── tests/                    # 367 tests, 98% de cobertura
├── frontend/src/
│   ├── app/page.tsx              # Orquesta el planificador y la navegación
│   ├── components/
│   │   ├── MapView.tsx           # MapLibre: puntos, rótulos y polilíneas
│   │   ├── ControlPanel.tsx      # Los cinco pasos del planificador
│   │   ├── auth/                 # Puerta de acceso, login, inactividad
│   │   └── registro/             # Sección Registro: panel, resumen, mapa
│   └── lib/{api,registro,mapStyle,vizTokens,statusIcons}.ts
├── deploy/                       # Proxy HTTPS: Caddyfile y nginx.conf
└── osrm/                         # Motor de ruteo — ver osrm/README.md
    ├── docker-compose.yml
    └── preparar.ps1
```

## Cómo correrlo

### Primera vez: clave maestra y usuarios

Todo el sistema exige iniciar sesión. Antes del primer arranque:

```powershell
cd backend
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m app.auth.cli inicializar
.\venv\Scripts\python.exe -m app.auth.cli crear-usuario --usuario admin --nombre "Administración" --rol admin
```

`inicializar` crea la clave maestra en `backend/data/clave_maestra.key`.
**Respaldala aparte** (fuera del equipo y separada de las bases): sin ella no
se puede verificar la auditoría. Sin clave el backend no arranca.

La contraseña que le pone el administrador a cada usuario es provisoria y la
tiene que cambiar al entrar.

### Backend

```powershell
cd backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --no-proxy-headers --port 8000
```

`--no-proxy-headers` deja que la IP real del cliente la resuelva el sistema
(ver [Seguridad](#seguridad-y-acceso)) en vez de uvicorn. La documentación
interactiva (`/docs`) está apagada; para desarrollo: `$env:API_DOCS=1`.

### Frontend

```powershell
cd frontend
npm run dev
```

Aplicación en <http://localhost:3000>. El navegador habla sólo con el
frontend: `/api/*` se reenvía al backend (variable `BACKEND_URL`, por defecto
`http://127.0.0.1:8000`).

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

## Seguridad y acceso

El sistema maneja infraestructura de cámaras de seguridad: todo, salvo
`/health`, exige una sesión iniciada.

**Ingreso.** Usuario y contraseña (Argon2id); con la contraseña correcta se
emite la cookie de sesión. No hay segundo factor: la contraseña es la única
barrera, así que no conviene exponer el sistema a internet sin sumar otra capa
(VPN, o volver a activar un segundo factor).

**Sin enumeración de usuarios.** Usuario inexistente, contraseña incorrecta,
cuenta bloqueada o deshabilitada: siempre "Credenciales inválidas.", con el
mismo tiempo de respuesta (se verifica contra un hash señuelo). El motivo real
queda sólo en la auditoría.

**Bloqueos y límites.** 5 fallos seguidos bloquean la cuenta 15 minutos; cada
bloqueo siguiente dura el doble, y al cuarto queda bloqueada hasta que la
desbloquee un administrador. Además, por ventana de 15 minutos: 20 fallos por
IP y 10 por nombre de usuario (exista o no). Los límites se cuentan en la
auditoría, así que sobreviven a un reinicio.

**Sesiones.** Token opaco de 256 bits en una cookie `__Host-sid` `HttpOnly`,
`Secure` y `SameSite=Strict`; en el servidor sólo se guarda su hash. Se cierra
tras 15 minutos sin actividad y, pase lo que pase, a las 8 horas. El token se
rota cada 5 minutos; usar uno viejo fuera de una gracia de 30 s revoca la
sesión entera (indica una cookie robada). Una cookie usada desde otro navegador
también la revoca. Máximo 3 sesiones simultáneas por usuario. El frontend avisa
un minuto antes del cierre por inactividad y, al cerrar, desmonta la aplicación
entera: no quedan datos en memoria. Nada sensible va a `localStorage`.

**CSRF y XSS.** Token anti-CSRF por sesión en `X-CSRF-Token` más chequeo de
`Origin` en todo pedido que modifica. Content-Security-Policy con nonce por
pedido (`script-src 'nonce-…' 'strict-dynamic'`): un script inyectado no corre.
Entradas validadas con esquemas estrictos (pydantic `strict`, sin campos de
más) y consultas SQL siempre parametrizadas.

**Auditoría** (`backend/data/seguridad.db`, tabla `auditoria_accesos`). Cada
intento de ingreso —exitoso o fallido—, cierre,
revocación y acción administrativa, con hora UTC en microsegundos, IP real del
cliente (resuelta detrás de proxies de confianza), IP de conexión,
`X-Forwarded-For` crudo, navegador y usuario intentado. Es de sólo agregado
(triggers) y cada fila está encadenada con un HMAC de la anterior: borrar o
editar una fila se detecta con `verificar-auditoria`.

**Administración** (desde la consola del servidor, nunca por la web):

```powershell
.\venv\Scripts\python.exe -m app.auth.cli listar-usuarios
.\venv\Scripts\python.exe -m app.auth.cli desbloquear --usuario jperez
.\venv\Scripts\python.exe -m app.auth.cli resetear-password --usuario jperez   # provisoria
.\venv\Scripts\python.exe -m app.auth.cli deshabilitar --usuario jperez        # y habilitar
.\venv\Scripts\python.exe -m app.auth.cli revocar-sesiones --usuario jperez    # cierra ya mismo
.\venv\Scripts\python.exe -m app.auth.cli verificar-auditoria
.\venv\Scripts\python.exe -m app.auth.cli exportar-auditoria --salida accesos.csv --desde 2026-10-01 --hasta 2026-10-31
```

Los administradores también ven la auditoría en `GET /api/auth/auditoria` y
son los únicos que pueden descargar el respaldo del registro.

### Despliegue en red

Fuera de `localhost` el sistema **tiene que** ir detrás de un proxy HTTPS: las
cookies son `Secure` y, sin TLS, el navegador no las guarda. En
[`deploy/`](deploy/) hay una configuración lista para
[Caddy](deploy/Caddyfile) (certificados automáticos) y otra para
[nginx](deploy/nginx.conf). Lo que no se puede omitir:

- El proxy **reescribe** `X-Forwarded-For` con la IP real del cliente; nunca
  agrega a lo que mandó el cliente. El backend sólo cree ese header si viene de
  `TRUSTED_PROXIES` (por defecto, loopback).
- Backend y frontend escuchan sólo en `127.0.0.1` (`npm run start` y uvicorn ya
  lo hacen): desde la red se llega únicamente por el proxy.
- `ALLOWED_ORIGINS=https://el-dominio-real` en el backend.
- La clave maestra por variable de entorno (`AUTH_MASTER_KEY`) desde un gestor
  de secretos, o el archivo con permisos sólo para la cuenta del servicio (en
  Windows, ajustá la ACL del archivo: el código no puede hacerlo).
- Exportar la auditoría periódicamente a un almacenamiento externo de sólo
  escritura: la cadena de HMAC detecta alteraciones, pero quien tenga la clave
  maestra y la base podría rehacerla.

Toda la configuración (tiempos, umbrales, orígenes) está documentada en
`backend/app/config.py` y se ajusta por variables de entorno.

## API

| Endpoint | Qué hace |
|---|---|
| `GET /health` | Estado del servicio y URL de OSRM configurada |
| `POST /upload-excel/` | Devuelve los encabezados y sugiere el mapeo de columnas |
| `POST /process/` | Ingesta + validación + agrupamiento DBSCAN |
| `POST /optimize/` | Todo lo anterior más el recorrido optimizado de cada cluster |
| `POST /export/` | Excel de seguimiento del plan (con el id del registro, si se pasa) |

Todas exigen sesión. Desde el navegador se llaman como `/api/...`.

### Autenticación

| Endpoint | Qué hace |
|---|---|
| `POST /auth/login` | Usuario y contraseña; abre la sesión |
| `GET /auth/sesion` | Usuario, token CSRF y vencimientos (cuenta como actividad) |
| `POST /auth/logout` | Cierra la sesión en el servidor |
| `GET /auth/sesiones` · `DELETE /auth/sesiones/{id}` · `POST /auth/sesiones/cerrar-otras` | Sesiones propias |
| `POST /auth/password` | Cambia la contraseña y cierra las demás sesiones |
| `GET /auth/auditoria` | Eventos de acceso (sólo administradores) |

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

## Pendientes de seguridad

- WebAuthn/FIDO2: la base ya tiene las columnas; falta el flujo
  (`py_webauthn` en el backend, `navigator.credentials` en el frontend).
- Chequear contraseñas contra listas de filtradas: hoy sólo hay una lista
  corta local (el sistema no sale a internet).
- Varias réplicas del backend: SQLite y el limitador en memoria asumen un único
  proceso; para escalar hace falta una base compartida.
- Auditar las dependencias con `pip-audit` y `npm audit` antes de cada
  despliegue.
