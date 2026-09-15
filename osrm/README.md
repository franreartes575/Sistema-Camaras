# Motor de ruteo OSRM — Provincia de Salta

Instancia local de [OSRM](https://project-osrm.org/) que le da al backend las
distancias reales por calle y las polilineas de los recorridos. Sin esto el
sistema funciona igual, pero con distancias en linea recta que subestiman el
recorrido real y no sirven para que una cuadrilla las siga.

Todo corre en contenedores y en `localhost`: no se expone nada a la red y
ningun dato de las camaras sale del equipo.

## Requisito previo: Docker

El equipo tiene virtualizacion activa y Windows 11 Home, que soporta WSL2.
**Los dos pasos siguientes piden permisos de administrador y un reinicio.**

### Opcion recomendada — WSL2 + Docker Engine

Sin licenciamiento comercial y mas liviano que Docker Desktop.

```powershell
# 1. PowerShell COMO ADMINISTRADOR. Instala WSL2 + Ubuntu.
wsl --install -d Ubuntu
# ... reiniciar Windows, y al volver crear usuario y contrasena de Ubuntu ...
```

```bash
# 2. Ya dentro de Ubuntu (abrir "Ubuntu" desde el menu inicio):
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# cerrar y volver a abrir Ubuntu para que tome el grupo
docker run --rm hello-world
```

Con esta opcion, los comandos de este README se corren **desde Ubuntu**, no
desde PowerShell. El proyecto se ve desde WSL en `/mnt/c/Laburo/sistema-logistico-free`.

### Opcion alternativa — Docker Desktop

Mas simple de operar, con interfaz grafica. Instalador:
<https://www.docker.com/products/docker-desktop/>

Ojo con la licencia: Docker Desktop es gratis para uso personal, educacion,
open source y empresas de menos de 250 empleados **y** menos de USD 10 M de
facturacion anual. Por encima de esos umbrales requiere suscripcion paga.

## Construir el grafo (una sola vez)

```powershell
cd C:\Laburo\sistema-logistico-free\osrm
.\preparar.ps1
```

El script descarga el extracto de Argentina de Geofabrik (~410 MB), lo recorta
al bounding box de Salta y corre el preprocesado de OSRM. En este equipo
(Ryzen 7, 8 nucleos) deberia tardar entre 5 y 15 minutos.

Para rehacerlo con un mapa actualizado: `.\preparar.ps1 -Force`

## Levantar el motor

```powershell
docker compose up -d          # arranca
docker compose logs -f        # ver los logs
docker compose down           # detener
```

Verificacion rapida — el punto es la plaza 9 de Julio de Salta capital:

```powershell
curl http://localhost:5000/nearest/v1/driving/-65.4117,-24.7859
```

Con el motor arriba, el backend lo detecta solo: en la interfaz, el selector
"Motor de distancias" en modo **Automatico** pasa a usar OSRM y el panel deja
de mostrar la advertencia de linea recta.

## Detalles de implementacion

**Por que se recorta.** Procesar Argentina entera pide varios GB de RAM y
bastante tiempo. El bounding box de Salta reduce el archivo a una fraccion y
el preprocesado entra holgado.

**Por que un bounding box y no el poligono exacto de la provincia.** El bbox
incluye una franja de las provincias vecinas, y eso es deseable: las rutas
nacionales que salen y vuelven a entrar a Salta siguen siendo navegables. Con
el poligono exacto, un tramo que cruza a Jujuy cortaria el recorrido.

    oeste -68.8 · sur -26.6 · este -62.0 · norte -21.7

**`--max-table-size 100`.** Es el tope de coordenadas por matriz de distancias,
y coincide con `OSRM_MAX_TABLE_SIZE` en `backend/app/services/routing.py`. Si
necesitas clusters de mas de 100 camaras hay que subir **los dos** valores;
tener en cuenta que el costo de la matriz crece al cuadrado.

**MLD y no CH.** MLD (`partition` + `customize`) es el algoritmo recomendado
por OSRM: preprocesa mas rapido y permite recustomizar sin reextraer.

**Archivos generados.** Todo queda en `data/`, que esta en `.gitignore`: son
cientos de MB de binarios derivados, reconstruibles con `preparar.ps1`.
