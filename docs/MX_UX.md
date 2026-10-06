# Renta MX — Experiencia de usuario (The UX)

Documento para The Designer y The Frontend. Fuente de verdad del producto: `docs/MX_SPEC.md`.
Copy listo para usar: `frontend/src/lib/mx-i18n.ts` (`mxCopy.es` / `mxCopy.en`, claves citadas abajo
como `zone.listingsEmptyTitle`, etc.).

Principios que gobiernan todo lo que sigue:

1. **Cero relleno.** Si no hay dato, la UI lo dice; nunca un ejemplo, un placeholder con cifras ni un anuncio de muestra.
2. **Cada afirmación legal es clicable hasta su cita literal.** La UI no redacta derecho: muestra `title`/`summary` de la API y, a un clic, `citation` + `quote` + documento + fecha.
3. **Ley ≠ práctica de mercado ≠ dato estadístico.** Tres tratamientos visuales distintos, nunca mezclados.
4. **La firma es un acto consciente.** Consentimiento explícito, versión exacta (huella) visible, alcance honesto.
5. **Español primero, "usted", sin jerga.** Términos legales en su forma oficial con explicación al lado (arrendador = propietario).

---

## 1. Arquitectura de información y flujos por rol

### 1.1 Mapa del sitio

```
/                         Landing "Renta en México": buscador estado → municipio, estados con cobertura
├── /zona/$cveEnt/$cveMun Zona: cifras INEGI · viviendas publicadas (o vacío honesto) · resumen de requisitos
│     └── /vivienda/$id   Detalle de vivienda · "Antes de rentar" · Iniciar contrato (formulario en 3 pasos)
│            └── /contrato/$id   Revisión · partes/firmas · firma · constancia · imprimir
├── /requisitos/$cveEnt   Checklist legal por categoría (federal + estatal), "Ver fundamento"
├── /publicar             Formulario para arrendadores (prellenable con ?cveEnt=&cveMun=)
├── /fuentes              Manifiesto: documentos, fecha de consulta, SHA-256, estados sin fuente
└── /us                   Proyecto anterior (EE. UU.), enlazado en el pie/nav como "Proyecto anterior"
```

Navegación global (header): **Buscar zona** · **Publicar vivienda** · **Fuentes** · botón de idioma.
"Proyecto anterior (EE. UU.)" va en el pie, no compite con el producto nuevo.
Breadcrumb en todas las rutas profundas: `Inicio › {Estado} › {Municipio} › {Vivienda} › Contrato`.

El formulario "Iniciar contrato" **no** es una ruta nueva: vive en `/vivienda/$id` (sección expandible o `Sheet`
con 3 pasos) para respetar el spec. Al recibir `contract_id` se navega a `/contrato/$id`.

### 1.2 Flujo del inquilino (arrendatario)

```
[/] elige Estado ──► escribe Municipio (autocompletado /mx/zones?cve_ent=&q=) ──► "Ver zona"
      │                                       └─ alternativa: "Ver solo los requisitos del estado" ─► /requisitos/$cveEnt
      ▼
[/zona] cifras con fuente ─► viviendas publicadas ─► resumen de requisitos ─► "Ver todos los requisitos"
      │   (si 0 viviendas: vacío honesto; CTA para publicar; el inquilino aún puede leer requisitos)
      ▼
[/vivienda/$id] detalle ─► caja "Antes de rentar en {estado}" ─► "Iniciar contrato"
      ▼
[Iniciar contrato] Paso 1 Partes (inquilino, arrendador prellenado, fiador opcional)
                   Paso 2 Inmueble y condiciones (domicilio completo, CP, inicio, duración, renta, depósito)
                   Paso 3 Revisar ─► "Generar contrato" (POST /mx/contracts)
      ▼
[/contrato/$id] lee cláusulas (cada una con su fundamento) ─► "Firmar como Arrendatario"
                consentimiento + trazo/tecleada ─► confirmación ─► firma registrada
                ─► "Comparta este contrato" (copiar enlace) ─► espera al resto ─► constancia / imprimir
```

Puntos de decisión con ayuda contextual:
- **¿Fiador?** Toggle "Agregar un fiador" con enlace "Ver fundamento sobre garantías y fiador" (requisitos de
  `category: garantias_fiador`). La UI no dice si es obligatorio: si el backend marca el rol `fiador` como requerido
  para la entidad, el toggle aparece activado y bloqueado con la etiqueta `contractForm.legallyRequired` + fundamento.
