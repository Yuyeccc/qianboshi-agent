# #14v2 分层前瞻回测报表（2026-09-01T01:24:49）

- run_id: `20260901T012449` | git: 5811cce | 规则: tuple_status_any_ok_v1
- 数据: view_tuple_status.json sha256=eb1036093f8e42dd | prediction_events=31320
- OOS: train≤2026-06-30 / test≥2026-07-01 / roll≥2026-07-15（expanding）
- 命中规则: bull ret>0 / bear ret<0 / risk 0.5(≤3d)·1.0(≤10d)·2.0(>10d)

## 四分母与覆盖率

| layer | resolved | error | skipped | eligible | 可评估覆盖率 |
|---|---|---|---|---|---|
| ok | 1595 | 430 | 2045 | 2025 | 78.8% |
| partial_anchor | 655 | 1435 | 1560 | 2090 | 31.3% |
| template_only | 5620 | 3585 | 3700 | 9205 | 61.1% |
| no_ru | 2065 | 4265 | 4365 | 6330 | 32.6% |

## 分层命中率（view 级计权，Wilson 95% CI；min_sample=30；binomial_p=事件级双侧检验）

| layer | direction | window | segment | n_view | hit_rate | CI | binomial_p | 样本不足 |
|---|---|---|---|---|---|---|---|---|
| ok | all | 1 | all | 143 | 60.8% | [52.7%,68.5%] | 0.614 |  |
| ok | all | 1 | train | 36 | 55.6% | [39.6%,70.5%] | 0.018 |  |
| ok | all | 1 | test | 107 | 62.6% | [53.2%,71.2%] | 0.079 |  |
| ok | all | 1 | roll | 9 | 66.7% | [35.4%,87.9%] | 0.346 | ⚠不足 |
| ok | all | 3 | all | 143 | 71.3% | [63.4%,78.1%] | 0.401 |  |
| ok | all | 3 | train | 36 | 50.0% | [34.5%,65.5%] | 0.018 |  |
| ok | all | 3 | test | 107 | 78.5% | [69.8%,85.2%] | 0.802 |  |
| ok | all | 3 | roll | 9 | 66.7% | [35.4%,87.9%] | 0.346 | ⚠不足 |
| ok | all | 5 | all | 143 | 59.4% | [51.2%,67.1%] | 0.467 |  |
| ok | all | 5 | train | 36 | 50.0% | [34.5%,65.5%] | 0.004 |  |
| ok | all | 5 | test | 107 | 62.6% | [53.2%,71.2%] | 0.024 |  |
| ok | all | 5 | roll | 9 | 55.6% | [26.7%,81.1%] | 0.637 | ⚠不足 |
| ok | all | 10 | all | 143 | 60.1% | [51.9%,67.8%] | 0.083 |  |
| ok | all | 10 | train | 36 | 52.8% | [37.0%,68.0%] | 0.009 |  |
| ok | all | 10 | test | 107 | 62.6% | [53.2%,71.2%] | 0.530 |  |
| ok | all | 10 | roll | 9 | 55.6% | [26.7%,81.1%] | 1.000 | ⚠不足 |
| ok | all | 20 | all | 143 | 46.2% | [38.2%,54.3%] | 0.006 |  |
| ok | all | 20 | train | 36 | 47.2% | [32.0%,63.0%] | 0.018 |  |
| ok | all | 20 | test | 107 | 45.8% | [36.7%,55.2%] | 0.060 |  |
| ok | all | 20 | roll | 9 | 66.7% | [35.4%,87.9%] | 1.000 | ⚠不足 |
| ok | bullish | 1 | all | 84 | 70.2% | [59.8%,79.0%] | 0.048 |  |
| ok | bullish | 1 | train | 21 | 61.9% | [40.9%,79.2%] | 0.047 | ⚠不足 |
| ok | bullish | 1 | test | 63 | 73.0% | [61.0%,82.4%] | 0.001 |  |
| ok | bullish | 1 | roll | 4 | 100.0% | [51.0%,100.0%] | 0.034 | ⚠不足 |
| ok | bullish | 3 | all | 84 | 78.6% | [68.7%,86.0%] | 0.068 |  |
| ok | bullish | 3 | train | 21 | 61.9% | [40.9%,79.2%] | 0.286 | ⚠不足 |
| ok | bullish | 3 | test | 63 | 84.1% | [73.2%,91.1%] | 0.008 |  |
| ok | bullish | 3 | roll | 4 | 75.0% | [30.1%,95.4%] | 0.157 | ⚠不足 |
| ok | bullish | 5 | all | 84 | 65.5% | [54.8%,74.8%] | 0.068 |  |
| ok | bullish | 5 | train | 21 | 42.9% | [24.5%,63.4%] | 0.001 | ⚠不足 |
| ok | bullish | 5 | test | 63 | 73.0% | [61.0%,82.4%] | 0.000 |  |
| ok | bullish | 5 | roll | 4 | 75.0% | [30.1%,95.4%] | 0.157 | ⚠不足 |
| ok | bullish | 10 | all | 84 | 58.3% | [47.6%,68.3%] | 0.000 |  |
| ok | bullish | 10 | train | 21 | 76.2% | [54.9%,89.4%] | 0.446 | ⚠不足 |
| ok | bullish | 10 | test | 63 | 52.4% | [40.3%,64.2%] | 0.000 |  |
| ok | bullish | 10 | roll | 4 | 75.0% | [30.1%,95.4%] | 0.157 | ⚠不足 |
| ok | bullish | 20 | all | 84 | 20.2% | [13.0%,30.0%] | 0.000 |  |
| ok | bullish | 20 | train | 21 | 42.9% | [24.5%,63.4%] | 0.009 | ⚠不足 |
| ok | bullish | 20 | test | 63 | 12.7% | [6.6%,23.1%] | 0.000 |  |
| ok | bullish | 20 | roll | 4 | 75.0% | [30.1%,95.4%] | 1.000 | ⚠不足 |
| ok | bearish | 1 | all | 47 | 46.8% | [33.3%,60.8%] | 0.162 |  |
| ok | bearish | 1 | train | 6 | 50.0% | [18.8%,81.2%] | 0.739 | ⚠不足 |
| ok | bearish | 1 | test | 41 | 46.3% | [32.1%,61.3%] | 0.174 |  |
| ok | bearish | 1 | roll | 5 | 40.0% | [11.8%,76.9%] | 0.527 | ⚠不足 |
| ok | bearish | 3 | all | 47 | 66.0% | [51.7%,77.8%] | 0.002 |  |
| ok | bearish | 3 | train | 6 | 33.3% | [9.7%,70.0%] | 0.096 | ⚠不足 |
| ok | bearish | 3 | test | 41 | 70.7% | [55.5%,82.4%] | 0.006 |  |
| ok | bearish | 3 | roll | 5 | 60.0% | [23.1%,88.2%] | 1.000 | ⚠不足 |
| ok | bearish | 5 | all | 47 | 48.9% | [35.3%,62.8%] | 0.401 |  |
| ok | bearish | 5 | train | 6 | 66.7% | [30.0%,90.3%] | 0.317 | ⚠不足 |
| ok | bearish | 5 | test | 41 | 46.3% | [32.1%,61.3%] | 0.244 |  |
| ok | bearish | 5 | roll | 5 | 40.0% | [11.8%,76.9%] | 0.527 | ⚠不足 |
| ok | bearish | 10 | all | 47 | 72.3% | [58.2%,83.1%] | 0.000 |  |
| ok | bearish | 10 | train | 6 | 16.7% | [3.0%,56.4%] | 0.020 | ⚠不足 |
| ok | bearish | 10 | test | 41 | 80.5% | [66.0%,89.8%] | 0.000 |  |
| ok | bearish | 10 | roll | 5 | 40.0% | [11.8%,76.9%] | 0.206 | ⚠不足 |
| ok | bearish | 20 | all | 47 | 89.4% | [77.4%,95.4%] | 0.000 |  |
| ok | bearish | 20 | train | 6 | 66.7% | [30.0%,90.3%] | 0.317 | ⚠不足 |
| ok | bearish | 20 | test | 41 | 92.7% | [80.6%,97.5%] | 0.000 |  |
| ok | bearish | 20 | roll | 5 | 60.0% | [23.1%,88.2%] | 1.000 | ⚠不足 |
| ok | risk | 1 | all | 12 | 50.0% | [25.4%,74.6%] | 0.467 | ⚠不足 |
| ok | risk | 1 | train | 9 | 44.4% | [18.9%,73.3%] | 0.166 | ⚠不足 |
| ok | risk | 1 | test | 3 | 66.7% | [20.8%,93.8%] | 0.317 | ⚠不足 |
| ok | risk | 3 | all | 12 | 41.7% | [19.3%,68.0%] | 0.090 | ⚠不足 |
| ok | risk | 3 | train | 9 | 33.3% | [12.1%,64.6%] | 0.052 | ⚠不足 |
| ok | risk | 3 | test | 3 | 66.7% | [20.8%,93.8%] | 1.000 | ⚠不足 |
| ok | risk | 5 | all | 12 | 58.3% | [31.9%,80.7%] | 0.467 | ⚠不足 |
| ok | risk | 5 | train | 9 | 55.6% | [26.7%,81.1%] | 0.405 | ⚠不足 |
| ok | risk | 5 | test | 3 | 66.7% | [20.8%,93.8%] | 1.000 | ⚠不足 |
| ok | risk | 10 | all | 12 | 25.0% | [8.9%,53.2%] | 0.029 | ⚠不足 |
| ok | risk | 10 | train | 9 | 22.2% | [6.3%,54.7%] | 0.013 | ⚠不足 |
| ok | risk | 10 | test | 3 | 33.3% | [6.2%,79.2%] | 1.000 | ⚠不足 |
| ok | risk | 20 | all | 12 | 58.3% | [31.9%,80.7%] | 0.808 | ⚠不足 |
| ok | risk | 20 | train | 9 | 44.4% | [18.9%,73.3%] | 0.166 | ⚠不足 |
| ok | risk | 20 | test | 3 | 100.0% | [43.9%,100.0%] | 0.045 | ⚠不足 |
| partial_anchor | all | 1 | all | 68 | 41.2% | [30.3%,53.0%] | 0.000 |  |
| partial_anchor | all | 1 | train | 43 | 41.9% | [28.4%,56.7%] | 0.007 |  |
| partial_anchor | all | 1 | test | 25 | 40.0% | [23.4%,59.3%] | 0.002 | ⚠不足 |
| partial_anchor | all | 1 | roll | 3 | 33.3% | [6.2%,79.2%] | 0.020 | ⚠不足 |
| partial_anchor | all | 3 | all | 68 | 57.4% | [45.5%,68.4%] | 0.930 |  |
| partial_anchor | all | 3 | train | 43 | 55.8% | [41.1%,69.6%] | 0.726 |  |
| partial_anchor | all | 3 | test | 25 | 60.0% | [40.7%,76.6%] | 0.599 | ⚠不足 |
| partial_anchor | all | 3 | roll | 3 | 66.7% | [20.8%,93.8%] | 0.317 | ⚠不足 |
| partial_anchor | all | 5 | all | 68 | 48.5% | [37.0%,60.2%] | 0.138 |  |
| partial_anchor | all | 5 | train | 43 | 53.5% | [38.9%,67.5%] | 0.726 |  |
| partial_anchor | all | 5 | test | 25 | 40.0% | [23.4%,59.3%] | 0.009 | ⚠不足 |
| partial_anchor | all | 5 | roll | 3 | 66.7% | [20.8%,93.8%] | 0.739 | ⚠不足 |
| partial_anchor | all | 10 | all | 68 | 57.4% | [45.5%,68.4%] | 0.432 |  |
| partial_anchor | all | 10 | train | 43 | 62.8% | [47.9%,75.6%] | 0.413 |  |
| partial_anchor | all | 10 | test | 25 | 48.0% | [30.0%,66.5%] | 0.036 | ⚠不足 |
| partial_anchor | all | 10 | roll | 3 | 66.7% | [20.8%,93.8%] | 0.020 | ⚠不足 |
| partial_anchor | all | 20 | all | 68 | 51.5% | [39.8%,62.9%] | 0.044 |  |
| partial_anchor | all | 20 | train | 43 | 55.8% | [41.1%,69.6%] | 0.558 |  |
| partial_anchor | all | 20 | test | 25 | 44.0% | [26.7%,62.9%] | 0.018 | ⚠不足 |
| partial_anchor | all | 20 | roll | 3 | 100.0% | [43.9%,100.0%] | 0.096 | ⚠不足 |
| partial_anchor | bullish | 1 | all | 41 | 39.0% | [25.7%,54.3%] | 0.001 |  |
| partial_anchor | bullish | 1 | train | 25 | 40.0% | [23.4%,59.3%] | 0.027 | ⚠不足 |
| partial_anchor | bullish | 1 | test | 16 | 37.5% | [18.5%,61.4%] | 0.009 | ⚠不足 |
| partial_anchor | bullish | 1 | roll | 1 | 100.0% | [20.6%,100.0%] | 0.317 | ⚠不足 |
| partial_anchor | bullish | 3 | all | 41 | 53.7% | [38.8%,67.9%] | 0.258 |  |
| partial_anchor | bullish | 3 | train | 25 | 48.0% | [30.0%,66.5%] | 0.206 | ⚠不足 |
| partial_anchor | bullish | 3 | test | 16 | 62.5% | [38.6%,81.5%] | 0.746 | ⚠不足 |
| partial_anchor | bullish | 3 | roll | 1 | 100.0% | [20.6%,100.0%] | 0.317 | ⚠不足 |
| partial_anchor | bullish | 5 | all | 41 | 36.6% | [23.6%,51.9%] | 0.002 |  |
| partial_anchor | bullish | 5 | train | 25 | 44.0% | [26.7%,62.9%] | 0.206 | ⚠不足 |
| partial_anchor | bullish | 5 | test | 16 | 25.0% | [10.2%,49.5%] | 0.001 | ⚠不足 |
| partial_anchor | bullish | 5 | roll | 1 | 0.0% | [0.0%,79.3%] | 0.317 | ⚠不足 |
| partial_anchor | bullish | 10 | all | 41 | 51.2% | [36.5%,65.8%] | 0.013 |  |
| partial_anchor | bullish | 10 | train | 25 | 68.0% | [48.4%,82.8%] | 0.343 | ⚠不足 |
| partial_anchor | bullish | 10 | test | 16 | 25.0% | [10.2%,49.5%] | 0.000 | ⚠不足 |
| partial_anchor | bullish | 10 | roll | 1 | 0.0% | [0.0%,79.3%] | 0.317 | ⚠不足 |
| partial_anchor | bullish | 20 | all | 41 | 36.6% | [23.6%,51.9%] | 0.000 |  |
| partial_anchor | bullish | 20 | train | 25 | 52.0% | [33.5%,70.0%] | 0.206 | ⚠不足 |
| partial_anchor | bullish | 20 | test | 16 | 12.5% | [3.5%,36.0%] | 0.000 | ⚠不足 |
| partial_anchor | bullish | 20 | roll | 1 | 100.0% | [20.6%,100.0%] | 0.317 | ⚠不足 |
| partial_anchor | bearish | 1 | all | 23 | 43.5% | [25.6%,63.2%] | 0.011 | ⚠不足 |
| partial_anchor | bearish | 1 | train | 15 | 40.0% | [19.8%,64.2%] | 0.050 | ⚠不足 |
| partial_anchor | bearish | 1 | test | 8 | 50.0% | [21.5%,78.5%] | 0.108 | ⚠不足 |
| partial_anchor | bearish | 1 | roll | 2 | 0.0% | [0.0%,65.8%] | 0.005 | ⚠不足 |
| partial_anchor | bearish | 3 | all | 23 | 69.6% | [49.1%,84.4%] | 0.101 | ⚠不足 |
| partial_anchor | bearish | 3 | train | 15 | 73.3% | [48.0%,89.1%] | 0.019 | ⚠不足 |
| partial_anchor | bearish | 3 | test | 8 | 62.5% | [30.6%,86.3%] | 0.819 | ⚠不足 |
| partial_anchor | bearish | 3 | roll | 2 | 50.0% | [9.4%,90.5%] | 0.157 | ⚠不足 |
| partial_anchor | bearish | 5 | all | 23 | 73.9% | [53.5%,87.5%] | 0.053 | ⚠不足 |
| partial_anchor | bearish | 5 | train | 15 | 73.3% | [48.0%,89.1%] | 0.019 | ⚠不足 |
| partial_anchor | bearish | 5 | test | 8 | 75.0% | [40.9%,92.8%] | 0.819 | ⚠不足 |
| partial_anchor | bearish | 5 | roll | 2 | 100.0% | [34.2%,100.0%] | 0.479 | ⚠不足 |
| partial_anchor | bearish | 10 | all | 23 | 69.6% | [49.1%,84.4%] | 0.025 | ⚠不足 |
| partial_anchor | bearish | 10 | train | 15 | 53.3% | [30.1%,75.2%] | 0.695 | ⚠不足 |
| partial_anchor | bearish | 10 | test | 8 | 100.0% | [67.6%,100.0%] | 0.003 | ⚠不足 |
| partial_anchor | bearish | 10 | roll | 2 | 100.0% | [34.2%,100.0%] | 0.005 | ⚠不足 |
| partial_anchor | bearish | 20 | all | 23 | 73.9% | [53.5%,87.5%] | 0.002 | ⚠不足 |
| partial_anchor | bearish | 20 | train | 15 | 60.0% | [35.8%,80.2%] | 0.239 | ⚠不足 |
| partial_anchor | bearish | 20 | test | 8 | 100.0% | [67.6%,100.0%] | 0.001 | ⚠不足 |
| partial_anchor | bearish | 20 | roll | 2 | 100.0% | [34.2%,100.0%] | 0.157 | ⚠不足 |
| partial_anchor | risk | 1 | all | 4 | 50.0% | [15.0%,85.0%] | 1.000 | ⚠不足 |
| partial_anchor | risk | 1 | train | 3 | 66.7% | [20.8%,93.8%] | 0.706 | ⚠不足 |
| partial_anchor | risk | 1 | test | 1 | 0.0% | [0.0%,79.3%] | 0.317 | ⚠不足 |
| partial_anchor | risk | 3 | all | 4 | 25.0% | [4.6%,69.9%] | 0.479 | ⚠不足 |
| partial_anchor | risk | 3 | train | 3 | 33.3% | [6.2%,79.2%] | 0.706 | ⚠不足 |
| partial_anchor | risk | 3 | test | 1 | 0.0% | [0.0%,79.3%] | 0.317 | ⚠不足 |
| partial_anchor | risk | 5 | all | 4 | 25.0% | [4.6%,69.9%] | 0.479 | ⚠不足 |
| partial_anchor | risk | 5 | train | 3 | 33.3% | [6.2%,79.2%] | 0.706 | ⚠不足 |
| partial_anchor | risk | 5 | test | 1 | 0.0% | [0.0%,79.3%] | 0.317 | ⚠不足 |
| partial_anchor | risk | 10 | all | 4 | 50.0% | [15.0%,85.0%] | 0.479 | ⚠不足 |
| partial_anchor | risk | 10 | train | 3 | 66.7% | [20.8%,93.8%] | 0.706 | ⚠不足 |
| partial_anchor | risk | 10 | test | 1 | 0.0% | [0.0%,79.3%] | 0.317 | ⚠不足 |
| partial_anchor | risk | 20 | all | 4 | 75.0% | [30.1%,95.4%] | 0.479 | ⚠不足 |
| partial_anchor | risk | 20 | train | 3 | 66.7% | [20.8%,93.8%] | 0.257 | ⚠不足 |
| partial_anchor | risk | 20 | test | 1 | 100.0% | [20.6%,100.0%] | 0.317 | ⚠不足 |
| template_only | all | 1 | all | 554 | 56.7% | [52.5%,60.8%] | 0.371 |  |
| template_only | all | 1 | train | 313 | 58.1% | [52.6%,63.5%] | 0.281 |  |
| template_only | all | 1 | test | 241 | 54.8% | [48.5%,60.9%] | 0.864 |  |
| template_only | all | 1 | roll | 64 | 60.9% | [48.7%,71.9%] | 0.303 |  |
| template_only | all | 3 | all | 554 | 64.6% | [60.6%,68.5%] | 0.905 |  |
| template_only | all | 3 | train | 313 | 63.3% | [57.8%,68.4%] | 0.362 |  |
| template_only | all | 3 | test | 241 | 66.4% | [60.2%,72.1%] | 0.439 |  |
| template_only | all | 3 | roll | 64 | 59.4% | [47.1%,70.5%] | 0.493 |  |
| template_only | all | 5 | all | 554 | 55.4% | [51.2%,59.5%] | 0.551 |  |
| template_only | all | 5 | train | 313 | 58.8% | [53.3%,64.1%] | 0.804 |  |
| template_only | all | 5 | test | 241 | 51.0% | [44.8%,57.3%] | 0.264 |  |
| template_only | all | 5 | roll | 64 | 57.8% | [45.6%,69.1%] | 0.864 |  |
| template_only | all | 10 | all | 554 | 57.4% | [53.2%,61.5%] | 0.591 |  |
| template_only | all | 10 | train | 313 | 59.7% | [54.2%,65.0%] | 0.097 |  |
| template_only | all | 10 | test | 241 | 54.4% | [48.0%,60.5%] | 0.013 |  |
| template_only | all | 10 | roll | 64 | 60.9% | [48.7%,71.9%] | 0.607 |  |
| template_only | all | 20 | all | 554 | 55.4% | [51.2%,59.5%] | 0.765 |  |
| template_only | all | 20 | train | 313 | 59.4% | [53.9%,64.7%] | 0.001 |  |
| template_only | all | 20 | test | 241 | 50.2% | [43.9%,56.5%] | 0.003 |  |
| template_only | all | 20 | roll | 64 | 82.8% | [71.8%,90.1%] | 0.059 |  |
| template_only | bullish | 1 | all | 341 | 54.2% | [48.9%,59.5%] | 0.034 |  |
| template_only | bullish | 1 | train | 195 | 56.9% | [49.9%,63.7%] | 0.183 |  |
| template_only | bullish | 1 | test | 146 | 50.7% | [42.7%,58.7%] | 0.092 |  |
| template_only | bullish | 1 | roll | 35 | 60.0% | [43.6%,74.5%] | 0.279 |  |
| template_only | bullish | 3 | all | 341 | 63.3% | [58.1%,68.3%] | 0.597 |  |
| template_only | bullish | 3 | train | 195 | 64.1% | [57.2%,70.5%] | 0.066 |  |
| template_only | bullish | 3 | test | 146 | 62.3% | [54.2%,69.8%] | 0.217 |  |
| template_only | bullish | 3 | roll | 35 | 42.9% | [28.0%,59.1%] | 0.022 |  |
| template_only | bullish | 5 | all | 341 | 54.0% | [48.6%,59.2%] | 0.082 |  |
| template_only | bullish | 5 | train | 195 | 61.5% | [54.5%,68.1%] | 0.539 |  |
| template_only | bullish | 5 | test | 146 | 43.8% | [36.0%,51.9%] | 0.001 |  |
| template_only | bullish | 5 | roll | 35 | 40.0% | [25.6%,56.4%] | 0.001 |  |
| template_only | bullish | 10 | all | 341 | 56.9% | [51.6%,62.0%] | 0.010 |  |
| template_only | bullish | 10 | train | 195 | 68.7% | [61.9%,74.8%] | 0.000 |  |
| template_only | bullish | 10 | test | 146 | 41.1% | [33.4%,49.2%] | 0.000 |  |
| template_only | bullish | 10 | roll | 35 | 54.3% | [38.2%,69.5%] | 0.185 |  |
| template_only | bullish | 20 | all | 341 | 47.2% | [42.0%,52.5%] | 0.000 |  |
| template_only | bullish | 20 | train | 195 | 63.1% | [56.1%,69.5%] | 0.000 |  |
| template_only | bullish | 20 | test | 146 | 26.0% | [19.6%,33.7%] | 0.000 |  |
| template_only | bullish | 20 | roll | 35 | 80.0% | [64.1%,90.0%] | 0.904 |  |
| template_only | bearish | 1 | all | 194 | 61.9% | [54.9%,68.4%] | 0.077 |  |
| template_only | bearish | 1 | train | 108 | 62.0% | [52.6%,70.6%] | 0.607 |  |
| template_only | bearish | 1 | test | 86 | 61.6% | [51.1%,71.2%] | 0.052 |  |
| template_only | bearish | 1 | roll | 25 | 64.0% | [44.5%,79.8%] | 0.362 | ⚠不足 |
| template_only | bearish | 3 | all | 194 | 67.5% | [60.7%,73.7%] | 0.650 |  |
| template_only | bearish | 3 | train | 108 | 63.0% | [53.6%,71.5%] | 0.508 |  |
| template_only | bearish | 3 | test | 86 | 73.3% | [63.0%,81.5%] | 1.000 |  |
| template_only | bearish | 3 | roll | 25 | 80.0% | [60.9%,91.1%] | 0.152 | ⚠不足 |
| template_only | bearish | 5 | all | 194 | 57.2% | [50.2%,64.0%] | 0.207 |  |
| template_only | bearish | 5 | train | 108 | 53.7% | [44.3%,62.8%] | 0.825 |  |
| template_only | bearish | 5 | test | 86 | 61.6% | [51.1%,71.2%] | 0.052 |  |
| template_only | bearish | 5 | roll | 25 | 80.0% | [60.9%,91.1%] | 0.001 | ⚠不足 |
| template_only | bearish | 10 | all | 194 | 58.8% | [51.7%,65.5%] | 0.013 |  |
| template_only | bearish | 10 | train | 108 | 44.4% | [35.4%,53.8%] | 0.004 |  |
| template_only | bearish | 10 | test | 86 | 76.7% | [66.8%,84.4%] | 0.000 |  |
| template_only | bearish | 10 | roll | 25 | 68.0% | [48.4%,82.8%] | 0.051 | ⚠不足 |
| template_only | bearish | 20 | all | 194 | 70.1% | [63.3%,76.1%] | 0.000 |  |
| template_only | bearish | 20 | train | 108 | 53.7% | [44.3%,62.8%] | 0.941 |  |
| template_only | bearish | 20 | test | 86 | 90.7% | [82.7%,95.2%] | 0.000 |  |
| template_only | bearish | 20 | roll | 25 | 88.0% | [70.0%,95.8%] | 0.003 | ⚠不足 |
| template_only | risk | 1 | all | 19 | 47.4% | [27.3%,68.3%] | 0.106 | ⚠不足 |
| template_only | risk | 1 | train | 10 | 40.0% | [16.8%,68.7%] | 0.071 | ⚠不足 |
| template_only | risk | 1 | test | 9 | 55.6% | [26.7%,81.1%] | 0.617 | ⚠不足 |
| template_only | risk | 1 | roll | 4 | 50.0% | [15.0%,85.0%] | 0.157 | ⚠不足 |
| template_only | risk | 3 | all | 19 | 57.9% | [36.3%,76.9%] | 0.858 | ⚠不足 |
| template_only | risk | 3 | train | 10 | 50.0% | [23.7%,76.3%] | 0.197 | ⚠不足 |
| template_only | risk | 3 | test | 9 | 66.7% | [35.4%,87.9%] | 0.317 | ⚠不足 |
| template_only | risk | 3 | roll | 4 | 75.0% | [30.1%,95.4%] | 1.000 | ⚠不足 |
| template_only | risk | 5 | all | 19 | 63.2% | [41.0%,80.8%] | 0.858 | ⚠不足 |
| template_only | risk | 5 | train | 10 | 60.0% | [31.3%,83.2%] | 0.439 | ⚠不足 |
| template_only | risk | 5 | test | 9 | 66.7% | [35.4%,87.9%] | 0.317 | ⚠不足 |
| template_only | risk | 5 | roll | 4 | 75.0% | [30.1%,95.4%] | 1.000 | ⚠不足 |
| template_only | risk | 10 | all | 19 | 52.6% | [31.7%,72.7%] | 0.858 | ⚠不足 |
| template_only | risk | 10 | train | 10 | 50.0% | [23.7%,76.3%] | 0.439 | ⚠不足 |
| template_only | risk | 10 | test | 9 | 55.6% | [26.7%,81.1%] | 0.317 | ⚠不足 |
| template_only | risk | 10 | roll | 4 | 75.0% | [30.1%,95.4%] | 0.479 | ⚠不足 |
| template_only | risk | 20 | all | 19 | 52.6% | [31.7%,72.7%] | 0.590 | ⚠不足 |
| template_only | risk | 20 | train | 10 | 50.0% | [23.7%,76.3%] | 0.197 | ⚠不足 |
| template_only | risk | 20 | test | 9 | 55.6% | [26.7%,81.1%] | 0.617 | ⚠不足 |
| template_only | risk | 20 | roll | 4 | 75.0% | [30.1%,95.4%] | 1.000 | ⚠不足 |
| no_ru | all | 1 | all | 217 | 54.4% | [47.7%,60.9%] | 0.258 |  |
| no_ru | all | 1 | train | 134 | 54.5% | [46.0%,62.7%] | 0.683 |  |
| no_ru | all | 1 | test | 83 | 54.2% | [43.5%,64.5%] | 0.226 |  |
| no_ru | all | 1 | roll | 9 | 66.7% | [35.4%,87.9%] | 0.014 | ⚠不足 |
| no_ru | all | 3 | all | 217 | 65.9% | [59.4%,71.9%] | 0.154 |  |
| no_ru | all | 3 | train | 134 | 62.7% | [54.2%,70.4%] | 0.041 |  |
| no_ru | all | 3 | test | 83 | 71.1% | [60.6%,79.7%] | 0.943 |  |
| no_ru | all | 3 | roll | 9 | 66.7% | [35.4%,87.9%] | 0.683 | ⚠不足 |
| no_ru | all | 5 | all | 217 | 57.6% | [50.9%,64.0%] | 0.184 |  |
| no_ru | all | 5 | train | 134 | 60.5% | [52.0%,68.3%] | 0.221 |  |
| no_ru | all | 5 | test | 83 | 53.0% | [42.4%,63.4%] | 0.521 |  |
| no_ru | all | 5 | roll | 9 | 77.8% | [45.3%,93.7%] | 0.221 | ⚠不足 |
| no_ru | all | 10 | all | 217 | 63.6% | [57.0%,69.7%] | 0.154 |  |
| no_ru | all | 10 | train | 134 | 61.9% | [53.5%,69.7%] | 0.414 |  |
| no_ru | all | 10 | test | 83 | 66.3% | [55.6%,75.5%] | 0.226 |  |
| no_ru | all | 10 | roll | 9 | 77.8% | [45.3%,93.7%] | 0.014 | ⚠不足 |
| no_ru | all | 20 | all | 217 | 58.1% | [51.4%,64.4%] | 0.301 |  |
| no_ru | all | 20 | train | 134 | 60.5% | [52.0%,68.3%] | 0.041 |  |
| no_ru | all | 20 | test | 83 | 54.2% | [43.5%,64.5%] | 0.521 |  |
| no_ru | all | 20 | roll | 9 | 77.8% | [45.3%,93.7%] | 0.221 | ⚠不足 |
| no_ru | bullish | 1 | all | 139 | 59.0% | [50.7%,66.8%] | 0.020 |  |
| no_ru | bullish | 1 | train | 96 | 55.2% | [45.2%,64.8%] | 0.695 |  |
| no_ru | bullish | 1 | test | 43 | 67.4% | [52.5%,79.5%] | 0.001 |  |
| no_ru | bullish | 1 | roll | 2 | 100.0% | [34.2%,100.0%] | 1.000 | ⚠不足 |
| no_ru | bullish | 3 | all | 139 | 71.9% | [64.0%,78.7%] | 0.000 |  |
| no_ru | bullish | 3 | train | 96 | 70.8% | [61.1%,79.0%] | 0.000 |  |
| no_ru | bullish | 3 | test | 43 | 74.4% | [59.8%,85.1%] | 0.139 |  |
| no_ru | bullish | 3 | roll | 2 | 0.0% | [0.0%,65.8%] | 0.045 | ⚠不足 |
| no_ru | bullish | 5 | all | 139 | 68.3% | [60.2%,75.5%] | 0.000 |  |
| no_ru | bullish | 5 | train | 96 | 72.9% | [63.3%,80.8%] | 0.001 |  |
| no_ru | bullish | 5 | test | 43 | 58.1% | [43.3%,71.6%] | 0.004 |  |
| no_ru | bullish | 5 | roll | 2 | 0.0% | [0.0%,65.8%] | 0.045 | ⚠不足 |
| no_ru | bullish | 10 | all | 139 | 66.2% | [58.0%,73.5%] | 0.713 |  |
| no_ru | bullish | 10 | train | 96 | 69.8% | [60.0%,78.1%] | 0.050 |  |
| no_ru | bullish | 10 | test | 43 | 58.1% | [43.3%,71.6%] | 0.002 |  |
| no_ru | bullish | 10 | roll | 2 | 100.0% | [34.2%,100.0%] | 0.045 | ⚠不足 |
| no_ru | bullish | 20 | all | 139 | 49.6% | [41.4%,57.9%] | 0.001 |  |
| no_ru | bullish | 20 | train | 96 | 64.6% | [54.6%,73.4%] | 0.010 |  |
| no_ru | bullish | 20 | test | 43 | 16.3% | [8.1%,30.0%] | 0.000 |  |
| no_ru | bullish | 20 | roll | 2 | 0.0% | [0.0%,65.8%] | 0.045 | ⚠不足 |
| no_ru | bearish | 1 | all | 70 | 44.3% | [33.2%,55.9%] | 0.000 |  |
| no_ru | bearish | 1 | train | 34 | 50.0% | [34.1%,65.9%] | 0.063 |  |
| no_ru | bearish | 1 | test | 36 | 38.9% | [24.8%,55.1%] | 0.000 |  |
| no_ru | bearish | 1 | roll | 6 | 50.0% | [18.8%,81.2%] | 0.005 | ⚠不足 |
| no_ru | bearish | 3 | all | 70 | 54.3% | [42.7%,65.4%] | 0.006 |  |
| no_ru | bearish | 3 | train | 34 | 44.1% | [28.9%,60.6%] | 0.063 |  |
| no_ru | bearish | 3 | test | 36 | 63.9% | [47.6%,77.5%] | 0.042 |  |
| no_ru | bearish | 3 | roll | 6 | 83.3% | [43.6%,97.0%] | 1.000 | ⚠不足 |
| no_ru | bearish | 5 | all | 70 | 40.0% | [29.3%,51.7%] | 0.001 |  |
| no_ru | bearish | 5 | train | 34 | 29.4% | [16.8%,46.2%] | 0.003 |  |
| no_ru | bearish | 5 | test | 36 | 50.0% | [34.5%,65.5%] | 0.068 |  |
| no_ru | bearish | 5 | roll | 6 | 100.0% | [61.0%,100.0%] | 0.059 | ⚠不足 |
| no_ru | bearish | 10 | all | 70 | 60.0% | [48.3%,70.7%] | 0.002 |  |
| no_ru | bearish | 10 | train | 34 | 44.1% | [28.9%,60.6%] | 0.116 |  |
| no_ru | bearish | 10 | test | 36 | 75.0% | [58.9%,86.2%] | 0.000 |  |
| no_ru | bearish | 10 | roll | 6 | 83.3% | [43.6%,97.0%] | 0.018 | ⚠不足 |
| no_ru | bearish | 20 | all | 70 | 74.3% | [63.0%,83.1%] | 0.000 |  |
| no_ru | bearish | 20 | train | 34 | 52.9% | [36.7%,68.5%] | 0.886 |  |
| no_ru | bearish | 20 | test | 36 | 94.4% | [81.9%,98.5%] | 0.000 |  |
| no_ru | bearish | 20 | roll | 6 | 100.0% | [61.0%,100.0%] | 0.059 | ⚠不足 |
| no_ru | risk | 1 | all | 8 | 62.5% | [30.6%,86.3%] | 0.763 | ⚠不足 |
| no_ru | risk | 1 | train | 4 | 75.0% | [30.1%,95.4%] | 0.317 | ⚠不足 |
| no_ru | risk | 1 | test | 4 | 50.0% | [15.0%,85.0%] | 0.257 | ⚠不足 |
| no_ru | risk | 1 | roll | 1 | 100.0% | [20.6%,100.0%] | 1.000 | ⚠不足 |
| no_ru | risk | 3 | all | 8 | 62.5% | [30.6%,86.3%] | 0.763 | ⚠不足 |
| no_ru | risk | 3 | train | 4 | 25.0% | [4.6%,69.9%] | 0.317 | ⚠不足 |
| no_ru | risk | 3 | test | 4 | 100.0% | [51.0%,100.0%] | 0.257 | ⚠不足 |
| no_ru | risk | 3 | roll | 1 | 100.0% | [20.6%,100.0%] | 0.157 | ⚠不足 |
| no_ru | risk | 5 | all | 8 | 25.0% | [7.1%,59.1%] | 0.132 | ⚠不足 |
| no_ru | risk | 5 | train | 4 | 25.0% | [4.6%,69.9%] | 0.317 | ⚠不足 |
| no_ru | risk | 5 | test | 4 | 25.0% | [4.6%,69.9%] | 0.257 | ⚠不足 |
| no_ru | risk | 5 | roll | 1 | 100.0% | [20.6%,100.0%] | 0.157 | ⚠不足 |
| no_ru | risk | 10 | all | 8 | 50.0% | [21.5%,78.5%] | 0.763 | ⚠不足 |
| no_ru | risk | 10 | train | 4 | 25.0% | [4.6%,69.9%] | 0.317 | ⚠不足 |
| no_ru | risk | 10 | test | 4 | 75.0% | [30.1%,95.4%] | 0.706 | ⚠不足 |
| no_ru | risk | 10 | roll | 1 | 0.0% | [0.0%,79.3%] | 0.157 | ⚠不足 |
| no_ru | risk | 20 | all | 8 | 62.5% | [30.6%,86.3%] | 0.132 | ⚠不足 |
| no_ru | risk | 20 | train | 4 | 25.0% | [4.6%,69.9%] | 0.317 | ⚠不足 |
| no_ru | risk | 20 | test | 4 | 100.0% | [51.0%,100.0%] | 0.008 | ⚠不足 |
| no_ru | risk | 20 | roll | 1 | 100.0% | [20.6%,100.0%] | 0.157 | ⚠不足 |

