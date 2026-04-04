package com.example.asrapp.model

import android.content.Context
import android.util.Log
import com.k2fsa.sherpa.onnx.OfflineTts
import com.k2fsa.sherpa.onnx.OfflineTtsConfig
import com.k2fsa.sherpa.onnx.OfflineTtsMatchaModelConfig
import com.k2fsa.sherpa.onnx.OfflineTtsModelConfig
import com.k2fsa.sherpa.onnx.OfflineTtsVitsModelConfig
import java.io.File

object TtsModelLoader {
    private const val TAG = "TtsModelLoader"
    private const val TTS_DIR = "tts"

    enum class InstalledTtsKind {
        MATCHA_ZH_EN,
        VITS_ZH,
        VITS_EN,
        VITS_MULTI_SPEAKER,
        UNKNOWN,
    }

    fun prepareAssets(context: Context) {
        File(context.filesDir, TTS_DIR).deleteRecursively()
        copyFolder(context, TTS_DIR)
    }

    fun areAssetsReady(context: Context): Boolean {
        val dir = File(context.filesDir, TTS_DIR)
        if (!dir.exists()) return false
        return getInstalledTtsKind(context) != InstalledTtsKind.UNKNOWN
    }

    fun createTts(context: Context): OfflineTts {
        val dir = File(context.filesDir, TTS_DIR)
        require(dir.exists()) {
            "未找到 TTS 目录: ${dir.absolutePath}。请将模型放到 app/src/main/assets/tts/"
        }

        try {
            System.loadLibrary("sherpa-onnx-jni")
        } catch (e: UnsatisfiedLinkError) {
            Log.e(TAG, "loadLibrary failed: ${e.message}")
            throw e
        }

        val preferredConfig = buildConfig(dir, preferInt8 = true)
        return runCatching {
            OfflineTts(assetManager = null, config = preferredConfig)
        }.getOrElse { err ->
            val message = err.message.orEmpty()
            if ("protobuf" !in message.lowercase() && "parse" !in message.lowercase()) {
                throw err
            }

            Log.w(TAG, "Failed to load int8 TTS model, fallback to fp32: $message")
            val fallbackConfig = buildConfig(dir, preferInt8 = false)
            OfflineTts(assetManager = null, config = fallbackConfig)
        }
    }

    fun getInstalledTtsKind(context: Context): InstalledTtsKind {
        val dir = File(context.filesDir, TTS_DIR)
        if (!dir.exists()) {
            return InstalledTtsKind.UNKNOWN
        }

        if (File(dir, "matcha-icefall-zh-en/model-steps-3.onnx").exists()) {
            return InstalledTtsKind.MATCHA_ZH_EN
        }

        if (File(dir, "vits-aishell3/vits-aishell3.int8.onnx").exists()) {
            return InstalledTtsKind.VITS_MULTI_SPEAKER
        }

        if (File(dir, "vits-piper-en_US-lessac-medium/model.onnx").exists() ||
            File(dir, "vits-ljs/model.onnx").exists() ||
            File(dir, "vits-melo-tts-zh_en/model.onnx").exists()
        ) {
            return InstalledTtsKind.VITS_EN
        }

        if (File(dir, "model.onnx").exists() ||
            dir.listFiles()?.any {
                it.isDirectory && (
                    it.name.startsWith("vits-zh-hf-") ||
                        it.name.contains("vits-zh")
                    )
            } == true
        ) {
            return InstalledTtsKind.VITS_ZH
        }

        return InstalledTtsKind.UNKNOWN
    }