- **Campos exigidos por ley**: el backend indica qué campos son obligatorios por requisito; la UI los marca con
  `contractForm.legallyRequiredFor(estado)` y un enlace a su requirement id. Los obligatorios "de producto" usan solo `common.required`.

### 1.3 Flujo del arrendador

```
[/publicar] (desde nav, desde el vacío honesto de una zona —prellenado— o desde la landing)
   Ubicación (estado, municipio, colonia, CP) ─► La vivienda ─► Condiciones ─► Sus datos + 2 consentimientos
   ─► "Publicar vivienda" (POST /mx/listings) ─► éxito: "Ver mi anuncio" / enlace copiable
      ▼
[recibir contrato] El inquilino genera el contrato y le comparte el enlace /contrato/$id
   (la demo no envía correos: se dice explícitamente en contract.shareBody)
      ▼
[/contrato/$id] lee ─► verifica que sus datos son correctos ─► "Firmar como Arrendador" ─► constancia
```

Antes de publicar se muestra un aviso enlazado `publish.seeRequirementsFirst(estado)` (no bloqueante).
El anuncio público **no** muestra calle/número ni correo (privacidad; el domicilio completo se pide en el contrato).

### 1.4 Flujo del fiador

Llega solo por enlace compartido. En `/contrato/$id` ve su rol marcado como pendiente; antes de firmar se le
muestra la caja de categoría `garantias_fiador` ("Ver fundamento") para que entienda a qué se obliga, siempre
con textos de la API. Firma con el mismo componente que las demás partes.

### 1.5 Estado del contrato (máquina de estados de UI)

| Estado UI | Condición (derivada de `GET /mx/contracts/{id}`) | Color/tono |
|---|---|---|
| `pendiente` | 0 firmas válidas | neutro (`future`) |
| `parcial` | ≥1 firma válida, faltan roles requeridos | `unknown` (ámbar) |
| `firmado` | todas las partes requeridas con firma válida | `applies` (verde) |
| `invalidado` | existe ≥1 firma cuyo hash ≠ hash actual | `destructive` (rojo) + banner |

---

## 2. Rutas: objetivo, jerarquía, estados y microcopy

Estados comunes a todas las rutas (reutilizar `StateMsg` y el banner `waking` de `Shell.tsx`):

| Estado | Comportamiento | Copy (ES / EN) |
|---|---|---|
| Cargando | Skeletons con la forma del contenido final (no spinner a pantalla completa); `aria-busy` en la sección | `common.loading` "Cargando…" / "Loading…" |
| API despertando (>2.5 s) | Banner `role="status"` bajo el header; a los ~20 s cambia a `wakingStill`. No bloquea navegación | "Activando el servidor; la primera consulta puede tardar hasta un minuto. No cierre la página." / "Waking up the server; …" |
| Error de red/5xx | `role="alert"`, conserva lo ya cargado, botón reintentar | `common.error`, `common.retry` |
| Sin conexión | Igual, mensaje específico | `common.errorOffline` |
| 404 de recurso | Mensaje propio de la ruta + CTA útil (no pantalla genérica) | ver cada ruta |
| Validación 422 | Resumen de errores arriba + error en cada campo, foco al resumen | `publish.errorSummaryTitle(n)`, `common.errorValidation` |

**Regla de reintentos**: los GET pueden reintentar (como `apiGet`). Los **POST nunca se reintentan
automáticamente** (evita doble publicación y el 409 de doble firma); el usuario pulsa "Intentar de nuevo" y
sus datos permanecen en el formulario.

### 2.1 `/` — Landing "Renta en México"

**Objetivo**: llevar al usuario a una zona en ≤2 interacciones y explicar en 3 líneas por qué confiar.

Jerarquía:
1. H1 `landing.title` + subtítulo `landing.subtitle`.
2. Buscador (fieldset `landing.searchLegend`): `Select` Estado → combobox Municipio (deshabilitado hasta elegir
   estado, con `landing.municipioDisabled` como hint) → botón `landing.searchButton`. Enlace secundario
   `landing.seeStateRequirements`.
3. Tres puntos de confianza (`landing.trustNoFake`, `trustQuotes`, `trustStats`).
4. "Explore por estado": grid de 32 estados con badge de cobertura (`coverage.stateVerified` / `coverage.federalOnly`)
   y `listingsCount(n)`. Orden: alfabético; filtro rápido opcional "Con marco estatal verificado".
5. "Cómo funciona" (5 pasos `landing.howSteps`, mismo patrón visual de `transparency.tsx`).
6. Bloque arrendador: `landing.publishPrompt` + CTA `landing.publishCta`.

