# SherpaAsrApp

Android 端侧实时语音识别，完全本地推理，无需网络。

## 技术栈

| 组件 | 方案 |
|---|---|
| ASR 引擎 | sherpa-onnx `OnlineRecognizer` |
| ASR 模型 | streaming-paraformer-bilingual-zh-en int8 |
| VAD | Silero VAD（android-vad） |
| UI | Jetpack Compose + Material 3 |

## 运行前准备：下载模型文件

模型文件体积较大，不包含在代码仓库中，需手动下载后放入 assets。

### 1. ASR 模型（~226 MB）

前往 sherpa-onnx releases 页面下载：
https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models

找到 `sherpa-onnx-streaming-paraformer-bilingual-zh-en` 的 int8 版本，
解压后将以下 4 个文件复制到：

```
app/src/main/assets/asr/
├── encoder.int8.onnx
├── decoder.int8.onnx
├── joiner.int8.onnx          # 如果模型包含的话
└── tokens.txt
```

> 注：不同版本模型文件名可能略有差异，以下载包内实际文件名为准，
> 并同步修改 `AsrModelLoader.kt` 中对应的文件路径。

### 2. VAD 模型（~2 MB）

```
app/src/main/assets/vad/
└── silero_vad.onnx
```

下载地址：
https://github.com/gkonovalov/android-vad/raw/master/vad/silero_vad.onnx

## 项目结构

```
app/src/main/java/com/example/asrapp/
├── AsrApplication.kt          应用入口，预拷贝 assets
├── MainActivity.kt            Activity 入口
├── audio/
│   ├── MicRecorder.kt         AudioRecord 采集（16kHz Float32）
│   └── AudioPipeline.kt       VAD + sherpa-onnx 流式推理
├── model/
│   └── AsrModelLoader.kt      模型加载 / assets 拷贝
├── utils/
│   └── FillerWordFilter.kt    填充词过滤（啊/嗯/重复词）
├── viewmodel/
│   └── AsrViewModel.kt        状态管理
└── ui/
    ├── AsrScreen.kt            主界面 Composable
    └── theme/
        └── Theme.kt            Material 3 主题
```

## 构建

```bash
./gradlew assembleDebug
```

最低 SDK：26（Android 8.0）
目标 SDK：34
NDK ABI：arm64-v8a, armeabi-v7a

## 性能参考（Snapdragon 8 Gen 2）

| 指标 | 数值 |
|---|---|
| 首字延迟 | 300–600 ms |
| 逐字输出间隔 | ~100 ms |
| 推理内存占用 | ~500 MB |
| VAD 每帧耗时 | < 3 ms |

## 可选优化

**NNAPI 加速**：在 `AsrModelLoader.kt` 中将 `provider = "cpu"` 改为 `"nnapi"`，
高端机推理速度提升 30–50%（需运行时检测是否支持）。

**调整灵敏度**：`AudioPipeline.kt` 中的 `SILENCE_COMMIT_FRAMES` 控制句尾切分时机，
默认 600 ms，可根据业务场景调整。
