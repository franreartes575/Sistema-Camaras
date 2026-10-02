"""Tests del login: contraseña, segundo factor, sesiones, bloqueo y auditoría.

Corren contra la app real (sin la sesión simulada del resto de la suite) y con
un reloj controlado: vencimientos, bloqueos y rotaciones se prueban moviendo
la hora, no esperando.
"""

import datetime as dt
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import config
from app.auth import auditoria, contrasenas, cripto, db, reloj, servicio, totp
from app.auth.contexto import ContextoPedido
from app.auth.dependencias import COOKIE_PREAUTH, COOKIE_SESION
from app.main import app

pytestmark = pytest.mark.auth_real

UA = "Mozilla/5.0 (pruebas de seguridad)"
ORIGEN = "http://localhost:3000"
PASSWORD = "una frase larga y segura"
INICIO = dt.datetime(2026, 10, 2, 12, 0, 0, tzinfo=dt.timezone.utc)


class Reloj:
    def __init__(self) -> None:
        self.momento = INICIO

    def __call__(self) -> dt.datetime:
        return self.momento

    def avanzar(self, **delta: float) -> None:
        self.momento += dt.timedelta(**delta)


@pytest.fixture
def ahora(monkeypatch) -> Reloj:
    controlado = Reloj()
    monkeypatch.setattr(reloj, "ahora", controlado)
    return controlado


def cliente(*, ua: str = UA, origen: str | None = ORIGEN, ip: str = "127.0.0.1", **extra) -> TestClient:
    headers = {"User-Agent": ua, **extra.pop("headers", {})}
    if origen:
        headers["Origin"] = origen
    return TestClient(app, base_url="https://testserver", headers=headers, client=(ip, 50000), **extra)


def crear_usuario(usuario: str = "jperez", rol: str = "operador", *, debe_cambiar: bool = False) -> None:
    conn = db.connect()
    try:
        servicio.crear_usuario(
            conn, usuario, usuario.title(), rol, PASSWORD, ContextoPedido.consola(), debe_cambiar_password=debe_cambiar
        )
    finally:
        conn.close()


def login(c: TestClient, usuario: str = "jperez", password: str = PASSWORD):
    return c.post("/auth/login", json={"usuario": usuario, "password": password})


def codigo(secreto: str, ahora: Reloj) -> str:
    return totp.codigo(secreto, totp.paso(ahora()))


def entrar_por_primera_vez(c: TestClient, ahora: Reloj, usuario: str = "jperez") -> tuple[str, dict]:
    """Login + enrolamiento TOTP. Devuelve el secreto y la sesión."""
    paso = login(c, usuario)
    assert paso.status_code == 200, paso.text
    csrf = paso.json()["csrf"]
    secreto = c.post("/auth/mfa/totp/enrolar", headers={"X-CSRF-Token": csrf}).json()["secreto"]
    sesion = c.post("/auth/mfa/totp/confirmar", json={"codigo": codigo(secreto, ahora)}, headers={"X-CSRF-Token": csrf})
    assert sesion.status_code == 200, sesion.text
    return secreto, sesion.json()


def entrar(c: TestClient, secreto: str, ahora: Reloj, usuario: str = "jperez") -> dict:
    """Login completo con un factor ya enrolado (avanza el reloj: un código
    no se puede usar dos veces)."""
    ahora.avanzar(seconds=31)
    paso = login(c, usuario)
    assert paso.status_code == 200, paso.text
    respuesta = c.post(
        "/auth/mfa/verificar", json={"codigo": codigo(secreto, ahora)}, headers={"X-CSRF-Token": paso.json()["csrf"]}
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def eventos(*, evento: str | None = None) -> list[dict]:
    conn = db.connect()
    try:
        filas = conn.execute("SELECT * FROM auditoria_accesos ORDER BY id").fetchall()
    finally:
        conn.close()
    return [dict(f) for f in filas if evento is None or f["evento"] == evento]


def usuario_db(usuario: str = "jperez") -> dict:
    conn = db.connect()
    try:
        return dict(conn.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,)).fetchone())
    finally:
        conn.close()


def set_cookies(respuesta) -> dict[str, str]:
    """Set-Cookie por nombre de cookie (el header completo, con atributos)."""
    return {linea.split("=", 1)[0]: linea for linea in respuesta.headers.get_list("set-cookie")}


# --------------------------------------------------------------------------
# 1. Contraseña: mensajes genéricos y sin enumeración
# --------------------------------------------------------------------------


def test_password_correcta_abre_el_segundo_factor_sin_sesion(ahora) -> None:
    crear_usuario()
    c = cliente()

    respuesta = login(c)

    assert respuesta.status_code == 200
    assert respuesta.json()["paso"] == "enrolar_mfa"
    cookies = set_cookies(respuesta)
    assert set(cookies) == {COOKIE_PREAUTH}  # todavía no hay cookie de sesión
    for atributo in ("HttpOnly", "Secure", "SameSite=strict", "Path=/", "Max-Age=300"):
        assert atributo in cookies[COOKIE_PREAUTH]
    assert c.get("/registro/planes/").status_code == 401


