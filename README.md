[English](./README.md) | [简体中文](./README.zh-CN.md)

## Project Overview

This is a vision-driven control project for automated battles in *Chinese Mainland version of Clash Royale*, with the goal of completing match recognition, card state tracking, resource tempo management, and automatic card deployment on an Android emulator or Android device.

The project currently focuses on two built-in decks:

* `Elixir Golem` automated playstyle.
* `Royal Recruits` automated playstyle.

This project Uses the MuMu emulator to emulate the Chinese mainland version of Clash Royale; users need to configure the environment themselves.

## Overall Goals and Uses

* Enable the program to automatically enter or take over battles, and continuously execute card deployment logic throughout an entire match.
* Enable the program to recognize the cards in the current match, the hand order, the next card, and the current battle phase.
* Enable the program to manage resource tempo based on the deck and the current phase, avoiding ineffective card deployment or resource loss of control.
* Enable the program to support different operating modes, including normal matchmaking loops, directly taking over the current battle, debug sampling, and offline evaluation.
* Enable the program to provide repeatable records, samples, and validation methods for recognition and strategy tuning.

## Libraries and Their Roles

* `opencv-python`: used for screenshot processing, region cropping, template matching, and color and edge feature analysis.
* `numpy`: used for image array operations, mask calculations, and numerical statistics.
* `uiautomator2`: used to connect to Android devices or emulators, and perform screenshots, taps, and app foreground control.
* `Pillow`: used for font template generation for text regions and character-level recognition assistance.
* Python standard library: used for command-line arguments, threads, time control, process invocation, file paths, and runtime state management.

## Module Breakdown

### Device and Runtime Entry

* Responsible for program startup, argument parsing, deck selection, and runtime mode switching.
* Responsible for connecting to Android devices or emulators, and providing a unified entry point for subsequent visual recognition and tap operations.
* Responsible for connecting the two runtime methods: the “normal battle loop” and “direct takeover of the current battle.”

### Screen Perception and State Determination

* Responsible for determining from device screenshots whether a battle has started, whether it has ended, and whether the current screen is still a valid battle interface.
* Responsible for reading battle time and phase information, and dividing the match into tempo intervals such as single elixir, double elixir, and triple elixir.
* Responsible for providing stable “start / end / phase change” signals to the main process.

### Card Recognition and Deck Order Tracking

* Responsible for recognizing the current hand, the pending draw card, and the next card from the card area.
* Responsible for maintaining the card cycle state, and continuously correcting card order information in the states of “known, unknown, pending confirmation.”
* Responsible for rechecking before and after card deployment to reduce the impact of recognition errors on the battle flow.

### Battle Flow and Card Deployment Strategy

* Responsible for converting recognized card states into actual card deployment actions.
* Responsible for executing phase-based playstyles according to the tempo templates of different decks.
* Responsible for handling champion abilities, resource pressure, and tempo switching at key moments.
* Responsible for synchronously updating cycle state and resource state after card deployment, ensuring consistency in subsequent decisions.

### Resource and Tempo Management

* Responsible for linking card cost, ability cost, and current resource consumption.
* Responsible for estimating the resource recovery rate according to the battle phase, and avoiding out-of-bound operations when resources are low or at critical levels.
* Responsible for resetting or settling resource state when the battle starts, ends, and changes phase.

### Debugging, Sampling, and Evaluation Tools

* Responsible for collecting battle screenshots, key region samples, and debug records.
* Responsible for offline evaluation and efficiency comparison of recognition performance.
* Responsible for checking whether the environment, resolution, and device connection are available before startup.

## Method Overview

* Uses a closed-loop control approach of “device screenshots + visual recognition + automatic taps.”
* Uses template matching, region cropping, and combined color / edge / texture judgment to recognize cards and battle information.
* Uses multi-frame observation and result voting to improve recognition stability and reduce the impact of single-frame noise.
* Uses a cycle state machine to represent the relationship among the hand, discard pile, and pending draw cards, and corrects the state through rechecks before and after card deployment.
* Uses a battle-phase-driven resource management approach, unifying tempo, cost, and ability release into the same runtime state.
* Uses a deck-specific strategy approach to separate the general process from specific playstyles, making it easier to extend new deck plans.

## Typical Battle Scenarios

* Normal automatic consecutive matches: wait for matchmaking, recognize the opening, execute the full-match playstyle, and enter the next match after settlement.
* Direct takeover of the current battle: skip the waiting process, directly enter an ongoing match, and continue executing the automated playstyle.
* Deck-specific playstyles: switch between different tempos in single elixir, double elixir, and triple elixir phases around a fixed deck.
* Recognition debugging: collect screenshots, check card recognition performance, and analyze misrecognitions and unknown cards.
* Offline evaluation: evaluate accuracy and time consumption on historical screenshot samples to compare recognition schemes.

## Summary

The core of this project is not a single “automatic tapping” function, but a complete automation system built around the *Clash Royale* battle interface: first perceive the state, then maintain card order and resources, then execute operations according to the deck tempo, and finally continuously calibrate recognition and strategy through debugging and evaluation tools.
