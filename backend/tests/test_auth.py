"""Tests del login: contraseña, sesiones, bloqueo y auditoría.

Corren contra la app real (sin la sesión simulada del resto de la suite) y con
un reloj controlado: vencimientos, bloqueos y rotaciones se prueban moviendo
la hora, no esperando.
"""

import datetime as dt
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import config
from app.auth import auditoria, contrasenas, cripto, db, reloj, servicio
from app.auth.contexto import ContextoPedido
from app.auth.dependencias import COOKIE_SESION
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


def entrar(c: TestClient, ahora: Reloj | None = None, usuario: str = "jperez") -> dict:
    """Login completo. Si se pasa el reloj lo avanza un segundo antes, para que
    cada sesión tenga un último uso distinto (el tope descarta la menos usada)."""
    if ahora is not None:
        ahora.avanzar(seconds=1)
    respuesta = login(c, usuario)
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


def test_password_correcta_abre_la_sesion(ahora) -> None:
    crear_usuario()
    c = cliente()

    respuesta = login(c)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["usuario"] == {"usuario": "jperez", "nombre": "Jperez", "rol": "operador"}
    assert cuerpo["csrf"] and cuerpo["debe_cambiar_password"] is False
    cookies = set_cookies(respuesta)
    assert set(cookies) == {COOKIE_SESION}  # una sola cookie: no hay paso intermedio
    for atributo in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"):
        assert atributo in cookies[COOKIE_SESION]
    assert "Max-Age" not in cookies[COOKIE_SESION] and "Domain" not in cookies[COOKIE_SESION]  # __Host-
    assert c.get("/auth/sesion").status_code == 200
    assert c.get("/registro/planes/").status_code == 200


def test_ya_no_existe_el_segundo_factor(ahora) -> None:
    crear_usuario()
    c = cliente()
    sesion = entrar(c)
    csrf = {"X-CSRF-Token": sesion["csrf"]}

    for ruta in ("/auth/mfa/verificar", "/auth/mfa/totp/enrolar", "/auth/mfa/totp/confirmar"):
        assert c.post(ruta, json={"codigo": "123456"}, headers=csrf).status_code in (404, 405)
    assert "codigos_recuperacion" not in sesion and "codigos_restantes" not in sesion
    assert "paso" not in sesion
    assert "metodo_mfa" not in c.get("/auth/sesiones").json()[0]


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


CASA = "198.51.100.10"  # IP desde la que el usuario ya entró antes
ATACANTE = "203.0.113.66"


def _bloquear_para_siempre(ahora) -> None:
    """Un atacante desde otra IP agota los bloqueos temporales y el permanente."""
    for minutos in (15, 30, 60):
        _fallar(5, c=cliente(ip=ATACANTE))
        ahora.avanzar(minutes=minutos + 1)
    _fallar(5, c=cliente(ip=ATACANTE))
    assert usuario_db()["bloqueado_permanente"] == 1


def test_un_atacante_no_deja_afuera_al_usuario_en_una_ip_conocida(ahora) -> None:
    """El bloqueo por fallos frena a quien prueba contraseñas, no al dueño de
    la cuenta desde donde ya entró: si no, cualquiera que sepa el nombre de
    usuario podría dejar sin acceso al único administrador."""
    crear_usuario()
    entrar(cliente(ip=CASA))

    _bloquear_para_siempre(ahora)

    assert login(cliente(ip=CASA)).status_code == 200
    assert login(cliente(ip="192.0.2.77")).status_code == 401  # IP nueva: sigue bloqueada
    assert login(cliente(ip=ATACANTE)).status_code in (401, 429)


def test_una_ip_conocida_vence(ahora) -> None:
    crear_usuario()
    entrar(cliente(ip=CASA))
    ahora.avanzar(days=config.LOCKOUT_KNOWN_IP_DAYS + 1)

    _fallar(5, c=cliente(ip=ATACANTE))

    assert login(cliente(ip=CASA)).status_code == 401


