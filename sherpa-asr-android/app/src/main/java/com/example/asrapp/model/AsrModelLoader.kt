package com.example.asrapp.model

import android.content.Context
import android.util.Log
import com.k2fsa.sherpa.onnx.EndpointConfig
import com.k2fsa.sherpa.onnx.EndpointRule
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.OnlineModelConfig
import com.k2fsa.sherpa.onnx.OnlineParaformerModelConfig
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import com.k2fsa.sherpa.onnx.OnlineRecognizerConfig
import com.k2fsa.sherpa.onnx.SileroVadModelConfig
import com.k2fsa.sherpa.onnx.Vad
import com.k2fsa.sherpa.onnx.VadModelConfig
import java.io.File

object AsrModelLoader {

    private const val TAG     = "AsrModelLoader"
    private const val ASR_DIR = "asr"
    private const val VAD_DIR = "vad"

    // ── Assets 预拷贝 ──────────────────────────────────────────────────────
    //
    // assets/asr/
    //   encoder.int8.onnx
    //   decoder.int8.onnx
    //   tokens.txt
    //
    // assets/vad/
    //   silero_vad.onnx
    //   下载：https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx

    fun prepareAssets(context: Context) {
        copyFolder(context, ASR_DIR)
        copyFolder(context, VAD_DIR)

        val asrDir = File(context.filesDir, ASR_DIR)
        listOf("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt").forEach { name ->
            val f = File(asrDir, name)
            if (f.exists()) Log.i(TAG, "✓ asr/$name (${f.length() / 1024} KB)")
            else            Log.e(TAG, "✗ MISSING: asr/$name")
        }
        val vadModel = File(context.filesDir, "$VAD_DIR/silero_vad.onnx")
        if (vadModel.exists()) Log.i(TAG, "✓ vad/silero_vad.onnx (${vadModel.length() / 1024} KB)")
        else                   Log.e(TAG, "✗ MISSING: vad/silero_vad.onnx")
    }

    fun areAssetsReady(context: Context): Boolean {
        val asrDir = File(context.filesDir, ASR_DIR)
        val vadDir = File(context.filesDir, VAD_DIR)
        return File(asrDir, "encoder.int8.onnx").exists() &&
            File(asrDir, "decoder.int8.onnx").exists() &&
            File(asrDir, "tokens.txt").exists() &&
            File(vadDir, "silero_vad.onnx").exists()
    }

    // ── OnlineRecognizer ──────────────────────────────────────────────────

    fun createRecognizer(context: Context): OnlineRecognizer {
        val dir = File(context.filesDir, ASR_DIR).absolutePath
        Log.i(TAG, "createRecognizer — dir: $dir")

        Log.i(TAG, "Step 1: loading sherpa-onnx-jni...")
        try {
            System.loadLibrary("sherpa-onnx-jni")
            Log.i(TAG, "Step 1: OK")
        } catch (e: UnsatisfiedLinkError) {
            Log.e(TAG, "Step 1: FAILED — ${e.message}")
            throw e
        }

        Log.i(TAG, "Step 2: building OnlineRecognizerConfig...")
        val config = OnlineRecognizerConfig(
            featConfig = FeatureConfig(
                sampleRate = 16000,
                featureDim = 80,
            ),
            modelConfig = OnlineModelConfig(
                paraformer = OnlineParaformerModelConfig(
                    encoder = "$dir/encoder.int8.onnx",
                    decoder = "$dir/decoder.int8.onnx",
                ),
                tokens     = "$dir/tokens.txt",
                numThreads = 4,
                debug      = false,
                provider   = "cpu",
                modelType  = "paraformer",
            ),
            endpointConfig = EndpointConfig(
                rule1 = EndpointRule(false, 2.0f, 0.0f),
                rule2 = EndpointRule(true,  1.1f, 0.0f),
                rule3 = EndpointRule(false, 0.0f, 20.0f),
            ),
            enableEndpoint = true,
            decodingMethod = "greedy_search",
            maxActivePaths = 4,
        )
        Log.i(TAG, "Step 2: OK")

        Log.i(TAG, "Step 3: creating OnlineRecognizer...")
        return try {
            val r = OnlineRecognizer(assetManager = null, config = config)
            Log.i(TAG, "Step 3: OK")
            r
        } catch (e: Exception) {
            Log.e(TAG, "Step 3: FAILED — ${e::class.simpleName}: ${e.message}")
            throw e
        }
    }

    // ── Vad (sherpa-onnx 内置 Silero VAD) ────────────────────────────────
    //
    // 类名是 Vad，不是 VoiceActivityDetector
    // empty() 检查缓冲区，不是 isEmpty()

    fun createVad(context: Context): Vad {
        val modelPath = File(context.filesDir, "$VAD_DIR/silero_vad.onnx").absolutePath
        Log.i(TAG, "createVad — model: $modelPath")

        val config = VadModelConfig(
            sileroVadModelConfig = SileroVadModelConfig(
                model              = modelPath,
                threshold          = 0.45f,   // 从0.5稍微降低，更容易检测开头语音
                minSilenceDuration = 0.45f,   // 秒：给句尾更多缓冲，避免尾音被截断
                minSpeechDuration  = 0.08f,   // 秒：保持对短音节的稳定性
                windowSize         = 512,     // samples，与 FRAME_SAMPLES 对齐
                maxSpeechDuration  = 30.0f,   // 秒：单句最长 30s
            ),
            sampleRate = 16000,
            numThreads = 1,
            provider   = "cpu",
            debug      = false,
        )

        return try {
            // assetManager = null → 使用绝对路径
            val vad = Vad(assetManager = null, config = config)
            Log.i(TAG, "createVad OK")
            vad
        } catch (e: Exception) {
            Log.e(TAG, "createVad FAILED — ${e::class.simpleName}: ${e.message}")
            Log.e(TAG, Log.getStackTraceString(e))
            throw e
        }
    }

    // ── 内部工具 ──────────────────────────────────────────────────────────

    private fun copyFolder(context: Context, folder: String) {
        val outDir = File(context.filesDir, folder).also { it.mkdirs() }
        val files  = context.assets.list(folder) ?: emptyArray()
        Log.i(TAG, "copyFolder: $folder (${files.size} files)")
        files.forEach { name ->
            val dst = File(outDir, name)
            if (!dst.exists()) {
                context.assets.open("$folder/$name").use { src ->
                    dst.outputStream().use { src.copyTo(it) }
                }
                Log.i(TAG, "  copied $name (${dst.length() / 1024} KB)")
            } else {
                Log.i(TAG, "  skip   $name (${dst.length() / 1024} KB)")
            }
        }
    }
}
