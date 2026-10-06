# Renta MX: blueprint de arquitectura (The Architect → The Implementor)

Base: `docs/MX_SPEC.md`. Este documento lo complementa; si chocan, se corrige el spec y se anota aquí.
Código leído: `api/main.py`, `extractor/validate.py` (`match_span`), `extractor/clean.py`
(`locate_quote`, `_QUOTE_FOLD`), `extractor/config.py`, `tests/conftest.py`, `tests/test_api.py`,
`render.yaml`, `frontend/src/lib/api.ts`.

## 1. Críticas al spec (corregir antes de codificar)

1. **El texto extraído puede amañarse.** El manifiesto guarda el `sha256` del PDF, pero la cita se
   verifica contra `text_path` (.txt). Si alguien edita el .txt, cualquier cita "pasa". Añadir
   `text_sha256` al manifiesto. `mx.verify` recalcula ambos hashes y, para PDF, vuelve a extraer el texto
   con `pypdf` (versión fijada en requirements) y lo compara. Si algo no coincide, el `doc_id` queda **inválido** y
   todas sus citas fallan.
2. **IDs de documento inconsistentes.** El spec da `D-MX-FED-NN` y, en el ejemplo YAML, `D-MX-003`. Se adopta
   solo `^D-MX-(FED|INEGI|[A-Z]{2,4})-\d{2}$`, único entre todos los `manifest_*.json`. Requisitos:
   `^MX-(FED|<ABBR>)-[A-Z_]+-\d{2}$`. El prefijo debe coincidir con `jurisdiction`, con el nombre del archivo YAML y con la
   jurisdicción del `doc_id` citado. Un requisito estatal no puede citar un doc federal, ni al revés.
3. **Arrendamiento = materia local.** El arrendamiento de casa habitación lo rige el **código civil
   estatal**; el Código Civil Federal no lo "rellena". En una entidad `solo_federal`, un contrato con base
   solo en el CCF es jurídicamente débil. El spec lo trata como algo normal, y no debe serlo (ver §5).
4. **`legal_coverage` no debe escribirse a mano** en `zones.json`, porque se desincroniza. Se **calcula**: es
   `estatal_verificada` si hay ≥1 requisito verificado de esa entidad; si no, `solo_federal`.
5. **Citas triviales.** Una `quote` como "arrendamiento" siempre verifica. Hay que exigir 40 ≤ len(quote) ≤ 1500
   después de normalizar. Además, comprobar el "ancla de artículo": se busca el `Artículo N` más cercano antes del offset y,
   si `citation` no contiene N, se emite un **warning** en `out/mx_validation.json` (no es fallo).
6. **`summary_*` no se puede verificar** (es una paráfrasis). La UI siempre lo muestra junto a la `quote`, con la etiqueta
   "Resumen no oficial". Se añade `reviewed_by` (texto) al YAML; si falta, se emite un warning.
7. **Topes numéricos legales** (incrementos, depósito): el spec no da forma legible por máquina. No
   se escriben en Python. Opcional: `checks: [{field, op, value}]` en el requisito, solo si el número
   aparece literalmente en la `quote` (verify lo comprueba con un regex). Sin `checks`, no se valida.
8. **`practica` nunca es obligación.** `kind: practica` ⇒ `applies_to_contract` debe ser `false`
   (verify falla si no). Nunca se usa para alimentar una cláusula.
9. **Firma sin identidad ni control de rol.** Con el spec tal cual, cualquiera con el `contract_id` firma como
   arrendador. Se añaden tokens de firma por rol (§4). Y se firma **un hash concreto**: el request lleva
   `contract_sha256`; si no coincide con el actual, responde 409.
10. **El contrato no se edita.** No hay ruta de edición. Una "modificación" es un contrato nuevo con
    `supersedes: <id>`. La regla "hash cambia ⇒ firmas inválidas" se implementa como **verificación al
    leer**: se recalcula el hash del texto guardado y se compara con el de cada evidencia. Esto detecta cambios
    en el store, que es lo que The Tester puede atacar.
11. **LFPDPPP "vigente".** Comprobar que el PDF descargado es la ley vigente a la fecha de
    `retrieved_at` (la ley se reemplazó en 2025). `last_reform` es obligatorio para FED, sin suponerlo de memoria.
