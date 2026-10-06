# Renta MX — especificación compartida (demo)

Pivote del proyecto: una plataforma tipo Airbnb **para rentar y vivir (arrendamiento de casa
habitación de largo plazo) en México**. El usuario busca por **zona** (estado → municipio/alcaldía),
ve las viviendas publicadas disponibles, los **requisitos legales** que aplican en esa entidad y
puede **generar y firmar electrónicamente un contrato de arrendamiento**.

Este documento es el contrato entre agentes. Si algo aquí choca con la realidad de las fuentes,
gana la fuente oficial y se documenta el cambio aquí.

## Regla cero: CERO datos inventados

1. Todo dato mostrado (cifra, requisito, artículo, monto, porcentaje, coordenada) proviene de una
   **fuente oficial descargada** y registrada en `corpus_mx/manifest_*.json` con `url`,
   `retrieved_at` (ISO), `sha256` del archivo y `publisher`.
2. Todo requisito legal lleva **cita literal** (`quote`) que un script verifica que existe en el
   texto descargado (misma filosofía que Module A: exacto → normalizado (espacios, guiones,
   comillas) → si no aparece, NO se exporta). Nada de citas de memoria.
3. **No hay anuncios de vivienda inventados.** El inventario empieza vacío. Los anuncios solo
   existen si un usuario (arrendador) los publica en la app. No se hace scraping de portales
   (Inmuebles24, Vivanuncios, Airbnb…: sus términos lo prohíben y no podemos verificar los datos).
   La UI muestra un estado vacío honesto ("Aún no hay viviendas publicadas en esta zona") con CTA
   para publicar.
4. Lo que es **práctica de mercado** (p. ej. "ingresos 3× la renta", póliza jurídica) NO es ley:
   solo se muestra si hay fuente verificable, y etiquetado `kind: "practica"`; si no hay fuente,
   se omite.
