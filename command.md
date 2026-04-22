Quick commands

# adjust specific details based on your menu
# python version: 3.10.20

Setup:

```powershell
cd E:\cr\Clash-Royal-Script
conda activate cr_env
python .\doctor.py --strict-resolution --deck elixir_golem
powershell -ExecutionPolicy Bypass -File .\run_main.ps1 -Init -Deck elixir_golem
```

Run by deck:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_main.ps1 -Deck elixir_golem
powershell -ExecutionPolicy Bypass -File .\run_main.ps1 -Deck royal_recruits
```

Run current battle directly:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_main.ps1 -Deck elixir_golem -DirectBattle
powershell -ExecutionPolicy Bypass -File .\run_main.ps1 -Deck royal_recruits -DirectBattle
```

test
e-golem

python .\doctor.py --strict-resolution --deck e_golem
python .\battle_debug_recorder.py --deck e_golem --duration 900 --interval 2 --save-crops

rr

python .\doctor.py --strict-resolution --deck royal_recruits
python .\battle_debug_recorder.py --deck royal_recruits --duration 900 --interval 2 --save-crops


Notes:

- Accepted deck aliases: `elixir_golem` / `e_golem` / `egolem`, `royal_recruits` / `rr`.
- `-DirectBattle` skips battle-start waiting and does not continue to the next battle loop.
- `royal_recruits` now has a minimal autoplay routine for follow-up tuning.
