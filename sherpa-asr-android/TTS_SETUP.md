# TTS Setup Guide

## Overview
This project now includes offline TTS based on `sherpa-onnx` and is wired into the existing ASR app flow. The current model is `vits-zh-aishell3` (int8 quantized), which supports **174 different speakers including both male and female voices**.

## Installed Model
- Source: official sherpa-onnx TTS releases
- Model: `vits-zh-aishell3` (int8 quantized, ~38MB)
- Speakers: 174 speakers (male + female)
- Language: Chinese
- Reference: https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/vits.html

## Required Asset Layout
TTS assets are loaded from:

```text
app/src/main/assets/tts/
└── vits-aishell3/                # All aishell3 model files in one directory
    ├── vits-aishell3.int8.onnx   # Model file (38MB, int8 quantized)
    ├── tokens.txt                # Token list
    ├── lexicon.txt               # Lexicon for pronunciation
    ├── date.fst                  # Date processing rules
    ├── new_heteronym.fst         # Heteronym processing rules
    ├── number.fst                # Number processing rules
    ├── phone.fst                 # Phonetic rules
    └── rule.far                  # Additional rules (180MB)
```

These files are already installed in the repository workspace.

## App Usage
1. Open the app.
2. Go to `Settings`.
3. Enable `离线 TTS`.
4. Adjust:
   - `语速`: default `1.0`
   - `说话人 ID`: **0-173** (174 speakers available, includes both male and female)
     - IDs 0-86: mostly female speakers
     - IDs 87-173: mostly male speakers
5. Return to the main screen and use:
   - `播报原文`
   - `播报纠正后`
   - `停止`

## Current Implementation
- Loader: `app/src/main/java/com/example/asrapp/model/TtsModelLoader.kt`
- Playback: `app/src/main/java/com/example/asrapp/audio/TtsPlayer.kt`
- ViewModel integration: `app/src/main/java/com/example/asrapp/viewmodel/AsrViewModel.kt`
- Settings UI: `app/src/main/java/com/example/asrapp/ui/SettingsScreen.kt`
- Main screen controls: `app/src/main/java/com/example/asrapp/ui/AsrScreen.kt`

## Notes
- TTS is stopped automatically when recording starts, to avoid acoustic feedback.
- Long text is split by sentence before synthesis.
- If `app/src/main/assets/tts/` is missing or incomplete, the app will show a TTS initialization error instead of affecting ASR.
- The current loader supports: aishell3 (multi-speaker), Kokoro, and basic VITS models.
- **Int8 quantized model** provides better performance on Android with minimal quality loss.

## Speaker ID Guide (aishell3)
| Speaker ID | Gender | Description |
|------------|--------|-------------|
| 0 | Female | Default speaker |
| 1-86 | Female | Various female speakers |
| 87-173 | Male | Various male speakers |

## Verification
The project was rebuilt successfully after installing the model:

```bash
./gradlew assembleDebug
```
