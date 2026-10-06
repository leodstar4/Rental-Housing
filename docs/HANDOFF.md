# Traspaso — Renta MX (para otra IA o persona)

Copia este archivo completo como primer mensaje a la IA que continúe el trabajo.

## 1. Qué es el proyecto

Renta MX: marketplace de arrendamiento de casa habitación en México (foco CDMX, `cve_ent=09`).
El usuario busca vivienda por zona en un mapa y un buscador, ve precios y requisitos legales con
cita literal verificada, y genera y firma un contrato en la app.

- Repo (monorepo, un solo `.git` en la raíz): `github.com/leodstar4/Rental-Housing`
- Ruta local: `C:\Users\Leo\Documents\hacknation1` (Windows, PowerShell)
- Backend: Python, FastAPI. Lógica determinista en `mx/`, router en `api/mx.py`, montado en `api/main.py`.
- Frontend: `frontend/`, con TanStack Start, React 19, Tailwind v4 y shadcn. Es la fuente de verdad.
  Lovable queda solo como demo. No quitar `@lovable.dev/vite-tanstack-config`: el build depende de él.
- El código de EE. UU. (`extractor/`, `resolver/`, rutas US) está congelado. Ver `docs/US_LEGACY.md`.

## 2. Regla cero (no negociable)

- No hay datos inventados. Cada cifra, coordenada o requisito tiene su fuente en `corpus_mx/manifest_*.json`
  (url, retrieved_at, sha256, text_sha256).
- Cada requisito lleva una cita literal que verifica `python -m mx.verify`. Si una cita no verifica, no se exporta.
- No hay anuncios inventados ni scraping de portales. Si no hay datos, se muestra un estado vacío honesto.
- Ley, práctica de mercado y dato estadístico se muestran con tratamientos visuales distintos.
- Una entidad sin código civil verificado se marca `solo_federal`.
- La firma es una firma electrónica **simple**. No se puede afirmar que sea "avanzada", "certificada",
  "NOM-151", "e.firma" ni que dé "fecha cierta", salvo para negarlo.
- El runtime no usa LLM ni red: `mx/*.py` y `api/mx.py` no importan SDKs de modelos ni clientes HTTP.

## 3. Estado: qué se hizo (rama `feature/renta-mx-fases`, SIN commit todavía)

| Fase | Hecho | Archivos clave |
|---|---|---|
| 0 Fundaciones | El build de `render.yaml` solo corre `pip install` y `mx.verify`. La API US devuelve 503 limpio si falta `out/`. CORS acepta `*.pages.dev`. `SqlStore` (SQLite/Postgres) se elige con `DATABASE_URL`; sin esa variable se usa el JSON efímero de antes. Docs de deploy. | `render.yaml`, `api/main.py`, `mx/store.py`, `requirements.txt` (`psycopg[binary]==3.3.6`), `docs/DEPLOY.md`, `docs/US_LEGACY.md`, `frontend/README.md` |
| 1 Mapa | MapLibre con tiles OSM sin API key. Solo pinta zonas que tienen `coord.source`; el resto se lista como "Sin coordenada oficial". La lista accesible está sincronizada con el mapa, y hay buscador sin acentos. | `frontend/src/components/mx/MxMap.tsx`, `routes/mapa.tsx`, `routes/index.tsx`, `routes/zona.$cveEnt.$cveMun.tsx`, `components/Shell.tsx` |
| 2(a) Precios | `listing_price_summary` es determinista y calcula min/mediana/max solo con 3 o más anuncios reales. La UI separa tres cosas: precio de anuncios, % de viviendas alquiladas (INEGI) y requisitos legales. | `mx/prices.py`, `api/mx.py`, `routes/zona...tsx` |
| 3 Contrato y firma | Enlace por rol `/contrato/{id}?rol=X#t=<token>`: el token va en el hash y se limpia de la URL al leerlo. `SignaturePad` permite dibujar o escribir la firma. Incluye caja de alcance de la firma simple, panel de estado, mapeo de errores 403/409/422, CSS de impresión/PDF y descarga de la constancia. | `components/mx/SignaturePad.tsx`, `lib/mx-sign.ts`, `routes/contrato.$id.tsx`, `styles.css`, `lib/mx-i18n.ts` |
| 4 Cobertura | Códigos civiles nuevos verificados: **GTO, DGO, CHIH**. Ahora son 11 de 32 entidades: CDMX, JAL, NL, MEX, QRO, PUE, YUC, QROO, GTO, DGO y CHIH. `SqlStore` queda listo para Postgres. | `corpus_mx/estados/{GTO,DGO,CHIH}/`, `corpus_mx/manifest_estados.json`, `data/mx/requirements/{GTO,DGO,CHIH}.yaml` |
| Pruebas | Batería adversarial de las fases nuevas, paridad entre JSON y SQL, precios, tolerancia US y pruebas del frontend (mapa, bloque de precio, firma). | `tests/test_mx_fases_adversarial.py`, `tests/test_mx_store_sql.py`, `tests/test_mx_prices.py`, `tests/test_us_tolerance.py`, `frontend/src/test/mx-*.test.tsx` |