def test_usuario_inexistente_y_password_incorrecta_son_indistinguibles(ahora) -> None:
    crear_usuario()

    inexistente = login(cliente(), "nadie", "cualquier cosa")
    incorrecta = login(cliente(), "jperez", "cualquier cosa")

    assert inexistente.status_code == incorrecta.status_code == 401
    assert inexistente.json() == incorrecta.json() == {"detail": "Credenciales inválidas."}
    assert "set-cookie" not in inexistente.headers and "set-cookie" not in incorrecta.headers
    # El motivo real queda sólo en la auditoría.
    assert [e["motivo"] for e in eventos(evento="login_fallido")] == ["usuario_inexistente", "password_incorrecta"]


def test_usuario_inexistente_verifica_contra_un_hash_senuelo(ahora, monkeypatch) -> None:
    """Argon2 corre igual: el tiempo de respuesta no delata qué cuentas hay."""
    verificados: list[str] = []
    original = contrasenas.verificar
    monkeypatch.setattr(contrasenas, "verificar", lambda h, p: verificados.append(h) or original(h, p))

    login(cliente(), "nadie", "x")

    assert verificados == [contrasenas.hash_senuelo()]


@pytest.mark.parametrize("estado", ["bloqueada", "deshabilitada"])
def test_cuenta_bloqueada_o_deshabilitada_responde_igual_aun_con_la_password_correcta(ahora, estado) -> None:
    crear_usuario()
    conn = db.connect()
    columna = "bloqueado_permanente = 1" if estado == "bloqueada" else "activo = 0"
    conn.execute(f"UPDATE usuarios SET {columna}")
    conn.close()

    respuesta = login(cliente())

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "Credenciales inválidas."}


def test_el_usuario_se_normaliza(ahora) -> None:
    crear_usuario()

    assert login(cliente(), "  JPerez ").status_code == 200


def test_inyeccion_sql_en_el_usuario_es_solo_texto(ahora) -> None:
    crear_usuario()

    respuesta = login(cliente(), "' OR '1'='1' --", "' OR '1'='1")

    assert respuesta.status_code == 401
    assert usuario_db()["usuario"] == "jperez"  # la tabla sigue intacta
    assert eventos(evento="login_fallido")[0]["usuario_intentado"] == "' or '1'='1' --"


# --------------------------------------------------------------------------
# 2. Bloqueo de cuenta y límites de intentos
# --------------------------------------------------------------------------


def _fallar(veces: int, usuario: str = "jperez", c: TestClient | None = None) -> None:
    c = c or cliente()
    for _ in range(veces):
        assert login(c, usuario, "incorrecta").status_code in (401, 429)


def test_cinco_fallos_bloquean_la_cuenta_quince_minutos(ahora) -> None:
    crear_usuario()

    _fallar(5)

    assert login(cliente()).status_code == 401  # correcta, pero bloqueada
    assert usuario_db()["bloqueado_hasta"] == reloj.iso(INICIO + dt.timedelta(minutes=15))
    assert eventos(evento="bloqueo_temporal")[0]["motivo"] == "15 min (bloqueo 1)"
    ahora.avanzar(minutes=16)
    assert login(cliente()).status_code == 200


def test_cada_bloqueo_dura_el_doble_y_despues_es_permanente(ahora) -> None:
    crear_usuario()
    duraciones = []
    for minutos in (15, 30, 60):
        _fallar(5)
        duraciones.append(eventos(evento="bloqueo_temporal")[-1]["motivo"])
        ahora.avanzar(minutes=minutos + 1)

    _fallar(5)

    assert duraciones == ["15 min (bloqueo 1)", "30 min (bloqueo 2)", "60 min (bloqueo 3)"]
    assert usuario_db()["bloqueado_permanente"] == 1
    ahora.avanzar(days=30)
    assert login(cliente()).status_code == 401  # sólo lo levanta un administrador

    conn = db.connect()
    servicio.administrar(conn, "jperez", "desbloquear", ContextoPedido.consola())
    conn.close()
    assert login(cliente()).status_code == 200


def test_el_segundo_factor_fallido_cuenta_para_el_bloqueo(ahora) -> None:
    """Quien llega al código ya tiene la contraseña: tampoco puede probar sin límite."""
    crear_usuario()
    secreto, _ = entrar_por_primera_vez(cliente(), ahora)

    for _ in range(5):
        ahora.avanzar(seconds=31)
        c = cliente()
        csrf = login(c).json()["csrf"]
        c.post("/auth/mfa/verificar", json={"codigo": "000000"}, headers={"X-CSRF-Token": csrf})

    assert usuario_db()["bloqueado_hasta"] is not None
    assert login(cliente()).status_code == 401


def test_un_ingreso_completo_reinicia_los_contadores(ahora) -> None:
    crear_usuario()
    _fallar(4)

    entrar_por_primera_vez(cliente(), ahora)

    fila = usuario_db()
    assert (fila["intentos_fallidos"], fila["bloqueos_temporales"]) == (0, 0)
    assert fila["ultimo_acceso_en"] == reloj.iso(INICIO)


def test_limite_por_ip_corta_aun_con_credenciales_correctas(ahora, monkeypatch) -> None:
    monkeypatch.setattr(config, "LOGIN_MAX_FAILURES_PER_IP", 3)
    crear_usuario()
    c = cliente(ip="203.0.113.5")
    for nombre in ("a1", "a2", "a3"):
        login(c, nombre, "x")

    respuesta = login(c)

    assert respuesta.status_code == 429
    assert respuesta.json()["detail"].startswith("Demasiados intentos")
    assert eventos(evento="login_limitado")[0]["motivo"] == "limite_por_ip"
    assert login(cliente(ip="203.0.113.6")).status_code == 200  # otra IP no está afectada
    ahora.avanzar(minutes=16)
    assert login(c).status_code == 200  # la ventana pasó


