# `rr` 规则研究报告

## 1. `rr` 的仓内含义
- 本仓库里，`rr` 选择性地对应 `royal_recruits`，也就是 **Royal Recruits / Royal Hogs** 这套体系；`run_main.ps1:53` 只把 `royalrecruits` 归一化到 `royal_recruits`，`src/cr_bot/config/decks.py:43` 也只定义了这一套 `rr` deck。
- `README.md:10` 与 `README.md:51` 把它描述成“recognition enabled + minimal autoplay”，所以这里把 `rr` 明确解释为“Royal Recruits 自动脚本”，不是别的缩写。

## 2. 卡组身份与阶段攻击性
- 这是一套 **分路压制 + 控场反打** 卡组，不是纯 beatdown。
- `Heuristic`：单倍圣水以防守、探牌、稳循环为主；不要急着把双赢条件同时丢出去。
- `Heuristic`：双倍圣水开始转向主动施压，靠 `Royal Recruits`、`Royal Hogs`、`Golden Knight` 逼对手交解牌。
- `Heuristic`：三倍圣水进入高节奏连压，但仍要保留一张稳定防守锚点，避免“一波打空后全线崩盘”。

## 3. 默认脚本结构
`src/cr_bot/gameplay/format2_royal_recruits.py:12`、`src/cr_bot/gameplay/format2_royal_recruits.py:31`、`src/cr_bot/gameplay/format2_royal_recruits.py:56` 给出了三段固定模板；`random_seed % 2` 只负责左右镜像偏置。

| 卡牌 | 角色 | 默认脚本位置 | 说明 |
|---|---|---:|---|
| `Royal Recruits` | 分路骨架 / 防守拆分 | 1x `lane_offset`；2x `lane_offset`；3x `4 + lane_offset` | 先分兵，再压节奏；不要和 `Hogs` 同波同线硬堆 |
| `Royal Hogs` | 主胜利条件 | 1x `8 + lane_offset`；2x `9 - lane_offset`；3x `8 + lane_offset` | 更像“逼解牌”的推进件，常接在防守后或对手交费后 |
| `Flying Machine` | 远程空中输出 | 1x `6 + lane_offset`；2x `6 + lane_offset`；3x `6 + lane_offset` | 全阶段都保持中后排支援位，优先保命和持续输出 |
| `Goblin Cage` | 防守建筑 / 拉扯锚点 | 1x `4 + lane_offset`；3x `4 + lane_offset` | 负责拦地面推进、拉扯、给后排争取输出时间 |
| `Golden Knight` | 英雄位 / 节奏反打 | 2x `3 - lane_offset`；3x `3 - lane_offset` | 当前仓库只脚本化“下卡”，没有能力键宏，能力时机只能做 `Estimate` |
| `Zappies` | 眩晕 / 重置 / 控场 | 1x `4 + lane_offset`；2x `4 + lane_offset`；3x `5 - lane_offset` | 既能防守也能给反打制造停顿窗口 |
| `Barbarian Barrel` | 低费清场 / 循环修正 | 2x `10 + lane_offset`；3x `10 + lane_offset` | 典型“防溢出”与“收残血”用牌 |
| `Arrows` | 群体清场 / 保险牌 | 2x `11 - lane_offset`；3x `11 - lane_offset` | 保留给群怪、空军、和被迫补循环时的低风险出牌 |

## 4. Hero 处理：`Golden Knight`
- `Heuristic`：`Golden Knight` 在这个仓库里应被视为“英雄/Champion 节奏卡”，不是单独的开局核弹。
- 当前代码没有任何“英雄技能触发”宏；所以能力时机只能按 **下卡后的一段窗口** 来近似，而不能按帧级精确控制。
- `Estimate`：能力时机优先按“能连到 2 个及以上目标”来估算，或者在对手地面单位靠拢、过河、站成一条线时触发；不要在空线、单体、或明显吃亏的站位上强开。
- `Heuristic`：更稳妥的用法是，把他当作 **桥头反打 / 中距离收割 / 迫使对手分散解牌** 的卡，而不是孤立冲锋牌。

## 5. `Flying Machine` 与关键卡的脚本用法
- `Flying Machine`：永远优先放在“有肉盾、有干扰、有节奏”的场景里。脚本把它固定在 `6 + lane_offset`，说明它的定位是 **后排持续火力**，不是先手探路牌。
- `Heuristic`：`Flying Machine` 不要和明显会吃法术价值的位置叠在一起；如果对手解牌已明牌，宁可后移一格，也不要为了抢一点输出把整张卡交掉。
- `Royal Recruits`：是整套牌的地基。单倍圣水偏保守分散，双倍开始拿来做节奏起手，三倍则可以更靠前、更频繁地压场。
- `Royal Hogs`：是主要终结器。它的价值不在“单次冲塔伤害”，而在 **逼迫对方在错误时间出手**，给 `Flying Machine`、`Zappies`、`Golden Knight` 留出二波空间。
- `Goblin Cage`：是防守锚点和节奏重置器；脚本里它和 `Flying Machine` 的循环优先级很高，说明它负责“别让一波崩到底”。
- `Zappies`：负责打断、防守、拖延，常用于保护 `Flying Machine` 或给 `Hogs` 争取输出时间。
- `Barbarian Barrel` / `Arrows`：是低风险循环卡，不只是清场，也是在卡手时“开出口”的工具。