Verificado al cerrar:
- `python -m pytest -q` → **429 passed**
- `python -m mx.verify` → **ok=True, 229/229 citas, 85/85 documentos** (268 warnings, que no bloquean)
- `cd frontend; bun run build` → OK (preset de Cloudflare)
- `cd frontend; bun run test` → **22 passed (5 archivos)**
- El grep de red/LLM en `mx/*.py` y `api/mx.py` no encuentra nada.
- Veredicto del arquitecto: APROBADO, sin bloqueantes.

## 4. Dónde me quedé / qué falta

1. **Commit y push**: todavía no se hicieron. Antes, revisar `git status` y agregar los archivos de forma
   explícita (no `git add .`; `.env` existe y no debe subirse).
2. **Deploy real (manual, lo hace el dueño)**:
   - Render: conectar el repo y usar `render.yaml`.
   - Cloudflare **Workers** (el build es preset `cloudflare-module`, no Pages): root `frontend`, build
     `bun install && bun run build`, deploy `npx wrangler deploy`, variable de build `VITE_API_BASE=https://<servicio>.onrender.com`.
   - Añadir la URL exacta `https://<worker>.<cuenta>.workers.dev` a `ALLOWED_ORIGINS` en Render (el regex CORS no cubre workers.dev).
   - Detalle completo en `docs/DEPLOY.md`.
3. **Las otras 21 entidades** siguen en `solo_federal`. Se agregan con el mismo patrón que GTO/DGO/CHIH:
   descargar la fuente oficial, calcular sha256 y text_sha256, escribir el YAML con la cita literal y correr `mx.verify`.
4. **Precio oficial (Fase 2b)**: no hay fuente oficial de renta descargada. Si se agrega una (SHF/INEGI), debe
   registrarse en un manifiesto y verificarse. Nunca se debe scrapear.
5. **Identidad y titularidad**: solo está diseñado y declarado como ausente. Falta un OTP por email y la
   verificación de titularidad.
6. **Mejoras pendientes del arquitecto** (no bloquean):
   - `SqlStore` y el rate limit funcionan en memoria por proceso. Con más de un worker, mantener `--workers 1`
     o mover los límites (caps) a la base de datos.
   - Para producción, cambiar los tiles de `tile.openstreetmap.org` por un proveedor con términos claros.
     Ver `docs/MX_COST_REVIEW.md`.

## 5. Cómo usar los agentes (`.kiro/agents/*.json`)

| Agente | Rol | Escribe código |
|---|---|---|
| `the-planner` | Convierte metas en fases con criterios de aceptación | No |
| `the-architect` | Critica el diseño; termina con `VEREDICTO: APROBADO` o `NEEDS_FIXES` | No |
| `the-implementor` | Implementa y verifica con pruebas | Sí |
| `the-tester` | Escribe pruebas adversariales que exponen fallos; no arregla el código de producción | Sí (solo pruebas) |
| `the-designer` | Frontend UI/UX (React/Tailwind/shadcn) | Sí |
| `the-ux` | Copy y flujos (`mx-i18n.ts`), lenguaje claro | Sí (copy) |
| `the-budgeter` | Costos (tokens, hosting, bundle) | Sí (docs/optimizaciones) |

Pipeline que funcionó (subagentes en Kiro CLI):
`planner → implementor/designer (en paralelo si tocan archivos distintos) → tester → implementor (correcciones) → ux → budgeter → architect`.
Hay dos bucles: tester → correcciones si aparece `VEREDICTO: NEEDS_FIXES`, y architect → correcciones si aparece
`VEREDICTO: NEEDS_FIXES`.

Instrucciones que conviene repetir a cada agente: rama `feature/renta-mx-fases`, PowerShell, no hacer
commit/push, tocar solo los archivos de su alcance, pinear dependencias, respetar la regla cero y reportar
números reales de las cuatro verificaciones (sección 3).

Desde Kiro CLI, por ejemplo: `kiro-cli chat --agent the-implementor` y pegar la tarea más este archivo.
Con otra IA sin agentes, dale este archivo y pídele que actúe como cada rol en el orden del pipeline.
