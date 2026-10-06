# Renta MX — Revisión de costos (The Budgeter)

Documento de The Budgeter para el pivote **Renta MX**. Objetivo: dejar por escrito, con evidencia
verificable en el repositorio, que la plataforma **no gasta tokens de LLM en tiempo de ejecución**
y cuál fue el costo real del pivote.

> Resumen en una línea: **el runtime de Renta MX cuesta $0 en LLM.** No hay ninguna llamada a un
> modelo ni a la red en las rutas `/mx/*`; todo el valor legal se precomputó y se verifica offline.

---

## 1. Cero LLM en tiempo de ejecución (hecho verificable)

El paquete `mx/` y el router `api/mx.py` **no importan** ningún SDK de modelo ni cliente de red.

Comprobación (desde la raíz del repo):

```
$ grep -nE "anthropic|openai|elevenlabs|requests|httpx|urllib|socket" mx/*.py api/mx.py
# (sin coincidencias: 0)
```

Qué significa:

- **Generación de contratos**: 100 % determinista (`mx/contracts.py`), plantillas fijas +
  datos de las partes. El mismo input + mismo reloj + mismo id produce el mismo texto y el mismo
  `sha256`. No hay redacción con IA.
- **Requisitos legales**: se sirven desde archivos YAML ya verificados (`data/mx/requirements/*.yaml`);
  cada cita se comprueba contra el texto oficial descargado con `python -m mx.verify` (offline).
- **Zonas / estadísticas**: se leen de `data/mx/zones.json` (catálogo y Censo 2020 de INEGI). Cada
  cifra lleva su `source` (doc_id) y solo se sirve si ese doc está íntegro en los manifiestos.
- **Firma electrónica**: hashing SHA-256 local; sin servicios externos.

La API es **read-only salvo** publicar anuncios, crear contratos y firmar, que escriben en un store
de archivos JSON efímero. Ninguna de esas operaciones llama a un modelo.

Factura de inferencia del runtime MX: **$0**. El único costo de operar la demo es el hosting
(Render free), igual que el proyecto original.

## 2. Dónde sí hubo costo (una sola vez, en construcción)

El costo del pivote fue de **trabajo de agentes en construcción**, no de runtime. Lo que quedó
versionado y ya no vuelve a costar:

| Artefacto | Volumen | Cómo se produjo | Costo de runtime a futuro |
|---|---:|---|---|
| Requisitos legales con cita literal | **195** (federal + 8 entidades) | Investigación con fuentes oficiales (DOF, Cámara de Diputados, consejerías/congresos estatales); extracción de texto con `pdftotext`/HTML, no con LLM | $0 |
| Documentos fuente en manifiestos | **82** | Descarga directa del sitio oficial + `sha256` + `text_sha256` | $0 |
| Zonas INEGI | **32** estados · **2,478** municipios | Catálogo y Censo 2020 de INEGI (archivos oficiales) | $0 |
| Cláusulas de contrato | plantillas fijas | Escritas a mano, sin hechos legales embebidos | $0 |

La verificación de todo lo anterior corre **offline y gratis** las veces que haga falta:

```
$ python -m mx.verify
mx.verify: 195/195 citas verificadas, 82/82 documentos íntegros, 221 avisos  (ok=True)
```

## 3. Comparación con el proyecto original (EE. UU.)

El proyecto original sí usó LLM, pero **solo en construcción** (Módulo A con Claude Opus para
extracción, Haiku para lenguaje sencillo y clasificación, ElevenLabs para audio). Su runtime
también es read-only sin LLM. Renta MX hereda esa misma disciplina y, además, **no requirió ningún
gasto de modelo para los datos**: la extracción legal mexicana se hizo con descarga + `pdftotext` +
verificación de cita literal, evitando por completo el costo de tokens de extracción.

| Concepto | Proyecto US | Renta MX |
|---|---|---|
| LLM en runtime (por request) | $0 | $0 |
| LLM para construir los datos | ~$3.87 extracción (Opus) + Haiku/audio | **$0 de tokens** (descarga + pdftotext + verificación) |
| Verificación de citas | offline, gratis | offline, gratis (`mx.verify`) |
| Hosting | Render free | Render free |