def test_limite_por_usuario_aunque_el_usuario_no_exista(ahora, monkeypatch) -> None:
    """Si sólo se limitara a los que existen, el límite delataría cuáles existen."""
    monkeypatch.setattr(config, "LOGIN_MAX_FAILURES_PER_USER", 3)
    for ip in ("198.51.100.1", "198.51.100.2", "198.51.100.3"):
        login(cliente(ip=ip), "fantasma", "x")

    respuesta = login(cliente(ip="198.51.100.4"), "fantasma", "x")

    assert respuesta.status_code == 429
    assert eventos(evento="login_limitado")[0]["motivo"] == "limite_por_usuario"


def test_los_ingresos_correctos_no_cuentan_para_el_limite(ahora, monkeypatch) -> None:
    monkeypatch.setattr(config, "LOGIN_MAX_FAILURES_PER_IP", 2)
    crear_usuario()
    c = cliente()
    for _ in range(5):
        assert login(c).status_code == 200


def test_pedidos_mal_formados_se_auditan_y_cuentan_por_ip(ahora, monkeypatch) -> None:
    monkeypatch.setattr(config, "LOGIN_MAX_FAILURES_PER_IP", 2)
    crear_usuario()
    c = cliente()
    for _ in range(2):
        assert c.post("/auth/login", json={"usuario": "x" * 65, "password": "y"}).status_code == 422

    assert login(c).status_code == 429
    assert [e["motivo"] for e in eventos(evento="login_rechazado")] == ["formato_invalido"] * 2


# --------------------------------------------------------------------------
# 3. Segundo factor (TOTP + códigos de recuperación)
# --------------------------------------------------------------------------


def test_enrolamiento_completo_emite_la_cookie_de_sesion(ahora) -> None:
    crear_usuario()
    c = cliente()
    csrf = login(c).json()["csrf"]

    enrolamiento = c.post("/auth/mfa/totp/enrolar", headers={"X-CSRF-Token": csrf}).json()
    respuesta = c.post(
        "/auth/mfa/totp/confirmar", json={"codigo": codigo(enrolamiento["secreto"], ahora)},
        headers={"X-CSRF-Token": csrf},
    )

    assert respuesta.status_code == 200
    assert enrolamiento["uri"].startswith("otpauth://totp/")
    assert enrolamiento["qr"].startswith("data:image/svg+xml")
    cookies = set_cookies(respuesta)
    sesion = cookies[COOKIE_SESION]
    for atributo in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"):
        assert atributo in sesion
    assert "Max-Age" not in sesion and "Domain" not in sesion  # cookie de sesión, __Host-
    assert "Max-Age=0" in cookies[COOKIE_PREAUTH]  # la de pre-autenticación se borra
    codigos = respuesta.json()["codigos_recuperacion"]
    assert len(codigos) == 10 and all(len(cod) == 14 and cod.count("-") == 2 for cod in codigos)
    assert c.get("/registro/planes/").status_code == 200


def test_el_secreto_se_repite_dentro_del_mismo_desafio(ahora) -> None:
    crear_usuario()
    c = cliente()
    csrf = login(c).json()["csrf"]

    primero = c.post("/auth/mfa/totp/enrolar", headers={"X-CSRF-Token": csrf}).json()["secreto"]
    segundo = c.post("/auth/mfa/totp/enrolar", headers={"X-CSRF-Token": csrf}).json()["secreto"]

    assert primero == segundo


def test_el_secreto_totp_se_guarda_cifrado(ahora) -> None:
    crear_usuario()
    secreto, _ = entrar_por_primera_vez(cliente(), ahora)

    conn = db.connect()
    fila = conn.execute("SELECT * FROM factores_mfa").fetchone()
    conn.close()

    assert secreto not in fila["secreto_cifrado"]
    assert cripto.descifrar(fila["secreto_cifrado"], f"usuario:{fila['usuario_id']}") == secreto
    with pytest.raises(Exception):  # copiado a otro usuario no descifra
        cripto.descifrar(fila["secreto_cifrado"], "usuario:999")


def test_con_factor_enrolado_pide_el_codigo_y_no_permite_reenrolar(ahora) -> None:
    crear_usuario()
    entrar_por_primera_vez(cliente(), ahora)
    c = cliente()

    paso = login(c).json()

    assert paso["paso"] == "mfa"
    assert c.post("/auth/mfa/totp/enrolar", headers={"X-CSRF-Token": paso["csrf"]}).status_code == 403


def test_un_codigo_totp_no_se_puede_usar_dos_veces(ahora) -> None:
    crear_usuario()
    secreto, _ = entrar_por_primera_vez(cliente(), ahora)
    ahora.avanzar(seconds=31)
    usado = codigo(secreto, ahora)
    c1 = cliente()
    csrf1 = login(c1).json()["csrf"]
    assert c1.post("/auth/mfa/verificar", json={"codigo": usado}, headers={"X-CSRF-Token": csrf1}).status_code == 200

    c2 = cliente()
    csrf2 = login(c2).json()["csrf"]
    respuesta = c2.post("/auth/mfa/verificar", json={"codigo": usado}, headers={"X-CSRF-Token": csrf2})

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "Código inválido."}