Estados: estados cargando → skeleton de 8 tarjetas; error → `landing.statesError` + reintentar (el buscador
queda deshabilitado con el motivo visible); municipio sin coincidencias → `landing.municipioNoMatches(q, estado)`
dentro del listbox; resultados anunciados con `aria-live="polite"` usando `landing.municipioResults(n)`.

| Clave | ES | EN |
|---|---|---|
| `landing.title` | Encuentre dónde rentar y vivir en México | Find where to rent and live in Mexico |
| `landing.municipioPlaceholder` | Escriba al menos 2 letras | Type at least 2 letters |
| `listingsCount(0)` | Sin viviendas publicadas | No homes listed |
| `coverage.federalOnly` | Solo marco federal | Federal law only |

### 2.2 `/zona/$cveEnt/$cveMun` — Zona

**Objetivo**: responder "¿cómo es esta zona, qué hay disponible y qué reglas aplican?" sin inventar nada.

Jerarquía:
1. Breadcrumb + H1 `{Municipio}, {Estado}` + badge de cobertura legal del estado.
2. **Si `legal_coverage = solo_federal`**: aviso informativo (no alarma, tono `unknown-soft`) con
   `coverage.federalOnlyTitle(estado)` + `coverage.federalOnlyBody`. Va antes de los requisitos, no arriba de todo.
3. **La zona en cifras** (`zone.statsTitle`): tarjetas de indicador → valor grande, etiqueta, línea de fuente
   `zone.statSource(doc, año)` con enlace a `/fuentes#{doc_id}`. Mapa a la derecha solo si hay `lat/lon`, con
   `zone.mapCaption` (aclara que es la cabecera municipal, no una vivienda); sin coordenadas → `zone.mapUnavailable`, sin iframe.
4. **Viviendas publicadas** (`zone.listingsTitle`) con filtros (renta máxima, recámaras) + grid de `ListingCard`.
5. **Requisitos legales en {Estado}**: `zone.requirementsSummary(n, cats)` + lista compacta de categorías con
   conteo + CTA `zone.requirementsCta` → `/requisitos/$cveEnt`.

Estados específicos:
- **Vacío honesto** (0 anuncios, sin filtros): ilustración neutra o icono, `zone.listingsEmptyTitle`,
  `zone.listingsEmptyBody`, CTA `zone.listingsEmptyCta(municipio)` → `/publicar?cveEnt=..&cveMun=..`.
  Nunca tarjetas grises "de ejemplo".
- **Vacío por filtros** (hay anuncios pero no coinciden): `zone.filtersNoResults(total)` + `zone.clearFilters`.
- **Indicador ausente**: el campo no existe en `stats` ⇒ la tarjeta muestra `zone.statNoData` en tono atenuado
  (para los indicadores que la UI conoce); si `stats` está vacío ⇒ un solo mensaje `zone.statsEmpty`.
- **404** municipio: `zone.notFound` + CTA `common.goHome`.

| Clave | ES | EN |
|---|---|---|
| `zone.listingsEmptyTitle` | Aún no hay viviendas publicadas en esta zona | No homes have been listed in this area yet |
| `zone.listingsEmptyBody` | Las viviendas aparecen aquí solo cuando un arrendador las publica en Renta MX. No copiamos anuncios de otros portales ni mostramos ejemplos ficticios. | Homes appear here only when a landlord lists them on Renta MX. We do not copy listings from other sites or show fictional examples. |
| `zone.statNoData` | Sin dato oficial | No official data |
| `zone.mapCaption` | Punto de la cabecera municipal según el catálogo oficial de INEGI. No indica la ubicación de ninguna vivienda. | Municipal seat point from INEGI's official catalog… |

### 2.3 `/requisitos/$cveEnt` — Checklist legal

**Objetivo**: que el usuario sepa qué dicen las fuentes oficiales, tema por tema, y pueda comprobarlo.

Jerarquía:
1. H1 `requirements.title(estado)` + intro + selector "Cambiar de estado".
2. Aviso de cobertura (igual que en zona) si `solo_federal`.
3. Índice de categorías (chips/anclas con conteo) en el orden `MX_CATEGORY_ORDER` (lo que el inquilino necesita
   antes de firmar primero: forma, duración, depósito, fiador, incrementos…; fiscal/registro al final).
