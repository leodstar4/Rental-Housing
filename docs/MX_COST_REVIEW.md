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

*Conclusión: el pivote a Renta MX es neutral en costo de tokens. El runtime no usa LLM; la
construcción tampoco gastó tokens de extracción porque las fuentes mexicanas se procesaron con
descarga + extracción de texto + verificación de cita literal. El único costo recurrente es el
hosting gratuito. — The Budgeter*
