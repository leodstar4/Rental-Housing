# Renta MX — Plataforma de arrendamiento con requisitos legales a la vista

> **Producto activo del repositorio** (`main`). Pivote sobre _Rental Housing Law Navigator_, el
> proyecto original de EE. UU. (ver [`README.md`](README.md) y [`docs/US_LEGACY.md`](docs/US_LEGACY.md)),
> que queda congelado y accesible en `/us`.
>
> ⚖️ **No es asesoría legal.** Prototipo informativo. Cada afirmación legal enlaza a su fuente
> oficial con cita literal; verifíquela y consulte a un profesional antes de firmar o actuar.

Renta MX es una plataforma tipo _marketplace_ **para rentar y vivir en México** (arrendamiento de
casa habitación de largo plazo, con foco inicial en CDMX). El usuario busca vivienda por **zona**
(estado → municipio/alcaldía) en un **buscador** o en un **mapa**, ve las viviendas que **publican los
propios arrendadores** con un **resumen honesto de precios**, consulta los **requisitos legales** que
aplican en esa entidad —cada uno con su **cita textual verificada**— y puede **generar y firmar
electrónicamente** un contrato de arrendamiento cuyo texto se arma de forma determinista a partir de
plantillas + requisitos citados.

Este documento explica **qué es, de dónde viene, cómo está construido, cómo correrlo y desplegarlo,
cómo se verifica y hacia dónde va**.

---

## Índice