def test_el_limite_por_usuario_no_corta_desde_una_ip_conocida(ahora, monkeypatch) -> None:
    monkeypatch.setattr(config, "LOGIN_MAX_FAILURES_PER_USER", 3)
    crear_usuario()
    entrar(cliente(ip=CASA))
    _fallar(3, c=cliente(ip=ATACANTE))

    assert login(cliente(ip=CASA)).status_code == 200
    assert login(cliente(ip="192.0.2.77")).status_code == 429


def test_un_bloqueo_temporal_no_cierra_las_sesiones_abiertas(ahora) -> None:
    crear_usuario()
    c = cliente(ip=CASA)
    entrar(c)

    _fallar(5, c=cliente(ip=ATACANTE))

    assert usuario_db()["bloqueado_hasta"] is not None
    assert c.get("/auth/sesion").status_code == 200


def test_un_ingreso_completo_reinicia_los_contadores(ahora) -> None:
    crear_usuario()
    _fallar(4)

    entrar(cliente())

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
# 3. Sesión: CSRF, rotación, vencimientos e invalidación desde el servidor
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
    sesion = entrar(c)
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
    entrar(c)
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
    entrar(c)
    ahora.avanzar(minutes=15)

    respuesta = c.get("/registro/planes/")

    assert respuesta.status_code == 401
    assert "Max-Age=0" in set_cookies(respuesta)[COOKIE_SESION]
    assert eventos(evento="sesion_expirada")[0]["motivo"] == "inactividad"


def _ultima_actividad() -> str:
    conn = db.connect()
    try:
        return conn.execute("SELECT ultima_actividad FROM sesiones").fetchone()[0]
    finally:
        conn.close()


def test_pedidos_seguidos_no_escriben_la_actividad_cada_vez(ahora) -> None:
    """Cada escritura es un commit a disco: con pedidos a segundos uno del
    otro (el Inicio dispara varios juntos) alcanza con marcarla cada tanto."""
    crear_usuario()
    c = cliente()
    entrar(c)
    al_entrar = _ultima_actividad()

    ahora.avanzar(seconds=config.SESSION_TOUCH_S - 1)
    assert c.get("/auth/sesion").status_code == 200
    sin_tocar = _ultima_actividad()
    ahora.avanzar(seconds=2)
    assert c.get("/auth/sesion").status_code == 200

    assert sin_tocar == al_entrar
    assert _ultima_actividad() > al_entrar


def test_la_actividad_mantiene_la_sesion_hasta_el_vencimiento_absoluto(ahora) -> None:
    crear_usuario()
    c = cliente()
    entrar(c)

    for _ in range(int(8 * 60 / 10) - 1):  # cada 10 min durante casi 8 h
        ahora.avanzar(minutes=10)
        assert c.get("/auth/sesion").status_code == 200
    ahora.avanzar(minutes=10)

    assert c.get("/auth/sesion").status_code == 401
    assert eventos(evento="sesion_expirada")[0]["motivo"] == "vencida"


def test_la_sesion_informa_sus_vencimientos(ahora) -> None:
    crear_usuario()
    c = cliente()
    entrar(c)

    sesion = c.get("/auth/sesion").json()

    assert sesion["usuario"] == {"usuario": "jperez", "nombre": "Jperez", "rol": "operador"}
    assert sesion["inactividad_minutos"] == 15
    assert dt.datetime.fromisoformat(sesion["expira_inactividad_en"]) == INICIO + dt.timedelta(minutes=15)
    assert dt.datetime.fromisoformat(sesion["expira_absoluta_en"]) == INICIO + dt.timedelta(hours=8)