12. **INEGI**: `zones.json` lo genera un script (`python -m mx.zones build`) desde
    `corpus_mx/inegi/raw/*.zip` (ITER 2020). No se edita a mano. Así verify re-deriva los valores y los compara.

## 2. Reutilización del código existente

- **Cascada de citas**: se reutiliza `extractor.validate.match_span(raw, quote, allow_fuzzy=False)`.
  Da exacto → normalizado (espacios, comillas curvas, guiones, NBSP vía `clean._QUOTE_FOLD`). **Sin fuzzy ni
  reintento LLM** (el spec lo prohíbe). Para PDF en español falta un pre-fold del *raw*, que se pone
  en `mx/verify.py` (no en `extractor/`): NFC, quitar soft hyphen U+00AD, unir el guion de corte de línea
  `(\w)-\n(\w)` y pasar «» a `"`. Si coincide solo tras este paso, `match_type="normalized_mx"`. Se guarda la quote
  **literal del raw** (`SpanMatch.text`) cuando el pre-fold no reordena offsets; si no, se rechaza la cita.
- Importar `extractor.validate` trae `jsonschema`, `rapidfuzz` y `extractor.config` (dotenv). Ya están en
  requirements y no hacen red, así que se acepta. **No** se importan `extractor.llm` ni el `Engine`.
- `api/main.py`: se reutilizan `DISCLAIMER`, `lang_of` y el patrón `lru_cache` de carga. **No** se toca `Store`
  de EE.UU.

## 3. Módulos `mx/` (deterministas, sin LLM, sin red)

```
mx/__init__.py
mx/paths.py        # raíces resueltas en llamada (no en import): MX_DATA=data/mx, MX_CORPUS=corpus_mx,
                   # MX_STORE_DIR=env o out/mx_store. Funciones, para que tests monkeypatcheen.
mx/models.py       # pydantic (abajo)
mx/sources.py      load_manifests(root: Path) -> dict[str, SourceDoc]   # valida ids únicos, hashes
                   doc_text(doc: SourceDoc) -> str                       # lru_cache por (doc_id, text_sha256)
mx/verify.py       verify_requirement(req: Requirement, docs) -> VerifyResult
                   verify_all(data_root, corpus_root) -> ValidationReport
                   verified_requirements(...) -> dict[str, Requirement]  # SOLO las que pasan; lo usa la API
                   main() -> int   # `python -m mx.verify`: escribe out/mx_validation.json; exit 1 si falla alguna
mx/zones.py        load_zones(path) -> ZonesIndex ; ZonesIndex.state(cve_ent), .municipio(cve_ent, cve_mun),
                   .search(cve_ent, q, limit) (sin acentos, casefold) ; build_from_inegi(raw_dir) -> dict
mx/requirements.py for_entity(cve_ent, lang) -> RequirementsView  # FED + estatal, agrupado por category,
                   coverage computado; cada item: id, kind, title, summary, citation, quote, url, retrieved_at,
                   last_reform, match_type
mx/contracts.py    TEMPLATE_VERSION = "mx-contract-1"
                   load_clauses(path) -> list[ClauseTemplate]
                   build_contract(req: ContractCreate, zone, listing|None, reqs, *, now: datetime,
                                  contract_id: str) -> ContractDoc        # pura; reloj inyectado
                   canonicalize(text: str) -> str ; contract_hash(text) -> str
mx/signatures.py   validate_png(b64: str) -> bytes ; required_roles(contract) -> set[str]
                   make_evidence(contract, role, signer, png, ua, ip, now) -> SignatureEvidence
                   signature_status(contract) -> {role: "valida"|"invalida"|"pendiente"}, overall
mx/store.py        class JsonStore(dir): get/put/list por colección ("listings","contracts");
                   threading.Lock + escritura atómica (tmp en mismo dir → fsync → os.replace); cap por colección
mx/ratelimit.py    TokenBucket por IP en memoria (dict + lock)
api/mx.py          router = APIRouter(prefix="/mx", tags=["mx"])
```