def test_codigo_de_recuperacion_sirve_una_sola_vez(ahora) -> None:
    crear_usuario()
    _, sesion = entrar_por_primera_vez(cliente(), ahora)
    recuperacion = sesion["codigos_recuperacion"][0]

    def usar(texto: str):
        c = cliente()
        csrf = login(c).json()["csrf"]
        return c.post("/auth/mfa/verificar", json={"codigo_recuperacion": texto}, headers={"X-CSRF-Token": csrf})

    primera = usar(recuperacion.lower().replace("-", " "))  # tolera minúsculas y espacios
    segunda = usar(recuperacion)

    assert primera.status_code == 200
    assert primera.json()["codigos_restantes"] == 9
    assert segunda.status_code == 401


def test_el_desafio_vence_a_los_cinco_minutos(ahora) -> None:
    crear_usuario()
    c = cliente()
    csrf = login(c).json()["csrf"]
    ahora.avanzar(minutes=5, seconds=1)

    respuesta = c.post("/auth/mfa/totp/enrolar", headers={"X-CSRF-Token": csrf})

    assert respuesta.status_code == 401
    assert "venció" in respuesta.json()["detail"]


def test_el_desafio_se_agota_y_no_acepta_ni_el_codigo_correcto(ahora, monkeypatch) -> None:
    monkeypatch.setattr(config, "LOCKOUT_THRESHOLD", 100)  # aislar el tope del desafío
    crear_usuario()
    secreto, _ = entrar_por_primera_vez(cliente(), ahora)
    ahora.avanzar(seconds=31)
    c = cliente()
    csrf = login(c).json()["csrf"]
    respuestas = [
        c.post("/auth/mfa/verificar", json={"codigo": "000000"}, headers={"X-CSRF-Token": csrf}).json()["detail"]
        for _ in range(5)
    ]

    correcto = c.post("/auth/mfa/verificar", json={"codigo": codigo(secreto, ahora)}, headers={"X-CSRF-Token": csrf})

    assert respuestas[:4] == ["Código inválido."] * 4
    assert "venció" in respuestas[4]
    assert correcto.status_code == 401
    assert len(eventos(evento="mfa_desafio_agotado")) == 1


def test_el_desafio_exige_el_token_csrf(ahora) -> None:
    crear_usuario()
    c = cliente()
    login(c)

    assert c.post("/auth/mfa/totp/enrolar").status_code == 403
    assert c.post("/auth/mfa/totp/enrolar", headers={"X-CSRF-Token": "otro"}).status_code == 403
    assert len(eventos(evento="csrf_rechazado")) == 2


def test_el_desafio_queda_atado_al_navegador(ahora) -> None:
    crear_usuario()
    c = cliente()
    csrf = login(c).json()["csrf"]
    robada = cliente(ua="curl/8.0", cookies={COOKIE_PREAUTH: c.cookies[COOKIE_PREAUTH]})

    assert robada.post("/auth/mfa/totp/enrolar", headers={"X-CSRF-Token": csrf}).status_code == 401
    assert len(eventos(evento="desafio_otro_navegador")) == 1
    # Y queda consumido: tampoco sirve ya en el navegador original.
    assert c.post("/auth/mfa/totp/enrolar", headers={"X-CSRF-Token": csrf}).status_code == 401


def test_un_login_nuevo_invalida_el_desafio_anterior(ahora) -> None:
    crear_usuario()
    viejo = cliente()
    csrf_viejo = login(viejo).json()["csrf"]
    login(cliente())

    assert viejo.post("/auth/mfa/totp/enrolar", headers={"X-CSRF-Token": csrf_viejo}).status_code == 401


# --------------------------------------------------------------------------
# 4. Sesión: CSRF, rotación, vencimientos e invalidación desde el servidor
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [
        ("post", "/upload-excel/"),
        ("post", "/process/"),
        ("post", "/optimize/"),
        ("post", "/export/"),
        ("get", "/registro/planes/"),
        ("get", "/registro/recorridos/"),
        ("get", "/registro/respaldo"),
        ("get", "/auth/sesion"),
        ("get", "/auth/auditoria"),
    ],
)
def test_todo_exige_sesion_salvo_health(ahora, metodo, ruta) -> None:
    c = cliente()

    assert getattr(c, metodo)(ruta).status_code == 401
    assert c.get("/health").status_code == 200


def test_csrf_y_origen_en_pedidos_que_modifican(ahora) -> None:
    crear_usuario()
    c = cliente()
    _, sesion = entrar_por_primera_vez(c, ahora)
    csrf = {"X-CSRF-Token": sesion["csrf"]}

    sin_token = c.post("/auth/sesiones/cerrar-otras")
    otro_origen = cliente(origen="https://atacante.example", cookies=dict(c.cookies)).post(
        "/auth/sesiones/cerrar-otras", headers=csrf
    )
    correcto = c.post("/auth/sesiones/cerrar-otras", headers=csrf)

    assert sin_token.status_code == otro_origen.status_code == 403
    assert sin_token.json() == {"detail": "Pedido rechazado."}
    assert correcto.status_code == 200
    assert c.get("/auth/sesiones").status_code == 200  # GET no lo necesita
    assert [e["motivo"] for e in eventos(evento="csrf_rechazado")] == ["token", "origen"]


def test_login_desde_otro_origen_se_rechaza(ahora) -> None:
    crear_usuario()

    respuesta = login(cliente(origen="https://atacante.example"))

    assert respuesta.status_code == 403
    assert eventos(evento="csrf_rechazado")[0]["motivo"] == "origen_login"


