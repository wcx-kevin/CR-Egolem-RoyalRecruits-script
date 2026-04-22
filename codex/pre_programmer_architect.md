# Hypothesis
- 项目应由四层构成：入口/调度、战斗编排、识别与状态、资源与配置；入口负责 `deck`、`direct battle`、时间/圣水阶段参数，战斗编排负责按 deck 选择策略，识别层负责截图与卡牌识别，状态层负责 cycle 与 confidence。
- 核心状态应以卡牌循环模型表达，至少包含 `available`、`unavailable`、`removed`、置信度数组、卡牌别名归一化，以及“下一张牌”位置映射。
- 下牌逻辑应提供按名称下牌、按位置下牌、备选卡牌列表下牌三种入口，并在每次下牌后同步更新 cycle；若涉及英雄卡，还应有能力触发与冷却窗口。
- `format2` 结构应以“deck + 阶段 + 行号”的形式组织，典型签名应类似 `format2_<deck>_<stage>(delay, random_seed, line)`，并通过 `line` 决定具体出牌和等待节奏。
- `changeCycle` 结构应是 deck-aware 的循环调整器，包含“是否已就绪”的判定、Unknown 卡牌处理、超时退出、以及最小化切循环次数的策略。
- RR 最小可测试逻辑应至少包含：识别启动、cycle 初始化、一次切循环、以及一条可执行的最小 1x/2x/3x 线路，保证 deck 可以单独跑通。
- 资源组织上，应按 deck 分目录放卡面模板与全尺寸模板，并保留通用 `templates`、`tmp`、`debug_output` 供诊断。
- 输出规范上，运行日志应能覆盖中文提示与 deck 名称，便于直接从终端判断 battle、direct battle、识别失败与超时状态。

# Observed
- `main.py` 负责 CLI 引导，已支持 `--deck`、`--direct-battle`、`--list-decks`，并把 `time_stage` / `elixir_stage` 规范化后转发给主循环。
- `src/cr_bot/app/main_loop.py` 负责战斗会话与线程调度，使用 `GameStateDetector` 判断开局/结束，并在 `run_direct_battle()` 与普通 `run()` 两条路径中切换。
- `src/cr_bot/config/decks.py` 已有两个 deck 定义：`elixir_golem` 与 `royal_recruits`，包含 `display_name`、`strategy`、`card_template_groups` 和别名归一化。
- `src/cr_bot/paths.py` 已把资源按 `assets/decks/<deck>/cards`、`assets/decks/<deck>/cards_full`、`templates`、`debug_output`、`tmp` 组织起来；`elixir_golem` 还保留 legacy 模板目录。
- `src/cr_bot/core/card_config.py` 与 `src/cr_bot/core/comCycle.py` 构成 cycle 核心：卡牌别名归一化、`CARD_POOL`、单例 `CRCardCycle`、`available/unavailable/removed`、`set_card()`、`use_card()`、`find_card()`。
- `src/cr_bot/recognition/finalGetCards.py` 已实现识别器：按 deck 加载模板、支持 `cards` / `cards_full` / legacy 来源、截图采集、模板匹配和位置区域定义。
- `src/cr_bot/recognition/checkType.py` 已实现战局状态检测：识别开局颜色区域、结束模板、持续确认、直接对战确认，以及 start/end 线程。
- `src/cr_bot/gameplay/battle_timing.py` 已有 `time_stage` / `elixir_stage` 的别名归一化与 `BattleTimingSelection`。
- `src/cr_bot/gameplay/placeCard.py` 已有按名称/位置下牌、备选下牌、cycle 回写、以及英雄技能触发窗口逻辑。
- `src/cr_bot/gameplay/card_tracker.py` 已有 bootstrap、verify、reconcile after play 的闭环，负责把识别结果回灌到 cycle。
- `src/cr_bot/gameplay/getCycle.py` 负责 `init5()` 初始化与识别重试；`src/cr_bot/gameplay/changeCycle.py` 已实现按 deck 分支的切循环逻辑与 Unknown 重试。
- `src/cr_bot/gameplay/format2_elixir_golem.py`、`src/cr_bot/gameplay/format2_royal_recruits.py` 已分别提供 `1x/2x/3x` 三段、按 `line` 编号驱动的出牌序列，且通过 `random_seed` 派生 lane_offset。
- `src/cr_bot/gameplay/deck_runtime.py` 已把 deck 策略串起来：`init5()` -> `cycle.show_all()` -> `changeCycle()` -> 各阶段 `format2_*` 执行；`royal_recruits` 也已有最小 autoplay 路径。
- `README.md` 已明确支持 deck、direct battle 与 `royal_recruits` 的 minimal autoplay 说明。

# Gap
- Hypothesis 预期的是“接口契约更显式”的结构，但 Observed 主要是模块级函数 + 单例状态，契约依赖约定而非统一接口对象。
- Hypothesis 预期 RR 有独立的最小可测试入口；Observed 只有运行时内嵌的 minimal autoplay，没有单独的 RR smoke/test 入口。
- Hypothesis 预期 `format2` 结构可能更偏共享抽象；Observed 目前是两个 deck 各自硬编码 `1x/2x/3x` 行逻辑，没有共享的 `format2` 描述层。
- Hypothesis 预期 `changeCycle` 的 readiness/出牌策略可继续抽象；Observed 目前直接写死卡名、位置和延时，扩展新 deck 时需要手工复制同类逻辑。
- Hypothesis 预期中文输出应覆盖更多异常与阶段语义；Observed 已有中文日志，但部分核心类 docstring/注释存在编码噪声，降低可读性。

# Actionable Changes
- 仅补一层薄的共享契约说明，把 `format2_<deck>_<stage>` 的参数和 `line` 语义固定下来，避免未来 deck 扩展时各文件各写一套理解。
- 给 `royal_recruits` 补一个最小 smoke 路径，复用现有 `init5()`、`changeCycle()`、`format2_royal_recruits_1x()` 即可，不需要新重构。
- 把 `changeCycle` 的 readiness 条件和出牌候选表保持在同一处，减少新 deck 接入时的散落硬编码。