Modelos pydantic (`mx/models.py`, `model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)`):
- `SourceDoc{doc_id, title, publisher, jurisdiction, url: HttpUrl, retrieved_at: datetime, sha256, text_sha256,
  file_path, text_path, last_reform: date|None}`
- `Requirement{id, jurisdiction, category: Literal[...14], kind: Literal[ley,reglamento,norma,practica],
  title_es, title_en, summary_es, summary_en, doc_id, citation, quote, applies_to_contract: bool,
  reviewed_by: str|None, checks: list[Check] = []}`
- `ListingCreate{cve_ent: constr(^\d{2}$), cve_mun: constr(^\d{3}$), cp: constr(^\d{5}$), colonia ≤120,
  title ≤120, description ≤2000, monthly_rent_mxn: condecimal(gt=0, le=10_000_000, decimal_places=2),
  bedrooms: conint(ge=0, le=20), bathrooms, area_m2|None, furnished: bool, available_from: date,
  contact_name ≤120, contact_email: EmailStr*}`. *`EmailStr` requiere `email-validator`. Si no se quiere añadir
  la dependencia, usar un regex simple más `len ≤ 254`.
- `Listing = ListingCreate + {id, created_at}`. **`contact_email` nunca sale en GET** (`ListingPublic` sin él).
- `Party{full_name ≤120, email, rol}`. `ContractCreate{listing_id|None, cve_ent, cve_mun, inmueble{calle,
  num_ext, num_int|None, colonia, cp}, arrendador: Party, arrendatario: Party, fiador: Party|None,
  monthly_rent_mxn, deposit_mxn ≥0, start_date, term_months: conint(1..120), payment_day: conint(1..28),
  lang}`. Ver la nota de campos de texto.
- `ContractDoc{contract_id, template_version, created_at, cve_ent, coverage, text, sha256,
  clauses: [{n, key, title, text, requirement_ids, basis: "ley"|"acuerdo_partes"}], legal_basis: [Requirement
  view], required_roles, supersedes|None}`
- `SignRequest{role, full_name, email, signature_png_base64|None, typed_signature|None, consent: Literal[True],
  contract_sha256, token}`. Exactamente uno de PNG o tecleada, para accesibilidad.
- `SignatureEvidence{role, full_name, email_sha256, contract_sha256, signature_sha256, signature_kind:
  "trazo"|"tecleada", signed_at (UTC ISO, reloj del servidor), user_agent ≤300, ip_hash, consent_text_sha256,
  prev_evidence_sha256|None, evidence_sha256}`. Es una cadena: cada evidencia hashea su JSON canónico más la anterior.

**Campos de texto libre**: se rechazan `\r`, `\n` y los caracteres de control (`[\x00-\x1f\x7f]`) en todos los
campos de una línea (nombres, calles). Así nadie inyecta "CLÁUSULA DÉCIMA…" dentro del contrato. Solo
`description` admite `\n`.

## 4. Decisiones

**Canonicalización (antes del hash).** `canonicalize(t)` hace: `unicodedata.normalize("NFC")` → `\r\n|\r → \n` →
`rstrip()` por línea → colapsar más de 2 líneas vacías → exactamente un `\n` final. El hash es
`sha256(canon.encode("utf-8"))`. Se hashea **el texto que leen las partes**: encabezado (con `contract_id`,
`template_version`, fecha), cláusulas y anexo "Fundamento legal" (citas y quotes). No se hashea el JSON. Los montos van
formateados de forma determinista (`f"{x:,.2f}"` y el importe con letra generado por una función propia y probada).
Si `lang=en`, el texto canónico sigue en **ES** (es el legalmente relevante) y la traducción va aparte, sin firmar.

**Invalidación.** `signature_status` recalcula `contract_hash(stored.text)`. Una evidencia con
`contract_sha256 != actual` cuenta como `invalida`. Si alguna es inválida, overall = `invalidado`. Overall = `firmado`
solo si todos los `required_roles` (arrendador, arrendatario y fiador si existe) tienen evidencia válida.
POST sign: si `contract_sha256` del body ≠ actual responde 409; si el rol ya tiene firma válida responde 409; si el token
es incorrecto responde 403; si `consent` no es true responde 422.

