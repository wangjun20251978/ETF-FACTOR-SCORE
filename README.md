# ETF-FACTOR-SCORE | ETF 多因子增强打分

A股口径 8 因子横截面打分看板（48 只 ETF 池，与 ETF-ROTATION-PRO 同池）。

- 线上地址: https://wangjun20251978.github.io/ETF-FACTOR-SCORE/
- 因子: F1动量20(↑25) F2动量60(↑20) F3趋势排列(↑15) F4位置突破(↑10) F5短期反转(↓10) F6低波动(↓10) F7量能配比(↑5) F8乖离保护(↓5)
- 数据源: 新浪财经日K公开接口；大盘择时: 上证综指 MA20/MA60
- 页面内置"个股实时打分"面板：输入任意 6 位代码，浏览器端直连东方财富行情实时打分
- 每日更新: GitHub Actions 北京时间 15:35 自动运行（cron '35 7 * * *' UTC）
- 本地运行: `python etf_factor_score.py`（生成 docs/index.html + docs/factors.json）
