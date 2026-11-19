# Whitelist: Congreso + X

> Documento de trabajo. Fecha de datos: **2026-11-19**. Los handles y la actividad cambian: esto es una lista de *candidatos a validar*, no un veredicto de confiabilidad.

---

## 1. El malentendido que hay que corregir primero

Nancy Pelosi **no tuitea sus operaciones**. Las declara bajo la STOCK Act, con hasta **45 días de retraso**. Si la metemos en la whitelist de X, el parser de NLP encontrará ~0 señales accionables: no hay `$NVDA long` en sus posts.

Por eso el sistema necesita **dos fuentes con dos relojes distintos**:

| Fuente | Qué es | Frecuencia | Cuándo se puede operar |
|---|---|---|---|
| **Divulgaciones del Congreso** | PTRs de la Cámara y el Senado | ~semanal, por miembro | En la **fecha de divulgación**, no en la de la transacción |
| **Cuentas de X** | analistas, medios, traders | minutos | En el momento del tuit |

Y una consecuencia de diseño: **los políticos no votan en el consenso de X**. Cada miembro es una señal independiente con su propio track record. El quórum de 3 cuentas aplica a X; para el Congreso se usa peso por miembro y, como mucho, un *boost* si 2+ miembros coinciden en el mismo ticker en 30 días.

---

> **Actualización 2026-11-19 — backtest real.** Extraje 291 PTRs oficiales de la Cámara (2024–2026) y obtuve **4.031 operaciones de 11 miembros**. Medido desde la fecha de divulgación y con significancia estadística, **ningún miembro pasa el filtro**. Pelosi es la única con exceso positivo (+5,0% a 21 días) pero con t=1,78 y n=25: peso 0,08, testimonial. Detalle en la sección 8.

## 2. Lo que dicen los datos reales (no la fama)

Consulta a la API gratuita de Bargo el 2026-11-19: **50,875 operaciones**, última divulgación **2026-11-16**, ventana de ~3 meses.

Miembros con más operaciones divulgadas en esa ventana:

| Miembro | Cámara | Estado | Trades | Nota |
|---|---|---:|---:|---|
| Gilbert Cisneros | House | CA31 | 119 | Lag mediano 21 días; rotación alta (RVTY, BBIO, MTSI) |
| Kevin Hern | House | OK01 | 105 | Ways & Means; mucha venta (2 compras / 101 ventas) |
| Ro Khanna | House | CA17 | 105 | Tech; 53/52 compras/ventas |
| Maria Elvira Salazar | House | FL27 | 54 | Comité de Relaciones Exteriores |
| David J. Taylor | House | OH02 | 47 | — |
| April McClain Delaney | House | MD06 | 37 | — |
| Pete Sessions | House | TX17 | 33 | — |
| Michael McCaul | House | TX10 | 20 | Defensa/semis; ex-chair Foreign Affairs |
| John Boozman | Senate | AR | 18 | Agricultura |
| Richard Blumenthal | Senate | CT | 12 | Judiciary |
| Jonathan Jackson | House | IL01 | 11 | — |
| Thomas Kean Jr. | House | NJ07 | 10 | — |
| Cleo Fields | House | LA06 | 9 | — |
| Lisa McClain | House | MI09 | 9 | — |
| Scott Franklin | House | FL18 | 9 | — |
| Byron Donalds | House | FL19 | 8 | Financieros |
| Sheldon Whitehouse | Senate | RI | 7 | Finanzas/Judiciary |
| Josh Gottheimer | House | NJ05 | 5 | Servicios Financieros |
| **Nancy Pelosi** | House | CA11 | **1** | 1 venta de WBD, $50k–$100k, lag 30 días |

Dos conclusiones incómodas:

1. **La fama no es actividad.** Pelosi tuvo 1 operación divulgada en 90 días; Cisneros, Hern y Khanna tuvieron >100. Si el sistema depende de frecuencia, la lista "famosa" es la peor.
2. **La atención sí mueve precio.** Pelosi tiene pocas operaciones pero un seguimiento mediático enorme: su divulgación puede mover el ticker aunque su track record estadístico sea pequeño (n=1 en la ventana). Eso es riesgo de multitud, no alpha.

---

## 3. Rúbrica de selección

### A. Miembros del Congreso (0–100)

| Criterio | Puntos | Cómo se mide |
|---|---:|---|
| Puntualidad | 25 | % de PTR presentados ≤45 días; <70% → 0 |
| Actividad | 15 | ≥8 transacciones/año |
| Tamaño | 15 | mediana de `amount_high` ≥ $50k, y ≥1% del patrimonio estimado |
| Comité | 20 | solapamiento entre jurisdicción del comité y sector operado |
| Alpha tradable | 15 | exceso vs ETF sectorial medido **desde la divulgación**, ≥15 trades y 3 años |
| Higiene | 10 | sin OTC/penny, sin idas y vueltas <30 días, sin opciones ilíquidas |