def test_logout_invalida_la_cookie_en_el_servidor(ahora) -> None:
    crear_usuario()
    c = cliente()
    sesion = entrar(c)
    copia = c.cookies[COOKIE_SESION]

    respuesta = c.post("/auth/logout", headers={"X-CSRF-Token": sesion["csrf"]})

    assert respuesta.status_code == 204
    assert "Max-Age=0" in set_cookies(respuesta)[COOKIE_SESION]
    assert cliente(cookies={COOKIE_SESION: copia}).get("/auth/sesion").status_code == 401
    assert eventos(evento="logout")[0]["usuario_intentado"] == "jperez"


def test_revocacion_desde_el_servidor_es_inmediata(ahora) -> None:
    crear_usuario()
    c = cliente()
    entrar(c)
    assert c.get("/registro/planes/").status_code == 200

    conn = db.connect()
    servicio.administrar(conn, "jperez", "revocar_sesiones", ContextoPedido.consola())
    conn.close()

    assert c.get("/registro/planes/").status_code == 401
    assert eventos(evento="sesion_revocada_usada")[0]["motivo"] == "administrador"


def test_la_cookie_copiada_a_otro_navegador_se_revoca(ahora) -> None:
    crear_usuario()
    c = cliente()
    entrar(c)

    robada = cliente(ua="Otro navegador", cookies={COOKIE_SESION: c.cookies[COOKIE_SESION]})

    assert robada.get("/auth/sesion").status_code == 401
    assert c.get("/auth/sesion").status_code == 401  # también para el original
    assert len(eventos(evento="sesion_otro_navegador")) == 1


def test_cambio_de_ip_se_audita_sin_cortar_la_sesion(ahora) -> None:
    crear_usuario()
    c = cliente(ip="127.0.0.1")
    entrar(c)

    movida = cliente(ip="127.0.0.1", headers={"X-Forwarded-For": "203.0.113.50"}, cookies=dict(c.cookies))

    assert movida.get("/auth/sesion").status_code == 200
    assert eventos(evento="sesion_ip_cambiada")[0]["motivo"] == "127.0.0.1 -> 203.0.113.50"


def test_tope_de_sesiones_simultaneas(ahora) -> None:
    crear_usuario()
    primera = cliente()
    entrar(primera, ahora)
    otras = [cliente() for _ in range(3)]
    for c in otras:
        entrar(c, ahora)

    assert primera.get("/auth/sesion").status_code == 401  # la menos usada cayó
    assert all(c.get("/auth/sesion").status_code == 200 for c in otras)


def test_listar_y_cerrar_sesiones_propias(ahora) -> None:
    crear_usuario()
    a = cliente()
    sesion_a = entrar(a, ahora)
    b = cliente()
    entrar(b, ahora)

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
    sesion = entrar(a)
    b = cliente()
    entrar(b, ahora)

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
    sesion = entrar(c)

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
    entrar(operador, usuario="jperez")
    admin = cliente()
    entrar(admin, usuario="jefa")

    assert operador.get("/auth/auditoria").status_code == 403
    assert operador.get("/registro/respaldo").status_code == 403
    assert admin.get("/registro/respaldo").status_code == 200
    filas = admin.get("/auth/auditoria", params={"usuario": "jperez"}).json()
    assert {f["evento"] for f in filas} >= {"usuario_creado", "password_ok", "sesion_iniciada"}


# --------------------------------------------------------------------------
# 4. Auditoría
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
# 5. Validación de entrada
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
# 6. Cabeceras y configuración segura por defecto
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
# 7. Administración (consola)
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


def test_consola_deshabilitar_y_habilitar(ahora, monkeypatch, capsys) -> None:
    crear_usuario()
    c = cliente()
    entrar(c)

    _consola(monkeypatch, capsys, "deshabilitar", "--usuario", "jperez")
    deshabilitado = login(cliente()).status_code
    listado = _consola(monkeypatch, capsys, "listar-usuarios")
    _consola(monkeypatch, capsys, "habilitar", "--usuario", "jperez")

    assert c.get("/auth/sesion").status_code == 401
    assert deshabilitado == 401 and "deshabilitado" in listado
    assert login(cliente()).status_code == 200