4. Por categoría (`<section>` con H2): dos subgrupos `level.stateSection(estado)` y `level.federalSection`
   (estatal primero, porque es lo específico). Cada requisito = `RequirementItem`:
   - checkbox local `requirements.markReviewed` (solo navegador, `requirements.checklistHint`),
   - badge de `kind` (`kind.ley`, `kind.reglamento`, `kind.norma`, `kind.practica` + `kind.practicaNotLaw`),
   - `title_*` (H3) + `summary_*`,
   - badge `fundamento.usedInContract` si `applies_to_contract`,
   - botón `fundamento.button` (abre panel, §3.4).
5. Toggle `kind.showPractice` (apagado por defecto): las prácticas de mercado se ocultan hasta que el usuario las pide.
6. Contador `requirements.reviewedCount(done, total)` fijo arriba en móvil; botón `requirements.print`.

Estados: categoría sin elementos ⇒ no se renderiza en la lista, pero en el índice aparece atenuada con
`category.empty` en tooltip/texto (honestidad: "no encontramos", no "no aplica"). Entidad sin requisitos ⇒
`requirements.empty`. 404 ⇒ `requirements.notFound`.

### 2.4 `/publicar` — Publicar vivienda

**Objetivo**: un arrendador publica en <3 min con datos verificables y sin exponer su domicilio.

Jerarquía (una sola página, 4 `fieldset` con legend): Ubicación · La vivienda · Condiciones · Sus datos.
Debajo: los dos consentimientos (`publish.truthfulnessConsent`, `publish.privacyConsent` con enlace
`publish.privacyBasisLink` a requisitos `datos_personales`), aviso `common.demoStorage`, botón `publish.submit`.

Validación (alineada con el spec): renta > 0 (`errRentPositive`), CP 5 dígitos (`errCp`, `inputmode="numeric"`,
`maxlength=5`), municipio de la lista (`errMunicipio`), email válido (`errEmail`), consentimientos (`errConsent`).
Validar al salir del campo y al enviar; nunca mientras escribe. Montos con `inputmode="decimal"` y el sufijo "MXN".
El depósito lleva `publish.depositHint` que enlaza a la categoría `deposito` del estado: la UI no sugiere montos.

Estados: enviando → botón deshabilitado + `publish.submitting`; error → `publish.errSubmit` (los datos se conservan);
422 → mapear errores pydantic a campos; éxito → panel `publish.successTitle` con `viewListing`, enlace copiable y `publishAnother`.

### 2.5 `/vivienda/$id` — Detalle de vivienda

**Objetivo**: decidir si iniciar un contrato con información completa y el contexto legal a un clic.

Jerarquía: breadcrumb/`listing.backToZone` → título + renta (`formatMXN`) grande → características (recámaras, baños,
m², amueblada, mascotas) en lista de definiciones → descripción → ubicación (colonia, municipio, estado;
`listing.exactAddressHidden`) → **caja lateral "Antes de rentar en {estado}"** (`listing.beforeRentingTitle`,
badge de cobertura, CTA `beforeRentingCta`) → bloque `listing.startContract` con `listing.startContractHelp`.
Badge `listingCard.userPublished` + fecha `listingCard.publishedOn`. Depósito rotulado como
`listing.requestedDeposit` (es lo que pide el arrendador, no un dato legal).

"Iniciar contrato" abre el formulario de 3 pasos (`contractForm.*`), con indicador `contractForm.stepLabel(n, 3)`,
botones Atrás/Continuar, y validación por paso. Paso 3 muestra resumen editable + `contractForm.generatedHow`.
Estados: generando → `contractForm.generating`; error → `contractForm.errGenerate` (datos conservados); 422 de reglas
legales → el mensaje de la API se muestra junto al campo (`errApiField`) con su "Ver fundamento" si trae requirement id.
404 vivienda → `listing.notFound` + `listing.notFoundCta`.

### 2.6 `/contrato/$id` — Revisión y firma

**Objetivo**: que cada parte lea, entienda qué firma y firme con consentimiento informado; y que cualquiera pueda
comprobar después qué se firmó.

Jerarquía (desktop: 2 columnas; contenido 2/3, panel de estado 1/3 *sticky*; móvil: panel arriba, colapsable):
1. H1 `contract.title` + badge de estado (`contract.status.*`) + `contract.signaturesProgress(done, total)`.
2. **Banner de invalidación** si aplica (§4.4), por encima de todo.
3. Panel "Partes y firmas": por rol → nombre, estado (`sigSigned(fecha)` / `sigPending` / `sigInvalidated`).
   Huella del contrato `contract.hashShort(shortHash(sha))` con botón para ver/copiar completa y `contract.hashHelp`.
