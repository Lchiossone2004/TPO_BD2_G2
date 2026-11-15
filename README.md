# FarmaRed S.A. — Sistema Políglota de Gestión Farmacéutica (TPO BD2)

Proyecto para el Trabajo Práctico Obligatorio de **Bases de Datos 2** basado en una arquitectura políglota con **MongoDB** y **Redis**, capa de aplicación en **Python** y una interfaz **Web + API REST (FastAPI)** junto con un **runner CLI**.

---

## 1. Arquitectura Políglota

El sistema combina dos motores de paradigmas distintos:

| Motor | Paradigma | Rol en el sistema | Justificación técnica |
| :--- | :--- | :--- | :--- |
| **MongoDB** | Documental | Fuente de verdad autoritativa (`clientes`, `sucursales`, `farmaceuticos`, `proveedores`, `productos`, `recetas`, `stock_lotes`, `ventas` con `items` embebidos, `contadores`) | Modelo documental con ítems embebidos en ventas, agregaciones (`$lookup`), índices únicos (`dni`, `matricula`, `id_operacion`) y **transacciones ACID multi-documento** sobre Replica Set `rs0` para confirmar venta, actualización de receta y descuento FEFO de stock en una única unidad atómica. |
| **Redis** | Clave-Valor (en memoria) | Caché **cache-aside** de referencia para productos (`farmared:producto:<id>`) y proveedores (`farmared:proveedor:<id>`) con **TTL de 300 segundos** | Acelera lecturas repetidas de catálogo y proveedores en consultas como Q1 y Q8. No almacena stock ni estado autoritativo de ventas; si Redis no está disponible, la aplicación hace *fallback* transparente a MongoDB sin bloquear lecturas ni escrituras. |

---

## 2. Estructura del Repositorio

```text
.
├── .devcontainer/
│   ├── devcontainer.json               # Configuración VS Code Dev Containers / GitHub Codespaces
│   └── docker-compose.devcontainer.yml # Servicio devcontainer Python 3.12 conectado a MongoDB y Redis
├── docker-compose.yml                  # Servicios MongoDB (Replica Set rs0) y Redis 7
├── requirements.txt                    # Dependencias Python
├── .env.example                        # Plantilla de variables de entorno
├── .gitignore
├── README.md
├── data/
│   ├── original/                       # Los 9 CSV originales provistos por la cátedra (sin modificar)
│   └── additional/                     # Datasets adicionales propios del grupo
├── seed.py                             # Script de carga reproducible e idempotente + creación de índices
├── main.py                             # Runner CLI para healthcheck y consultas/servicios Q1–Q15
├── src/
│   ├── clock.py                        # Helper único hoy() en America/Argentina/Buenos_Aires y fechas BSON/ISO
│   ├── infrastructure/                 # Conexiones MongoDB / Redis y configuración por entorno
│   ├── queries/                        # Consultas y servicios q01 a q15
│   ├── services/                       # Reglas de negocio compartidas entre Web y CLI
│   └── web/
│       ├── app.py                      # Aplicación FastAPI (Web + API OpenAPI)
│       └── static/                     # HTML, CSS y JavaScript estáticos
└── tests/                              # Suite automatizada con pytest
```

---

## 3. Requisitos e Instalación de Dependencias

### Requisitos previos

- **Docker** y **Docker Compose** (v2 o superior) para ejecutar MongoDB y Redis localmente.
- **Python 3.11+** (el devcontainer utiliza Python 3.12) si se ejecuta desde el host sin Dev Containers.
- Alternativamente, **GitHub Codespaces** o **VS Code + Dev Containers** (no requiere instalar Python ni motores en el host).