**IDs.** `listing_id` y `contract_id` son `uuid4().hex`: no adivinables, porque el contrato tiene datos personales
y su URL hace de capacidad. No se usa un hash del contenido como ID: filtraría igualdad y colisionaría en reintentos.
POST /contracts devuelve, una sola vez, `sign_tokens: {role: secrets.token_urlsafe(24)}` y en el store solo se guarda
`sha256(token)`. La UI arma un enlace por parte (`/contrato/{id}?rol=arrendatario#t=<token>`; el fragmento no
llega a logs).

**PNG de firma.** Límites: base64 ≤ 200 000 caracteres, decodificado ≤ 150 KB, firma mágica `\x89PNG\r\n\x1a\n`,
IHDR ancho ≤ 1200 y alto ≤ 600, y `base64.b64decode(validate=True)`. Si no cumple, responde 422. Además, un middleware en
`/mx/*` POST rechaza `Content-Length` > 256 KB con 413 (FastAPI no limita el body por defecto). Se guarda el PNG (hace
falta para imprimir) y su sha256.

**CORS (obligatorio).** Hoy `api/main.py:135` tiene `allow_methods=["GET"]`, así que el preflight de cualquier POST
JSON falla en el navegador. Cambiar a `["GET", "POST", "OPTIONS"]` y mantener el regex de orígenes y
`ALLOWED_ORIGINS`. Las rutas existentes no se ven afectadas.

**Montaje.** En `api/main.py`: `from .mx import router as mx_router; app.include_router(mx_router)`. Los datos MX se
cargan **perezosamente** (`@lru_cache def mx_state()`), fuera del `_lifespan` actual. Si faltan `data/mx` o
el corpus, las rutas `/mx/*` responden 503 `{"detail": "datos MX no disponibles"}` y las de EE.UU. siguen funcionando.
El store se inyecta con `Depends(get_store)` para que los tests usen `app.dependency_overrides`. Ojo: `conftest.py`
monkeypatchea `config.OUT_DIR` después del import, por eso `mx/paths.py` resuelve las rutas en cada llamada.

**La API solo sirve requisitos verificados.** Al cargar, `verified_requirements()` corre la verificación en
memoria. No se lee un `out/` posiblemente viejo, y lo que no verifica no se exporta, nunca. `render.yaml`: añadir
`&& python -m mx.verify` al `buildCommand`, para que un deploy con citas rotas **falle**.

**Persistencia efímera (Render free).** El disco se borra en cada deploy y reinicio, y el servicio duerme tras
inactividad. Se comunica así: `GET /mx/health` → `{store: "efimero", store_started_at, listings, contracts}`;
banner fijo en `/publicar` y `/contrato/*`: "Demo: los anuncios y contratos se borran al reiniciar el servidor;
descarga tu constancia". `/mx/contracts/{id}/evidence` devuelve un JSON autocontenido (texto, hash, evidencias) que el
usuario guarda. Un solo worker de uvicorn: `threading.Lock` basta (las rutas sync corren en threadpool). Si un día
hay varios workers, hace falta un lock de archivo o una BD: anotarlo como deuda.

**Seguridad y datos personales.**
- Minimización: no se piden CURP, RFC, INE ni teléfono. Email: en evidencia solo `email_sha256`; en el contrato, el
  nombre. IP: `sha256(ip + MX_IP_SALT)` (env; si falta, un salt aleatorio por proceso). User-agent truncado.
- Aviso de privacidad (LFPDPPP) en `GET /mx/privacy` y enlazado en cada formulario: responsable (equipo
  demo), finalidad (generar contrato y evidencia), retención (efímera), sin transferencias. Su texto cita
  requisitos `MX-FED-DATOS_*` verificados; si no hay ninguno, dice "sin fuente verificada".
- Rate limit: 10 POST/min/IP y 120 GET/min/IP, con 429 + `Retry-After`. La IP sale de `request.client.host`; arrancar
  uvicorn con `--proxy-headers --forwarded-allow-ips='*'` en Render. Caps globales: 1 000 anuncios y 500
  contratos; al superarlos, 507.
- Escape: la API devuelve **texto plano**, nunca HTML. El frontend renderiza con React, sin
  `dangerouslySetInnerHTML`. La vista de impresión es una ruta React con CSS `@media print`. Si alguien añade HTML del
  lado servidor, todo pasa por `html.escape`.