4. Acciones: `contract.copyLink` (con `contract.shareBody`), `contract.print`, `evidence.download`.
5. Texto del contrato: cláusulas numeradas (`contract.clauseNumber(n)`), cada una con disclosure
   `contract.clauseBasis` que lista sus `requirement_ids` → "Ver fundamento". Sin requirement ids ⇒ `contract.clauseNoBasis`.
6. Anexo `contract.legalBasisTitle` (de `legal_basis`), con citas literales.
7. Sección de firma (§4) al final del texto, más un botón "Firmar" en el panel que hace scroll/foco a ella.
8. Constancia (§4.5) cuando hay ≥1 firma.

Estados: 404 → `contract.notFound`; todos firmaron → panel verde `contract.allSignedTitle` + `allSignedBody` y la
sección de firma se oculta; el contrato se re-consulta al volver a la pestaña (`refetchOnWindowFocus`) para reflejar
firmas de otras partes.

### 2.7 `/fuentes` — Transparencia

**Objetivo**: que cualquiera audite de dónde sale cada dato.

Jerarquía: H1 + intro → "Cómo verificamos" (5 pasos `sources.howSteps`) → filtro por jurisdicción → tabla
(`Table` de shadcn; en móvil, lista de tarjetas) con documento, publicador, jurisdicción, fecha de consulta,
SHA-256 (8 caracteres + copiar completo), enlace externo → sección `sources.noStateSourcesTitle` con los estados `solo_federal`.
Cada fila tiene `id={doc_id}` para que los enlaces desde cifras/fundamentos aterricen ahí (`/fuentes#D-MX-INEGI-01`).
Estados: vacío → `sources.empty`; error → `StateMsg`.

---

## 3. Incertidumbre y honestidad de datos

### 3.1 Tres tipos de información, tres tratamientos

| Tipo | Origen | Tratamiento visual | Nunca |
|---|---|---|---|
| **Requisito legal** (`kind: ley/reglamento/norma`) | `/mx/requirements` | Tarjeta con badge de kind (sólido, `primary`), título, resumen, "Ver fundamento" | Mostrar sin cita; parafrasear en la UI |
| **Práctica de mercado** (`kind: practica`) | idem | Oculta por defecto; borde punteado, badge `kind.practica` + `kind.practicaNotLaw`, nota `kind.practicaHelp` | Mezclarla en la misma lista sin marca; usar color de "ley" |
| **Dato estadístico** (INEGI) | `/mx/zones…` `stats` | Número grande + etiqueta + línea de fuente y año | Mostrar un número sin `source`/`year`; redondear a "aprox." |

### 3.2 "Sin fuente estatal verificada"

- Badge en cada tarjeta de estado y en el H1 de zona/requisitos: `coverage.federalOnly` (gris/ámbar suave, icono de información, no de alerta).
- Aviso expandido una vez por página: `coverage.federalOnlyTitle(estado)` + `coverage.federalOnlyBody`.
- En el contrato de un estado `solo_federal`, el mismo aviso aparece en el paso 3 de "Iniciar contrato" y arriba del anexo legal.
- Lenguaje: "todavía no hemos verificado", nunca "no existe ley" ni "no hay requisitos".

### 3.3 Cada cifra INEGI con fuente y fecha

Formato de tarjeta de indicador:

```
Viviendas particulares habitadas         ← zone.stat.<clave>
  123,456                                ← formatInt(value) — valor real de la API
  Fuente: <título corto del doc> (2020) ↗ ← zone.statSource(doc, year); enlace a /fuentes#doc_id
  Consultado el 3 de octubre de 2026     ← common.retrievedOn(fecha) desde /mx/sources por doc_id
```

El título del documento y `retrieved_at` se resuelven cruzando `source` (doc_id) con `/mx/sources` (cachear con
`staleTime: Infinity`). Si el doc_id no está en el manifiesto ⇒ no mostrar la cifra (y reportarlo en consola: es un bug de datos).

### 3.4 "Ver fundamento" (panel)

Componente reutilizable `FundamentoSheet` (patrón de `WhyDrawer.tsx`: `Sheet` derecha en desktop, abajo en móvil).
Contenido en este orden:

1. Título del requisito + badges (nivel `level.federal|estatal`, kind).
2. `fundamento.plainSummary`: `summary_*` + nota pequeña `fundamento.summaryCaveat`.
3. `fundamento.citation`: `citation` en negritas.
4. `fundamento.quoteLabel`: `<blockquote lang="es">` con la `quote` **exacta** (sin recortar, sin cambiar comillas,
   sin traducir; en EN añadir `fundamento.quoteLangNote`). Debajo, con icono de check: `fundamento.quoteVerified`.