def test_rotacion_del_token_y_deteccion_de_reuso(ahora) -> None:
    crear_usuario()
    c = cliente()
    entrar_por_primera_vez(c, ahora)
    viejo = c.cookies[COOKIE_SESION]
    ahora.avanzar(minutes=6)

    rotada = c.get("/auth/sesion")
    nuevo = set_cookies(rotada)[COOKIE_SESION].split(";")[0].split("=", 1)[1]

    assert rotada.status_code == 200 and nuevo != viejo
    # Un pedido que salió con el token viejo justo antes de rotar todavía pasa…
    assert cliente(cookies={COOKIE_SESION: viejo}).get("/auth/sesion").status_code == 200
    # …pero fuera de la ventana de gracia es un token robado: cae la sesión entera.
    ahora.avanzar(seconds=31)
    assert cliente(cookies={COOKIE_SESION: viejo}).get("/auth/sesion").status_code == 401
    assert cliente(cookies={COOKIE_SESION: nuevo}).get("/auth/sesion").status_code == 401
    assert len(eventos(evento="token_reusado")) == 1


def test_la_inactividad_cierra_la_sesion(ahora) -> None:
    crear_usuario()
    c = cliente()
    entrar_por_primera_vez(c, ahora)
    ahora.avanzar(minutes=15)

    respuesta = c.get("/registro/planes/")

    assert respuesta.status_code == 401
    assert "Max-Age=0" in set_cookies(respuesta)[COOKIE_SESION]
    assert eventos(evento="sesion_expirada")[0]["motivo"] == "inactividad"


def test_la_actividad_mantiene_la_sesion_hasta_el_vencimiento_absoluto(ahora) -> None:
    crear_usuario()
    c = cliente()
    entrar_por_primera_vez(c, ahora)

    for _ in range(int(8 * 60 / 10) - 1):  # cada 10 min durante casi 8 h
        ahora.avanzar(minutes=10)
        assert c.get("/auth/sesion").status_code == 200
    ahora.avanzar(minutes=10)

    assert c.get("/auth/sesion").status_code == 401
    assert eventos(evento="sesion_expirada")[0]["motivo"] == "vencida"


def test_la_sesion_informa_sus_vencimientos(ahora) -> None:
    crear_usuario()
    c = cliente()
    entrar_por_primera_vez(c, ahora)

    sesion = c.get("/auth/sesion").json()

    assert sesion["usuario"] == {"usuario": "jperez", "nombre": "Jperez", "rol": "operador"}
    assert sesion["inactividad_minutos"] == 15
    assert dt.datetime.fromisoformat(sesion["expira_inactividad_en"]) == INICIO + dt.timedelta(minutes=15)
    assert dt.datetime.fromisoformat(sesion["expira_absoluta_en"]) == INICIO + dt.timedelta(hours=8)


def test_logout_invalida_la_cookie_en_el_servidor(ahora) -> None:
    crear_usuario()
    c = cliente()
    _, sesion = entrar_por_primera_vez(c, ahora)
    copia = c.cookies[COOKIE_SESION]

    respuesta = c.post("/auth/logout", headers={"X-CSRF-Token": sesion["csrf"]})

    assert respuesta.status_code == 204
    assert "Max-Age=0" in set_cookies(respuesta)[COOKIE_SESION]
    assert cliente(cookies={COOKIE_SESION: copia}).get("/auth/sesion").status_code == 401
    assert eventos(evento="logout")[0]["usuario_intentado"] == "jperez"


def test_revocacion_desde_el_servidor_es_inmediata(ahora) -> None:
    crear_usuario()
    c = cliente()
    entrar_por_primera_vez(c, ahora)
    assert c.get("/registro/planes/").status_code == 200

    conn = db.connect()
    servicio.administrar(conn, "jperez", "revocar_sesiones", ContextoPedido.consola())
    conn.close()

    assert c.get("/registro/planes/").status_code == 401
    assert eventos(evento="sesion_revocada_usada")[0]["motivo"] == "administrador"


def test_la_cookie_copiada_a_otro_navegador_se_revoca(ahora) -> None:
    crear_usuario()
    c = cliente()
    entrar_por_primera_vez(c, ahora)

    robada = cliente(ua="Otro navegador", cookies={COOKIE_SESION: c.cookies[COOKIE_SESION]})

    assert robada.get("/auth/sesion").status_code == 401
    assert c.get("/auth/sesion").status_code == 401  # también para el original
    assert len(eventos(evento="sesion_otro_navegador")) == 1


def test_cambio_de_ip_se_audita_sin_cortar_la_sesion(ahora) -> None:
    crear_usuario()
    c = cliente(ip="127.0.0.1")
    entrar_por_primera_vez(c, ahora)

    movida = cliente(ip="127.0.0.1", headers={"X-Forwarded-For": "203.0.113.50"}, cookies=dict(c.cookies))

    assert movida.get("/auth/sesion").status_code == 200
    assert eventos(evento="sesion_ip_cambiada")[0]["motivo"] == "127.0.0.1 -> 203.0.113.50"


def test_tope_de_sesiones_simultaneas(ahora) -> None:
    crear_usuario()
    primera = cliente()
    secreto, _ = entrar_por_primera_vez(primera, ahora)
    otras = [cliente() for _ in range(3)]
    for c in otras:
        entrar(c, secreto, ahora)

    assert primera.get("/auth/sesion").status_code == 401  # la menos usada cayó
    assert all(c.get("/auth/sesion").status_code == 200 for c in otras)