- `frontend/src/lib/api.ts`: `API_BASE = import.meta.env.VITE_API_BASE ?? "<actual>"`. Añadir `apiPost` **sin
  reintentos automáticos** (`apiGet` reintenta en 5xx y 429; repetir un POST duplica anuncios o firmas). Antes de un
  POST se llama a `apiGet("/mx/health")` para despertar Render; luego va un solo POST con timeout de 70 s.

## 5. Cláusulas ↔ requisitos y entidades `solo_federal`

`data/mx/contract_clauses.yaml`:
```yaml
- key: deposito
  title_es: "Depósito en garantía"
  basis: ley                # ley | acuerdo_partes
  scope: estatal            # federal | estatal | cualquiera
  requirement_ids: [MX-CDMX-DEPOSITO-01, MX-JAL-DEPOSITO-01]   # se usan los de la entidad del contrato
  template_es: "El ARRENDATARIO entrega la cantidad de ${deposit_mxn} ..."   # string.Template; solo campos validados
  required_fields: [deposit_mxn]
```
Reglas en `build_contract`:
1. Los `requirement_ids` efectivos de una cláusula son su lista ∩ requisitos **verificados** de FED ∪ entidad.
2. `basis: ley` sin ningún requirement efectivo ⇒ la cláusula **se omite** y se lista en `omitted_clauses` con su motivo.
3. `basis: acuerdo_partes` (precio, plazo, día de pago) se incluye siempre con `requirement_ids: []` y la leyenda
   "Pacto entre las partes". Nunca se le inventa fundamento.
4. Las cláusulas `scope: federal` (consentimiento electrónico, datos personales, CFDI) aplican en todas las entidades.
5. Entidad `solo_federal`: se genera el contrato con `coverage: "solo_federal"`, sin cláusulas `estatal`. Se añade al
   texto (y por tanto al hash) un aviso fijo: "No contamos con el código civil verificado de esta entidad. El
   arrendamiento se rige por la legislación civil local; este documento puede no cumplirla. Revíselo con un
   profesional". La UI exige marcar una casilla de "entiendo" antes de crear el contrato.
6. `required_fields`: la unión de los de todas las cláusulas incluidas. Si falta alguno, 422 que lista los campos.
   El anexo "Fundamento legal" está formado solo por los requisitos efectivos usados, con citation, quote, url y retrieved_at.

## 6. Riesgos legales del diseño

- **Firma simple ≠ avanzada.** Prohibidas en UI y API las palabras "avanzada", "certificada", "NOM-151",
  "e.firma" o "fecha cierta" aplicadas a lo que emite la demo. La constancia se llama "Constancia de evidencia
  de firma electrónica simple (no es constancia de conservación NOM-151)". El alcance se explica con citas
  verificadas (Código de Comercio, CCF sobre consentimiento electrónico); si no verifican, no se afirma nada.
- **Identidad no verificada.** El email no se confirma (no hay OTP) y el token solo prueba posesión del enlace.
  Decirlo en la constancia.
- **Sello de tiempo** = reloj del servidor, no un TSA. Decirlo.
- **Plantilla con apariencia de válida** en entidades sin fuente (ver §5.5). Mismo riesgo con cláusulas
  potencialmente abusivas (PROFECO): las plantillas no llevan penas, renuncias de derechos ni intereses
  moratorios. Solo pactos neutros.
- **Fiscal:** solo se informa (CFDI, IVA exento de casa habitación) con cita; la app no calcula impuestos.
- **Anuncios:** sin verificar quién publica ni la titularidad. Advertir "verifica al arrendador", y nada de
  pagos dentro de la app.
- **Disclaimer** en cada respuesta `/mx/*` (`disclaimer` ES/EN), igual que hace la API actual.

## 7. API (`api/mx.py`), detalles no obvios