5. Documento: título, `fundamento.publisher`, `common.retrievedOn(fecha)`, `common.lastReform(fecha)` si existe,
   `common.openSource` ↗ (`target=_blank` + `common.openInNewTab` para lector de pantalla), enlace a `/fuentes#doc_id`.
6. `fundamento.requirementId`: id en monoespaciada, copiable (útil para soporte y para The Tester).

Si la carga falla: `fundamento.loadError` + reintentar. Nunca mostrar el resumen sin la cita.

### 3.5 Disclaimer

Siempre visible en el footer fijo existente (`Shell.tsx`) con `common.disclaimer`. Además, una etiqueta corta
`common.notAdvice` junto a: checklist de requisitos, paso 3 del contrato, sección de firma y constancia impresa.

---

## 4. Flujo de firma

### 4.1 Antes de firmar (en `/contrato/$id`, sección "Firmar el contrato")

Orden de la sección (un solo `form`, sin pasos ocultos):

1. **Recordatorio**: `sign.readFirst` con enlace "Ir al inicio del contrato". No forzamos scroll hasta el final
   (antipatrón de accesibilidad); el consentimiento cubre la lectura.
2. **Caja de alcance** (`sign.scopeTitle`), siempre visible, no colapsada:
   - `sign.scopeBody` — describe lo que la demo **hace** (hechos del producto, no del derecho).
   - `sign.scopeNotIncluded` — lo que la demo **no** emite (e.firma SAT, constancia NOM-151 de un PSC).
   - Enlace `sign.scopeLegalLink` → abre un `FundamentoSheet` en modo lista con **todos los requisitos de
     `category: firma_electronica`** (federal + estatal) que devuelva `/mx/requirements?cve_ent=…`. Ahí, y solo ahí,
     se explica el alcance legal, con cita literal.
   - Si la API no devuelve ningún requisito `firma_electronica` ⇒ en vez del enlace se muestra `sign.scopeNoSource`.
   - La UI **no** usa frases como "tiene plena validez", "equivale a firma autógrafa" o "fuerza probatoria":
     cualquier afirmación así debe venir del `summary_*` de un requirement id.
3. **Rol** (`sign.roleLegend`, `RadioGroup`): roles requeridos del contrato; los ya firmados aparecen deshabilitados con
   `sign.roleAlreadySigned`. Si el enlace trae `?rol=fiador`, se preselecciona.
4. **Nombre y correo**: `sign.fullName` + `sign.fullNameHint`. Si no coincide con el registrado para ese rol, aviso
   en línea `sign.nameMismatch(esperado)` (el backend decide si bloquea).
5. **Método** (`sign.methodLegend`, `RadioGroup`/`ToggleGroup`): `sign.methodDraw` | `sign.methodType`.
6. **Firma** (§4.3).
7. **Consentimiento**: `Checkbox` **desmarcado por defecto**, texto `sign.consent(shortHash)` — liga explícitamente la
   firma a la versión. No se puede enviar sin él (`sign.errConsent`), y se envía `consent: true` solo si se marcó.
8. Botón `sign.submit` → diálogo de confirmación (`AlertDialog`): `sign.confirmTitle`, `sign.confirmBody(rol, hash)`,
   `sign.confirmYes` / `sign.confirmNo` (este último es el foco inicial, para evitar firmas accidentales).

### 4.2 Envío y respuestas

- Durante el POST: `sign.signing`, formulario deshabilitado, sin reintento automático.
- 200 → toast + región viva `sign.signed`; si faltan partes, `sign.remaining(n)` y se resalta "Comparta este contrato".
- 409 (rol ya firmado) → `sign.errConflict(rol)` y se recarga el estado de firmas.
- Hash distinto al que el usuario vio (el backend responde que el contrato cambió) → `sign.errHashChanged` + botón
  recargar; **no** se conserva el trazo (debe volver a firmar consciente de la nueva versión).
- 422 (firma demasiado grande, email inválido, etc.) → error en el campo (`sign.errTooLarge`, `publish.errEmail`).
- Otro error → `sign.errSubmit` ("No se firmó nada"): la certeza de que no quedó a medias reduce ansiedad.

Recomendación al backend (vía The Designer/Frontend): enviar en el POST el `sha256` que el usuario tenía en pantalla
para que la API detecte el cambio de versión en vez de firmar silenciosamente la nueva.

