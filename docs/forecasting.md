# Forecasting

`forecasting/forecast.py` projects month-end spend per scope (org total,
team, application).

## Method

OLS on the trailing 28 days of daily cost: intercept + linear trend + weekend
dummy. Remaining days of the month are predicted (clipped at 0) and added to
month-to-date actuals. The 95% band is `1.96 × residual σ × √(remaining days)`.

Fallbacks: mean of available history (< 10 fit days), `actuals` for fully
elapsed months, `no_data` for empty scopes.

## Trend labels

`increasing` / `decreasing` when the fitted slope implies > 10% change over 30
days relative to the mean daily rate; otherwise `stable`.

## Division of labour with anomaly detection

Spikes are the anomaly detector's job; **slow sustained growth is this
module's job.** The demo's injected 35% summarizer growth is deliberately
invisible to spike detection and surfaces here as an `increasing` trend
projecting past budget.

## Stated limitations

Assumes current patterns continue; knows nothing about future anomalies; the
band reflects recent day-to-day variance only. Month-boundary and seasonality
effects beyond the weekend dummy are not modelled. Every `Forecast` carries
this caveat in its payload.