def test_listar_y_cerrar_sesiones_propias(ahora) -> None:
    crear_usuario()
    a = cliente()
    secreto, sesion_a = entrar_por_primera_vez(a, ahora)
    b = cliente()
    entrar(b, secreto, ahora)

    listado = a.get("/auth/sesiones").json()
    otra = next(s for s in listado if not s["actual"])
    cerrada = a.delete(f"/auth/sesiones/{otra['id']}", headers={"X-CSRF-Token": sesion_a["csrf"]})

    assert len(listado) == 2 and sum(s["actual"] for s in listado) == 1
    assert cerrada.status_code == 204
    assert b.get("/auth/sesion").status_code == 401
    assert a.get("/auth/sesion").status_code == 200


def test_cambio_de_password_obligatorio_antes_de_usar_la_app(ahora) -> None:
    crear_usuario(debe_cambiar=True)
    a = cliente()
    secreto, sesion = entrar_por_primera_vez(a, ahora)
    b = cliente()
    entrar(b, secreto, ahora)

    bloqueada = a.get("/registro/planes/")
    debil = a.post(
        "/auth/password", json={"password_actual": PASSWORD, "password_nueva": "corta"},
        headers={"X-CSRF-Token": sesion["csrf"]},
    )
    cambio = a.post(
        "/auth/password", json={"password_actual": PASSWORD, "password_nueva": "otra frase larga distinta"},
        headers={"X-CSRF-Token": sesion["csrf"]},
    )

    assert sesion["debe_cambiar_password"] is True
    assert bloqueada.status_code == 403
    assert debil.status_code == 422
    assert cambio.status_code == 204
    assert COOKIE_SESION in set_cookies(cambio)  # token nuevo para esta sesión
    assert a.get("/registro/planes/").status_code == 200
    assert b.get("/auth/sesion").status_code == 401  # las demás sesiones se cerraron
    assert login(cliente(), password="otra frase larga distinta").status_code == 200


def test_cambio_de_password_con_la_actual_incorrecta_cuenta_para_el_bloqueo(ahora) -> None:
    crear_usuario()
    c = cliente()
    _, sesion = entrar_por_primera_vez(c, ahora)

    for _ in range(5):
        respuesta = c.post(
            "/auth/password", json={"password_actual": "adivinando", "password_nueva": "otra frase larga distinta"},
            headers={"X-CSRF-Token": sesion["csrf"]},
        )

    assert respuesta.status_code in (401, 403)
    assert c.get("/auth/sesion").status_code == 401  # la cuenta se bloqueó y la sesión cayó


def test_auditoria_y_respaldo_solo_para_administradores(ahora) -> None:
    crear_usuario("jperez", "operador")
    crear_usuario("jefa", "admin")
    operador = cliente()
    entrar_por_primera_vez(operador, ahora, "jperez")
    admin = cliente()
    entrar_por_primera_vez(admin, ahora, "jefa")

    assert operador.get("/auth/auditoria").status_code == 403
    assert operador.get("/registro/respaldo").status_code == 403
    assert admin.get("/registro/respaldo").status_code == 200
    filas = admin.get("/auth/auditoria", params={"usuario": "jperez"}).json()
    assert {f["evento"] for f in filas} >= {"usuario_creado", "password_ok", "mfa_enrolado", "sesion_iniciada"}


# --------------------------------------------------------------------------
# 5. Auditoría
# --------------------------------------------------------------------------


