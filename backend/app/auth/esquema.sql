-- Base de seguridad: usuarios, segundo factor, sesiones y auditoría.
--
-- Vive en un archivo propio (AUTH_DB_PATH), separado del registro: el
-- respaldo del registro no se lleva hashes, secretos ni la auditoría.
-- Se aplica al abrir la base; todo es IF NOT EXISTS.
--
-- Todas las fechas son texto ISO-8601 en UTC con microsegundos
-- ("2026-10-02T13:05:01.123456+00:00"): se comparan como texto.

CREATE TABLE IF NOT EXISTS usuarios (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario               TEXT    NOT NULL UNIQUE,   -- normalizado: NFKC + minúsculas
    nombre                TEXT    NOT NULL,
    rol                   TEXT    NOT NULL CHECK (rol IN ('admin', 'operador')),
    password_hash         TEXT    NOT NULL,          -- Argon2id (incluye sal y parámetros)
    activo                INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    debe_cambiar_password INTEGER NOT NULL DEFAULT 1 CHECK (debe_cambiar_password IN (0, 1)),
    intentos_fallidos     INTEGER NOT NULL DEFAULT 0,  -- seguidos, desde el último acceso
    bloqueos_temporales   INTEGER NOT NULL DEFAULT 0,
    bloqueado_hasta       TEXT,
    bloqueado_permanente  INTEGER NOT NULL DEFAULT 0 CHECK (bloqueado_permanente IN (0, 1)),
    creado_en             TEXT    NOT NULL,
    password_cambiada_en  TEXT    NOT NULL,
    ultimo_acceso_en      TEXT
);

-- Segundo factor. TOTP hoy; WebAuthn/FIDO2 tiene sus columnas reservadas para
-- sumarlo sin migrar la tabla (credencial, clave pública, contador de firmas).
CREATE TABLE IF NOT EXISTS factores_mfa (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id       INTEGER NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
    tipo             TEXT    NOT NULL CHECK (tipo IN ('totp', 'webauthn')),
    secreto_cifrado  TEXT,              -- TOTP: AES-256-GCM con la clave derivada "totp"
    ultimo_paso      INTEGER,           -- TOTP: último intervalo aceptado (anti-reuso)
    credencial_id    TEXT,              -- WebAuthn
    clave_publica    TEXT,              -- WebAuthn (COSE, base64)
    contador_firmas  INTEGER,           -- WebAuthn (detecta autenticadores clonados)
    confirmado       INTEGER NOT NULL DEFAULT 0 CHECK (confirmado IN (0, 1)),
    creado_en        TEXT    NOT NULL,
    confirmado_en    TEXT
);

-- Códigos de recuperación de un solo uso, por si se pierde el autenticador.
-- Se guarda su HMAC (clave derivada "recuperacion"), nunca el código.
CREATE TABLE IF NOT EXISTS codigos_recuperacion (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
    codigo_hmac TEXT    NOT NULL,
    usado_en    TEXT,
    UNIQUE (usuario_id, codigo_hmac)
);

-- Pre-autenticación: la contraseña ya se verificó, falta el segundo factor.
-- Corta, con intentos contados y atada al navegador que la empezó. Recién al
-- pasar el segundo factor se emite la cookie de sesión.
CREATE TABLE IF NOT EXISTS desafios_mfa (
    id                 TEXT    PRIMARY KEY,
    token_hash         TEXT    NOT NULL UNIQUE,
    usuario_id         INTEGER NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
    proposito          TEXT    NOT NULL CHECK (proposito IN ('verificar', 'enrolar')),
    factor_pendiente_id INTEGER REFERENCES factores_mfa (id) ON DELETE SET NULL,
    csrf               TEXT    NOT NULL,
    intentos           INTEGER NOT NULL DEFAULT 0,
    creado_en          TEXT    NOT NULL,
    expira_en          TEXT    NOT NULL,
    consumido_en       TEXT,
    ip                 TEXT    NOT NULL,
    user_agent         TEXT    NOT NULL
);

-- Sesiones de servidor. La cookie lleva un token opaco; acá sólo su hash.
-- Revocar es marcar revocada_en: el siguiente pedido ya no pasa.
CREATE TABLE IF NOT EXISTS sesiones (
    id                  TEXT    PRIMARY KEY,         -- id público, para listar y revocar
    usuario_id          INTEGER NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
    token_hash          TEXT    NOT NULL UNIQUE,
    token_anterior_hash TEXT,                        -- vale SESSION_ROTATION_GRACE_S tras rotar
    rotado_en           TEXT    NOT NULL,
    csrf                TEXT    NOT NULL,            -- token anti-CSRF (sincronizador)
    metodo_mfa          TEXT    NOT NULL,
    creada_en           TEXT    NOT NULL,
    ultima_actividad    TEXT    NOT NULL,
    expira_absoluta     TEXT    NOT NULL,
    ip_inicio           TEXT    NOT NULL,
    ip_ultima           TEXT    NOT NULL,
    user_agent          TEXT    NOT NULL,
    revocada_en         TEXT,
    motivo_revocacion   TEXT
);

CREATE INDEX IF NOT EXISTS idx_sesiones_anterior ON sesiones (token_anterior_hash);
CREATE INDEX IF NOT EXISTS idx_sesiones_usuario  ON sesiones (usuario_id, revocada_en);
CREATE INDEX IF NOT EXISTS idx_factores_usuario  ON factores_mfa (usuario_id);

-- Auditoría de accesos (requisito legal). Una fila por evento: cada intento de
-- inicio de sesión —exitoso o fallido—, cada segundo factor, cada cierre o
-- revocación de sesión y cada acción administrativa.
--
-- Es de sólo agregado: los triggers rechazan UPDATE y DELETE, y cada fila
-- lleva el HMAC de su contenido encadenado con el de la anterior. Quien edite
-- el archivo a mano (borrando los triggers) no puede rehacer la cadena sin la
-- clave maestra: `python -m app.auth.cli verificar-auditoria` lo detecta.
CREATE TABLE IF NOT EXISTS auditoria_accesos (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT    NOT NULL,          -- UTC con microsegundos
    evento            TEXT    NOT NULL,
    resultado         TEXT    NOT NULL CHECK (resultado IN ('exito', 'fallo', 'info')),
    usuario_intentado TEXT,                      -- lo que se escribió, normalizado
    usuario_id        INTEGER,                   -- sin FK: la auditoría sobrevive al usuario
    ip                TEXT    NOT NULL,          -- del cliente, resuelta detrás de proxies
    ip_conexion       TEXT    NOT NULL,          -- par TCP (el último proxy)
    x_forwarded_for   TEXT,                      -- el header crudo, para peritaje
    user_agent        TEXT,
    motivo            TEXT,                      -- detalle interno; al cliente nunca llega
    sesion_id         TEXT,
    hash_anterior     TEXT    NOT NULL,
    hash              TEXT    NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_auditoria_ip      ON auditoria_accesos (ip, ts);
CREATE INDEX IF NOT EXISTS idx_auditoria_usuario ON auditoria_accesos (usuario_intentado, ts);
CREATE INDEX IF NOT EXISTS idx_auditoria_ts      ON auditoria_accesos (ts);

CREATE TRIGGER IF NOT EXISTS auditoria_sin_modificar
BEFORE UPDATE ON auditoria_accesos
BEGIN
    SELECT RAISE(ABORT, 'La auditoría es de sólo agregado');
END;

CREATE TRIGGER IF NOT EXISTS auditoria_sin_borrar
BEFORE DELETE ON auditoria_accesos
BEGIN
    SELECT RAISE(ABORT, 'La auditoría es de sólo agregado');
END;
