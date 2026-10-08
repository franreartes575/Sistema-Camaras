-- Registro de recorridos: esquema de la base SQLite.
--
-- Se aplica cada vez que el backend abre la base y todo es IF NOT EXISTS: crear
-- la base es simplemente arrancar el backend, y aplicarlo dos veces no cambia
-- nada. La versión del esquema queda en `PRAGMA user_version` (ver database.py)
-- para poder migrar en el futuro sin adivinar qué tiene cada base.
--
-- Modelo:
--   planes              un plan guardado desde el planificador (o al exportar)
--   └─ recorridos       una jornada: fecha, salida, distancia, polilínea
--      └─ paradas       una cámara a visitar = una tarea, con su estado
--   cargas_seguimiento  historial de Excel de seguimiento cargados
--   camaras             catálogo: todas las cámaras, se planifiquen o no
--   sedes               bases operativas de las que salen las cuadrillas
--   cargas_catalogo     historial de planillas importadas al catálogo
--   correcciones        quién corrigió a mano cada tarea, y qué cambió
--   actividad           quién creó, cambió o borró cada plan y cargó cada seguimiento
--
-- El estado guardado de una parada es el que informaron los técnicos
-- (pendiente / realizada / no_realizada). "Reprogramada" no se guarda: se
-- deriva en `v_paradas` cuando la misma cámara volvió a planificarse en un plan
-- posterior. Así borrar o rehacer un plan nunca deja marcas viejas colgadas.

CREATE TABLE IF NOT EXISTS planes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre          TEXT    NOT NULL,
    creado_en       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    archivo_origen  TEXT,
    motor           TEXT,                    -- 'osrm' o 'haversine'
    por_calle       INTEGER NOT NULL DEFAULT 0 CHECK (por_calle IN (0, 1)),
    notas           TEXT
);

CREATE TABLE IF NOT EXISTS recorridos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id             INTEGER NOT NULL REFERENCES planes (id) ON DELETE CASCADE,
    fecha               TEXT    NOT NULL,    -- AAAA-MM-DD
    cluster_id          INTEGER NOT NULL,
    dia                 INTEGER NOT NULL CHECK (dia >= 1),  -- jornada dentro del cluster
    salida_nombre       TEXT,
    salida_lat          REAL    NOT NULL,
    salida_lon          REAL    NOT NULL,
    distancia_m         REAL    NOT NULL,
    duracion_s          REAL    NOT NULL,
    tramos_sin_conexion INTEGER NOT NULL DEFAULT 0 CHECK (tramos_sin_conexion IN (0, 1)),
    geometria           TEXT    NOT NULL DEFAULT '[]',  -- JSON: [[lat, lon], ...]
    UNIQUE (plan_id, cluster_id, dia)
);

CREATE TABLE IF NOT EXISTS paradas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recorrido_id    INTEGER NOT NULL REFERENCES recorridos (id) ON DELETE CASCADE,
    orden           INTEGER NOT NULL CHECK (orden >= 1),
    camara_id       TEXT    NOT NULL,
    lat             REAL    NOT NULL,
    lon             REAL    NOT NULL,
    descripcion     TEXT,
    nodo_preliminar TEXT,
    nodo_migrado    TEXT,                    -- lo carga el técnico
    observacion     TEXT,
    estado          TEXT    NOT NULL DEFAULT 'pendiente'
                    CHECK (estado IN ('pendiente', 'realizada', 'no_realizada')),
    verificado_en   TEXT,                    -- última vez que un seguimiento la tocó
    -- Copia de recorridos.plan_id, que nunca cambia: con el índice
    -- (camara_id, plan_id) "¿se volvió a planificar?" es una búsqueda, no
    -- un recorrido por todas las paradas (ver v_paradas).
    plan_id         INTEGER,
    -- Lo que informa el seguimiento: quién la hizo y qué día se trabajó (la
    -- fecha de cierre, o la programada). Si la fecha no es la de su jornada,
    -- la tarea se reprogramó por fuera del programa (ver v_paradas).
    cuadrilla       TEXT,
    fecha_informada TEXT,                    -- AAAA-MM-DD: fecha de ejecución
    requiere_camion TEXT,                    -- «INDICAR SI REQUIERE CAMION» de Zeta
    pendientes_manual TEXT,                  -- escritos a mano; si no, se calculan
    UNIQUE (recorrido_id, orden)
);

CREATE TABLE IF NOT EXISTS cargas_seguimiento (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    archivo          TEXT    NOT NULL,
    sha256           TEXT    NOT NULL,       -- detecta el mismo archivo cargado dos veces
    cargado_en       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    plan_id          INTEGER REFERENCES planes (id) ON DELETE SET NULL,
    filas            INTEGER NOT NULL,
    coincidencias    INTEGER NOT NULL,
    actualizadas     INTEGER NOT NULL,
    realizadas       INTEGER NOT NULL,
    no_realizadas    INTEGER NOT NULL,
    sin_coincidencia INTEGER NOT NULL
);