### Instalación en entorno local (host)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --no-cache-dir -r requirements.txt
```

Las dependencias declaradas en [`requirements.txt`](requirements.txt) incluyen `pymongo`, `redis`, `fastapi`, `uvicorn[standard]`, `python-dotenv`, `pytest` y `httpx`.

---

## 4. Variables de Entorno

Copiar [`.env.example`](.env.example) como `.env` para ejecución local desde el host:

```bash
cp .env.example .env
```

| Variable | Valor desde el host local | Valor desde Devcontainer / Codespaces | Descripción |
| :--- | :--- | :--- | :--- |
| `MONGODB_URI` | `mongodb://localhost:27017/?replicaSet=rs0&directConnection=true` | `mongodb://mongodb:27017/?replicaSet=rs0&directConnection=true` | URI de conexión al Replica Set `rs0` (`directConnection=true` requerido para conexiones directas al nodo único). |
| `MONGODB_DB` | `farmared` | `farmared` | Nombre de la base de datos en MongoDB. |
| `REDIS_URL` | `redis://localhost:6379/0` | `redis://redis:6379/0` | URL de conexión a Redis para la caché cache-aside. |

> En Dev Containers / GitHub Codespaces estas variables ya vienen configuradas automáticamente mediante `remoteEnv` en [`.devcontainer/devcontainer.json`](.devcontainer/devcontainer.json).

---

## 5. Levantar las Bases de Datos y Entornos

### Opción A: Ejecución local con Docker Compose

Levantar MongoDB (con inicialización automática del Replica Set `rs0`) y Redis esperando a que ambos pasen sus `healthcheck`:

```bash
docker compose up -d --wait
```

Verificar el estado de los contenedores:

```bash
docker compose ps
```

> **Nota de compatibilidad en Linux (kernel >= 6.19):** El servicio `mongodb` en [`docker-compose.yml`](docker-compose.yml) configura `GLIBC_TUNABLES: "glibc.pthread.rseq=1"` para evitar fallos de arranque de `mongod` en kernels Linux recientes (issue `SERVER-121912`). Los datos de MongoDB persisten en el volumen `mongodb_data`.

### Opción B: GitHub Codespaces o VS Code Dev Containers

1. Abrir el repositorio en **GitHub Codespaces** (o en VS Code con *Reopen in Container*).
2. El entorno utiliza [`.devcontainer/devcontainer.json`](.devcontainer/devcontainer.json) junto con [`docker-compose.yml`](docker-compose.yml) y [`.devcontainer/docker-compose.devcontainer.yml`](.devcontainer/docker-compose.devcontainer.yml).
3. Compose levanta `mongodb` y `redis` y espera a que estén `healthy` antes de iniciar el contenedor Python 3.12 (`devcontainer`).
4. `postCreateCommand` instala automáticamente `requirements.txt`.
5. Los puertos `8000` (*FarmaRed Web & API (FastAPI)*), `27017` y `6379` quedan reenviados automáticamente.

---

## 6. Verificación, Carga de Datos, Web/API, CLI y Tests

### Verificar conectividad y estado de motores

```bash
python main.py --health
```

### Cargar los datasets (originales + adicionales)

La carga es explícita e idempotente (resetea únicamente la base configurada y las claves Redis del proyecto, crea los índices y carga `data/original/` y `data/additional/`):

```bash
python seed.py                           # genera los adicionales con la fecha de hoy, valida y carga
python seed.py --dry-run                 # valida todo sin tocar MongoDB ni Redis
python seed.py --original-only           # solo los 9 CSV originales
python seed.py --base-date 2026-10-13    # fija la fecha base de los escenarios relativos
```

Los CSV de `data/additional/` los genera `src/loading/extra_data.py` a partir de la fecha base, para que Q5, Q6, Q11 y Q12 siempre tengan datos vigentes; con la misma fecha base el resultado es idéntico. Si algún dato es inválido (tipos, referencias, totales, reglas de recetas) el seed lo informa y no modifica la base. Ejecutarlo antes de la defensa.

### Arrancar la Web y API FastAPI

```bash
uvicorn src.web.app:app --host 0.0.0.0 --port 8000
```

Una vez levantado el servidor (en local o mediante el puerto reenviado `8000` en Codespaces):