def test_cada_intento_registra_hora_ip_real_navegador_y_usuario(ahora) -> None:
    """Detrás del proxy de confianza (loopback), la IP es la del cliente."""
    crear_usuario()
    c = cliente(ip="127.0.0.1", headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.77"})

    login(c, "jperez", "mal")
    login(c)

    fallido, correcto = eventos(evento="login_fallido")[0], eventos(evento="password_ok")[0]
    for fila in (fallido, correcto):
        assert fila["ip"] == "203.0.113.77"  # "1.2.3.4" lo pudo inventar el cliente
        assert fila["ip_conexion"] == "127.0.0.1"
        assert fila["x_forwarded_for"] == "1.2.3.4, 203.0.113.77"
        assert fila["user_agent"] == UA
        assert fila["usuario_intentado"] == "jperez"
        assert fila["ts"] == "2026-10-02T12:00:00.000000+00:00"  # UTC con microsegundos
    assert (fallido["resultado"], correcto["resultado"]) == ("fallo", "exito")


def test_x_forwarded_for_de_un_cliente_directo_se_ignora(ahora) -> None:
    login(cliente(ip="198.51.100.9", headers={"X-Forwarded-For": "10.0.0.1"}), "x", "y")

    fila = eventos(evento="login_fallido")[0]
    assert fila["ip"] == "198.51.100.9"
    assert fila["x_forwarded_for"] == "10.0.0.1"  # se guarda igual, como evidencia


def test_caracteres_de_control_en_el_usuario_se_neutralizan(ahora) -> None:
    login(cliente(), "admin\n2026-10-02 login_ok admin", "x")

    assert eventos(evento="login_fallido")[0]["usuario_intentado"] == "admin?2026-10-02 login_ok admin"


def test_la_auditoria_no_admite_cambios_ni_borrados(ahora) -> None:
    login(cliente(), "x", "y")
    conn = db.connect()
    try:
        with pytest.raises(sqlite3.IntegrityError, match="sólo agregado"):
            conn.execute("UPDATE auditoria_accesos SET ip = '0.0.0.0'")
        with pytest.raises(sqlite3.IntegrityError, match="sólo agregado"):
            conn.execute("DELETE FROM auditoria_accesos")
    finally:
        conn.close()


def test_alterar_la_auditoria_a_mano_se_detecta(ahora) -> None:
    crear_usuario()
    for _ in range(3):
        login(cliente(), "jperez", "mal")
    conn = db.connect()
    assert auditoria.verificar_cadena(conn).integra
    # Alguien con acceso al archivo saca los triggers y "corrige" la IP.
    conn.execute("DROP TRIGGER auditoria_sin_modificar")
    conn.execute("UPDATE auditoria_accesos SET ip = '10.9.9.9' WHERE id = 3")

    resultado = auditoria.verificar_cadena(conn)
    conn.close()

    assert (resultado.integra, resultado.primera_alterada) == (False, 3)


def test_exportar_la_auditoria_a_csv_neutraliza_formulas(ahora, tmp_path) -> None:
    login(cliente(), "=HYPERLINK(\"http://x\")", "y")
    destino = tmp_path / "accesos.csv"
    conn = db.connect()
    cantidad = auditoria.exportar_csv(conn, destino, None, None)
    conn.close()

    contenido = destino.read_text(encoding="utf-8-sig")
    assert cantidad == 1
    assert "'=hyperlink" in contenido


# --------------------------------------------------------------------------
# 6. Validación de entrada
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"usuario": "jperez", "password": PASSWORD, "rol": "admin"},  # campo de más
        {"usuario": 123, "password": PASSWORD},  # tipo incorrecto (strict)
        {"usuario": "jperez"},  # falta la contraseña
        {"usuario": "", "password": PASSWORD},
        {"usuario": "jperez", "password": "x" * 257},
    ],
)
def test_esquema_estricto_en_el_login(ahora, cuerpo) -> None:
    respuesta = cliente().post("/auth/login", json=cuerpo)

    assert respuesta.status_code == 422
    assert respuesta.json() == {"detail": "Pedido inválido."}  # sin eco de lo enviado
    assert PASSWORD not in respuesta.text


def test_json_invalido_y_cuerpo_gigante(ahora) -> None:
    c = cliente()

    roto = c.post("/auth/login", content=b"{no es json", headers={"Content-Type": "application/json"})
    gigante = c.post("/auth/login", content=b"x" * 9000, headers={"Content-Type": "application/json"})

    assert roto.status_code == 422
    assert gigante.status_code == 413


@pytest.mark.parametrize(
    "cuerpo",
    [{"codigo": "12345a"}, {"codigo": "1234567"}, {}, {"codigo": "123456", "codigo_recuperacion": "AAAA-BBBB-CCCC"},
     {"codigo_recuperacion": "AAAA-BBBB-CCC!"}],
)
def test_esquema_estricto_en_el_segundo_factor(ahora, cuerpo) -> None:
    assert cliente().post("/auth/mfa/verificar", json=cuerpo).status_code == 422


def test_politica_de_password_al_crear_usuarios() -> None:
    conn = db.connect()
    try:
        for debil in ("corta", "jperez-es-mi-clave-larga", "aaaaaaaaaaaaaaaa", "123456789012345"):
            with pytest.raises(servicio.PasswordRechazada):
                servicio.crear_usuario(conn, "jperez", "J", "operador", debil, ContextoPedido.consola())
        with pytest.raises(servicio.ErrorAuth, match="El usuario debe tener"):
            servicio.crear_usuario(conn, "j p", "J", "operador", PASSWORD, ContextoPedido.consola())
    finally:
        conn.close()


# --------------------------------------------------------------------------
# 7. Cabeceras y configuración segura por defecto
# --------------------------------------------------------------------------


def test_cabeceras_de_seguridad(ahora) -> None:
    respuesta = cliente().get("/health")

    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.headers["x-content-type-options"] == "nosniff"
    assert respuesta.headers["x-frame-options"] == "DENY"
    assert respuesta.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert "max-age=" in respuesta.headers["strict-transport-security"]
    sin_tls = TestClient(app).get("/health")
    assert "strict-transport-security" not in sin_tls.headers  # HSTS sólo sobre HTTPS


