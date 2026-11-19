# AlphaConsensus

> Consenso ponderado de traders y analistas de X (Twitter) para **paper trading** con validación estadística.
> Fase 0 completa: el pipeline entero corre de punta a punta con datos sintéticos, sin API keys y sin dinero.

📄 **Resultados de la investigación y análisis de viabilidad:** [report.md](report.md) (en inglés).


---

## ⚠️ Aviso

- Esto **no es asesoría financiera**. Es infraestructura de investigación.
- El demo usa **precios y tuits sintéticos**. Las cuentas "buenas" del demo conocen el futuro *por construcción*: sirve para validar el pipeline, **no** para inferir que la estrategia gana dinero.
- El scraping de X vía terceros (Apify y similares) **viola los Términos de Servicio de X**. Úsalo como puente de investigación, no como base de un producto comercial sin datos licenciados. Ver [Datos de X](#datos-de-x).

---

## Qué hay hoy

| Fase | Estado | Qué incluye |
|---|---|---|
| **0 — Esqueleto** | ✅ | Repo, modelos, config, SQLite, CLI, tests, demo end-to-end |
| **1 — Datos y credibilidad** | 🟡 | Scoring bayesiano, conector real de divulgaciones del Congreso (Bargo, ~3 meses). Falta histórico de tuits y años de divulgaciones |
| **2 — Ingesta y parsing** | 🟡 | Adaptadores Apify y X API, filtro de ruido, parser de reglas + capa LLM lista. Falta correr contra datos reales |
| **3 — Simulación** | 🟡 | Consenso, riesgo, simulador, métricas, ablation. Alpaca paper **conectado y verificado** (smoke test de orden real). Falta el bucle en vivo |

El demo imprime, en un solo comando:

```
tweets → filtro → señales → pesos por cuenta → señales de consenso → trades → P&L
```

y además una **ablación**: la misma estrategia con todos los votos iguales, para ver si la capa de credibilidad aporta algo o es decorativa.

---

## Quickstart

Requiere Python ≥ 3.9. **Cero dependencias** para el core (stdlib pura).

```bash
git clone <repo> && cd AlphaConsensus

make demo          # pipeline completo con datos sintéticos (~2 s)
make test          # 81 tests, sin dependencias

# promedio sobre 20 seeds (un solo seed no es evidencia)
PYTHONPATH=src python3 -m alphaconsensus robustness --seeds 20
```

Salida esperada del demo: periodo de 40 sesiones, tabla de credibilidad por cuenta, señales de consenso, operaciones, métricas de riesgo y la ablación.

Opciones útiles:

```bash
PYTHONPATH=src python3 -m alphaconsensus demo --seed 13   # otro escenario
PYTHONPATH=src python3 -m alphaconsensus demo --json      # reporte completo en JSON
PYTHONPATH=src python3 -m alphaconsensus accounts         # inspeccionar whitelist
PYTHONPATH=src python3 -m alphaconsensus paper            # verificar Alpaca paper (solo lectura)
PYTHONPATH=src python3 -m alphaconsensus paper --smoke-test  # compra ~$1 de SPY y la cierra
PYTHONPATH=src python3 -m alphaconsensus congress --member Pelosi  # divulgaciones STOCK Act (3 meses)
PYTHONPATH=src python3 -m alphaconsensus house    # PTRs oficiales 2024-2026 (gratis, histórico)
PYTHONPATH=src python3 -m alphaconsensus congress-score  # credibilidad desde la divulgación
PYTHONPATH=src python3 -m alphaconsensus x-history   # timelines de X → pesos de credibilidad
```

Artefactos: `data/alphaconsensus.db` (SQLite) y `data/demo_report.json`.

---

## Arquitectura

```
  [X API v2 / Apify]
         │ tweets crudos
         ▼
  ┌──────────────┐  RT, replies, spam, duplicados, links
  │   Ingesta    │─────────────────────────────────────▶ descartado
  └──────┬───────┘
         ▼
  ┌──────────────┐  ticker, dirección, horizonte, confianza
  │ NLP          │  (reglas deterministas o LLM con JSON schema)
  └──────┬───────┘
         ▼
  ┌──────────────┐  hit rate vs SPY + exceso medio → peso 0..1
  │ Credibilidad │◀──── precios históricos (synthetic | yfinance)
  └──────┬───────┘
         ▼
  ┌──────────────┐  quórum ponderado + ventana + cooldown
  │   Consenso   │
  └──────┬───────┘
         ▼
  ┌──────────────┐  liquidez, ATR, sizing, límites, kill switch
  │    Riesgo    │
  └──────┬───────┘
         ▼
  ┌──────────────┐
  │  Ejecución   │──▶ simulador interno | Alpaca paper
  └──────────────┘
         │
         └──▶ SQLite: tweets, señales, pesos, consenso, trades, equity
```

### Estructura

```
config/
  settings.json      # umbrales de consenso, riesgo, NLP, backtest
  accounts.json      # whitelist semilla (handles ficticios demo_*)
  universe.json      # tickers válidos + blacklist de acrónimos
src/alphaconsensus/
  models.py          # Tweet, TradingSignal, ConsensusSignal, Trade…
  config.py          # carga tipada + lector de .env
  ingestion/
    mock.py          # generador sintético determinista (skill oculta por cuenta)
    apify.py         # adaptador Apify (histórico)
    x_api.py         # adaptador X API v2 (tiempo real)
    congress.py      # divulgaciones STOCK Act (Bargo, ~3 meses gratis)
    house_clerk.py   # PTRs oficiales de la Cámara (histórico gratis, 2024-2026)
    pipeline.py      # filtro de ruido y deduplicación
  nlp/
    tickers.py       # cashtags + símbolos desnudos con guardrails
    rules.py         # parser de reglas (baseline sin coste)
    llm.py           # parser LLM con salida JSON estructurada
    service.py       # fachada, caché, fallback
  credibility/
    prices.py        # mercado sintético + yfinance
    alpaca_bars.py   # barras diarias históricas vía Alpaca (IEX)
    scorer.py        # hit rate, exceso vs SPY, shrinkage bayesiano
    congress_scorer.py  # dos relojes: transacción vs divulgación + t-stat
  consensus/engine.py
  risk/engine.py
  execution/
    simulator.py     # fills, stops, targets, horizonte, equity
    alpaca.py        # órdenes market contra paper-api
  backtest/
    runner.py        # replay end-to-end + ablación
    metrics.py       # Sharpe, drawdown, profit factor…
  storage/db.py
  cli.py
docs/whitelist.md    # rúbrica + candidatos Congreso/X con datos reales
tests/               # 81 tests (unittest, stdlib)
```

---

## Cómo decide el sistema

### 1. Extracción de señal

- **Ticker**: cashtags (`$NVDA`) siempre; símbolos sin `$` solo si están en `config/universe.json`. URLs eliminadas antes. Blacklist para `$CEO`, `$USD`, `$AI`…
- **Dirección**: léxico financiero con manejo de negaciones (`"not bullish"` no cuenta).
- **Horizonte**: intraday 1d, swing 5d, mes 21d, largo plazo 60d; configurable.
- **Confianza**: fuerza de la señal + cashtag + target explícito + verbo de acción − hedging.
- **Ruido**: RT, replies, promos, tweets cortos y sin dirección se descartan antes del consenso.

### 2. Credibilidad (el filtro que evita el ruido)

Para cada cuenta, sobre su historial:

```
exceso_i   = dirección_i × (retorno_ticker_i − retorno_SPY_i)   # ventana del horizonte
hit        = 1 si exceso_i > 0
hit_rate   = hits / n
shrunk     = (hits + 4×0.5) / (n + 4)                            # Beta(4,4) prior
reliability= clamp(2 × (shrunk − 0.5), 0, 1)                     # 0..1
magnitude  = tanh(exceso_medio / 4%)
peso       = reliability × (0.55 + 0.45 × magnitude)
```

Decisiones deliberadas:

- Se mide **exceso vs SPY**, no retorno absoluto: un permabull en un mercado alcista no obtiene crédito por beta.
- El prior castiga muestras pequeñas: 3 aciertos no superan a 60 mediocres.
- Una cuenta con edge negativo recibe **peso 0** (se silencia, no se invierte).
- Con `n < 20` el peso se descuenta: cuentas nuevas entran, pero no mandan.

### 3. Consenso

Una señal se dispara solo si, en la ventana (`window_minutes`):

- ≥ `min_accounts` cuentas distintas del lado ganador (un voto por cuenta, no por tweet),
- suma de pesos ≥ `min_weight`,
- el lado ganador tiene ≥ `min_agreement` del peso total (bloquea 51/49),
- el ticker no disparó en `cooldown_minutes`.

### 4. Riesgo

Tamaño por riesgo fijo: `qty = (equity × 1%) / (2 × ATR)`, tope por notional, stop y target por ATR, máximo de posiciones simultáneas, filtro de liquidez y volatilidad, y **kill switch** al superar el drawdown máximo.

---

## Whitelist: Congreso + X

La lista de candidatos, la rúbrica de selección y los datos reales de actividad están en [docs/whitelist.md](docs/whitelist.md). En resumen:

- **Los políticos no votan en el consenso de X**: no tuitean sus operaciones, las declaran con hasta 45 días de retraso. Son una fuente aparte, con su propio track record y su propio reloj (fecha de divulgación).
- **La fama no es actividad**: en la ventana de 3 meses, Pelosi tuvo 1 operación divulgada; Cisneros, Hern y Khanna superaron las 100.
- **Ninguna cuenta es "confiable" por decreto**: la rúbrica exige muestra, puntualidad y alpha medido desde la divulgación, no desde la transacción.

Ingesta de divulgaciones (sin API key, ventana ~3 meses):

```bash
PYTHONPATH=src python3 -m alphaconsensus congress --health
PYTHONPATH=src python3 -m alphaconsensus congress --chamber senate --limit 10
```

---

## Configuración

`config/settings.json` (valores por defecto):

| Clave | Valor | Significado |
|---|---|---|
| `consensus.window_minutes` | 1440 | ventana de agregación (24 h) |
| `consensus.min_accounts` | 3 | cuentas distintas mínimas |
| `consensus.min_weight` | 0.9 | peso mínimo del lado ganador |
| `consensus.min_agreement` | 0.65 | dominancia mínima |
| `consensus.cooldown_minutes` | 2880 | mute por ticker tras disparar |
| `risk.equity` | 1000 | capital de la cuenta paper |
| `risk.risk_per_trade_pct` | 1.0 | % de equity entre entrada y stop ($10) |
| `risk.max_position_pct` | 24 | tope por posición |
| `risk.max_open_positions` | 4 | posiciones simultáneas |
| `risk.allow_shorts` | false | perfil long-only |
| `risk.allow_fractional` | true | fracciones para longs (Alpaca) |
| `risk.min_notional` | 20 | tamaño mínimo por orden |
| `risk.stop_atr_mult` / `take_profit_atr_mult` | 2 / 4 | stops y targets |
| `risk.max_drawdown_pct` | 15 | kill switch |
| `nlp.mode` | `rules` | `rules` \| `llm` \| `hybrid` |
| `backtest.price_days` | 260 | historia de precios |
| `backtest.history_days` | 200 | historia para puntuar cuentas |
| `backtest.live_days` | 40 | ventana de replay |

`config/accounts.json` contiene **handles ficticios** (`demo_*`) para que el demo sea reproducible y no atribuya rendimientos falsos a personas reales. Sustitúyelos por tu whitelist real; el campo `weight_override` permite fijar un peso manual.

`config/universe.json` define los tickers aceptados sin cashtag y la blacklist de acrónimos.

### Perfil operativo: cuenta paper de $1,000

Con $1,000 el sizing por acciones enteras no funciona: un riesgo del 1% son $10, y un stop de 2×ATR sobre una acción de $300 ronda los $15, así que `int()` deja la orden en cero. Por eso el perfil activo es:

- **fracciones** para longs (Alpaca las soporta en órdenes market);
- **sin shorts** (Alpaca no permite fracciones en cortos y 1 acción de QQQ sería ~50% de la cuenta);
- **máximo 4 posiciones** al 24% cada una (≤96% de exposición);
- **mínimo $20** por orden, para no generar polvo.

Consecuencia visible: las señales de consenso bajistas se registran pero el motor de riesgo las rechaza con `shorts_disabled`. El sistema es long-only hasta que subas el capital o habilites shorts con acciones enteras.

Verificado contra Alpaca paper: `ACTIVE`, `multiplier=1` (cuenta cash, sin margen), `shorting_enabled=false`, 0 posiciones. El smoke test (`paper --smoke-test`) compra ~$1 de SPY, espera el fill, cierra la posición y deja la cuenta plana; rechaza ejecutarse si el mercado está cerrado o si ya hay una posición en el símbolo.

---

## Datos de X

### Opción A — Apify (recomendada para el histórico)

El problema del histórico: la búsqueda de la API oficial de X en los planes baratos solo cubre ~7 días y ~10k lecturas/mes. Eso **no alcanza** para puntuar 12–24 meses de llamadas por cuenta.

Apify resuelve el histórico a un coste bajo (precios de Apify Store, consultados 2026-11):

| Actor | Precio | Uso |
|---|---|---|
| `apidojo/tweet-scraper` (V2) | ~$0.40 / 1.000 tweets | búsqueda avanzada, filtros de fecha |
| `apidojo/twitter-scraper-lite` | ~$0.016/query + ~$0.0004/item | barato para perfiles y búsquedas |
| `kaitoeasyapi/...` (cheapest) | ~$0.18–0.25 / 1.000 tweets | volumen |

Fuentes: [Apify Tweet Scraper V2](https://apify.com/apidojo/tweet-scraper), [comparativa de precios 2026](https://use-apify.com/docs/best-apify-actors/best-twitter-scrapers), [pricing de referencia](https://twexapi.io/compare/apify-vs-twexapi).

**Coste estimado de la Fase 1**: 20 cuentas × ~500 tuits históricos = 10.000 tuits ≈ **$4**; 24 meses de actividad (≈30k tuits) ≈ **$12–15**. El plan Starter de Apify ($19/mes) incluye ese consumo.

```bash
cp .env.example .env       # añade APIFY_TOKEN
PYTHONPATH=src python3 -m alphaconsensus ingest --source apify \
  --handle demo_semis --since 2025-01-01 --until 2026-11-01 --limit 500
```

Riesgos a asumir:

- **ToS**: scrapear X incumple sus términos. Sin cuenta tuya involucrada, el riesgo inmediato es de bloqueo del proveedor, no tuyo — pero un producto comercial necesita datos licenciados.
- **Cobertura**: los actores leen endpoints de búsqueda de X; la profundidad histórica real varía. **Valida con una cuenta y 12+ meses antes de comprar un plan grande.**
- **Estabilidad**: los actores se rompen cuando X cambia su frontend, y hay issues reportados de inestabilidad. Mantén el actor configurable (`APIFY_ACTOR`) y un fallback.
- **Input**: se puede sobreescribir el payload con `APIFY_INPUT_JSON` para adaptarse a cambios de esquema.

### Histórico de tuits

La búsqueda de X en planes baratos cubre ~7 días; para 12–24 meses se usa el **timeline del perfil**, que devuelve hasta los últimos ~3.200 posts. El adaptador `ApifySource.fetch_profiles` construye ``startUrls`` por cuenta y pagina por `maxItems`. El actor por defecto es `apidojo/twitter-profile-scraper` (para búsqueda por fecha usa `apidojo/tweet-scraper`). La whitelist propuesta está en [config/x_accounts.json](config/x_accounts.json): 6 cuentas con voto y 9 de contexto con peso 0.

```bash
# con APIFY_TOKEN en .env
PYTHONPATH=src python3 -m alphaconsensus x-history --since 2024-01-01 --limit 800
```

Ese comando descarga los timelines, filtra ruido, extrae señales, baja barras de Alpaca y calcula pesos con hit rate vs benchmark. Guarda todo en `data/x/`. Requiere `APIFY_TOKEN`.

### Opción B — API oficial de X v2

`ingestion/x_api.py` implementa *recent search* con paginación. Sirve para el bucle en vivo con un plan pagado; no para backtesting. Requiere `X_BEARER_TOKEN`.

### Opción C — Dataset licenciado

Para producción: X API Enterprise o proveedores de datos. Es la única vía limpia para redistribuir señales derivadas.

---

## Divulgaciones del Congreso (STOCK Act)

Los miembros no tuitean sus operaciones: las declaran con hasta ~45 días de retraso. Por eso son una fuente separada, con su propio reloj. `ingestion/congress.py` consume la API gratuita de [Bargo](https://www.bargo.ai/free-apis/congress):

- **Ventana**: ~3 meses (rolling), 50.875 operaciones al 2026-11-19.
- **Datos**: miembro, cámara, ticker, tipo, rango de monto, fechas de transacción y divulgación, y performance por operación.
- **Cuota anónima baja**: con `BARGO_API_KEY` gratuita suben los límites. Si ves `429`, espera o pide key.
- **Uso correcto**: la señal se fecha en `disclosure_date`, no en `transaction_date`. El retorno desde la transacción no es lo que habrías capturado.

```bash
PYTHONPATH=src python3 -m alphaconsensus congress --health
PYTHONPATH=src python3 -m alphaconsensus congress --ticker NVDA --limit 10
```

Para backtest de 12–24 meses hace falta histórico de pago (Quiver, Unusual Whales) o parsear los filings oficiales de la Cámara y el Senado. La lista de candidatos y la rúbrica están en [docs/whitelist.md](docs/whitelist.md).

**Ya hay histórico oficial.** `python -m alphaconsensus house` descarga el índice anual de la Cámara, filtra los PTRs de los miembros objetivo, baja los PDFs y los parsea: **291 PTRs → 4.031 operaciones de 11 miembros (2023-12 → 2026-11)**, gratis. Luego `congress-score` mide el retorno desde la divulgación y aplica un t-test.

Resultado del backtest (21 días, benchmark QQQ): **ningún miembro supera t≥2**. Pelosi es la única con exceso positivo (+5,0%), pero `t=1,78`, `n=25` y sus apuestas grandes son opciones (excluidas): peso **0,08 provisional**. Al cambiar el horizonte, los "mejores" rotan (5d: Hill/Hern; 60d: Kean/Sessions), señal de ruido. Detalle en [docs/whitelist.md](docs/whitelist.md#8-backtest-real-2026-11-19).

---

## Capa LLM (opcional)

El parser de reglas es el baseline por defecto: determinista, gratis y auditable. La capa LLM (`nlp/llm.py`) usa cualquier endpoint compatible con OpenAI (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`) y devuelve JSON estructurado con validación estricta. Cualquier fallo cae de vuelta a reglas: el pipeline no se detiene.

```bash
# .env
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

Para comparar ambos parsers contra el mismo corpus, `nlp.mode` acepta `rules`, `llm` o `hybrid`.

---

## Qué falta (y en qué orden)

1. **Histórico de X** (bloqueante para la mitad X): 12–24 meses de tuits vía Apify. El histórico del Congreso ya está resuelto con los PTRs oficiales.
2. **Mejorar el backtest del Congreso**: OCR de los PTRs escaneados (McCaul falta), Senate eFD, incluir opciones/LEAPS, agrupar por ticker/fecha y corregir por multiple testing. Hoy el resultado es "sin evidencia", no "sin habilidad".
3. **Bucle en vivo**: scheduler (cada 5 min), dedupe persistente, alertas Telegram/Slack, y latencia medida de punta a punta.
4. **Alpaca paper real**: ejecutar órdenes, reconciliar posiciones, y comparar el fill real contra el simulador.
5. **Intradía**: velas de 5 min para stops y fills realistas; hoy el backtest es diario.
6. **Anti-manipulación**: cuentas nuevas, clusters coordinados, float bajo, picos de volumen y noticias SEC antes de operar.
7. **LLM en producción**: coste por tweet, caché, evaluación contra el parser de reglas.
8. **Sizing por convicción**: hoy todas las señales que pasan el quórum arriesgan lo mismo. Escalar el tamaño con el score de consenso (y permitir varias entradas por ticker) es la palanca para convertir edge en retorno sin bajar el estándar de calidad.

---

## Sobre el demo (lectura honesta)

- El mercado sintético es **sin deriva** (drift ≈ 0) para que el beta no regale retorno; el único edge posible es acertar dirección.
- Las cuentas tienen una `skill` oculta (`DEMO_SKILLS` en `ingestion/mock.py`); el scorer la recupera solo con precios y direcciones.
- **Un seed no es evidencia.** `robustness --seeds 20` promedia; incluso así, el demo no dice nada sobre traders reales.
- La ablación compara *retorno medio por operación*, no retorno total: la variante sin pesos dispara 3–4× más señales (incluye ruido) y despliega más capital. Comparar totales sería engañoso.
- Hallazgo con 20 seeds (perfil $1k): ponderar sube el edge por operación (+3.44% vs +1.85%), el win rate (72.6% vs 63.6%) y reduce el drawdown (-0.86% vs -1.70%), pero dispara ~4× menos señales (11 vs 42) y deja el retorno total por debajo (+2.25% vs +3.86%) porque el capital queda ocioso. **El siguiente cuello de botella no es filtrar mejor, es convertir convicción en tamaño de posición.**

---

## Tests

```bash
make test
```

81 tests: extracción de tickers, negaciones, multi-ticker, quórum y cooldown, shrinkage del scorer, stops/targets/equity del simulador, filtros de ingesta, normalización de divulgaciones del Congreso, smoke test de órdenes y pipeline completo.

---

## Seguridad

- Las keys viven en `.env` (ignorado por git) o en variables de entorno. `.env.example` documenta todas.
- `AlpacaPaperBroker` apunta a `paper-api.alpaca.markets` por defecto y avisa si la URL no es de paper.
- No hay ningún camino de código que pueda enviar una orden real sin cambiar explícitamente `ALPACA_BASE_URL`.
- Si una key se expone (chat, captura, log), regenérala en Alpaca y actualiza `.env`. Las de paper no mueven dinero real, pero la higiene es la misma.

---

## Decisiones que necesito de ti

1. **Histórico de pago**: ¿Bargo gratis (3 meses, empezar a acumular ya) o Quiver/Unusual Whales (años, backtest inmediato)? Apify (~$19/mes) sigue pendiente para los tuits.
2. **Whitelist**: el backtest del Congreso no valida a nadie (Pelosi 0,08 provisional). ¿Seguimos por esa vía con OCR/opciones, o pivotamos a las cuentas de X?
3. **Universo**: hoy son 24 tickers US; ¿lo ampliamos a todo el mercado US? ¿opciones?
4. **Riesgo**: ✅ decidido — $1,000, 1% por operación, long-only, máximo 4 posiciones.
5. **Hosting**: ¿VPS/cloud para el bucle 24/7, o solo research local por ahora?

---

## Licencia

MIT (código). Los datos de X y de mercado tienen sus propias licencias.