## 4. Recomendaciones para mantener el costo en cero

1. **No introducir LLM en las rutas `/mx/*`.** Si en el futuro se quiere "explicar" un requisito en
   lenguaje aún más simple, precomputarlo en construcción y versionarlo (como el `summary_es/en`),
   nunca generarlo por request.
2. **Mantener el guard de `mx.verify` en CI.** Es gratis y evita que una cita no verificada llegue a
   producción.
3. **Si se agregan entidades**, repetir el patrón sin tokens: descargar el texto oficial, fijar
   `sha256`/`text_sha256`, escribir el requisito con su `quote` y validar con `mx.verify`.
4. **Audio (opcional).** Si algún día se agrega audio tipo el del proyecto US, es el único rubro con
   costo marginal (ElevenLabs por carácter); cachearlo por hash de texto como ya se hace allá.

---

## 5. Revisión de costos de las fases 0-4 (The Budgeter)

Revisión de las superficies nuevas (zonas/precio, mapa, publicación, contratos, firma). Objetivo:
confirmar que las fases 0-4 **no mueven la factura de inferencia de $0** y acotar el único costo
marginal real (hosting). Evidencia reproducible, con comandos y su salida real en este árbol.

### 5.1 Runtime sigue en $0 de LLM (verificado)

Ni `mx/*.py` ni `api/mx.py` importan un SDK de modelo o un cliente de red; sus imports son solo
stdlib, FastAPI y módulos `mx.*`.

```
$ grep -nE "anthropic|openai|elevenlabs|requests|httpx|urllib|socket|aiohttp" mx/*.py api/mx.py
# (0 coincidencias)
```

Las fases nuevas son deterministas y puras:

- **Precio por zona** (`mx/prices.py`): `listing_price_summary` es una función pura sobre los
  anuncios que publican usuarios (`basis = "viviendas_publicadas"`), con `Decimal`; nunca scrapea
  un portal ni inventa cifras, y oculta min/median/max con menos de `MIN_COUNT_FOR_STATS = 3`
  registros sanos. El dato INEGI es estadístico, no precio, y se trata aparte.
- **Mapa** (ver 5.2): el componente no llama a ningún backend propio; pinta solo coordenadas
  oficiales INEGI ya versionadas.
- **Contratos / firma** (`mx/contracts.py`, `mx/signatures.py`): plantillas fijas + SHA-256 local.

Verificación de citas, offline y gratis (corre en el build de Render, falla el deploy si una cita
no cuadra):

```
$ python -m mx.verify
mx.verify: 229/229 citas verificadas, 85/85 documentos íntegros, 268 avisos  (ok=True)
```

> El corpus creció respecto al baseline del plan (195/82) porque otras etapas agregaron entidades;
> el punto de costo no cambia: toda verificación es offline y $0.

Pruebas offline (sin red, sin modelo), ambas en verde en este árbol:

```
$ python -m pytest -q
429 passed in 33.02s

$ cd frontend; bun run test
Test Files  5 passed (5)
     Tests  22 passed (22)
```

### 5.2 Mapa: tiles OSM sin clave ni facturación (con deuda anotada)

`frontend/src/components/mx/MxMap.tsx` usa **maplibre-gl** (open source, sin SDK propietario) con
tiles raster servidos directamente desde el *standard tile server* de OSM:

```
tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"]
attribution: mx.map.attribution   // "© Colaboradores de OpenStreetMap" / "© OpenStreetMap contributors"
```

Ni Mapbox, ni MapTiler, ni Stadia, ni ningún servicio con `api_key` o facturación por carga
(`grep -nE "mapbox|maptiler|stadia|access[_-]?token|api[_-]?key" frontend/src/components/mx` → 0).
**Costo de servicio del mapa en la demo: $0.**

