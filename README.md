# ETF-FACTOR-SCORE | ETF 多因子增强打分

A股口径 8 因子横截面打分看板（48 只 ETF 池，与 ETF-ROTATION-PRO 同池）。

- 线上地址: https://wangjun20251978.github.io/ETF-FACTOR-SCORE/
- 因子(按A股有效性排序加权): F1短期反转(↓20) F2低波动(↓15) F3动量60(↑15) F4动量20(↑15) F5趋势排列(↑10) F6位置突破(↑10) F7乖离保护(↓10) F8量能配比(↑5)
- 数据源: 新浪财经日K公开接口；大盘择时: 上证综指 MA20/MA60
- 页面内置"个股实时打分"面板：输入任意 6 位代码，浏览器端直连东方财富行情实时打分
- 每日更新: GitHub Actions 北京时间 15:35 自动运行（cron '35 7 * * *' UTC）
- 本地运行: `python etf_factor_score.py`（生成 docs/index.html + docs/factors.json）