- Las GET aceptan `lang` y validan con `lang_of`. `cve_ent`/`cve_mun` desconocidos dan 404, no una lista vacía.
- `/mx/listings` y `/mx/zones` incluyen `listings_count` real (0 permitido) y `empty_state: true` cuando es 0.
- `/mx/sources` devuelve el manifiesto completo más `verification: {doc_id: "ok"|"hash_mismatch"}`.
- POST /mx/listings → 201 `ListingPublic`; POST /mx/contracts → 201 `ContractDoc + sign_tokens`;
  POST sign → 200 `{status, signatures}`.

## 8. Plan de pruebas mínimo (The Tester), todo offline

Fixtures en `tests/fixtures/mx/`: un corpus mini (un .txt FED y uno CDMX con su manifiesto y hashes reales), YAMLs
pequeños y `zones.json` con 2 entidades (una `solo_federal`). Los tests MX **no** dependen de `out/` ni del
skip de `test_api.py`; usan `app.dependency_overrides` y `tmp_path` para el store.

1. verify: quote exacta pasa; quote con saltos de línea, comillas curvas o guion de corte pasa como `normalized*`;
   una palabra cambiada falla y da exit 1; quote < 40 caracteres falla; `.txt` alterado (text_sha256) hace fallar
   todo el doc; `practica` con `applies_to_contract: true` falla; prefijo de id ≠ jurisdicción falla.
2. requirements: la API nunca devuelve un requisito no verificado (se inyecta uno roto en el fixture);
   `legal_coverage` es calculado; entidad sin YAML ⇒ solo FED + `solo_federal`.
3. zones: ninguna stat sin `source`; `q` sin acentos ("cuauhtemoc") encuentra "Cuauhtémoc"; ids inválidos dan 404.
4. listings: store vacío ⇒ `[]` y `empty_state`; rechazos 422 (renta ≤ 0, CP de 4 dígitos, municipio inexistente,
   email inválido, `\n` en nombre, campo extra); el email no aparece en GET.
5. contratos: misma entrada y mismo reloj dan el mismo `text` y el mismo `sha256`; canonicalize es idempotente y
   `\r\n` ≡ `\n`; todo `requirement_id` de cláusulas existe en `legal_basis`; `solo_federal` ⇒ aviso presente y
   ninguna cláusula estatal; `<script>` en nombre ⇒ el texto lo contiene literal (sin interpretar) y no hay HTML en la respuesta.
6. firmas: sin consent da 422; token incorrecto 403; `contract_sha256` viejo 409; doble firma del rol 409; PNG
   > 150 KB, no-PNG o base64 inválido dan 422; body > 256 KB da 413; todas las partes firmadas ⇒ `firmado`; editar el
   texto en el JSON del store ⇒ `invalidado`; la cadena `prev_evidence_sha256` se rompe si se borra una evidencia.
7. store: escritura atómica (no quedan `.tmp`), 20 hilos publicando ⇒ N registros sin JSON corrupto.
8. Regresión: `pytest -q` completo verde; el preflight `OPTIONS /mx/listings` con Origin de lovable.app da 200 y
   los GET de EE.UU. no cambian.
9. Rate limit: el POST 11 dentro del mismo minuto da 429 (reloj inyectable en `TokenBucket`).

## 9. Orden de construcción

1. `mx/paths.py`, `mx/models.py`, `mx/sources.py` (con `text_sha256`) y tests de manifiesto.
2. `mx/verify.py` + `python -m mx.verify` + tests 1. Se ejecuta sobre los YAML reales a medida que llegan.
3. `mx/zones.py` (build desde ITER 2020 y load/search) + tests 3.
4. `mx/requirements.py` + `api/mx.py` con las GET de solo lectura (`states`, `zones`, `requirements`, `sources`,
   `health`); `include_router` y CORS POST en `api/main.py`; tests 2 y 8.
5. `mx/store.py`, `mx/ratelimit.py`, middleware de tamaño y listings (GET/POST) + tests 4, 7 y 9.
6. `mx/contracts.py` + `contract_clauses.yaml` + POST/GET contracts + tests 5.
7. `mx/signatures.py` + sign/evidence + tests 6.
8. `render.yaml` (`mx.verify` en el build, `--proxy-headers`, env `MX_IP_SALT`), `api.ts` (`VITE_API_BASE`,
   `apiPost`) y rutas del frontend.
9. Revisión final de copys legales (§6) con grep de las palabras prohibidas.