- **60** para entrar; **75** para peso completo.
- Si el alpha medido desde la transacción es +20% pero desde la divulgación es 0%, **no sirve**: el movimiento ya ocurrió.

### B. Cuentas de X (0–100)

| Criterio | Puntos | Cómo se mide |
|---|---:|---|
| Accionabilidad | 25 | % de tuits con ticker + dirección explícita |
| Acierto | 25 | hit rate vs SPY/sector en ventana 5–20 días |
| Muestra | 15 | ≥100 llamadas/año |
| Timing | 15 | publica antes del movimiento, no después |
| Originalidad | 10 | no es RT ni agregador de titulares |
| Independencia | 10 | baja correlación con las demás cuentas (Jaccard de tickers/tiempo) |

- **65** para votar en el consenso.
- Las cuentas de **contexto** (titulares, macro) entran con **peso 0**: informan filtros de riesgo, no quórum.

### Reglas de exclusión

- Anónimos que solo venden cursos, Telegram o "señales".
- Cuentas que borran tuits o cambian de tesis sin reconocerlo.
- Penny stocks / OTC.
- >50% retweets.
- Cualquiera cuyo alpha desaparezca al medir desde la fecha de divulgación.

---

## 4. Lista propuesta (30 candidatos)

### Congreso — 15 (fuente: divulgaciones)

1. Gilbert Cisneros (CA31)
2. Kevin Hern (OK01)
3. Ro Khanna (CA17)
4. Maria Elvira Salazar (FL27)
5. David J. Taylor (OH02)
6. April McClain Delaney (MD06)
7. Pete Sessions (TX17)
8. Michael McCaul (TX10)
9. John Boozman (AR, Senate)
10. Richard Blumenthal (CT, Senate)
11. Jonathan Jackson (IL01)
12. Thomas Kean Jr. (NJ07)
13. Josh Gottheimer (NJ05)
14. French Hill (AR02)
15. Nancy Pelosi (CA11) — *solo por atención mediática; peso sujeto a track record*

### X — 15 (fuente: tuits)

| Handle | Rol | Por qué | Riesgo |
|---|---|---|---|
| `@jimcramer` | voto | volumen enorme de llamadas explícitas | acierto históricamente cuestionado; muestra grande |
| `@BillAckman` | voto | tesis activistas con ticker | pocas, pero de alto impacto |
| `@unusual_whales` | voto | flujo de opciones con ticker | ruidoso y repetitivo |
| `@markminervini` | voto | setups técnicos con niveles | estilo momentum, rachas |
| `@stockbee` | voto | breadth y momentum | poco frecuente |
| `@firstadopter` | voto | análisis tech con tickers | research, no siempre direccional |
| `@DeItaone` | contexto | titulares macro/empresas | no da dirección |
| `@FirstSquawk` | contexto | titulares rápidos | no da dirección |
| `@zerohedge` | contexto | sesgo bajista permanente | ruido/contrarian |
| `@convertbond` | contexto | macro, tasas, liquidez | macro, no tickers |
| `@dariusdale42` | contexto | ciclos macro | macro, no tickers |
| `@LizAnnSonders` | contexto | macro/mercado | sin llamadas accionables |
| `@RayDalio` | contexto | macro de largo plazo | sin tickers |
| `@chamath` | contexto | tech/macro | opinión, no track record auditado |
| `@dylan522p` | contexto | semis/IA, investigación profunda | research, no direccional |

> Los handles deben verificarse antes de cargarlos: actividad, si siguen públicos y si no cambiaron de estilo. La rúbrica los elimina si no cumplen.

---

## 5. Cómo se valida (sin autoengaño)

1. **Point-in-time**: elegir la lista con datos hasta el corte (p. ej. 2024-12-31) y evaluar 2025–2026. Elegir por lo que funcionó en 2026 es look-ahead.
2. **Dos relojes**: para cada operación del Congreso, calcular retorno desde `transaction_date` (lo que sabían) y desde `disclosure_date` (lo que podías copiar). Solo el segundo es tradable.
3. **Benchmark correcto**: comparar contra el ETF del sector, no solo SPY. Un miembro concentrado en tech no tiene alpha si QQQ subió lo mismo.
4. **Muestra mínima**: 15 operaciones y 3 años para peso completo; antes, peso provisional.
5. **Forward test**: la ventana gratuita de 3 meses sirve para empezar a acumular señales *desde ya*; el backtest de 12–24 meses requiere datos de pago (Quiver, Unusual Whales) o parsear los filings oficiales.

---

## 6. Fuentes de datos