-- Catálogo de cámaras. El id es el mismo texto que `paradas.camara_id`: el
-- cruce con el registro es por ahí, sin clave foránea, porque un plan puede
-- tener cámaras que (todavía) no están en el catálogo.
CREATE TABLE IF NOT EXISTS camaras (
    id               TEXT    PRIMARY KEY,
    lat              REAL    NOT NULL,
    lon              REAL    NOT NULL,
    localidad        TEXT    NOT NULL DEFAULT 'Sin calcular',  -- municipio, por coordenadas
    localidad_manual INTEGER NOT NULL DEFAULT 0 CHECK (localidad_manual IN (0, 1)),
    descripcion      TEXT,
    nodo             TEXT,
    observacion      TEXT,
    creada_en        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    actualizada_en   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS sedes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre    TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    lat       REAL    NOT NULL,
    lon       REAL    NOT NULL,
    creada_en TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS cargas_catalogo (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    archivo      TEXT    NOT NULL,
    sha256       TEXT    NOT NULL,
    cargado_en   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    filas        INTEGER NOT NULL,
    nuevas       INTEGER NOT NULL,
    actualizadas INTEGER NOT NULL,
    sin_cambios  INTEGER NOT NULL,
    descartadas  INTEGER NOT NULL
);

-- Correcciones manuales de una tarea desde el Registro: quién cambió qué
-- campo, cuándo, y de qué valor a cuál. Una fila por campo cambiado. Sólo se
-- agrega (la API no edita ni borra filas). Guarda cámara, plan y fecha por su
-- cuenta para que el historial no se pierda si después se borra el plan
-- (`parada_id` queda en NULL).
CREATE TABLE IF NOT EXISTS correcciones (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    parada_id      INTEGER REFERENCES paradas (id) ON DELETE SET NULL,
    plan_id        INTEGER NOT NULL,
    camara_id      TEXT    NOT NULL,
    fecha          TEXT    NOT NULL,         -- AAAA-MM-DD de la jornada
    corregido_en   TEXT    NOT NULL,
    usuario        TEXT    NOT NULL,         -- usuario con el que inició sesión
    nombre         TEXT    NOT NULL,         -- su nombre visible en ese momento
    campo          TEXT    NOT NULL,         -- columna de `paradas` (o «jornada», si se movió)
    valor_anterior TEXT,
    valor_nuevo    TEXT
);

-- Quién hizo cada cambio sobre los planes: crearlos, reemplazarlos,
-- renombrarlos, borrarlos y cargarles seguimientos. Sólo se agrega, en la
-- misma transacción que el cambio. Sin clave foránea a `planes`: guarda el
-- id y el nombre para que lo borrado siga figurando.
CREATE TABLE IF NOT EXISTS actividad (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    en          TEXT    NOT NULL,
    usuario     TEXT    NOT NULL,
    nombre      TEXT    NOT NULL,
    accion      TEXT    NOT NULL CHECK (accion IN (
                    'plan_creado', 'plan_reemplazado', 'plan_editado', 'plan_borrado',
                    'seguimiento_cargado')),
    plan_id     INTEGER,
    plan_nombre TEXT,
    detalle     TEXT
);

CREATE INDEX IF NOT EXISTS idx_recorridos_plan  ON recorridos (plan_id);
CREATE INDEX IF NOT EXISTS idx_recorridos_fecha ON recorridos (fecha);
CREATE INDEX IF NOT EXISTS idx_paradas_recorrido ON paradas (recorrido_id);
CREATE INDEX IF NOT EXISTS idx_paradas_camara   ON paradas (camara_id);
CREATE INDEX IF NOT EXISTS idx_paradas_camara_plan ON paradas (camara_id, plan_id);
CREATE INDEX IF NOT EXISTS idx_paradas_plan      ON paradas (plan_id, estado);
CREATE INDEX IF NOT EXISTS idx_cargas_sha256    ON cargas_seguimiento (sha256);
CREATE INDEX IF NOT EXISTS idx_camaras_localidad ON camaras (localidad);
CREATE INDEX IF NOT EXISTS idx_correcciones_parada ON correcciones (parada_id);

-- Cada parada con su jornada y su estado efectivo. Una tarea que quedó
-- pendiente (o no realizada) y cuya cámara aparece en un plan posterior ya no
-- falta: se volvió a programar.
CREATE VIEW IF NOT EXISTS v_paradas AS
SELECT
    pa.*,
    r.plan_id,
    pl.nombre AS plan_nombre,
    r.fecha,
    r.cluster_id,
    r.dia,
    CASE
        WHEN pa.estado <> 'realizada' AND EXISTS (
            SELECT 1 FROM paradas otra
            WHERE otra.camara_id = pa.camara_id AND otra.plan_id > r.plan_id
        ) THEN 'reprogramada'
        ELSE pa.estado
    END AS estado_actual,
    (pa.fecha_informada IS NOT NULL AND pa.fecha_informada <> r.fecha) AS fuera_de_plan
FROM paradas pa
JOIN recorridos r ON r.id = pa.recorrido_id
JOIN planes pl ON pl.id = r.plan_id;

-- Una fila por jornada con el avance de sus tareas. Agrega sobre `paradas` y
-- no sobre v_paradas: un LEFT JOIN a esa vista obliga a SQLite a calcularla
-- entera (todas las paradas del registro) aunque se pida una sola jornada.
-- Los EXISTS repiten la regla de "reprogramada" de v_paradas (una búsqueda en
-- el índice (camara_id, plan_id), sólo para las que no están realizadas).
CREATE VIEW IF NOT EXISTS v_recorridos AS
SELECT
    r.id,
    r.plan_id,
    pl.nombre AS plan_nombre,
    r.fecha,
    r.cluster_id,
    r.dia,
    r.salida_nombre,
    r.salida_lat,
    r.salida_lon,
    r.distancia_m,
    r.duracion_s,
    r.tramos_sin_conexion,
    COUNT(pa.id)                                   AS total,
    COALESCE(SUM(pa.estado = 'realizada'), 0)      AS realizadas,
    COALESCE(SUM(pa.estado = 'pendiente' AND NOT EXISTS (
        SELECT 1 FROM paradas otra
        WHERE otra.camara_id = pa.camara_id AND otra.plan_id > r.plan_id
    )), 0)                                         AS pendientes,
    COALESCE(SUM(pa.estado = 'no_realizada' AND NOT EXISTS (
        SELECT 1 FROM paradas otra
        WHERE otra.camara_id = pa.camara_id AND otra.plan_id > r.plan_id
    )), 0)                                         AS no_realizadas,
    COALESCE(SUM(pa.estado <> 'realizada' AND EXISTS (
        SELECT 1 FROM paradas otra
        WHERE otra.camara_id = pa.camara_id AND otra.plan_id > r.plan_id
    )), 0)                                         AS reprogramadas
FROM recorridos r
JOIN planes pl ON pl.id = r.plan_id
LEFT JOIN paradas pa ON pa.recorrido_id = r.id
GROUP BY r.id;

-- Una fila por plan con el avance acumulado de todas sus jornadas. Con
-- subconsultas por plan (índices por plan_id) y no agregando v_recorridos:
-- así pedir un plan calcula sólo ese, no todos.
CREATE VIEW IF NOT EXISTS v_planes AS
SELECT
    pl.id,
    pl.nombre,
    pl.creado_en,
    pl.archivo_origen,
    pl.motor,
    pl.por_calle,
    pl.notas,
    (SELECT COUNT(*) FROM recorridos r WHERE r.plan_id = pl.id)      AS recorridos,
    (SELECT MIN(r.fecha) FROM recorridos r WHERE r.plan_id = pl.id)  AS fecha_desde,
    (SELECT MAX(r.fecha) FROM recorridos r WHERE r.plan_id = pl.id)  AS fecha_hasta,
    (SELECT COALESCE(SUM(r.distancia_m), 0) FROM recorridos r WHERE r.plan_id = pl.id) AS distancia_m,
    (SELECT COALESCE(SUM(r.duracion_s), 0) FROM recorridos r WHERE r.plan_id = pl.id)  AS duracion_s,
    (SELECT COUNT(*) FROM paradas pa WHERE pa.plan_id = pl.id)       AS total,
    (SELECT COUNT(*) FROM paradas pa
     WHERE pa.plan_id = pl.id AND pa.estado = 'realizada')           AS realizadas,
    (SELECT COUNT(*) FROM paradas pa
     WHERE pa.plan_id = pl.id AND pa.estado = 'pendiente' AND NOT EXISTS (
         SELECT 1 FROM paradas otra
         WHERE otra.camara_id = pa.camara_id AND otra.plan_id > pl.id))  AS pendientes,
    (SELECT COUNT(*) FROM paradas pa
     WHERE pa.plan_id = pl.id AND pa.estado = 'no_realizada' AND NOT EXISTS (
         SELECT 1 FROM paradas otra
         WHERE otra.camara_id = pa.camara_id AND otra.plan_id > pl.id))  AS no_realizadas,
    (SELECT COUNT(*) FROM paradas pa
     WHERE pa.plan_id = pl.id AND pa.estado <> 'realizada' AND EXISTS (
         SELECT 1 FROM paradas otra
         WHERE otra.camara_id = pa.camara_id AND otra.plan_id > pl.id))  AS reprogramadas
FROM planes pl;