    private fun buildConfig(dir: File, preferInt8: Boolean): OfflineTtsConfig {
        val matchaDir = File(dir, "matcha-icefall-zh-en")
        val matchaModel = File(matchaDir, "model-steps-3.onnx")
        val matchaVocoder = File(matchaDir, "vocos-16khz-univ.onnx")
        val matchaTokens = File(matchaDir, "tokens.txt")
        val matchaLexicon = File(matchaDir, "lexicon.txt")
        val matchaDataDir = File(matchaDir, "espeak-ng-data")
        val matchaRuleFsts = listOf(
            File(matchaDir, "date-zh.fst"),
            File(matchaDir, "number-zh.fst"),
            File(matchaDir, "phone-zh.fst"),
        ).filter(File::exists).joinToString(",") { it.absolutePath }

        if (matchaModel.exists() && matchaTokens.exists() && matchaVocoder.exists()) {
            Log.i(TAG, "Detected Matcha model from APK assets: ${matchaDir.name}")
            return OfflineTtsConfig(
                model = OfflineTtsModelConfig(
                    matcha = OfflineTtsMatchaModelConfig(
                        acousticModel = matchaModel.absolutePath,
                        vocoder = matchaVocoder.absolutePath,
                        tokens = matchaTokens.absolutePath,
                        lexicon = matchaLexicon.takeIf(File::exists)?.absolutePath.orEmpty(),
                        dataDir = matchaDataDir.takeIf(File::exists)?.absolutePath.orEmpty(),
                    ),
                    numThreads = 2,
                    provider = "cpu",
                ),
                ruleFsts = matchaRuleFsts,
                maxNumSentences = 1,
            )
        }

        val vitsDirCandidates = dir.listFiles()
            ?.filter {
                it.isDirectory && (
                    it.name.startsWith("vits-") ||
                        it.name.contains("-vits-")
                    )
            }
            ?.sortedBy { it.name }
            .orEmpty()

        for (modelDir in vitsDirCandidates) {
            val preferredFiles = if (preferInt8) {
                listOf(
                    File(modelDir, "model.int8.onnx"),
                    File(modelDir, "${modelDir.name}.int8.onnx"),
                    File(modelDir, "model.onnx"),
                    File(modelDir, "${modelDir.name}.onnx"),
                )
            } else {
                listOf(
                    File(modelDir, "model.onnx"),
                    File(modelDir, "${modelDir.name}.onnx"),
                    File(modelDir, "model.int8.onnx"),
                    File(modelDir, "${modelDir.name}.int8.onnx"),
                )
            }
            val modelFile = preferredFiles.firstOrNull(File::exists) ?: continue
            val tokensFile = File(modelDir, "tokens.txt")
            val lexiconFile = File(modelDir, "lexicon.txt")

            if (modelDir.exists() && tokensFile.exists()) {
                Log.i(TAG, "Detected VITS model: ${modelDir.name}")
                return OfflineTtsConfig(
                    model = OfflineTtsModelConfig(
                        vits = OfflineTtsVitsModelConfig(
                            model = modelFile.absolutePath,
                            tokens = tokensFile.absolutePath,
                            dataDir = "",
                            lexicon = lexiconFile.takeIf(File::exists)?.absolutePath.orEmpty(),
                        ),
                        numThreads = 2,
                        provider = "cpu",
                    ),
                    maxNumSentences = 1,
                )
            }
        }

        // 标准模型检测
        val tokens = File(dir, "tokens.txt")
        val lexicon = File(dir, "lexicon.txt")
        val dataDir = File(dir, "espeak-ng-data")

        // 检测 aishell3 模型（多说话人，支持男女声）
        val aishell3Dir = File(dir, "vits-aishell3")
        val aishell3Model = File(aishell3Dir, "vits-aishell3.int8.onnx")
        val aishell3Tokens = File(aishell3Dir, "tokens.txt")
        val aishell3Lexicon = File(aishell3Dir, "lexicon.txt")

        if (aishell3Model.exists() && aishell3Tokens.exists()) {
            Log.i(TAG, "Detected VITS aishell3 multi-speaker model (supports male/female voices, int8 quantized)")
            return OfflineTtsConfig(
                model = OfflineTtsModelConfig(
                    vits = OfflineTtsVitsModelConfig(
                        model = aishell3Model.absolutePath,
                        tokens = aishell3Tokens.absolutePath,
                        dataDir = aishell3Dir.absolutePath,
                        lexicon = aishell3Lexicon.takeIf(File::exists)?.absolutePath.orEmpty(),
                    ),
                    numThreads = 2,
                    provider = "cpu",
                ),
                maxNumSentences = 1,
            )
        }

        val vitsModel = File(dir, "model.onnx")
        if (vitsModel.exists() && tokens.exists()) {
            Log.i(TAG, "Detected VITS TTS model in ${dir.absolutePath}")
            return OfflineTtsConfig(
                model = OfflineTtsModelConfig(
                    vits = OfflineTtsVitsModelConfig(
                        model = vitsModel.absolutePath,
                        tokens = tokens.absolutePath,
                        dataDir = dataDir.takeIf(File::exists)?.absolutePath.orEmpty(),
                        lexicon = lexicon.takeIf(File::exists)?.absolutePath.orEmpty(),
                    ),
                    numThreads = 2,
                    provider = "cpu",
                ),
                maxNumSentences = 1,
            )
        }

        error(
            "未识别到可用的 TTS 模型。当前支持:\n" +
                "1. vits-zh-hf-*: tts/vits-zh-hf-{name}/ (中文单说话人)\n" +
                "2. vits-aishell3: tts/vits-aishell3/vits-aishell3.int8.onnx (中文多说话人)\n" +
                "3. vits-piper-en_US-lessac-medium: tts/vits-piper-en_US-lessac-medium/\n" +
                "4. vits-ljs: tts/vits-ljs/\n" +
                "5. vits-melo-tts-zh_en: tts/vits-melo-tts-zh_en/\n" +
                "6. 通用旧目录: tts/model.onnx, tts/tokens.txt"
        )
    }

    private fun copyFolder(context: Context, folder: String) {
        val entries = try {
            context.assets.list(folder) ?: emptyArray()
        } catch (_: Exception) {
            emptyArray()
        }

        if (entries.isEmpty()) {
            Log.w(TAG, "No bundled assets found in $folder/")
            return
        }

        copyAssetTree(context, folder, File(context.filesDir, folder))
    }

    private fun copyAssetTree(context: Context, assetPath: String, output: File) {
        val children = context.assets.list(assetPath) ?: emptyArray()
        if (children.isEmpty()) {
            output.parentFile?.mkdirs()
            context.assets.open(assetPath).use { src ->
                output.outputStream().use { src.copyTo(it) }
            }
            Log.i(TAG, "Copied $assetPath")
            return
        }

        output.mkdirs()
        children.forEach { child ->
            copyAssetTree(context, "$assetPath/$child", File(output, child))
        }
    }
}