1. [Estado actual en una tabla](#1-estado-actual-en-una-tabla)
2. [De dónde venimos y a dónde vamos (el upgrade)](#2-de-dónde-venimos-y-a-dónde-vamos-el-upgrade)
3. [Principios de diseño ("regla cero")](#3-principios-de-diseño-regla-cero)
4. [Arquitectura](#4-arquitectura)
5. [Datos: qué hay y de dónde salió](#5-datos-qué-hay-y-de-dónde-salió)
6. [Funcionalidades por fase](#6-funcionalidades-por-fase)
7. [API (`/mx/*`)](#7-api-mx)
8. [Frontend (rutas y componentes)](#8-frontend-rutas-y-componentes)
9. [Persistencia: `JsonStore` y `SqlStore`](#9-persistencia-jsonstore-y-sqlstore)
10. [Seguridad y robustez](#10-seguridad-y-robustez)
11. [Cómo correrlo localmente](#11-cómo-correrlo-localmente)
12. [Despliegue (Render + Cloudflare Workers)](#12-despliegue-render--cloudflare-workers)
13. [Cómo se verifica (pruebas)](#13-cómo-se-verifica-pruebas)
14. [Costo: por qué el runtime cuesta $0 en LLM](#14-costo-por-qué-el-runtime-cuesta-0-en-llm)
15. [Agentes de desarrollo (`.kiro/agents`)](#15-agentes-de-desarrollo-kiroagents)
16. [Relación con el proyecto US (Módulo A congelado)](#16-relación-con-el-proyecto-us-módulo-a-congelado)
17. [Estructura del repositorio](#17-estructura-del-repositorio)
18. [Hacia dónde va el proyecto (roadmap)](#18-hacia-dónde-va-el-proyecto-roadmap)
19. [Limitaciones honestas](#19-limitaciones-honestas)
20. [Historial y traspaso](#20-historial-y-traspaso)

---

## 1. Estado actual en una tabla

Medido sobre `main` (commit `dd681f4`, PR #2 `feature/renta-mx-fases`), 2026-10-06:

| | |
|---|---|
| Requisitos legales con cita literal verificada | **229/229** (`python -m mx.verify`, 268 avisos no bloqueantes) |
| Documentos fuente íntegros (sha256 + text_sha256) | **85/85** |
| Entidades con código civil estatal verificado | **11 de 32**: CDMX, Jalisco, Nuevo León, Estado de México, Querétaro, Puebla, Yucatán, Quintana Roo, **Guanajuato, Durango, Chihuahua** (las 21 restantes: solo marco federal, marcadas `solo_federal`) |
| Zonas | 32 estados · **2,478** municipios/alcaldías (catálogo INEGI + Censo 2020) |
| Zonas en el mapa | **2,469** con coordenada oficial (ITER 2020: cabecera municipal o localidad más poblada); 9 se listan aparte como "Sin coordenada oficial" |
| Inventario de viviendas | arranca **vacío**; solo existe lo que publican los usuarios |
| Precios | resumen min/mediana/máx **solo con ≥ 3 anuncios reales** de la zona; nunca scraping ni cifras inventadas |
| Contrato y firma | contrato determinista + anexo de fundamento legal; **firma electrónica simple** (trazo o nombre escrito) con enlace por rol y constancia descargable |
| Persistencia | `JsonStore` efímero por defecto · `SqlStore` (SQLite/PostgreSQL) con `DATABASE_URL` |
| Pruebas backend | **429 passed**, offline |
| Pruebas frontend | **22 passed** (5 archivos) · `bun run build` OK (preset Cloudflare) |
| LLM / red en runtime | **ninguno** (`mx/*.py` y `api/mx.py` no importan SDKs de modelos ni clientes HTTP) |

---

## 2. De dónde venimos y a dónde vamos (el upgrade)

**Proyecto original (EE. UU.):** _Rental Housing Law Navigator_ respondía "¿qué reglas de vivienda
aplican en esta dirección hoy?" para California, Nueva Jersey y Massachusetts, con extracción de
reglas por IA (Claude Opus), verificación de citas literales y una API read-only. Se entregó al
7.º Global AI Hackathon (Hack-Nation × RealPage) y hoy está **congelado** (ver §16).

**Este upgrade (México):** reutiliza la **misma filosofía de rigor** (cita literal verificada, cero
datos inventados, estado as-of, nada de asesoría legal) y la **gira hacia un producto**: ya no solo
"consultar la ley", sino **encontrar vivienda, entender la ley que aplica y firmar el contrato**, por
zona de la República Mexicana.

| | Proyecto original (US) | Renta MX |
|---|---|---|
| Pregunta | ¿Qué reglas aplican en esta dirección? | ¿Dónde rento, cuánto cuesta, qué exige la ley aquí y cómo firmo el contrato? |
| Unidad de búsqueda | Dirección (500 de muestra) | Zona: estado → municipio (32 estados, 2,478 municipios), con buscador y mapa |
| Fuente legal | Leyes estatales/municipales de EE. UU. | Código Civil Federal + **11 códigos civiles estatales** + marco fiscal, firma electrónica y datos personales |
| Extracción | LLM (Opus) con verificación de cita | **Descarga oficial + `pdftotext`/HTML + verificación de cita** (sin tokens de LLM) |
| Inventario | — | Viviendas publicadas por usuarios (arranca **vacío**, sin anuncios inventados) |
| Precio | — | Resumen de anuncios publicados (≥ 3), separado del % de viviendas alquiladas (INEGI) |
| Acción del usuario | Leer la respuesta | Publicar vivienda · generar contrato · **firma electrónica simple** |
| Runtime | Read-only, sin LLM | Read-only + escrituras (anuncios/contratos/firmas), **sin LLM** |

## 3. Principios de diseño ("regla cero")

Reglas no negociables (fuente: [`docs/MX_SPEC.md`](docs/MX_SPEC.md)):

1. **Cero datos inventados.** Cada cifra, coordenada, requisito, artículo o monto proviene de una
   **fuente oficial descargada** registrada en `corpus_mx/manifest_*.json` con `url`,
   `retrieved_at`, `sha256`, `text_sha256` y `publisher`.
2. **Cita literal verificable.** Cada requisito lleva un `quote` que `python -m mx.verify` confirma
   en el texto descargado (cascada exacto → normalizado → normalizado-MX). Si no aparece, **no se
   exporta** — y el despliegue falla.
3. **No hay anuncios inventados ni scraping.** El inventario empieza vacío; la UI muestra un **estado
   vacío honesto**, nunca tarjetas de ejemplo. Los precios salen **solo** de anuncios publicados.
4. **Ley ≠ práctica de mercado ≠ dato estadístico.** Tres tratamientos visuales distintos; la
   práctica de mercado se marca "No es ley" y se oculta por defecto.
5. **Sin fuente estatal verificada → se dice.** Las entidades sin código civil descargado se marcan
   `solo_federal` y lo declaran ("todavía no verificado"), nunca rellenan.
6. **Sin coordenada oficial → no se pinta.** Un municipio sin `coord.source` no aparece en el mapa; se
   lista aparte.
7. **Firma con alcance honesto.** Es firma electrónica **simple**; la UI nunca dice "avanzada",
   "certificada", "NOM-151", "e.firma" ni "fecha cierta", salvo para negarlo.
8. **No es asesoría legal.** Disclaimer visible siempre.

## 4. Arquitectura

```
Fuentes oficiales (DOF, Cámara de Diputados, congresos/consejerías estatales, INEGI)
        │  descarga + sha256 + text_sha256   (sin LLM)
        ▼
corpus_mx/  ── manifest_*.json ──► mx.verify (cascada de cita literal, offline; corre en el build)
        │                                   │ 229/229 citas, 85/85 docs
        ▼                                   ▼
data/mx/requirements/*.yaml      data/mx/zones.json (Censo 2020 + catálogo INEGI + ITER 2020 coords)
        │                                   │
        └───────────────┬───────────────────┘
                        ▼
            mx/  (paquete Python, lógica determinista, SIN LLM, SIN red)
            ├─ sources.py      carga y valida manifiestos, recomputa hashes
            ├─ verify.py       verificación de citas (cascada)
            ├─ requirements.py vista de requisitos por jurisdicción
            ├─ zones.py        índice de estados/municipios + stats y coordenadas con fuente
            ├─ prices.py       resumen de precios de anuncios publicados (≥ 3)
            ├─ contracts.py    generación DETERMINISTA de contratos (plantillas)
            ├─ signatures.py   firma electrónica simple (SHA-256, cadena de evidencia)
            ├─ store.py        JsonStore (efímero) o SqlStore (SQLite/Postgres) vía DATABASE_URL
            ├─ ratelimit.py    token-bucket por IP, memoria acotada
            └─ models.py       modelos pydantic (validación estricta de entradas)
                        │
                        ▼
            api/mx.py  (FastAPI APIRouter, prefijo /mx, read-only + POST de anuncios/contratos/firmas)
                        │  montado por api/main.py (rutas US legacy intactas, tolerantes a out/ ausente)
                        ▼
            frontend/  (TanStack Start + React 19 + Tailwind v4 + Radix/shadcn + MapLibre)
            ├─ rutas MX: / /mapa /zona /requisitos /publicar /vivienda /contrato /fuentes
            └─ /us  (proyecto original, sin cambios)
```

**Clave:** el motor es genérico; agregar una jurisdicción es **solo datos + configuración** (así se
sumaron Guanajuato, Durango y Chihuahua en este ciclo, sin tocar código).

## 5. Datos: qué hay y de dónde salió

| Qué | Volumen | Fuente |
|---|---:|---|
| Requisitos legales con cita literal | **229** | Código Civil Federal, Código de Comercio, NOM-151, LFPDPPP, LISR/LIVA/CFF + códigos civiles de **11 entidades** |
| Documentos fuente | **85** | DOF, Cámara de Diputados, consejerías jurídicas y congresos estatales, INEGI |
| Estados | **32** | Catálogo oficial INEGI |
| Municipios/alcaldías | **2,478** | Catálogo INEGI + Censo de Población y Vivienda 2020 (viviendas, población, % alquiladas, con fuente por campo) |
| Coordenadas | **2,469** | ITER 2020 (LATITUD/LONGITUD de la cabecera municipal según el catálogo INEGI; para alcaldías de CDMX, la localidad más poblada) |
| Cláusulas de contrato | plantillas fijas | `data/mx/contract_clauses.yaml`, escritas a mano, **sin hechos legales embebidos** (toda cita va al anexo) |

Requisitos por archivo (`data/mx/requirements/`): `FED`, `CDMX`, `JAL`, `NL`, `MEX`, `QRO`, `PUE`,
`YUC`, `QROO`, `GTO`, `DGO`, `CHIH`. Códigos estatales nuevos de este ciclo: Guanajuato (reforma del
18 de diciembre de 2025, DL 111), Durango y Chihuahua, en `corpus_mx/estados/{GTO,DGO,CHIH}/`.

## 6. Funcionalidades por fase

Trabajo del ciclo `feature/renta-mx-fases` (fusionado en `main` con el PR #2):

| Fase | Qué se hizo | Archivos clave |
|---|---|---|
| **0 · Fundaciones** | El build de Render solo instala dependencias y corre `mx.verify`. La API US devuelve **503 limpio** si falta `out/`. CORS acepta `*.pages.dev`. `SqlStore` (SQLite/Postgres) elegido con `DATABASE_URL`; sin ella, el JSON efímero de antes. Docs de despliegue. | `render.yaml`, `api/main.py`, `mx/store.py`, `requirements.txt`, `docs/DEPLOY.md`, `docs/US_LEGACY.md` |
| **1 · Mapa** | MapLibre con tiles OSM sin API key. Solo pinta zonas con `coord.source`; el resto va a "Sin coordenada oficial". Lista accesible sincronizada con el mapa y buscador **insensible a acentos**. El popup dice qué representa la coordenada. | `components/mx/MxMap.tsx`, `routes/mapa.tsx`, `routes/index.tsx`, `routes/zona.$cveEnt.$cveMun.tsx` |
| **2(a) · Precios** | `listing_price_summary`: determinista; `count` siempre, y min/mediana/máx en MXN **solo con ≥ 3 anuncios válidos** (si no, `has_stats=false`, `reason=insufficient_sample`). Ignora registros corruptos. La UI separa tres cosas: precio de anuncios, % de viviendas alquiladas (INEGI, estadística) y requisitos legales. | `mx/prices.py`, `api/mx.py`, `routes/zona...tsx` |
| **3 · Contrato y firma** | Enlace por rol `/contrato/{id}?rol=X#t=<token>` (el token va en el *fragment* y se borra de la URL al leerlo). `SignaturePad` para **dibujar o escribir** la firma. Caja de alcance de la firma simple, panel de estado, mapeo de errores 403/409/422, CSS de impresión/PDF y descarga de la constancia. | `components/mx/SignaturePad.tsx`, `lib/mx-sign.ts`, `routes/contrato.$id.tsx`, `styles.css`, `lib/mx-i18n.ts` |
| **4 · Cobertura** | Códigos civiles nuevos verificados: **GTO, DGO, CHIH** → 11 de 32 entidades. | `corpus_mx/estados/{GTO,DGO,CHIH}/`, `corpus_mx/manifest_estados.json`, `data/mx/requirements/{GTO,DGO,CHIH}.yaml` |
| **Pruebas** | Batería adversarial de las fases nuevas, paridad JSON ↔ SQL, precios, tolerancia de la API US y pruebas de frontend (mapa, bloque de precio, firma). | `tests/test_mx_fases_adversarial.py`, `tests/test_mx_store_sql.py`, `tests/test_mx_prices.py`, `tests/test_us_tolerance.py`, `frontend/src/test/mx-*.test.tsx` |

Veredicto del agente arquitecto al cerrar el ciclo: **APROBADO**, sin bloqueantes.

## 7. API (`/mx/*`)

Read-only salvo las operaciones de escritura. **Ninguna ruta llama a un LLM ni a la red.** Todas
responden con `disclaimer`. Contrato completo: [`docs/API.md`](docs/API.md).

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/mx/health` | estado, conteos, tipo de store (`efimero` / `sqlite` / `postgres`) y `store_notice` honesto |
| GET | `/mx/states` | 32 estados con cobertura legal, nº de anuncios y `price_summary` |
| GET | `/mx/zones?cve_ent=&q=` | municipios (autocompletado sin acentos) con stats, coordenada con fuente, nº de anuncios y `price_summary` |
| GET | `/mx/zones/{cve_ent}/{cve_mun}` | zona: stats INEGI con fuente + anuncios + `price_summary` + resumen de requisitos |
| GET | `/mx/requirements?cve_ent=&lang=` | requisitos por categoría (federal + estatal) con cita, quote, url |
| GET | `/mx/listings` · `/mx/listings/{id}` | anuncios publicados por usuarios |
| POST | `/mx/listings` | publica un anuncio (validación pydantic; sin exponer calle ni correo) |
| GET | `/mx/contract-form?cve_ent=` | qué pide el contrato en esa entidad (cláusulas, campos exigidos, roles) |
| POST | `/mx/contracts` | genera el contrato (determinista) + anexo "Fundamento legal" + enlaces por rol |
| GET | `/mx/contracts/{id}` | contrato + estado de firmas |
| POST | `/mx/contracts/{id}/sign` | firma de una parte (token por rol, consentimiento, hash; 403/409/422 claros) |
| GET | `/mx/contracts/{id}/evidence` | constancia de firma (JSON) |
| GET | `/mx/sources` | manifiesto de fuentes (transparencia) |
| GET | `/mx/privacy` | aviso de privacidad |

Idioma `lang=es|en`, por defecto `es`. `price_summary` siempre trae `count`, `currency` (`MXN`),
`basis` (`viviendas_publicadas`), `min_count_for_stats` (3) y `as_of`.

## 8. Frontend (rutas y componentes)

Experiencia en español por defecto (inglés opcional). Guías: [`docs/MX_UX.md`](docs/MX_UX.md)
(flujos y copy) y [`docs/MX_ARCHITECTURE.md`](docs/MX_ARCHITECTURE.md). El `frontend/` del repo es la
**fuente de verdad**; Lovable queda solo como demo (no quitar `@lovable.dev/vite-tanstack-config`: el
build depende de él).

| Ruta | Qué muestra |
|---|---|
| `/` | Landing: buscador estado → municipio, grid de los 32 estados con badge de cobertura, acceso al mapa, "cómo funciona", CTA publicar |
| `/mapa` | **Mapa** (MapLibre + OSM) con las zonas que tienen coordenada oficial, lista accesible sincronizada, buscador sin acentos y sección "Sin coordenada oficial" |
| `/zona/$cveEnt/$cveMun` | Cifras INEGI con fuente + mapa + **bloque de precio** (solo con ≥ 3 anuncios) + viviendas (o **estado vacío honesto**) + resumen de requisitos |
| `/requisitos/$cveEnt` | Checklist legal por categoría; cada punto con **"Ver fundamento"** (cita literal + documento + fecha) |
| `/publicar` | Formulario del arrendador (4 secciones, validación, no expone domicilio ni correo) |
| `/vivienda/$id` | Detalle + "Antes de rentar en {estado}" + formulario **Iniciar contrato** |
| `/contrato/$id` | Cláusulas numeradas, anexo de fundamento, panel de firmas, **SignaturePad** (dibujar o escribir), caja de alcance, impresión/PDF y descarga de constancia; enlace por rol `?rol=X#t=<token>` |
| `/fuentes` | Transparencia: tabla de documentos con hash SHA-256 y fecha de consulta |
| `/us` | Proyecto original (EE. UU.), intacto |

**Componentes compartidos:** `MxShared.tsx` (`FundamentoSheet`, `CoverageBadge`/`CoverageNotice`,
`EmptyState`, `KindBadge`, `HashChip`, `StatCard`, `MxLoading`/`MxError`), `MxMap.tsx` y
`SignaturePad.tsx`. Copy centralizado y tipado en `lib/mx-i18n.ts` (mismas claves ES/EN garantizadas
por el compilador) y lógica de firma en `lib/mx-sign.ts`. `API_BASE` configurable con `VITE_API_BASE`.

## 9. Persistencia: `JsonStore` y `SqlStore`

`mx/store.py` ofrece dos backends con **la misma interfaz** (`get`/`list`/`count`/`put`, límites,
filtrado de registros corruptos, ids inválidos, thread-safety). `make_store()` elige según
`DATABASE_URL`:

| `DATABASE_URL` | Backend | `store` en `/mx/health` | ¿Persiste? |
|---|---|---|---|
| *(sin definir)* | `JsonStore`: un archivo por registro en `MX_STORE_DIR` (`out/mx_store`), escritura atómica | `efimero` | No en Render free (disco efímero) |
| `sqlite:///ruta/abs.db` | `SqlStore` sobre `sqlite3` (stdlib) | `sqlite` | Mientras sobreviva el disco |
| `postgres://…` / `postgresql://…` | `SqlStore` sobre `psycopg[binary]==3.3.6` (import diferido) | `postgres` | **Sí** (Postgres administrado) |

Límites: 1,000 anuncios y 500 contratos. El aviso de la UI cambia solo: con store efímero pide
"descarga tu constancia"; con base persistente dice que los datos se conservan. Un lock por proceso
serializa escrituras: **un solo worker de uvicorn** (con varios, usar el backend SQL y mover límites
a la base).

## 10. Seguridad y robustez

**Ciclo 1 — los 9 arreglos de The Tester** (55 pruebas en `tests/test_mx_adversarial.py`):

| # | Problema | Arreglo | Archivo |
|---|---|---|---|
| 1 | Un `.txt` sin `text_sha256` podía respaldar una cita **inventada** | Se exige `text_sha256` cuando el `.txt` es un archivo aparte | `mx/sources.py` + manifiestos |
| 2 | `U+00AD` (soft hyphen) burlaba el mínimo de longitud de la cita | La longitud se mide tras remover soft hyphens | `mx/verify.py` |
| 3 | Las plantillas aceptaban hechos legales **en palabras** ("diez por ciento") | Guard que rechaza números/porcentajes/artículos en letra | `mx/contracts.py` |
| 4 | Cifras de zona sin fuente se servían igual | `Municipio.public()` ya no esparce campos sin fuente | `mx/zones.py` |
| 5 | Coordenadas sin bloque de fuente se servían | Se exige `coord` con `source` conocido | `mx/zones.py` |
| 6 | Saltos de línea Unicode inyectaban cláusulas falsas | Se rechazan `U+0085`, `U+2028`, `U+2029` y controles ASCII | `mx/models.py` |
| 7 | Contrato con entidad desconocida daba 404 | Ahora **422**, como `/mx/listings` | `api/mx.py` |
| 8 | Un registro JSON malformado tiraba 500 | El store descarta no-dicts; las rutas filtran corruptos | `mx/store.py`, `api/mx.py` |
| 9 | El `user_agent` crudo se exponía | Solo su hash (`user_agent_sha256`) | `api/mx.py` |

**Ciclo 2 — fases nuevas** (`tests/test_mx_fases_adversarial.py`, `test_mx_store_sql.py`,
`test_mx_prices.py`, `test_us_tolerance.py`): paridad de comportamiento JSON ↔ SQL, precios con
muestras pequeñas o corruptas (NaN, negativos, texto), token de firma fuera de la query string y
borrado del fragment, y API US tolerante a `out/` ausente.

Además: la IP del firmante se guarda **hasheada** con `MX_IP_SALT` (nunca en claro), el rate limiter
(`mx/ratelimit.py`) acota su memoria en cada llamada (defensa ante `X-Forwarded-For` falsificado) y
uvicorn corre con `--proxy-headers` para ver la IP real.

## 11. Cómo correrlo localmente

Requisitos: Python 3.11+ y (para el frontend) Bun o Node.js.

**Backend** (sin API keys; no usa LLM):

```bash
pip install -r requirements.txt
python -m mx.verify                  # 229/229 citas, 85/85 documentos
uvicorn api.main:app --reload        # API en http://localhost:8000 · docs en /docs
# Persistencia opcional:  DATABASE_URL=sqlite:///C:/ruta/renta.db   (o postgres://...)
```

**Frontend** (otra terminal, apuntando al backend local):

```bash
cd frontend
# Windows PowerShell:  $env:VITE_API_BASE = "http://localhost:8000"
# bash:                export VITE_API_BASE="http://localhost:8000"
bun install && bun run dev           # (o npm install && npm run dev)
```

Sin `VITE_API_BASE`, el frontend apunta a la API de producción en Render, no a tus cambios locales.

Recorrido rápido: `/` → `/mapa` (elige una zona) → `/zona/09/...` (cifras, precio, viviendas) →
`/requisitos/09` ("Ver fundamento") → `/publicar` → desde la vivienda, **Iniciar contrato** → comparte
los enlaces por rol → **firma** (dibujada o escrita) → descarga la constancia → `/fuentes`.

## 12. Despliegue (Render + Cloudflare Workers)

Detalle completo en [`docs/DEPLOY.md`](docs/DEPLOY.md).

**Backend — Render** (`render.yaml`):
- Build: `pip install -r requirements.txt && python -m mx.verify` (una cita rota **tumba el deploy**).
  Ya no regenera los artefactos US.
- Start: `uvicorn api.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'`.
  Health check: `/health`.
- Variables: `PYTHON_VERSION=3.12.10`, `ALLOWED_ORIGINS` (orígenes CORS exactos extra), `MX_IP_SALT`
  (generada por Render; mantenerla estable), `DATABASE_URL` (opcional, ver §9).
- Plan free: $0, duerme tras ~15 min (la primera petición tarda ~1 min) y su disco es efímero. Para
  producción: plan starter (~$7/mes) + PostgreSQL administrado (~$7/mes) conectado a `DATABASE_URL`.
- Cambios solo de `frontend/**`, `docs/**` o `*.md` no redespliegan la API.

**Frontend — Cloudflare Workers** (preset `cloudflare-module`, no Pages):
- Root `frontend`, build `bun install && bun run build`, deploy `npx wrangler deploy`.
- Variable de build: `VITE_API_BASE=https://<servicio>.onrender.com`.
- Agregar la URL exacta `https://<worker>.<cuenta>.workers.dev` a `ALLOWED_ORIGINS` en Render (el
  regex CORS cubre Lovable, `*.pages.dev` y localhost, no `workers.dev`).

**Por qué no Fly.io:** en 2026 ya no tiene plan gratuito; Render + Cloudflare es el combo de costo $0.

## 13. Cómo se verifica (pruebas)

Todo corre **offline**:

```bash
python -m pytest -q                 # 429 passed (backend MX + US legacy)
python -m mx.verify                 # ok=True · 229/229 citas · 85/85 documentos (268 avisos no bloqueantes)
cd frontend && bun run build        # build OK (preset Cloudflare)
cd frontend && bun run test         # 22 passed (5 archivos: mapa, precio, firma, ...)
```

Verificación adicional: un `grep` de SDKs de modelos y clientes HTTP en `mx/*.py` y `api/mx.py` no
encuentra nada (el runtime no puede llamar a un LLM ni a la red).

## 14. Costo: por qué el runtime cuesta $0 en LLM

Detalle en [`docs/MX_COST_REVIEW.md`](docs/MX_COST_REVIEW.md). `mx/*.py` y `api/mx.py` **no importan**
ningún SDK de modelo ni cliente de red. La generación de contratos es determinista; los requisitos y
las citas se precomputaron y se verifican offline. La extracción legal mexicana se hizo con
**descarga + `pdftotext` + verificación de cita**, sin gasto de tokens. Costos recurrentes: hosting
(Render free + Cloudflare Workers free = $0 para la demo; ~$14/mes con starter + Postgres) y, a
futuro, tiles de mapa de un proveedor con términos de producción.

El único gasto en LLM del repositorio es histórico y del proyecto US (≈ $10 en total; snapshot
oficial del Módulo A: $3.87). Ver [`docs/PIPELINE.md`](docs/PIPELINE.md#cost).

## 15. Agentes de desarrollo (`.kiro/agents`)

El pivote se construyó con un equipo de agentes especializados, versionados en `.kiro/agents/`:

| Agente | Rol | Escribe código |
|---|---|---|
| `the-planner` | Convierte metas en fases con criterios de aceptación (nuevo en este ciclo) | No |
| `the-architect` | Critica el diseño; cierra con `VEREDICTO: APROBADO` o `NEEDS_FIXES` | No |
| `the-implementor` | Implementa y verifica con pruebas | Sí |
| `the-tester` | Escribe pruebas adversariales; no arregla código de producción | Solo pruebas |
| `the-designer` | Frontend UI (React/Tailwind/shadcn) | Sí |
| `the-ux` | Copy y flujos (`mx-i18n.ts`) | Copy |
| `the-budgeter` | Costos (tokens, hosting, bundle) | Docs/optimizaciones |

Pipeline que funcionó: `planner → implementor/designer (en paralelo si tocan archivos distintos) →
tester → implementor (correcciones) → ux → budgeter → architect`, con dos bucles de corrección
(tester y architect con `NEEDS_FIXES`). Los documentos `docs/MX_SPEC.md`, `MX_ARCHITECTURE.md`,
`MX_UX.md` y `MX_COST_REVIEW.md` son el contrato entre ellos. Uso: `kiro-cli chat --agent the-implementor`.

## 16. Relación con el proyecto US (Módulo A congelado)

El proyecto original vive en el mismo repo y **está congelado** ([`docs/US_LEGACY.md`](docs/US_LEGACY.md)):

| Pieza | Ruta | Estado |
|---|---|---|
| Módulo A — extracción de reglas (Claude Opus 5.5, cita verificada) | `extractor/` | congelado; snapshot inmutable `snapshots/a-0.4.0/` (prompt, salida cruda del modelo, ids, costo $3.87) |
| Módulos B/C — resolución de direcciones y seguimiento de cambios | `resolver/` | congelado |
| Rutas US | `/lookup`, `/explain`, `/timeline`, `/changes`, `/rules`, `/conflicts` en `api/main.py` | montadas; devuelven **503 limpio** si falta `out/` |
| Datos y audio US | `data/*.json|yaml`, `data/audio/` | versionados, sin cambios |

Para servir las rutas US localmente: `python -m extractor.cli reproduce && python -m resolver.cli lookup
&& python -m resolver.cli changes` (sin API key; reproduce `rules.json` byte a byte desde el snapshot).
Lo que Renta MX heredó del Módulo A: la **cascada de cita literal**, la idea de **manifiesto con
sha256/text_sha256**, el **estado as-of** y la regla de **nunca rellenar con conocimiento externo**.
La diferencia de fondo: en MX la extracción no usa LLM.

## 17. Estructura del repositorio

```
mx/                          # paquete Python determinista (SIN LLM, SIN red): sources, verify, requirements,
                             #   zones, prices, contracts, signatures, store (Json/Sql), ratelimit, models
api/mx.py                    # router FastAPI /mx/* (montado por api/main.py)
corpus_mx/                   # textos oficiales descargados + manifest_*.json (url, sha256, text_sha256)
  cdmx/  estados/{JAL,NL,MEX,QRO,PUE,YUC,QROO,GTO,DGO,CHIH}/
data/mx/
  requirements/*.yaml        # 229 requisitos con cita literal (FED + 11 entidades)
  zones.json                 # 32 estados · 2,478 municipios con stats, coordenadas y fuente por campo
  contract_clauses.yaml      # plantillas de cláusula (sin hechos legales)
scripts/
  build_mx_zones.py          # arma zones.json desde los archivos INEGI
  fetch_mx_inegi.py          # descarga de catálogos/censo INEGI
frontend/src/
  routes/{index,mapa,zona.$...,requisitos.$cveEnt,publicar,vivienda.$id,contrato.$id,fuentes,us}.tsx
  components/mx/{MxShared,MxMap,SignaturePad}.tsx
  lib/{mx-i18n,mx-sign,api}.ts
  test/mx-*.test.tsx         # mapa, bloque de precio, firma
docs/
  MX_SPEC.md  MX_ARCHITECTURE.md  MX_UX.md  MX_COST_REVIEW.md   # contrato entre agentes
  DEPLOY.md  HANDOFF.md  US_LEGACY.md  API.md  PIPELINE.md  METHOD.md
tests/
  test_mx_verify.py  test_mx_api.py  test_mx_contracts.py  test_mx_adversarial.py
  test_mx_fases_adversarial.py  test_mx_store_sql.py  test_mx_prices.py  test_us_tolerance.py  mx_support.py
render.yaml                  # blueprint de Render (build = pip install + mx.verify)
.kiro/agents/*.json          # los 7 agentes de desarrollo
extractor/ resolver/ snapshots/   # proyecto US congelado (ver §16)
```

## 18. Hacia dónde va el proyecto (roadmap)

**Hecho en este ciclo:** mapa con coordenadas oficiales, resumen de precios honesto, firma con trazo y
enlaces por rol, `SqlStore` listo para Postgres, 3 entidades nuevas (11/32), despliegue Render +
Cloudflare documentado.

**Siguiente (corto plazo)**
- **Deploy real** (lo hace el dueño): conectar Render con `render.yaml`, publicar el Worker en
  Cloudflare con `VITE_API_BASE`, y agregar el origen `workers.dev` a `ALLOWED_ORIGINS`.
- **Postgres en producción**: plan starter + base administrada en `DATABASE_URL`.
- **Cubrir las 21 entidades restantes** con el mismo patrón (descargar → `sha256`/`text_sha256` →
  YAML con `quote` → `mx.verify`). El motor no cambia.
- **Tiles de mapa de producción**: cambiar `tile.openstreetmap.org` por un proveedor con términos
  claros (ver `docs/MX_COST_REVIEW.md`).

**Mediano plazo**
- **Precio oficial (Fase 2b):** solo si existe una fuente oficial descargable (SHF/INEGI), registrada en
  manifiesto y verificada. Nunca scraping.
- **Identidad y titularidad:** OTP por correo y verificación de titularidad del inmueble (hoy se
  declara ausente).
- **Firma más robusta (opcional):** camino a firma avanzada (e.firma SAT) y constancia NOM-151 de un
  PSC acreditado; hoy se dice honestamente que la demo no las emite.
- **Varios workers:** mover límites y rate limit a la base de datos.
- **Notificaciones** del flujo de firma (hoy se comparte por enlace).

**Largo plazo:** panel para arrendadores, más datos de zona con fuente por campo y audio de
requisitos ES/EN cacheado por hash (único rubro con costo marginal).

**Qué NO va a cambiar:** la regla cero, el runtime sin LLM, la cita literal verificable y el
disclaimer.

## 19. Limitaciones honestas

- **11 de 32 entidades** con código civil estatal verificado; las 21 restantes muestran solo el marco
  federal y lo dicen.
- **Inventario vacío** hasta que alguien publique (intencional). Sin anuncios suficientes no hay
  resumen de precios (mínimo 3).
- **Firma electrónica simple**, no avanzada; sin verificación de identidad ni de titularidad.
- **Store efímero** por defecto en Render free (los datos se borran al reiniciar; la UI avisa y deja
  descargar la constancia). Persistencia real requiere `DATABASE_URL` con Postgres.
- **Un solo worker**: el lock del store y el rate limit viven en memoria por proceso.
- **Tiles OSM** (`tile.openstreetmap.org`) solo para demo; producción necesita otro proveedor.
- **9 municipios** sin coordenada oficial no aparecen en el mapa (se listan aparte).
- El **lint del repo** reporta avisos de fin de línea (CRLF) preexistentes del checkout en Windows; no
  afectan al build ni a las pruebas.

## 20. Historial y traspaso

| Fecha | Rama / PR | Qué |
|---|---|---|
| 2026-10-01 → 10-04 | `module-a`, `module-b`, `audio`, `ux-extras`, `docs` | Proyecto US: extracción, lookup, cambios T1–T5, API, audio, docs; entrega al hackathon (tag `submission-safe`) |
| 2026-10-05 | `feature/renta-mx-upgrade` | Pivote a Renta MX: corpus MX, `mx/`, `/mx/*`, frontend en español, 8 entidades, 9 arreglos adversariales |
| 2026-10-06 | `feature/renta-mx-fases` → PR #2 a `main` | Mapa, precios, firma, `SqlStore`, GTO/DGO/CHIH (11 entidades), despliegue Render + Cloudflare |

Para continuar el trabajo (otra persona u otra IA): empezar por [`docs/HANDOFF.md`](docs/HANDOFF.md)
— qué se hizo, dónde quedó, cómo usar los agentes y qué verificar antes de cada entrega.

---

*Construido sobre el 7.º Global AI Hackathon · Hack-Nation × RealPage. Investigación e información
únicamente. **No es asesoría legal.***
