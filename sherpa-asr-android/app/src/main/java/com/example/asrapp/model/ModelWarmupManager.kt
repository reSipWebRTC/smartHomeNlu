package com.example.asrapp.model

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import com.example.asrapp.audio.TtsPlayer
import com.example.asrapp.audio.AudioPipeline
import com.example.asrapp.audio.MicRecorder
import com.k2fsa.sherpa.onnx.OfflineTts
import com.k2fsa.sherpa.onnx.Vad
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * 模型预热管理器
 *
 * 在应用启动时后台预热 ASR 和 TTS 模型，减少首次使用等待时间
 */
object ModelWarmupManager {
    private const val TAG = "ModelWarmupManager"

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val mutex = Mutex()

    // 预热状态
    private var warmupJob: Job? = null
    private var _asrWarmed = false
    private var _ttsWarmed = false

    // 缓存的模型实例（供 ViewModel 使用）
    private var cachedRecognizer: OnlineRecognizer? = null
    private var cachedVad: Vad? = null
    private var cachedTts: OfflineTts? = null

    // 状态监听
    private val listeners = mutableSetOf<Listener>()

    interface Listener {
        fun onAsrWarmed()
        fun onTtsWarmed()
    }

    /**
     * 预热状态
     */
    data class WarmupState(
        val asrWarmed: Boolean = false,
        val ttsWarmed: Boolean = false,
        val asrWarmupTime: Long = 0,
        val ttsWarmupTime: Long = 0
    )

    val currentState: WarmupState
        get() = WarmupState(
            asrWarmed = _asrWarmed,
            ttsWarmed = _ttsWarmed,
            asrWarmupTime = asrWarmupTime,
            ttsWarmupTime = ttsWarmupTime
        )

    private var asrWarmupTime: Long = 0
    private var ttsWarmupTime: Long = 0

    /**
     * 开始预热
     * @param context Application context
     * @param forceTts 是否强制预热 TTS（即使设置中未启用）
     */
    fun startWarmup(context: Context, forceTts: Boolean = false) {
        if (warmupJob?.isActive == true) {
            Log.d(TAG, "startWarmup: 预热已在进行中")
            return
        }

        warmupJob = scope.launch {
            Log.i(TAG, "startWarmup: 开始模型预热")

            // 先等待资源准备完成
            val prepareStart = System.currentTimeMillis()
            waitForAssetsReady(context)
            Log.d(TAG, "startWarmup: 资源准备耗时 ${System.currentTimeMillis() - prepareStart}ms")

            // 并行预热 ASR 和 TTS
            val asrJob = launch { warmupAsr(context) }
            val ttsJob = launch {
                if (shouldWarmupTts(context, forceTts)) {
                    warmupTts(context)
                } else {
                    Log.d(TAG, "startWarmup: TTS 未启用，跳过预热")
                }
            }

            asrJob.join()
            ttsJob.join()

            Log.i(TAG, "startWarmup: 预热完成 - ASR: ${if (_asrWarmed) "✓" else "✗"}($asrWarmupTime ms), TTS: ${if (_ttsWarmed) "✓" else "✗"}($ttsWarmupTime ms)")
        }
    }

    /**
     * 预热 ASR 模型
     */
    private suspend fun warmupAsr(context: Context) {
        if (_asrWarmed) {
            Log.d(TAG, "warmupAsr: ASR 已预热，跳过")
            return
        }

        mutex.withLock {
            if (_asrWarmed) return
            val startTime = System.currentTimeMillis()

            try {
                Log.d(TAG, "warmupAsr: 开始加载 ASR 模型")
                val recognizer = AsrModelLoader.createRecognizer(context)
                val vad = AsrModelLoader.createVad(context)

                // 执行一次空识别，确保模型完全初始化
                Log.d(TAG, "warmupAsr: 执行空识别以完全初始化模型")
                val stream = recognizer.createStream()
                try {
                    val samples = FloatArray(1600) { 0f }
                    stream.acceptWaveform(samples, 16000)
                    while (recognizer.isReady(stream)) {
                        recognizer.decode(stream)
                    }
                    recognizer.getResult(stream)
                } finally {
                    stream.release()
                }

                cachedRecognizer = recognizer
                cachedVad = vad
                _asrWarmed = true
                asrWarmupTime = System.currentTimeMillis() - startTime

                Log.i(TAG, "warmupAsr: ASR 预热完成，耗时 $asrWarmupTime ms")

                listeners.forEach { it.onAsrWarmed() }
            } catch (e: Exception) {
                Log.e(TAG, "warmupAsr: 预热失败", e)
                // 清理部分加载的模型
                cachedRecognizer?.release()
                cachedVad?.release()
                cachedRecognizer = null
                cachedVad = null
            }
        }
    }