5. Si una entidad no tiene texto oficial descargado, la UI lo dice ("Sin fuente verificada para
   este estado todavía") y solo muestra el marco federal. Nunca rellenar.
6. Nada es asesoría legal. Disclaimer visible siempre (ES por defecto, EN opcional).

## Alcance de la demo

- **Marco federal** (aplica a toda la República): Código Civil Federal (arrendamiento, consentimiento
  por medios electrónicos), Código de Comercio (firma electrónica / mensajes de datos), NOM-151-SCFI
  vigente (conservación de mensajes de datos), Ley Federal de Protección de Datos Personales en
  Posesión de los Particulares vigente (aviso de privacidad), LISR/LIVA/CFF (CFDI por arrendamiento,
  IVA de casa habitación), y lo que la investigación encuentre relevante y oficial.
- **Entidades con código civil verificado** (prioridad, en orden): Ciudad de México, Jalisco,
  Nuevo León, Estado de México, Querétaro, Puebla, Yucatán, Quintana Roo. Cubrir las que se
  puedan descargar de sitios oficiales (congresos estatales, consejería jurídica, periódicos
  oficiales). Las demás entidades aparecen con marco federal + "sin fuente estatal verificada".
- **Zonas**: las 32 entidades y sus municipios/alcaldías (catálogo oficial INEGI). Por municipio,
  estadísticas oficiales INEGI (Censo de Población y Vivienda 2020) — p. ej. viviendas particulares
  habitadas y, si está disponible a nivel municipio, viviendas por tenencia (alquilada) — con la
  fuente por campo. Coordenadas (para mapa) solo si salen de un archivo oficial (p. ej. cabecera
  municipal del catálogo de localidades INEGI).

## Datos (archivos)

```
corpus_mx/                       # textos oficiales descargados (PDF/HTML/TXT) + texto extraído .txt
corpus_mx/manifest_*.json        # uno por agente/grupo (p. ej. manifest_fed_cdmx.json, manifest_estados.json, manifest_inegi.json)
                                 # cada uno: {"docs":[{doc_id, title, publisher, jurisdiction, url, retrieved_at, sha256, file_path, text_path, last_reform?}]}
                                 # doc_id: D-MX-FED-NN, D-MX-<ABBR>-NN, D-MX-INEGI-NN
data/mx/requirements/<ABBR>.yaml # requisitos con cita literal, un archivo por jurisdicción (FED.yaml, CDMX.yaml, JAL.yaml, ...)
data/mx/zones.json               # entidades y municipios con estadísticas y fuente por campo
data/mx/contract_clauses.yaml    # cláusulas de contrato, cada una ligada a requirement ids
mx/                              # paquete Python (lógica determinista; sin LLM en runtime)
```

### `data/mx/requirements/<ABBR>.yaml` (lista de elementos)

```yaml
- id: MX-CDMX-DEPOSITO-01          # estable; prefijo MX-FED / MX-<CLAVE_ENTIDAD>
  jurisdiction: CDMX               # FED | clave de entidad INEGI abreviada (CDMX, JAL, NL, MEX, QRO, PUE, YUC, QROO)
  category: contrato_forma | deposito | incremento_renta | duracion | obligaciones_arrendador |
            obligaciones_arrendatario | garantias_fiador | terminacion | registro | firma_electronica |
            datos_personales | fiscal | habitabilidad | otro
  kind: ley | reglamento | norma | practica
  title_es: "..."
  title_en: "..."
  summary_es: "..."                # paráfrasis fiel, sin agregar nada que no diga la cita
  summary_en: "..."
  doc_id: D-MX-003
  citation: "Código Civil para el Distrito Federal, art. 2448-..."
  quote: "texto literal tal cual aparece en el documento"
  applies_to_contract: true|false   # si alimenta una cláusula
```

Script de verificación: `python -m mx.verify` → falla (exit 1) si alguna `quote` no está en
`text_path` de su `doc_id`; escribe `out/mx_validation.json`.

### `zones.json`

```json
{"source_docs": ["D-MX-INEGI-..."], "states": [{"cve_ent": "09", "name": "Ciudad de México", "abbr": "CDMX",
 "legal_coverage": "estatal_verificada|solo_federal",
 "municipios": [{"cve_mun": "015", "name": "Cuauhtémoc", "lat": 19.43, "lon": -99.15,
   "stats": {"viviendas_particulares_habitadas": {"value": 0, "source": "D-MX-INEGI-01", "year": 2020}}}]}]}
```
(`value` real del archivo; si no hay dato, el campo no existe.)

## API (FastAPI, en `api/main.py` vía `APIRouter` de `api/mx.py`, prefijo `/mx`)

Read-only salvo publicación de anuncios y firmas (persistencia en archivo JSON bajo `out/mx_store/`,
suficiente para demo; documentar que en Render free el disco es efímero).

| Método | Ruta | Respuesta |
|---|---|---|
| GET | `/mx/states` | `[{cve_ent, name, abbr, legal_coverage, listings_count}]` |
| GET | `/mx/zones?cve_ent=09&q=cuauh` | municipios con stats + `listings_count` |
| GET | `/mx/zones/{cve_ent}/{cve_mun}` | zona + stats con fuentes + anuncios + resumen de requisitos |
| GET | `/mx/requirements?cve_ent=09&lang=es` | requisitos agrupados por categoría (federal + estatal), con cita, quote, url, retrieved_at |
| GET | `/mx/listings?cve_ent=&cve_mun=&max_rent=&bedrooms=` | anuncios publicados por usuarios |
| POST | `/mx/listings` | publica un anuncio (validación pydantic; sin fotos binarias en demo) |
| GET | `/mx/listings/{id}` | detalle |
| POST | `/mx/contracts` | genera contrato desde datos de las partes + anuncio/ inmueble + entidad. Devuelve `{contract_id, text, clauses:[{n, title, text, requirement_ids}], sha256, legal_basis:[...]}` |
| GET | `/mx/contracts/{id}` | contrato + estado de firmas |
| POST | `/mx/contracts/{id}/sign` | `{role: arrendador|arrendatario|fiador, full_name, email, signature_png_base64, consent: true}` → registra evidencia: sha256 del contrato, sha256 de la firma, timestamp UTC, user-agent; el contrato queda `firmado` cuando firman todas las partes requeridas |
| GET | `/mx/contracts/{id}/evidence` | constancia de firma (JSON) |
| GET | `/mx/sources` | manifiesto de fuentes (transparencia) |

`lang=es|en` en las GET con texto; default `es`.

## Contrato y firma

- Generación **determinista** (plantillas + datos), sin LLM. Cada cláusula referencia `requirement_ids`
  y el contrato incluye un anexo "Fundamento legal" con citas y URLs.
- Campos que la ley exija para el contrato en la entidad (p. ej. forma escrita, datos mínimos) se
  validan como obligatorios.
- Firma: **firma electrónica simple** (nombre + trazo + consentimiento explícito + hash). La UI
  debe explicar, con cita, el alcance legal y que para mayor fuerza probatoria se usa firma
  electrónica avanzada (e.firma SAT) y/o constancia de conservación NOM-151 emitida por un
  Prestador de Servicios de Certificación acreditado — eso no lo emite la demo y se dice claramente.
- Contrato modificado después de una firma ⇒ hash cambia ⇒ firmas previas se invalidan.
- Descargable/imprimible (vista de impresión HTML → "Guardar como PDF" del navegador).

## Frontend (TanStack Start, `frontend/`)

Nueva experiencia en español por defecto (EN opcional), rutas:
- `/` → landing nueva "Renta en México": buscador de zonas (estado + municipio con autocompletado).
  La app anterior (EE.UU.) se mueve bajo `/us` o queda enlazada como "Proyecto anterior", sin romperla.
- `/zona/$cveEnt/$cveMun` → estadísticas INEGI con fuente, anuncios (o estado vacío), requisitos.
- `/requisitos/$cveEnt` → checklist legal por categoría, cada punto con "Ver fundamento" (cita + quote + enlace).
- `/publicar` → formulario para publicar vivienda.
- `/vivienda/$id` → detalle + "Iniciar contrato".
- `/contrato/$id` → revisión, firma con trazo (canvas, accesible: alternativa de firma tecleada),
  estado de firmas, constancia, imprimir.
- `/fuentes` → transparencia: manifiesto de fuentes oficiales con fecha de consulta y hash.

`API_BASE` configurable con `import.meta.env.VITE_API_BASE` (fallback al actual).

## Invariantes que The Tester debe atacar

- Ningún requisito exportado sin quote verificada; ninguna cifra de zona sin fuente.
- Estado vacío real cuando no hay anuncios (nunca relleno).
- Validación de entradas en POST (renta > 0, CP de 5 dígitos, entidad/municipio existentes, email válido, consentimiento obligatorio, tamaño máximo de firma).
- Firma sobre contrato alterado → inválida. Doble firma del mismo rol → 409.
- Pruebas offline (`python -m pytest -q`), sin red.