**Deuda para producción (política de uso justo de OSM).** El tile server de OSMF es para
desarrollo y volumen bajo, **no** para tráfico de producción (ver *OSM Tile Usage Policy*:
atribución obligatoria —ya la cumplimos—, nada de descargas masivas/pre-fetch, un `User-Agent`
identificable). Si Renta MX escala, la ruta recomendada es:

1. un proveedor de tiles con plan gratuito y clave (MapTiler / Stadia / Protomaps) detrás de una
   variable de entorno, o
2. auto-hospedar tiles vectoriales (Protomaps `.pmtiles` en el bucket/estático), que es $0 de
   servicio recurrente salvo el almacenamiento.

Ambas no cambian el runtime Python (el mapa es 100 % cliente). Queda anotado como deuda; la demo
no la necesita.

### 5.3 Bundle del mapa: carga diferida confirmada

maplibre se importa de forma **dinámica dentro de un `useEffect`** (es client-only: necesita
`window`/WebGL), así que vive en su propio *chunk async* y **no entra en el bundle inicial**:

```
// MxMap.tsx
const maplibregl = (await import("maplibre-gl")).default;
await import("maplibre-gl/dist/maplibre-gl.css");
```

Evidencia del build (`cd frontend; bun run build`, Cloudflare/nitro target):

- El entry principal **no contiene maplibre** (`Select-String index-*.js -Pattern maplibre` → `False`).
- El chunk `MxMap-*.js` (6.3 KB) hace `import("./maplibre-gl-C4xRBlvl.js")`: la librería y su CSS
  (`maplibre-gl-*.css`, 81 KB) solo se piden cuando una zona con coordenada oficial monta el mapa.
- Hay fallback de lista navegable por teclado cuando no hay WebGL, así que un cliente sin WebGL
  nunca descarga maplibre.
- Dependencia pineada **exacta**: `"maplibre-gl": "6.12.0"` en `frontend/package.json` (sin `^`).

Payload JS del cliente: 28 chunks, ~709.6 KB sin comprimir en total (code-split por ruta); el peso
de maplibre está aislado tras el `import()` y no penaliza la carga de las páginas sin mapa.

### 5.4 Hosting: Postgres/Render starter como disparador OPCIONAL

El único costo recurrente posible. Hoy la demo corre en **Render free + store de archivos JSON
efímero** (`mx/store.py` `JsonStore`), coherente con el proyecto US. `render.yaml` lo deja
documentado y **comentado**: nada se activa por defecto.

| Escenario | Config (`render.yaml` / `DATABASE_URL`) | Persistencia | Costo mensual (orden) |
|---|---|---|---|
| Demo (actual) | `plan: free`, `DATABASE_URL` sin definir | efímero (se pierde al reiniciar) | **$0** |
| SQLite local | `DATABASE_URL=sqlite:///abs/path.db` | aún en disco efímero del free | $0 |
| Producción | `plan: starter` + Render **managed Postgres** | persistente | de pago (plan starter + Postgres) |

El disparador para pasar a Postgres es **conservar anuncios/contratos entre reinicios**, no un
límite de inferencia. `mx/store.py` ya trae `SqlStore` (SQLite/`psycopg` perezoso) con la misma
interfaz, así que el cambio es de configuración, no de código. Para cifras exactas de Render
starter y su Postgres, consultar el tarifario vigente de Render (no se fija aquí para no inventar
números).

### 5.5 Conclusión de las fases 0-4

Las fases 0-4 **no introducen ningún costo de LLM ni de servicios con clave**: runtime $0 de
inferencia (verificado por `grep` y por pruebas offline en verde), mapa con tiles OSM sin clave y
maplibre en carga diferida, y persistencia como palanca opcional de hosting. La única acción
pendiente es de operación, no de costo de la demo: migrar los tiles a un proveedor con política de
producción (y, si se quiere conservar datos, Postgres) cuando haya tráfico real.

---

*Conclusión: el pivote a Renta MX es neutral en costo de tokens. El runtime no usa LLM; la
construcción tampoco gastó tokens de extracción porque las fuentes mexicanas se procesaron con
descarga + extracción de texto + verificación de cita literal. El único costo recurrente es el
hosting gratuito. — The Budgeter*