def test_sin_documentacion_ni_cors_por_defecto(ahora) -> None:
    c = cliente()

    assert c.get("/docs").status_code == 404
    assert c.get("/openapi.json").status_code == 404
    preflight = c.options(
        "/auth/login",
        headers={"Origin": "https://atacante.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in preflight.headers


def test_sin_clave_maestra_el_backend_no_arranca(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "AUTH_MASTER_KEY", "")
    monkeypatch.setattr(config, "AUTH_MASTER_KEY_FILE", str(tmp_path / "no-existe.key"))

    with pytest.raises(cripto.ClaveMaestraFaltante, match="inicializar"):
        with TestClient(app):
            pass


def test_rehash_al_entrar_si_cambiaron_los_parametros(ahora, monkeypatch) -> None:
    crear_usuario()
    anterior = usuario_db()["password_hash"]
    monkeypatch.setattr(contrasenas, "necesita_rehash", lambda _: True)

    login(cliente())

    assert usuario_db()["password_hash"] != anterior
    assert contrasenas.verificar(usuario_db()["password_hash"], PASSWORD)


# --------------------------------------------------------------------------
# 8. Administración (consola)
# --------------------------------------------------------------------------


def _consola(monkeypatch, capsys, *argumentos: str, passwords: tuple[str, ...] = ()) -> str:
    from app.auth import cli

    respuestas = iter(passwords)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(respuestas))
    cli.main(list(argumentos))
    return capsys.readouterr().out


def test_consola_crea_usuarios_y_los_lista(ahora, monkeypatch, capsys) -> None:
    salida = _consola(
        monkeypatch, capsys, "crear-usuario", "--usuario", "Ana.Gomez", "--nombre", "Ana Gómez", "--rol", "admin",
        passwords=("corta", PASSWORD, "otra", PASSWORD, PASSWORD),  # rechaza la débil y la que no coincide
    )
    listado = _consola(monkeypatch, capsys, "listar-usuarios")

    assert "Usuario 'ana.gomez' creado" in salida
    assert "ana.gomez" in listado and "admin" in listado and "activo" in listado
    assert usuario_db("ana.gomez")["debe_cambiar_password"] == 1
    assert eventos(evento="usuario_creado")[0]["user_agent"].startswith("cli:")


def test_consola_resetear_mfa_obliga_a_enrolar_de_nuevo(ahora, monkeypatch, capsys) -> None:
    crear_usuario()
    c = cliente()
    entrar_por_primera_vez(c, ahora)

    _consola(monkeypatch, capsys, "resetear-mfa", "--usuario", "jperez")

    assert c.get("/auth/sesion").status_code == 401  # sus sesiones se cerraron
    assert login(cliente()).json()["paso"] == "enrolar_mfa"


def test_consola_deshabilitar_y_habilitar(ahora, monkeypatch, capsys) -> None:
    crear_usuario()
    c = cliente()
    entrar_por_primera_vez(c, ahora)

    _consola(monkeypatch, capsys, "deshabilitar", "--usuario", "jperez")
    deshabilitado = login(cliente()).status_code
    listado = _consola(monkeypatch, capsys, "listar-usuarios")
    _consola(monkeypatch, capsys, "habilitar", "--usuario", "jperez")

    assert c.get("/auth/sesion").status_code == 401
    assert deshabilitado == 401 and "deshabilitado" in listado
    assert login(cliente()).status_code == 200


def test_consola_password_provisoria_obliga_a_cambiarla(ahora, monkeypatch, capsys) -> None:
    crear_usuario()
    secreto, _ = entrar_por_primera_vez(cliente(), ahora)

    _consola(monkeypatch, capsys, "resetear-password", "--usuario", "jperez",
             passwords=("provisoria muy larga 2026",) * 2)
    c = cliente()
    ahora.avanzar(seconds=31)
    csrf = login(c, password="provisoria muy larga 2026").json()["csrf"]
    sesion = c.post("/auth/mfa/verificar", json={"codigo": codigo(secreto, ahora)}, headers={"X-CSRF-Token": csrf}).json()

    assert sesion["debe_cambiar_password"] is True
    assert c.get("/registro/planes/").status_code == 403


def test_consola_verifica_y_exporta_la_auditoria(ahora, monkeypatch, capsys, tmp_path) -> None:
    from app.auth import cli

    login(cliente(), "x", "y")
    login(cliente(), "z", "y")
    integra = _consola(monkeypatch, capsys, "verificar-auditoria")
    exportado = _consola(
        monkeypatch, capsys, "exportar-auditoria", "--salida", str(tmp_path / "a.csv"),
        "--desde", "2026-10-01", "--hasta", "2026-10-02",
    )
    conn = db.connect()
    conn.execute("DROP TRIGGER auditoria_sin_borrar")
    conn.execute("DELETE FROM auditoria_accesos WHERE id = 1")
    conn.close()

    with pytest.raises(SystemExit) as salida:
        cli.main(["verificar-auditoria"])

    assert "íntegra: 2 eventos" in integra
    assert "2 eventos exportados" in exportado  # --hasta incluye todo el día
    assert salida.value.code == 2
    assert "ALTERADA" in capsys.readouterr().out


def test_consola_informa_errores_sin_traza(ahora, monkeypatch, capsys) -> None:
    from app.auth import cli

    with pytest.raises(SystemExit) as salida:
        cli.main(["desbloquear", "--usuario", "nadie"])

    assert salida.value.code == 1
    assert "No existe el usuario 'nadie'" in capsys.readouterr().err


def test_consola_inicializar_crea_la_clave_una_sola_vez(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(config, "AUTH_MASTER_KEY", "")
    monkeypatch.setattr(config, "AUTH_MASTER_KEY_FILE", str(tmp_path / "clave.key"))

    primera = _consola(monkeypatch, capsys, "inicializar")
    segunda = _consola(monkeypatch, capsys, "inicializar")

    assert "Clave maestra creada" in primera and "RESPALDALA" in primera
    assert "ya existe" in segunda


def test_auditoria_filtrada_por_fecha(ahora) -> None:
    crear_usuario("jefa", "admin")
    admin = cliente()
    entrar_por_primera_vez(admin, ahora, "jefa")
    ahora.avanzar(minutes=10)  # dentro de la ventana de inactividad
    login(cliente(), "x", "y")

    recientes = admin.get("/auth/auditoria", params={"desde": "2026-10-02T12:05:00+00:00"}).json()
    viejos = admin.get("/auth/auditoria", params={"hasta": "2026-10-02T12:05:00+00:00"}).json()

    assert [f["evento"] for f in recientes] == ["login_fallido"]
    assert "login_fallido" not in {f["evento"] for f in viejos}