def test_consola_password_provisoria_obliga_a_cambiarla(ahora, monkeypatch, capsys) -> None:
    crear_usuario()
    entrar(cliente())

    _consola(monkeypatch, capsys, "resetear-password", "--usuario", "jperez",
             passwords=("provisoria muy larga 2026",) * 2)
    c = cliente()
    sesion = login(c, password="provisoria muy larga 2026").json()

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


def _ancla(salida: str) -> str:
    """El "id:hash" que imprime `anclar-auditoria`."""
    return next(palabra for palabra in salida.split() if palabra.count(":") == 1 and len(palabra) > 60)


def test_un_ancla_detecta_que_borraron_los_ultimos_eventos(ahora, monkeypatch, capsys) -> None:
    """Borrar las últimas filas deja una cadena que cierra: sólo un ancla
    guardada afuera (id y hash de la última fila) lo delata."""
    from app.auth import cli

    for _ in range(3):
        login(cliente(), "x", "y")
    ancla = _ancla(_consola(monkeypatch, capsys, "anclar-auditoria"))
    conn = db.connect()
    conn.execute("DROP TRIGGER auditoria_sin_borrar")
    conn.execute("DELETE FROM auditoria_accesos WHERE id = (SELECT MAX(id) FROM auditoria_accesos)")
    conn.close()

    sin_ancla = _consola(monkeypatch, capsys, "verificar-auditoria")
    with pytest.raises(SystemExit) as salida:
        cli.main(["verificar-auditoria", "--ancla", ancla])

    assert "íntegra" in sin_ancla  # la cadena sola no lo ve
    assert salida.value.code == 2
    assert f"id={ancla.split(':')[0]}" in capsys.readouterr().out


def test_las_anclas_se_guardan_en_un_archivo_y_se_verifican_desde_ahi(
    ahora, monkeypatch, capsys, tmp_path
) -> None:
    archivo = tmp_path / "otro-equipo" / "anclas.txt"
    login(cliente(), "x", "y")
    _consola(monkeypatch, capsys, "anclar-auditoria", "--archivo", str(archivo))
    login(cliente(), "z", "y")
    _consola(monkeypatch, capsys, "anclar-auditoria", "--archivo", str(archivo))

    salida = _consola(monkeypatch, capsys, "verificar-auditoria", "--anclas-archivo", str(archivo))

    assert len(archivo.read_text(encoding="utf-8").splitlines()) == 2
    assert "íntegra" in salida and "2 ancla(s)" in salida


def test_un_ancla_con_otro_hash_no_pasa(ahora, monkeypatch, capsys) -> None:
    from app.auth import cli

    login(cliente(), "x", "y")
    ancla = _ancla(_consola(monkeypatch, capsys, "anclar-auditoria"))
    falsa = ancla.split(":")[0] + ":" + "0" * 64

    with pytest.raises(SystemExit) as salida:
        cli.main(["verificar-auditoria", "--ancla", falsa])

    assert salida.value.code == 2


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
    entrar(admin, usuario="jefa")
    ahora.avanzar(minutes=10)  # dentro de la ventana de inactividad
    login(cliente(), "x", "y")

    recientes = admin.get("/auth/auditoria", params={"desde": "2026-10-02T12:05:00+00:00"}).json()
    viejos = admin.get("/auth/auditoria", params={"hasta": "2026-10-02T12:05:00+00:00"}).json()

    assert [f["evento"] for f in recientes] == ["login_fallido"]
    assert "login_fallido" not in {f["evento"] for f in viejos}


def test_sin_redireccion_que_filtre_la_direccion_interna(ahora) -> None:
    """Sin la barra final no hay 307 hacia http://127.0.0.1:8000/...: 404 seco."""
    respuesta = cliente().post("/upload-excel", follow_redirects=False)

    assert respuesta.status_code == 404
    assert "location" not in respuesta.headers