### 4.3 Trazo y alternativa tecleada (accesibilidad)

- **Dibujar**: `<canvas>` con `role="img"` y `aria-label={sign.canvasLabel}`, instrucciones visibles
  `sign.canvasInstructions` enlazadas por `aria-describedby`; soporta pointer events (dedo, mouse, lápiz),
  `touch-action: none`; botones `sign.undo` y `sign.clear`. Altura mínima 160 px, borde y línea base de guía.
- **Escribir**: `Input` `sign.typedLabel` (prellenado con el nombre), vista previa `sign.typedPreview` en fuente
  manuscrita; la vista previa se rasteriza a PNG en un canvas oculto ⇒ mismo `signature_png_base64`. En el copy se
  aclara que "tiene la misma función en esta demo" — así nadie se siente forzado a dibujar.
- El método "Escribir" es el **primero en el orden de tabulación** cuando se detecta navegación por teclado y siempre
  lleva el hint `sign.methodTypeHint`.
- Validar antes de enviar: firma vacía → `sign.errEmptySignature`; tamaño > límite → `sign.errTooLarge`.

### 4.4 Qué pasa si el contrato cambia después de firmar

La regla del spec ("hash cambia ⇒ firmas previas se invalidan") se comunica en 4 lugares:
1. En el consentimiento (`sign.consent(hash)`) y en el diálogo (`sign.confirmBody`) — **antes** de firmar.
2. Banner `contract.changedTitle` + `contract.changedBody` (rojo, `role="alert"`) cuando hay firmas inválidas,
   con comparación `contract.signedHash` vs `contract.currentHash` (8 caracteres cada uno, mismo formato).
3. En la lista de partes, cada firma afectada muestra `contract.sigInvalidated` tachada visualmente **y** con texto.
4. En la constancia, cada firma marca `evidence.valid` o `evidence.invalid`.

### 4.5 Constancia

Sección "Constancia de firma" (`evidence.title`) con `evidence.intro` arriba (deja claro que no es NOM-151).
Por firma: rol, nombre, correo enmascarado (`m***@dominio.mx`), `evidence.signedAtUtc` (ISO) **y**
`evidence.signedAtLocal` (formateado), `evidence.signatureHash`, `evidence.userAgent` (colapsable),
`evidence.consentRecorded`, estado válida/anulada. Al pie: `evidence.contractHash` completo con copiar,
`evidence.verifyHint`, botones `evidence.download` (JSON de `/evidence`) y `contract.print`.
Vacío: `evidence.empty`.

### 4.6 Impresión

Vista `@media print`: oculta header, nav, footer fijo, banners y botones; muestra título, estado, huella completa,
partes, cláusulas, anexo legal (con URLs impresas en texto, no solo enlaces), imágenes de firma y constancia, y el
disclaimer al final. Pie de página con `contract.hashShort` en cada hoja. `contract.printHint` junto al botón.

---

## 5. Copy (`frontend/src/lib/mx-i18n.ts`)

- `mxCopy: Record<"es"|"en", MxCopy>`; `MxCopy = typeof es`, por lo que el compilador exige las mismas claves en EN.
- Agrupado por sección (`common`, `coverage`, `level`, `kind`, `category`, `fundamento`, `landing`, `zone`,
  `listingCard`, `requirements`, `publish`, `listing`, `contractForm`, `contract`, `sign`, `evidence`, `sources`) y
  `listingsCount(n)` en la raíz. Cadenas con datos variables son funciones (`zone.statSource(doc, year)`).
- Helpers: `getMxCopy(lang)`, `MX_CATEGORY_ORDER`, `formatMXN`, `formatInt`, `shortHash`. Fechas: usar `formatDate` de `lib/dates.ts`.
- Integración sugerida: añadir `mx: getMxCopy(lang)` al contexto de `I18nProvider` (o un hook `useMx()`), y que el
  idioma por defecto sea `es` en las rutas MX.
- **No contiene** artículos, montos, plazos ni porcentajes. Lo único normativo que se nombra es lo que el spec ordena
  decir que la demo **no** emite (e.firma SAT, NOM-151), sin atribuirle efectos legales.
- Los textos de la API (`title_*`, `summary_*`, `citation`, `quote`, mensajes 422) se muestran tal cual, sin reescribir
  (misma regla que `frontend/AGENTS.md`).

Glosario fijo (usar siempre así):