| Fuente | Cobertura | Coste | Uso |
|---|---|---|---|
| **Bargo Congress Trades API** ([docs](https://www.bargo.ai/free-apis/congress)) | ~3 meses, 50k trades, performance por trade | gratis (cuota anónima baja; key gratis sube límites) | señales en vivo y recolección forward |
| **Quiver Quantitative** ([congress](https://www.quiverquant.com/congresstrading/)) | años de histórico | pago | backtest de credibilidad |
| **Unusual Whales** | años de histórico + flujo | pago | backtest + contexto |
| **House Clerk / Senate eFD** | oficial, años | gratis | ground truth; parsing de PDFs pesado |
| **NANC / GOP (KRUZ)** | ETF que replican la idea | comisión | benchmark de si la estrategia ya está arbitrada |

Contexto: House Stock Watcher y Senate Stock Watcher, los datasets gratuitos clásicos, **están caídos desde 2026** (403); no construir sobre ellos. Ver [nota](https://dev.to/fatihbuilds/house-stock-watcher-and-senate-stock-watcher-are-down-what-to-use-instead-2026-2h0n).

---

## 7. Lo que NO voy a hacer

- Presentar esta lista como "cuentas confiables" sin haberlas medido. La confiabilidad se calcula, no se declara.
- Meter políticos en el consenso de X para inflar el número de votos.
- Operar una divulgación de 45 días de antigüedad como si fuera tiempo real.
- Ignorar que los ETFs tipo NANC ya replican esta idea: parte del alpha puede estar arbitrada.

---

## 8. Backtest real (2026-11-19)

**Dataset.** 291 PTRs oficiales de la Cámara (2024–2026), 266 PDFs con capa de texto, 65 escaneados sin texto, **4.031 operaciones de 11 miembros**, rango 2023-12-01 → 2026-11-09, lag mediano **24 días**.

**Método.**
- Retorno desde `disclosure_date` (lo que podías copiar) y desde `transaction_date` (lo que sabían).
- Ventana de 21 días, benchmark **QQQ** (más justo que SPY para una cartera tech).
- Exceso direccional vs benchmark; shrinkage Beta(4,4); t-stat.
- Peso 0 si t<1; mitad si 1≤t<2; significativo solo si t≥2 y n≥15.

**Resultado (21 días, benchmark QQQ).**

| Miembro | Ops | Hit | Exceso div. | t | Peso |
|---|---:|---:|---:|---:|---:|
| Nancy Pelosi | 25 | 60,0% | +5,02% | 1,78 | 0,08 provisional |
| Gilbert Cisneros | 1.412 | 48,5% | −0,04% | −0,11 | 0 |
| Josh Gottheimer | 909 | 48,0% | −0,97% | −2,91 | 0 |
| April McClain Delaney | 456 | 48,5% | −0,94% | −2,24 | 0 |
| Kevin Hern | 217 | 41,5% | −2,28% | −2,64 | 0 |
| David J. Taylor | 191 | 51,3% | +0,67% | 0,95 | 0 |
| Jonathan Jackson | 157 | 49,7% | −0,04% | −0,04 | 0 |
| Thomas H. Kean | 122 | 50,8% | +1,73% | 2,08 | 0 |
| Maria Elvira Salazar | 105 | 44,8% | −2,03% | −1,26 | 0 |
| Pete Sessions | 22 | 50,0% | +0,17% | 0,10 | 0 |
| James French Hill | 21 | 42,9% | −1,43% | −0,40 | 0 |

**La prueba que mata la historia:** al cambiar el horizonte, los "ganadores" rotan.

| Horizonte | Quién parece bueno | t |
|---|---|---|
| 5 días | French Hill (+2,6%), Kevin Hern (+1,1%) | ~1,5 |
| 21 días | Nancy Pelosi (+5,0%) | 1,78 |
| 60 días | Thomas Kean (+3,2%), Pete Sessions (+1,1%) | ~1,2–2,1 |

Si el mejor miembro cambia según la ventana, no es habilidad: es ruido y múltiples comparaciones. Con 11 miembros y 3 horizontes, alguien *tiene* que verse bien por azar.

**Lectura honesta.**

- **No hay evidencia suficiente para copiar a ningún miembro del Congreso** en este sample.
- Pelosi: el único exceso positivo, pero n=25, t=1,78 (p≈0,09 dos colas) y sus operaciones grandes son **opciones/LEAPS**, que este parser excluye. El +5% puede ser el "efecto Pelosi" (el mercado compra tras la divulgación), pero no es estadísticamente sólido.
- **McCaul no aparece**: todos sus PTRs de la ventana son PDFs escaneados sin capa de texto. Es una ausencia de datos, no una conclusión sobre él.
- Faltan los senadores (eFD) y las opciones, donde suele estar el tamaño real de las apuestas.

**Lo que haría falta para cambiar la conclusión:** OCR de los PTRs escaneados, Senate eFD, incluir opciones/LEAPS, agrupar por ticker/fecha para no contar la misma tesis 20 veces, corregir por multiple testing y hacer walk-forward (2024–2025 para elegir, 2026 para evaluar).

---

## 9. Siguiente paso

1. Aprobar/editar los 30 nombres.
2. Elegir la fuente histórica: Bargo free (3 meses, empezar a acumular) o proveedor de pago (3 años, backtest inmediato).
3. Cargar las cuentas de X validadas en `config/accounts.json` y los miembros en un `config/congress.json` (aún no existe; se crea al conectar la fuente).
4. Correr la rúbrica con datos y dejar solo las que pasen 60/65.