    /**
     * 预热 TTS 模型
     */
    private suspend fun warmupTts(context: Context) {
        if (_ttsWarmed) {
            Log.d(TAG, "warmupTts: TTS 已预热，跳过")
            return
        }

        mutex.withLock {
            if (_ttsWarmed) return
            val startTime = System.currentTimeMillis()

            try {
                Log.d(TAG, "warmupTts: 开始加载 TTS 模型")
                val tts = TtsModelLoader.createTts(context)

                // 生成一句短文本以完全初始化模型
                Log.d(TAG, "warmupTts: 生成测试文本以完全初始化模型")
                tts.generate("测试", sid = 0, speed = 1.0f)

                cachedTts = tts
                _ttsWarmed = true
                ttsWarmupTime = System.currentTimeMillis() - startTime

                Log.i(TAG, "warmupTts: TTS 预热完成，耗时 $ttsWarmupTime ms")

                listeners.forEach { it.onTtsWarmed() }
            } catch (e: Exception) {
                Log.e(TAG, "warmupTts: 预热失败", e)
                cachedTts?.release()
                cachedTts = null
            }
        }
    }

    /**
     * 检查是否应该预热 TTS
     */
    private fun shouldWarmupTts(context: Context, force: Boolean): Boolean {
        if (force) return true
        val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)
        return prefs.getBoolean("tts_enabled", false)
    }

    /**
     * 等待资源准备完成
     */
    private suspend fun waitForAssetsReady(context: Context) {
        val maxWait = 10000L // 最多等待 10 秒
        val startWait = System.currentTimeMillis()

        while (System.currentTimeMillis() - startWait < maxWait) {
            if (AsrModelLoader.areAssetsReady(context) &&
                TtsModelLoader.areAssetsReady(context)) {
                return
            }
            delay(100)
        }

        Log.w(TAG, "waitForAssetsReady: 等待资源准备超时")
    }

    /**
     * 获取预热的 ASR 模型
     * @return Pair<Recognizer, VAD> 或 null（如果未预热）
     */
    fun takeAsrModels(): Pair<OnlineRecognizer, Vad>? {
        return synchronized(this) {
            if (!_asrWarmed) return null
            val recognizer = cachedRecognizer ?: return null
            val vad = cachedVad ?: return null
            cachedRecognizer = null
            cachedVad = null
            // 标记为未预热，因为模型已被取走
            _asrWarmed = false
            recognizer to vad
        }
    }

    /**
     * 获取预热的 TTS 模型
     * @return OfflineTts 或 null（如果未预热）
     */
    fun takeTtsModel(): OfflineTts? {
        return synchronized(this) {
            if (!_ttsWarmed) return null
            val tts = cachedTts ?: return null
            cachedTts = null
            // 标记为未预热，因为模型已被取走
            _ttsWarmed = false
            tts
        }
    }

    /**
     * 添加状态监听器
     */
    fun addListener(listener: Listener) {
        listeners.add(listener)
        // 如果已经预热完成，立即通知
        if (_asrWarmed) listener.onAsrWarmed()
        if (_ttsWarmed) listener.onTtsWarmed()
    }

    /**
     * 移除状态监听器
     */
    fun removeListener(listener: Listener) {
        listeners.remove(listener)
    }

    /**
     * 取消预热
     */
    fun cancel() {
        warmupJob?.cancel()
        warmupJob = null
    }

    /**
     * 释放所有资源
     */
    fun release() {
        cancel()
        cachedRecognizer?.release()
        cachedVad?.release()
        cachedTts?.release()
        cachedRecognizer = null
        cachedVad = null
        cachedTts = null
        _asrWarmed = false
        _ttsWarmed = false
        listeners.clear()
    }
}