- **Interfaz Web (panel de consultas Q1–Q15 y arquitectura):** [http://localhost:8000/](http://localhost:8000/)
- **Documentación interactiva Swagger UI / OpenAPI:** [http://localhost:8000/docs](http://localhost:8000/docs)

### Ejecutar la suite de tests automatizados

```bash
pytest -v
```

---

## 7. Cómo ejecutar cada consulta y servicio (Q1–Q15)

Con las bases levantadas y los datos cargados (`python seed.py`), cada consulta se ejecuta desde la CLI con `python main.py --query qNN` y, si lleva parámetros, `--param clave=valor` (repetible). La salida es JSON. `python main.py --list` muestra el catálogo con motores y parámetros. La misma funcionalidad está en la Web (`http://localhost:8000/`, un botón por consulta) y en la API (Swagger en `/docs`).

| Id | Consulta / servicio | Motores | Comando |
| :--- | :--- | :--- | :--- |
| Q1 | Productos activos con proveedor | MongoDB + Redis | `python main.py --query q01` |
| Q2 | Ventas pendientes con farmacéutico y sucursal | MongoDB | `python main.py --query q02` |
| Q3 | Historial cronológico de un cliente | MongoDB | `python main.py --query q03 --param id_cliente=C001` |
| Q4 | Clientes con más de una receta | MongoDB | `python main.py --query q04` |
| Q5 | Ventas por farmacéutico activo (últimos 60 días) | MongoDB | `python main.py --query q05` |
| Q6 | Recetas prolongadas con próxima dispensa vencida | MongoDB | `python main.py --query q06` |
| Q7 | Top 5 productos más vendidos | MongoDB | `python main.py --query q07` |
| Q8 | Lotes con menos de 50 unidades | MongoDB + Redis | `python main.py --query q08` |
| Q9 | Ventas libres menores a $5.000 | MongoDB | `python main.py --query q09` |
| Q10 | Clientes atendidos en una sucursal | MongoDB | `python main.py --query q10 --param id_sucursal=S001` |
| Q11 | Ingresos por farmacéutico en el mes actual | MongoDB | `python main.py --query q11` |
| Q12 | Clientes sin ventas en el último año | MongoDB | `python main.py --query q12` |
| Q13 | ABM de clientes | MongoDB | ver ejemplos abajo |
| Q14 | Registro de nueva venta integrada | MongoDB (transacción) | ver ejemplo abajo |
| Q15 | Descuento de stock FEFO de una venta de servicio | MongoDB (transacción) | `python main.py --query q15 --param id_venta=V900` |

### Ejemplos de Q13, Q14 y Q15

```bash
# Q13 — alta, modificación y baja de un cliente (acciones: alta | modificacion | baja)
python main.py --query q13 --param accion=alta --param nombre=José --param apellido=Amalfitani  --param dni=30111222 --param email=pepe@mail.com --param telefono=1155550000 --param ciudad="Liniers" --param provincia="Buenos Aires" --param obra_social="Galeano" --param nro_afiliado=VS-1994 
python main.py --query q13 --param accion=alta --param nombre=José --param apellido=Amalfitani --param dni=30111222 --param ciudad="Liniers" --param provincia="Buenos Aires" --param obra_social="Galeano"   # rechazo: DNI_DUPLICADO

# Q14 — venta integrada (ítems como PRD001:2,PRD002:1; el id_operacion hace idempotente el reintento)
python main.py --query q14 --param id_cliente=C001 --param id_farmaceutico=F001 --param medio_pago=Efectivo --param items=PRD001:2,PRD002:1 --param id_operacion=demo-001

# Q15 — descuento FEFO de una venta de servicio Completada sin stock aplicado
# (V900 es la venta técnica que crea `python demo.py`; ver la Web para recrearla)
python main.py --query q15 --param id_venta=V900
```

> Los valores de `accion` de Q13 y los campos exactos de cada servicio están en `python main.py --list` y en `src/queries/q13.py`, `q14.py` y `q15.py` (docstrings de `ejecutar`). Q14 y Q15 modifican datos: para repetir una demo desde cero, volver a correr `python seed.py --base-date 2026-10-13`.

### Verificación rápida en GitHub Codespaces

```bash
python main.py --health                  # Mongo y Redis en "ok"
python seed.py --base-date 2026-10-13    # carga idempotente
python main.py --query q07               # una consulta de ejemplo
pytest -q                                # suite completa
uvicorn src.web.app:app --host 0.0.0.0 --port 8000   # abrir el puerto 8000 reenviado
```

También está `python demo.py` (levanta bases, carga datos, crea la venta V900 de q15 y abre la Web); con `--no-docker` usa los servicios ya disponibles, como en Codespaces, y con `--reset` recarga los datos.