# Resultados de X (2026-11-19)

## 1. Whitelist original (15 cuentas)

- 12.212 tuits descargados, 6.531 aceptados, **265 señales accionables**.
- Solo 94 señales venían de las 6 cuentas con voto.
- **0 consensos** de 3 cuentas, incluso con ventana de 30 días.
- Máxima coincidencia: 3 votantes en AMD, una vez.
- Pesos: solo `unusual_whales` 0,02 (n=9); el resto 0.

Conclusión: las cuentas famosas no publican llamadas accionables. Cramer: 393 tuits → 3 señales. Ackman: 318 → 1. ZeroHedge/DeItaone son titulares.

## 2. Descubrimiento por cashtags (30 cuentas)

Barrido de 10 tickers × 2 consultas, orden Top, desde 2025: 1.900 tuits, 753 autores con señal. Se puntuaron los 30 con más llamadas:

| Cuenta | Señales | Hit | Exceso | Peso |
|---|---:|---:|---:|---:|
| darkflowalert | 11 | 81,8% | +2,05% | 0,20 provisional |
| stockmktnewz | 20 | 70,0% | +0,31% | 0,20 ok |
| curiouspejjy | 28 | 60,7% | +0,66% | 0,12 ok |
| fcastillomarco | 8 | 62,5% | +1,20% | 0,05 provisional |
| ethan__trader | 621 | 51,7% | +2,07% | 0,03 ok |
| jasonl_capital | 13 | 53,8% | −0,14% | 0,02 provisional |
| thestockwhale | 119 | 41,2% | −1,07% | 0 |
| cheddarflow | 175 | 43,4% | +0,28% | 0 |
| kobeissiletter | 38 | 39,5% | −1,86% | 0 |
| traderjonesy | 93 | 18,3% | −0,14% | 0 |

Con esos pesos:

- consenso de 3 cuentas / 7 días → **3 señales** (NVDA, AAPL, UBER), todas de noviembre 2026;
- consenso de 2 cuentas / 7 días → **31 señales**, casi todas de la última semana;
- 5.027 señales en total, pero el 80% son de los últimos dos meses.

## 3. Por qué no está listo para operar

1. **Los pesos altos no son "pesos pesados".** `stockmktnewz` es un agregador de titulares; `darkflowalert` y `cheddarflow` publican flujo de opciones; `curiouspejjy` es un permabull de Tesla. Ninguno es un gestor con track record auditado.
2. **Muestras pequeñas.** `darkflowalert` tiene 11 llamadas; 81,8% de acierto puede ser suerte. `fcastillomarco`, 8.
3. **Ventana corta.** Los timelines solo traen los últimos meses; la búsqueda histórica funciona, pero aún no se usó para validar.
4. **El consenso aparece solo en la última semana.** Con 3 señales no se puede concluir nada.
5. **Sesgo de selección.** Elegimos estas 30 porque publicaron llamadas, no porque hayan demostrado habilidad.

## 4. Qué haría

1. **Validar los 6 mejores con 2 años de búsqueda histórica** (~$4–7 de Apify). Si el peso aguanta, hay algo; si no, se descarta.
2. **Paper log sin órdenes** durante 6–8 semanas: registrar señales y fills simulados, sin tocar la cuenta.
3. **Si no aguanta, cambiar la fuente**: flujo de opciones, 13F o insider trading, donde el dato ya viene estructurado.

La cuenta de Alpaca sigue en **$1.000 y 0 posiciones**. No se ha enviado ninguna orden.
