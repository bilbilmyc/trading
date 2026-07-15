# Frontend Overhaul v0.4 — Design Thesis

> 取代"再做一次 KPIHero"作为迭代方向。本文件定义 6 项**结构性**变更，
> 不是又一轮样式微调。

## 1. Subject 与 Single Job

- **Subject**：个人量化交易员在自部署的 localhost 永续合约 Dashboard 上盯盘。
- **Single Job per page**：告诉我现在暴露了多少、最近一笔交易发生了什么、
  我的风控阈值踩没踩、机器人是不是活着的。

> 之前的迭代反复做"大数字面板"。这是模板答案。这一版以**信息密度优先**
> 而不是"陈列感"优先。

## 2. 三个 AI-生成 Default 我明确回避

| Default look | 我现在的现状 | 是否回避 |
| --- | --- | --- |
| Cream + serif + terracotta | 不适用 | ✓ |
| Near-black + acid-green | 接近（indigo/purple 玻璃化） | ✓ 引入 hairline-replace-glass |
| Broadsheet + hairline + newspaper column | 不适用 | ✓ |

**调整**：保留 dark + indigo 主体，但把"`glass` / `glow` / 渐变按钮"压到只剩
两处（brand mark + 主 CTA）；其它一律 1px hairline + 0px shadow。

## 3. Token 体系补充（styles.css 增量）

```css
:root {
  /* Mono numerics — used by EVERY numeric surface */
  --font-num: "JetBrains Mono", "SF Mono", Menlo, monospace;
  --num-tracking: -0.01em;
  --num-leading: 1.15;
  /* Hairlines — replaces 90% of glass-card */
  --hairline: 1px solid var(--border);
  --hairline-strong: 1px solid var(--border-strong);
  /* Spine — the signature element */
  --spine-width: 4px;
  --spine-segment-gap: 1px;
  /* Tile sizes — every 4px, but specifically these */
  --tile-h-sm: 64px;   /* row tile, inline KPI */
  --tile-h-md: 96px;   /* page hero strip row */
  --tile-h-lg: 144px;  /* big stat */
}
```

## 4. 6 项结构性变更

### A. **The Spine**（signature element）
4px 宽的竖向状态带，贴在主内容区左边，从上到下：
- 行 1：API online（绿/红 1px hairline 块）
- 行 2：实盘模式（中性 / 警示）
- 行 3：Risk / Kill Switch（关 = 灰，开 = 红）
- 行 4：Bot 状态（disabled = 灰，enabled = 青，alerting = 黄橙呼吸）
- 行 5：Drawdown 当前值（绿→黄→红的渐变背景填充，按比例）

特征：**不占任何横向宽度**（用 `flex-shrink` 配合负 margin 反向吸收）。
设计师的一句话："the spine is the only chrome I added — every other pixel is data"。

### B. **Live TopTicker**
现状是 `SAMPLE_ITEMS` 硬编码 BTC 价格。改为：复用 `engine.ticker` SSE-like
轮询（每 3s）调用 `/api/v1/ticker/binance_usdm` for each watch symbol。
无数据时显示占位 `—` 而不是假数据。

### C. **StatusDrawer**
底部抽屉：`max-height: 28vh`，默认收起。展开后展示最近 50 条 monitor alert
（实时通过 `/api/v1/events/recent?limit=50`）。CRITICAL/ERROR 红条在最上方，
WARNING 灰条，INFO 点缀。点 alert 跳转到 `/audit?event_id=...`。

### D. **BotMonitorPage**
`/bot` 路由（与 Settings、Risk 同组）。三块：
1. Bot 状态卡（启用/未启用；如启用：token 后 4 位；当前 chat 列表；最近 error）
2. 命令速查表（按用户选择：列出 /status /pnl 等的 HTML 预览）
3. Quiet Hours 可视化（24h 条 + 当前小时指示器 + 配置输入）
4. 与 `/api/v1/risk/kill-switch` 同屏显示的 "kill from Telegram" 演示按钮

### E. **Inline-Style Cleanup**
Sidebar/Topbar 内联 style 全清空：
- `style={{display: "flex", gap: 6}}` → `.flex-row { display:flex; gap: var(--space-2); }`
- `<Sidebar 局部 ProgressBar>` 抽出到 `components/ProgressBar.tsx`
- 全部颜色用 `var(--*)`，不写 hex

完成后 `style={{` 在主要组件中出现次数 ≤ 3 处。

### F. **Tabular Numerics Default**
新增 `app/styles.css` 一行：
```css
.num {
  font-family: var(--font-num);
  font-variant-numeric: tabular-nums;
  letter-spacing: var(--num-tracking);
  line-height: var(--num-leading);
}
```
所有 `KPIHero.value`、表格数字、图表轴标签默认套 `<span class="num">`。
视觉后果：**所有数字对齐**，像终端一样可读。

## 5. 不在这次覆盖范围内（明确拒绝）

- ❌ 重写 KPIHero 颜色 / 渐变预设；
- ❌ 新增更多 preset 渐变；
- ❌ 拆 `api.ts` 之外的更多组件（本次不做大搬家）；
- ❌ 引入 UI 库（Mantine / Chakra / shadcn）；
- ❌ 加图表库（Recharts/Plotly）—— chart 走 SVG，保持手写；
- ❌ 暗色模式 toggle 的二次设计（已 OK）。

## 6. Reference 项目（不进外观，但是方法论参考）

| 项目 | 学到 |
| --- | --- |
| **TradingView Pro** | 数据密度优先；hairline > shadow；mono 用于一切数值 |
| **Hyperliquid UI** | glow 用得克制；spine-like 边条作为状态带 |
| **Reflexer RAI** | monochrome + 单 accent，避免饱和 |
| **Linear** | 类型层级清晰，避免装饰性 padding |
| **Vercel Analytics** | 几乎零 chrome；所有空白都是有意义的 |
| **Raycast Store** | side panel 内容密度高于 chrome |

## 7. Commit Plan

每个改动单独一个 commit，方便回滚：

1. `feat(ui): 加 The Spine — 4px 竖向状态带作为 signature`
2. `feat(ui): Live TopTicker — 真实 ticker 价格（不再用硬编码）`
3. `feat(ui): StatusDrawer — 底部抽屉，最近 50 条 alert`
4. `feat(ui): BotMonitorPage — bot 配置 + 命令速查 + quiet hours`
5. `refactor(ui): 抽 ProgressBar + 清 Sidebar/Topbar 内联 style`
6. `style(ui): tabular-nums default — 所有数字对齐`

## 8. 不重写原则

每次动手前自问：
1. 这是第 6 次 KPIHero 化的诱惑吗？
2. 我加的玻璃/glow 在不用它的版本里照样能读吗？
3. 这一格我自己站到两米外还能看见吗？

答否的，砍掉。