| ES | EN | Nota |
|---|---|---|
| Arrendador (propietario) | Landlord (arrendador) | primera mención con paréntesis, luego solo "arrendador" |
| Arrendatario (inquilino) | Tenant (arrendatario) | en UI general preferir "inquilino" |
| Fiador | Guarantor (fiador) | |
| Fundamento | Legal basis | nunca "prueba" ni "evidencia" |
| Huella digital (SHA-256) | Fingerprint (SHA-256) | |
| Constancia de firma | Signature record | evitar "certificado" (connotación legal) |
| Marco federal / estatal | Federal / state framework | |
| Práctica de mercado | Market practice | siempre acompañado de "No es ley" |

---

## 6. Recomendaciones priorizadas para The Designer

**P0 — imprescindible para la demo**
1. **`FundamentoSheet`** reutilizable (basado en `WhyDrawer.tsx`) usado en requisitos, cláusulas, firma y datos personales. Blockquote con `lang="es"`, cita sin truncar.
2. **`CoverageBadge` + `CoverageNotice`** (verificado / solo federal). Tono informativo: tokens `applies` para verificado y `unknown-soft` para solo federal. Icono + texto, nunca solo color.
3. **`EmptyState`** honesto (icono, título, cuerpo, CTA) para viviendas; prohibido renderizar skeletons o tarjetas "fantasma" cuando la respuesta es una lista vacía.
4. **`SignaturePad`** con pestañas Dibujar/Escribir, misma salida PNG; canvas con instrucciones, deshacer, borrar; targets ≥44 px.
5. **`SignScopeBox`** fija sobre el formulario de firma + `AlertDialog` de confirmación con foco inicial en "Volver a revisar".
6. **`ContractStatusPanel`** sticky (estado, progreso, partes, huella, acciones) y **banner de invalidación** con `role="alert"`.
7. **Header nuevo** "Renta MX" (Buscar zona / Publicar / Fuentes / idioma), idioma por defecto ES, `/us` en el pie. Mantener el banner `waking` y el footer de disclaimer existentes.

**P1 — jerarquía y claridad**
8. **`RequirementItem`** con jerarquía: badge kind → título (H3, sans) → resumen → fila de acciones (Lo revisé · Ver fundamento · "Se usa en el contrato"). Práctica de mercado con borde punteado y badge contrastado distinto de ley.
9. **`StatCard`**: valor en `text-3xl` tabular-nums, etiqueta arriba, línea de fuente `text-sm text-muted-foreground` con enlace. "Sin dato oficial" en itálica atenuada, nunca "0" ni "—" a secas.
10. **`ListingCard`**: renta como dato principal, luego recámaras/baños/m², colonia·municipio, badge "Publicada por su arrendador" + fecha. Sin imágenes en la demo: usar bloque de color/icono, no fotos de stock (serían engañosas).
11. **Stepper** de "Iniciar contrato" (3 pasos) con `aria-current="step"` y resumen editable en el paso 3.
12. Tipografía del contrato: Merriweather (serif existente) para el cuerpo de cláusulas, ancho máximo ~70 caracteres, numeración visible; Public Sans para la UI alrededor.

**P2 — accesibilidad (WCAG 2.2 AA)**
13. Combobox de municipio replicando el patrón ARIA de `AddressSearch` (role combobox/listbox, flechas, Enter, Escape) y `aria-live` con número de resultados.
14. Formularios: `label` visible siempre (no solo placeholder), errores con `aria-invalid` + `aria-describedby`, resumen de errores con foco al enviar, `autocomplete` (`name`, `email`, `postal-code`), `inputmode` numérico.
15. Estados nunca solo por color (verde/ámbar/rojo + icono + texto). Contraste ≥4.5:1 en badges `*-soft`.
16. Foco visible (ya existe `:focus-visible` de 3 px) y orden de tabulación lógico en el panel sticky; los `Sheet` atrapan foco y lo devuelven al botón que los abrió.
17. Huellas SHA-256: mostrar 8 caracteres agrupados (`shortHash`) y `aria-label` con el hash completo; botón copiar con confirmación `common.copied` en región viva.
18. Enlaces externos con ↗ visible y `common.openInNewTab` para lector de pantalla.
19. `prefers-reduced-motion`: sin animación en banners de error/invalidación ni en el trazo.

**P3 — pulido**
20. Hoja de impresión del contrato (§4.6) y de la checklist de requisitos.
21. Anclas profundas (`/fuentes#doc_id`, `/requisitos/$cveEnt#deposito`) para enlazar desde cifras y cláusulas.
22. Checklist "Lo revisé" persistido en `localStorage` con try/catch (conveniencia por visitante, no estado crítico).