> 总参考行未列（混合值禁止引用）。template_only 为弱语义/污染对照层，显著偏离 50% 不构成预测证据。

## ok vs template_only 差值（效应量，view 级，all 方向）

| segment | window | ok_rate | tmpl_rate | 差值 | 差值 95% CI | 含 0? |
|---|---|---|---|---|---|---|
| all | 1 | 60.8%(n=143) | 56.7%(n=554) | +4.2% | [-4.8%,+13.2%] | 是 |
| all | 3 | 71.3%(n=143) | 64.6%(n=554) | +6.7% | [-1.7%,+15.1%] | 是 |
| all | 5 | 59.4%(n=143) | 55.4%(n=554) | +4.0% | [-5.0%,+13.1%] | 是 |
| all | 10 | 60.1%(n=143) | 57.4%(n=554) | +2.7% | [-6.3%,+11.8%] | 是 |
| all | 20 | 46.2%(n=143) | 55.4%(n=554) | -9.3% | [-18.4%,-0.1%] | 否 |
| test | 1 | 62.6%(n=107) | 54.8%(n=241) | +7.9% | [-3.3%,+19.0%] | 是 |
| test | 3 | 78.5%(n=107) | 66.4%(n=241) | +12.1% | [+2.3%,+21.9%] | 否 |
| test | 5 | 62.6%(n=107) | 51.0%(n=241) | +11.6% | [+0.5%,+22.7%] | 否 |
| test | 10 | 62.6%(n=107) | 54.4%(n=241) | +8.3% | [-2.9%,+19.4%] | 是 |
| test | 20 | 45.8%(n=107) | 50.2%(n=241) | -4.4% | [-15.8%,+6.9%] | 是 |
| train | 1 | 55.6%(n=36) | 58.1%(n=313) | -2.6% | [-19.7%,+14.5%] | 是 |
| train | 3 | 50.0%(n=36) | 63.3%(n=313) | -13.3% | [-30.4%,+3.9%] | 是 |
| train | 5 | 50.0%(n=36) | 58.8%(n=313) | -8.8% | [-26.0%,+8.4%] | 是 |
| train | 10 | 52.8%(n=36) | 59.7%(n=313) | -7.0% | [-24.1%,+10.2%] | 是 |
| train | 20 | 47.2%(n=36) | 59.4%(n=313) | -12.2% | [-29.4%,+5.0%] | 是 |