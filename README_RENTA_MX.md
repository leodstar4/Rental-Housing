# Renta MX — Plataforma de arrendamiento con requisitos legales a la vista

> **Rama:** `feature/mx-renta-zonas` · **Upgrade sobre:** _Rental Housing Law Navigator_ (proyecto
> original EE. UU., ver [`README.md`](README.md)).
>
> ⚖️ **No es asesoría legal.** Prototipo informativo. Cada afirmación legal enlaza a su fuente
> oficial con cita literal; verifíquela y consulte a un profesional antes de firmar o actuar.

Renta MX es una plataforma tipo _marketplace_ **para rentar y vivir en México** (arrendamiento de
casa habitación de largo plazo). El usuario busca por **zona** (estado → municipio/alcaldía), ve las
viviendas que **publican los propios arrendadores**, consulta los **requisitos legales** que aplican
en esa entidad —cada uno con su **cita textual verificada**— y puede **generar y firmar
electrónicamente** un contrato de arrendamiento cuyo texto se arma de forma determinista a partir de
plantillas + requisitos citados.

Este documento explica **qué cambió respecto al proyecto original, cómo está construido, cómo
correrlo y hacia dónde va**.

---

## Índice

1. [De dónde venimos y a dónde vamos (el upgrade)](#1-de-dónde-venimos-y-a-dónde-vamos-el-upgrade)
2. [Principios de diseño ("regla cero")](#2-principios-de-diseño-regla-cero)
3. [Arquitectura](#3-arquitectura)
4. [Datos: qué hay y de dónde salió](#4-datos-qué-hay-y-de-dónde-salió)
5. [API (`/mx/*`)](#5-api-mx)
6. [Frontend (rutas y componentes)](#6-frontend-rutas-y-componentes)
7. [Seguridad y robustez: los 9 arreglos de este ciclo](#7-seguridad-y-robustez-los-9-arreglos-de-este-ciclo)
8. [Cómo correrlo localmente](#8-cómo-correrlo-localmente)
9. [Cómo se verifica (pruebas)](#9-cómo-se-verifica-pruebas)
10. [Costo: por qué el runtime cuesta $0 en LLM](#10-costo-por-qué-el-runtime-cuesta-0-en-llm)
11. [Agentes de desarrollo (`.kiro/agents`)](#11-agentes-de-desarrollo-kiroagents)
12. [Estructura del repositorio (lo nuevo)](#12-estructura-del-repositorio-lo-nuevo)
13. [Hacia dónde va el proyecto (roadmap)](#13-hacia-dónde-va-el-proyecto-roadmap)
14. [Limitaciones honestas](#14-limitaciones-honestas)

---

## 1. De dónde venimos y a dónde vamos (el upgrade)

**Proyecto original (EE. UU.):** _Rental Housing Law Navigator_ respondía "¿qué reglas de vivienda
aplican en esta dirección hoy?" para California, Nueva Jersey y Massachusetts, con extracción de
reglas por IA (Claude Opus), verificación de citas literales y una API read-only.

**Este upgrade (México):** reutiliza la **misma filosofía de rigor** (cita literal verificada, cero
datos inventados, estado as-of, nada de asesoría legal) y la **gira hacia un producto**: ya no solo
"consultar la ley", sino **encontrar vivienda, entender la ley que aplica y firmar el contrato**, por
zona de la República Mexicana.

| | Proyecto original (US) | Renta MX (este upgrade) |
|---|---|---|
| Pregunta | ¿Qué reglas aplican en esta dirección? | ¿Dónde rento, qué exige la ley aquí y cómo firmo el contrato? |
| Unidad de búsqueda | Dirección (500 de muestra) | Zona: estado → municipio (32 estados, 2.478 municipios) |
| Fuente legal | Leyes estatales/municipales de EE. UU. | Código Civil Federal + 8 códigos civiles estatales + marco fiscal/firma electrónica/datos personales |
| Extracción | LLM (Opus) con verificación de cita | **Descarga oficial + `pdftotext`/HTML + verificación de cita** (sin tokens de LLM) |
| Inventario | — | Viviendas publicadas por usuarios (inventario arranca **vacío**, sin anuncios inventados) |
| Acción del usuario | Leer la respuesta | Publicar vivienda · generar contrato · **firma electrónica simple** |
| Runtime | Read-only, sin LLM | Read-only + escrituras (anuncios/contratos/firmas), **sin LLM** |

El proyecto original sigue vivo y accesible en la ruta **`/us`** del frontend; nada de él se rompió.

## 2. Principios de diseño ("regla cero")

Todo el pivote obedece reglas no negociables (fuente: [`docs/MX_SPEC.md`](docs/MX_SPEC.md)):

1. **Cero datos inventados.** Cada cifra, requisito, artículo o monto proviene de una **fuente
   oficial descargada** y registrada en `corpus_mx/manifest_*.json` con `url`, `retrieved_at`,
   `sha256` y `publisher`.
2. **Cita literal verificable.** Cada requisito lleva un `quote` que un script
   (`python -m mx.verify`) confirma que existe en el texto descargado (cascada exacto → normalizado →
   normalizado-MX). Si no aparece, **no se exporta**.
3. **No hay anuncios inventados.** El inventario empieza vacío. Las viviendas solo existen si un
   arrendador las publica. **No se hace scraping** de portales. La UI muestra un **estado vacío
   honesto**, nunca tarjetas de ejemplo.
4. **Ley ≠ práctica de mercado ≠ dato estadístico.** Tres tratamientos visuales distintos; la
   práctica de mercado se marca "No es ley" y se oculta por defecto.
5. **Sin fuente estatal verificada → se dice.** Las entidades sin código civil descargado muestran
   solo el marco federal y lo declaran ("todavía no verificado"), nunca rellenan.
6. **No es asesoría legal.** Disclaimer visible siempre; la firma explica su alcance real (firma
   electrónica **simple**, no e.firma del SAT ni constancia NOM-151).

## 3. Arquitectura

```
Fuentes oficiales (DOF, Cámara de Diputados, congresos/consejerías estatales, INEGI)
        │  descarga + sha256 + text_sha256   (sin LLM)
        ▼
corpus_mx/  ── manifest_*.json ──► mx.verify (cascada de cita literal, offline)
        │                                   │ 195/195 citas, 82/82 docs
        ▼                                   ▼
data/mx/requirements/*.yaml      data/mx/zones.json (Censo 2020 + catálogo INEGI)
        │                                   │
        └───────────────┬───────────────────┘
                        ▼
            mx/  (paquete Python, lógica determinista, SIN LLM, SIN red)
            ├─ sources.py      carga y valida manifiestos, recomputa hashes
            ├─ verify.py       verificación de citas (cascada)
            ├─ requirements.py vista de requisitos por jurisdicción
            ├─ zones.py        índice de estados/municipios + stats con fuente
            ├─ contracts.py    generación DETERMINISTA de contratos (plantillas)
            ├─ signatures.py   firma electrónica simple (SHA-256, cadena de evidencia)
            ├─ store.py        store de archivos JSON (efímero en Render free)
            ├─ ratelimit.py    token-bucket por IP, memoria acotada
            └─ models.py       modelos pydantic (validación estricta de entradas)
                        │
                        ▼
            api/mx.py  (FastAPI APIRouter, prefijo /mx, read-only + POST de anuncios/contratos/firmas)
                        │  montado por api/main.py (las rutas US siguen intactas)
                        ▼
            frontend/  (TanStack Start + React 19 + Tailwind v4 + Radix/shadcn)
            ├─ rutas MX: / /zona /requisitos /publicar /vivienda /contrato /fuentes
            └─ /us  (proyecto original, sin cambios)
```

**Clave:** el motor es genérico; agregar una jurisdicción es **solo datos + configuración**, nunca
tocar el código.

## 4. Datos: qué hay y de dónde salió

Verificado con `python -m mx.verify` → **ok=True, 195/195 citas, 82/82 documentos íntegros**.

| Qué | Volumen | Fuente |
|---|---:|---|
| Requisitos legales con cita literal | **195** | Código Civil Federal, Código de Comercio, NOM-151, LFPDPPP, LISR/LIVA/CFF + códigos civiles de **8 entidades** (CDMX, Jalisco, Nuevo León, Edomex, Querétaro, Puebla, Yucatán, Quintana Roo) |
| Documentos fuente | **82** | DOF, Cámara de Diputados, consejerías jurídicas y congresos estatales, INEGI |
| Estados | **32** | Catálogo oficial INEGI |
| Municipios/alcaldías | **2.478** | Catálogo INEGI + Censo de Población y Vivienda 2020 (viviendas, población, etc., con fuente por campo) |
| Cláusulas de contrato | plantillas fijas | Escritas a mano, **sin hechos legales embebidos** (todo cita va al anexo) |

Las 24 entidades sin código civil descargado aparecen con **marco federal** y la etiqueta "sin
fuente estatal verificada".

## 5. API (`/mx/*`)

Read-only salvo las tres operaciones de escritura. **Ninguna ruta llama a un LLM ni a la red.**
Todas responden con `disclaimer`. Contrato completo: [`docs/API.md`](docs/API.md).

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/mx/health` | estado, conteos, aviso de store efímero |
| GET | `/mx/states` | 32 estados con cobertura legal y nº de anuncios |
| GET | `/mx/zones?cve_ent=&q=` | municipios (autocompletado) con stats y nº de anuncios |
| GET | `/mx/zones/{cve_ent}/{cve_mun}` | zona: stats INEGI con fuente + anuncios + resumen de requisitos |
| GET | `/mx/requirements?cve_ent=&lang=` | requisitos por categoría (federal + estatal) con cita, quote, url |
| GET | `/mx/listings` · `/mx/listings/{id}` | anuncios publicados por usuarios |
| POST | `/mx/listings` | publica un anuncio (validación pydantic; sin exponer calle/correo) |
| GET | `/mx/contract-form?cve_ent=` | qué pide el contrato en esa entidad (cláusulas, campos exigidos, roles) |
| POST | `/mx/contracts` | genera el contrato (determinista) + anexo "Fundamento legal" |
| GET | `/mx/contracts/{id}` | contrato + estado de firmas |
| POST | `/mx/contracts/{id}/sign` | firma de una parte (token por rol, consentimiento, hash) |
| GET | `/mx/contracts/{id}/evidence` | constancia de firma (JSON) |
| GET | `/mx/sources` | manifiesto de fuentes (transparencia) |
| GET | `/mx/privacy` | aviso de privacidad |

Idioma `lang=es|en`, por defecto `es`.

## 6. Frontend (rutas y componentes)

Nueva experiencia en español por defecto (inglés opcional). Guías: [`docs/MX_UX.md`](docs/MX_UX.md)
(flujos y copy) y [`docs/MX_ARCHITECTURE.md`](docs/MX_ARCHITECTURE.md).

| Ruta | Qué muestra |
|---|---|
| `/` | Landing: buscador estado → municipio, grid de los 32 estados con badge de cobertura, "cómo funciona", CTA publicar |
| `/zona/$cveEnt/$cveMun` | Cifras INEGI con fuente + mapa (solo si hay coordenadas oficiales) + viviendas (o **estado vacío honesto**) + resumen de requisitos |
| `/requisitos/$cveEnt` | Checklist legal por categoría; cada punto con **"Ver fundamento"** (cita literal + documento + fecha) |
| `/publicar` | Formulario del arrendador (4 secciones, validación, no expone domicilio ni correo) |
| `/vivienda/$id` | Detalle + "Antes de rentar en {estado}" + formulario **Iniciar contrato** |
| `/contrato/$id` | Cláusulas numeradas, anexo de fundamento, panel de firmas, **firma con consentimiento** |
| `/fuentes` | Transparencia: tabla de documentos con hash SHA-256 y fecha de consulta |
| `/us` | Proyecto original (EE. UU.), intacto |

**Componentes compartidos** (`frontend/src/components/mx/MxShared.tsx`): `FundamentoSheet` (muestra
la cita verbatim, nunca reescrita), `CoverageBadge`/`CoverageNotice`, `EmptyState` honesto,
`KindBadge` (ley vs práctica), `HashChip` (SHA-256 copiable), `StatCard`, `MxLoading`/`MxError`.
Copy centralizado y tipado en `frontend/src/lib/mx-i18n.ts` (mismas claves ES/EN garantizadas por el
compilador). El `Shell` trae header Renta MX y el enlace al proyecto anterior en el pie.
`API_BASE` configurable con `VITE_API_BASE`.

## 7. Seguridad y robustez: los 9 arreglos de este ciclo

Un agente adversarial ("The Tester") escribió 55 pruebas en `tests/test_mx_adversarial.py` que
exponían fallos reales. Se arreglaron los 9 problemas raíz (todas las pruebas pasan ahora):

| # | Problema | Arreglo | Archivo |
|---|---|---|---|
| 1 | Un `.txt` sin `text_sha256` podía respaldar una cita **inventada** | Se exige `text_sha256` cuando el `.txt` es un archivo aparte; sin él el doc no respalda citas | `mx/sources.py` + manifiestos |
| 2 | `U+00AD` (soft hyphen) burlaba el mínimo de longitud de la cita | La longitud se mide tras remover soft hyphens | `mx/verify.py` |
| 3 | Las plantillas aceptaban hechos legales escritos **con palabras** ("diez por ciento") | Guard que rechaza números/porcentajes/artículos en letra | `mx/contracts.py` |
| 4 | Cifras de zona sin fuente se servían igual | `Municipio.public()` ya no esparce campos extra sin fuente | `mx/zones.py` |
| 5 | Coordenadas sin bloque de fuente se servían | Se exige `coord` con `source` conocido para mostrar lat/lon | `mx/zones.py` |
| 6 | Nombres con saltos de línea Unicode inyectaban cláusulas falsas | Se rechazan `U+0085`, `U+2028`, `U+2029` además de controles ASCII | `mx/models.py` |
| 7 | Contrato con entidad desconocida daba 404 (incoherente con anuncios) | Ahora da **422** como `/mx/listings` | `api/mx.py` |
| 8 | Un registro JSON malformado tiraba 500 en varias rutas | El store descarta no-dicts; las rutas filtran registros corruptos → 404/200 | `mx/store.py`, `api/mx.py` |
| 9 | El `user_agent` crudo se exponía en respuestas públicas | Solo se expone su hash (`user_agent_sha256`) | `api/mx.py` |

Además, el **rate limiter** (`mx/ratelimit.py`) acota su memoria en cada llamada (defensa ante
`X-Forwarded-For` falsificado).

## 8. Cómo correrlo localmente

Requisitos: Python 3.11+ y (para el frontend) Node.js o Bun.

**Backend** (sin API keys; no usa LLM):

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload        # API en http://localhost:8000 · docs en /docs
```

**Frontend** (en otra terminal, apuntando al backend local):

```bash
cd frontend
# Windows PowerShell:  $env:VITE_API_BASE = "http://localhost:8000"
# bash:                export VITE_API_BASE="http://localhost:8000"
bun install && bun run dev           # (o npm install && npm run dev)
```

Abre la URL que imprime Vite (p. ej. `http://localhost:8080`). Sin `VITE_API_BASE`, el frontend
apunta a la API de producción en Render, no a tus cambios locales.

Recorrido rápido: `/` → elige estado y municipio → `/requisitos/09` (CDMX, con "Ver fundamento") →
`/publicar` (crea una vivienda) → desde la vivienda, **Iniciar contrato** → **firmar** → `/fuentes`.

## 9. Cómo se verifica (pruebas)

Todo corre **offline**:

```bash
python -m pytest -q        # 337 pruebas (incluye 55 adversariales de The Tester)
python -m mx.verify        # 195/195 citas verificadas, 82/82 documentos íntegros
cd frontend && bun run build && bun run test   # build sin errores TS + 4 pruebas de UI
```

Evidencia de este ciclo: `337 passed`; `mx.verify ok=True 195/195 citas 82/82 docs`;
`bun run build ✓`; `bun run test 4/4`.

## 10. Costo: por qué el runtime cuesta $0 en LLM

Detalle completo en [`docs/MX_COST_REVIEW.md`](docs/MX_COST_REVIEW.md). En corto: `mx/*.py` y
`api/mx.py` **no importan** ningún SDK de modelo ni cliente de red (verificado con `grep`). La
generación de contratos es determinista; los requisitos y las citas se precomputaron y se verifican
offline. El único costo recurrente es el hosting gratuito. La extracción legal mexicana se hizo con
**descarga + `pdftotext` + verificación de cita**, evitando por completo el gasto de tokens.

## 11. Agentes de desarrollo (`.kiro/agents`)

El pivote se construyó con un equipo de agentes especializados, versionados en `.kiro/agents/`:
**the-tester** (rompe el código), **the-architect** (critica el diseño), **the-budgeter** (vigila el
costo de tokens), **the-implementor** (escribe el código), **the-designer** (frontend/UI) y
**the-ux** (experiencia de usuario). Los documentos `docs/MX_SPEC.md`, `MX_ARCHITECTURE.md`,
`MX_UX.md` y `MX_COST_REVIEW.md` son el contrato entre ellos.

## 12. Estructura del repositorio (lo nuevo)

```
mx/                          # paquete Python determinista (Módulos MX): sources, verify, requirements,
                             #   zones, contracts, signatures, store, ratelimit, models  (SIN LLM)
api/mx.py                    # router FastAPI /mx/* (montado por api/main.py)
corpus_mx/                   # textos oficiales descargados + manifest_*.json (url, sha256, text_sha256)
data/mx/
  requirements/*.yaml        # 195 requisitos con cita literal (FED + 8 estados)
  zones.json                 # 32 estados · 2.478 municipios con stats y fuente por campo
  contract_clauses.yaml      # plantillas de cláusula (sin hechos legales)
scripts/
  build_mx_zones.py          # arma zones.json desde los archivos INEGI
  fetch_mx_inegi.py          # descarga de catálogos/censo INEGI
frontend/src/
  routes/{index,zona.$...,requisitos.$cveEnt,publicar,vivienda.$id,contrato.$id,fuentes,us}.tsx
  components/mx/MxShared.tsx  # componentes compartidos MX
  lib/mx-i18n.ts             # copy ES/EN tipado + helpers (formatMXN, shortHash, orden de categorías)
docs/
  MX_SPEC.md                 # especificación compartida (regla cero, alcance, formatos)
  MX_ARCHITECTURE.md         # blueprint técnico (The Architect)
  MX_UX.md                   # flujos, estados y copy (The UX)
  MX_COST_REVIEW.md          # revisión de costos (The Budgeter)
tests/
  test_mx_verify.py  test_mx_api.py  test_mx_contracts.py  test_mx_adversarial.py  mx_support.py
.kiro/agents/*.json          # los 6 agentes de desarrollo
```

## 13. Hacia dónde va el proyecto (roadmap)

**Corto plazo**
- **Cubrir las 24 entidades restantes** con su código civil (mismo patrón: descargar → `sha256`/
  `text_sha256` → escribir requisito con `quote` → `mx.verify`). El motor no cambia.
- **Firma más robusta (opcional):** camino hacia firma electrónica avanzada (e.firma SAT) y
  constancia de conservación **NOM-151** emitida por un PSC acreditado. Hoy se declara honestamente
  que la demo **no** las emite.
- **Persistencia real:** el store de archivos es efímero en Render free; migrar anuncios/contratos a
  una base de datos para producción.

**Mediano plazo**
- **Verificación de titularidad** del inmueble y de identidad de las partes (hoy no se verifica y se
  advierte explícitamente).
- **Notificaciones** (la demo no envía correos; el flujo de firma se comparte por enlace).
- **Más datos de zona** de INEGI (precios de renta por área cuando exista fuente oficial), siempre
  con fuente por campo.
- **Audio de requisitos** en ES/EN (como el proyecto US), cacheado por hash — único rubro con costo
  marginal.

**Largo plazo**
- Escalar a **todos los municipios** con búsqueda y mapa, manteniendo la regla de cero datos sin
  fuente.
- Panel para arrendadores (gestión de anuncios y contratos).

**Qué NO va a cambiar:** la regla cero (nada sin fuente), el runtime sin LLM, la cita literal
verificable y el disclaimer. Esos son el corazón del producto.

## 14. Limitaciones honestas

- **8 de 32 entidades** tienen código civil estatal verificado; el resto muestra solo marco federal
  y lo dice.
- **Inventario vacío** hasta que un usuario publique: es intencional, no un error.
- **Firma electrónica simple**, no avanzada; sin verificación de identidad ni de titularidad.
- **Store efímero** en Render free: anuncios y contratos se borran al reiniciar el servidor
  (se avisa en la UI; se puede descargar la constancia).
- El **lint del repo** reporta ~6.200 avisos de fin de línea (CRLF) preexistentes del checkout en
  Windows; no afectan al `build` ni a las pruebas. Los archivos nuevos de este ciclo quedaron en LF.

---

*Construido sobre el 7.º Global AI Hackathon · Hack-Nation × RealPage. Investigación e información
únicamente. **No es asesoría legal.***