## 6. 循环逻辑、抗溢出、抗过度投入
- `src/cr_bot/gameplay/changeCycle.py:127` 起的 RR 循环目标很明确：让 `royal_recruits` 可用，同时把 `royal_hogs` 压到 5 以内、`flying_machine` 压到 6 以内、`goblin_cage` 压到 7 以内。
- `src/cr_bot/gameplay/changeCycle.py:132` 的循环优先消耗顺序是 `Barbarian Barrel` → `Arrows` → `Zappies` → `Golden Knight`，如果这些都不可用，再回退到 `Goblin Cage` / `Flying Machine` / `Royal Hogs` / `Royal Recruits`。
- `Heuristic`：这就是本脚本的抗溢出阀门；当关键卡还没转回来时，先用低风险卡“开循环”，不要硬等高费连动。
- `src/cr_bot/gameplay/changeCycle.py:11` 和 `src/cr_bot/gameplay/changeCycle.py:12` 还说明了两个保护：循环超时 90 秒、`Unknown` 最多重试 4 次；这能避免识别失败时无限等待。
- `Heuristic`：抗过度投入的核心原则是 **同一波里不要把 `Royal Recruits`、`Royal Hogs`、`Flying Machine` 全堆在同一路**。这套牌最怕“单波全压后被一张法术/一组防守同时化解”。
- `Heuristic`：抗“一波脆弱性”的做法是分层出牌：先锚定 `Cage` / `Zappies`，再上 `Flying Machine`，最后用 `Hogs` 或 `Recruits` 做压力收尾。

## 7. 单 / 双 / 三倍圣水脚本计划
`src/cr_bot/gameplay/deck_runtime.py:83` 到 `src/cr_bot/gameplay/deck_runtime.py:124` 给出的默认 autoplay 顺序是三段式，下面把它整理成更稳健的脚本计划：

### 单倍圣水
- `Heuristic`：目标是“探牌 + 防守 + 不亏费”。
- 优先顺序：`Goblin Cage` → `Flying Machine` → `Royal Hogs` → `Zappies` → `Royal Recruits`。
- 只在对手交过关键解牌、或你已经拿到防守收益时，才考虑把 `Hogs` / `Recruits` 作为主动波。
- `Estimate`：这一阶段应以保守节奏为主，给后续双倍圣水留核心牌和循环余量。

### 双倍圣水
- `Heuristic`：进入主攻前奏，开始用 `Royal Recruits` 打拆分，用 `Flying Machine` 补输出，用 `Golden Knight` 做桥头节奏。
- 默认模板里已经开始出现 `Golden Knight`、`Barbarian Barrel`、`Arrows`，说明这一段的核心是 **拆解对手防线后立刻接压**。
- `Heuristic`：如果对手已经露出清场法术，就把 `Flying Machine` 往更安全的中后排放，别贪前压。
- `Heuristic`：双倍阶段最重要的是“别让自己手里同时卡着两张重牌”，一旦卡手，优先用 `Barbarian Barrel` / `Arrows` / `Zappies` 打开循环。

### 三倍圣水
- `Heuristic`：进入高频压制期，默认节奏应当是 `Hogs` 与 `Recruits` 交替施压，`Flying Machine` 和 `Zappies` 负责把对手的防守变成迟滞。
- `Golden Knight` 在这里更像“反打扳机”，而不是纯输出卡；能连冲就冲，不能连冲就保留作为后续节奏点。
- `Heuristic`：三倍阶段最怕一波全梭哈后没有后续，所以必须保留至少一张防守锚点，通常是 `Goblin Cage` 或 `Zappies`。
- `Estimate`：如果局面进入拉扯优势，三倍阶段可以用更激进的分路压制换塔，但前提仍然是“下一轮防守可回收”。

## 8. 结论
- `rr` 在仓内应明确解释为 `royal_recruits`，即 Royal Recruits / Royal Hogs 分路压制卡组。
- 这套脚本的最稳健思路不是“记固定连招”，而是 **保循环、保锚点、分路压、少一次性梭哈**。
- 真正要写进脚本的优先级是：先让关键卡回到可用位，再根据圣水阶段决定是防守探牌、双路施压，还是三倍圣水连压。
