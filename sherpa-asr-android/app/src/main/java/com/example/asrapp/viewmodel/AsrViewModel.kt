package com.example.asrapp.viewmodel

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.SharedPreferences
import androidx.annotation.RequiresPermission
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.asrapp.NetworkMonitor
import com.example.asrapp.audio.AudioPipeline
import com.example.asrapp.audio.MicRecorder
import com.example.asrapp.audio.TtsPlayer
import com.example.asrapp.model.AsrModelLoader
import com.example.asrapp.model.TtsModelLoader
import com.example.asrapp.network.NetworkConfig
import com.example.asrapp.network.WordfillerApiClient
import com.example.asrapp.network.model.SmartHomeResponse
import com.example.asrapp.router.AsrCorrectionResult
import com.example.asrapp.router.AsrImmediateResult
import com.example.asrapp.router.ResultRouter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID

// ── UI state ──────────────────────────────────────────────────────────────────

data class AsrUiState(
    val finalText:    String  = "",
    val partialText:  String  = "",
    val isListening:  Boolean = false,
    val isSpeaking:   Boolean = false,
    val isLoading:    Boolean = false,
    val error:        String? = null,

    // 纠错相关状态
    val isCorrecting: Boolean = false,              // 是否正在等待纠错
    val correctedText: String = "",                 // 纠错后的完整文本
    val pendingCorrections: Map<Int, SentenceCorrection> = emptyMap(),  // 按句子索引的纠错
    val detectedCommands: List<CommandInfo> = emptyList(),              // 解析的命令
    val networkAvailable: Boolean = true,           // 网络状态

    // 识别时间统计
    val asrLatencyMs: Float = 0f,                  // ASR识别延时（毫秒）
    val correctionLatencyMs: Float = 0f,            // 纠错处理延时（毫秒）
    val totalLatencyMs: Float = 0f,                // 总延时（毫秒）

    // 上传状态
    val isUploading: Boolean = false,               // 是否正在上传
    val uploadSuccess: Boolean = false,             // 上传是否成功
    val uploadError: String? = null,                // 上传错误信息
    val pendingConfirmToken: String? = null,        // 待确认令牌
    val pendingConfirmMessage: String? = null,      // 待确认提示文案
    val isConfirming: Boolean = false,              // 是否正在提交确认
    val confirmError: String? = null,               // 确认失败信息

    // TTS 状态
    val isTtsEnabled: Boolean = false,
    val isSpeakingTts: Boolean = false,
    val ttsSpeed: Float = 1.0f,
    val ttsSpeakerId: Int = 0,
    val ttsError: String? = null
)

/**
 * 句子级别的纠错信息
 */
data class SentenceCorrection(
    val index: Int,
    val original: String,
    val corrected: String,
    val corrections: List<com.example.asrapp.network.model.DiffSpan>,
    val commands: List<com.example.asrapp.network.model.CommandInfo>,
    val confidence: Float,
    val processingTimeMs: Float
)

/**
 * 智能家居命令信息（UI用）
 */
data class CommandInfo(
    val action: String,      // 打开/关闭
    val device: String,      // 射灯/空调
    val location: String? = null,  // 二楼/客厅
    val description: String  // 完整描述
) {
    companion object {
        fun fromNetworkCommand(cmd: com.example.asrapp.network.model.CommandInfo): CommandInfo {
            val loc = cmd.location?.let { "在$it" } ?: ""
            val desc = "${cmd.action}${cmd.device}$loc".trim()
            return CommandInfo(
                action = cmd.action,
                device = cmd.device,
                location = cmd.location,
                description = desc
            )
        }
    }
}

// ── ViewModel ─────────────────────────────────────────────────────────────────

class AsrViewModel(
    app: Application,
    private val networkConfig: NetworkConfig = NetworkConfig()
) : AndroidViewModel(app) {

    private val _state = MutableStateFlow(AsrUiState())
    val state: StateFlow<AsrUiState> = _state.asStateFlow()

    private val finalBuffer = StringBuilder()
    private val correctedBuffer = StringBuilder()
    private var sentenceIndex = 0  // 句子索引计数器
    private var lastUploadedText = ""  // 上次尝试上传的文本，用于重试

    private var pipeline: AudioPipeline? = null
    private var mic:      MicRecorder?   = null
    private var router:   ResultRouter?  = null
    private var ttsPlayer: TtsPlayer? = null
    private var modelInitJob: Job? = null
    private var ttsWarmupJob: Job? = null
    private val apiClient: WordfillerApiClient = WordfillerApiClient(networkConfig)
    private val preferences = getApplication<Application>().getSharedPreferences(
        "settings",
        Context.MODE_PRIVATE
    )
    private val sessionId: String = loadOrCreateId("nlu_session_id", "sess_android")
    private val userId: String = loadOrCreateId("nlu_user_id", "usr_android")

    // 时间跟踪
    private var speakingStartTime: Long = 0L  // 开始说话时间

    // Serial channel for partial/final events so UI updates stay ordered
    private val resultChannel = Channel<AsrEvent>(
        capacity       = 8,
        onBufferOverflow = BufferOverflow.DROP_OLDEST
    )

    sealed interface AsrEvent {
        data class Partial(val text: String) : AsrEvent
        data class Final(val text: String, val index: Int, val timestamp: Long = System.currentTimeMillis()) : AsrEvent
        data class Correction(val correction: AsrCorrectionResult) : AsrEvent
    }

    private val networkListener = { available: Boolean ->
        setNetworkAvailable(available)
    }

    private val preferenceListener =
        SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
            if (key in setOf("tts_enabled", "tts_speed", "tts_speaker_id")) {
                loadTtsSettings()
            }
        }

    init {
        setupRouter()
        consumeResults()
        loadTtsSettings()
        preferences.registerOnSharedPreferenceChangeListener(preferenceListener)

        // 监听网络状态变化
        NetworkMonitor.addListener(networkListener)
        setNetworkAvailable(NetworkMonitor.getAvailable())

        // 在页面真正开始录音前后台预热 ASR/VAD，减少首次点击等待。
        initModels()
    }

    // ── Public API ────────────────────────────────────────────────────────

    fun initModels() {
        if (pipeline != null) return
        if (modelInitJob?.isActive == true) return
        _state.update { it.copy(isLoading = true, error = null) }

        modelInitJob = viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                val initStartTime = System.currentTimeMillis()
                val recognizer = AsrModelLoader.createRecognizer(getApplication())
                val vad        = AsrModelLoader.createVad(getApplication())

                pipeline = AudioPipeline(
                    recognizer = recognizer,
                    vad        = vad,
                    onPartial  = { text ->
                        resultChannel.trySend(AsrEvent.Partial(text))
                    },
                    onFinal    = { text ->
                        resultChannel.trySend(AsrEvent.Final(text, sentenceIndex, System.currentTimeMillis()))
                        sentenceIndex++
                    }
                )
                mic = MicRecorder { frame -> pipeline?.feedFrame(frame) }
                android.util.Log.d(
                    "AsrViewModel",
                    "initModels: recognizer+vad 初始化耗时 ${System.currentTimeMillis() - initStartTime}ms"
                )

            }.onSuccess {
                _state.update { it.copy(isLoading = false) }
            }.onFailure { err ->
                _state.update {
                    it.copy(isLoading = false, error = "模型加载失败：${err.message}")
                }
            }
        }
    }

    @RequiresPermission(Manifest.permission.RECORD_AUDIO)
    fun startListening() {
        stopTts()
        val m = mic ?: return
        m.start(viewModelScope)

        // 重置句子索引和时间统计
        sentenceIndex = 0
        speakingStartTime = 0L
        finalBuffer.clear()
        correctedBuffer.clear()

        _state.update {
            it.copy(
                isListening = true,
                error = null,
                finalText = "",
                correctedText = "",
                pendingCorrections = emptyMap(),
                detectedCommands = emptyList(),
                asrLatencyMs = 0f,
                correctionLatencyMs = 0f,
                totalLatencyMs = 0f,
                isUploading = false,
                uploadSuccess = false,
                uploadError = null,
                pendingConfirmToken = null,
                pendingConfirmMessage = null,
                isConfirming = false,
                confirmError = null,
                ttsError = null
            )
        }
    }

    fun stopListening() {
        mic?.stop()
        _state.update {
            it.copy(
                isListening = false,
                isSpeaking = false,
                partialText = ""
            )
        }
    }

    /**
     * 停止录音并上传识别文本到后台
     * 用于按住说话后松开的场景
     */
    fun stopListeningAndUpload() {
        mic?.stop()

        // 获取当前识别文本
        val textToUpload = finalBuffer.toString()

        _state.update {
            it.copy(
                isListening = false,
                isSpeaking = false,
                partialText = "",
                uploadSuccess = false,
                uploadError = null
            )
        }

        // 如果有识别文本，上传到后台
        if (textToUpload.isNotEmpty()) {
            uploadTextToBackend(textToUpload)
        }
    }

    /**
     * 关闭录音模式
     * 用于用户点击录音按钮关闭录音状态
     * 允许TTS播报
     */
    fun closeRecordingMode() {
        mic?.stop()
        _state.update {
            it.copy(
                isListening = false,
                isSpeaking = false,
                partialText = "",
                ttsError = null  // 清除可能存在的TTS错误
            )
        }
    }

    /**
     * 重试上传
     */
    fun retryUpload() {
        if (lastUploadedText.isNotEmpty()) {
            uploadTextToBackend(lastUploadedText)
        }
    }

    fun confirmPendingCommand(accept: Boolean) {
        val token = _state.value.pendingConfirmToken ?: return
        submitPendingConfirmation(token = token, accept = accept)
    }

    /**
     * 上传识别文本到后台服务器
     */
    private fun uploadTextToBackend(text: String) {
        lastUploadedText = text  // 保存文本以便重试

        val pendingToken = _state.value.pendingConfirmToken
        if (!pendingToken.isNullOrBlank()) {
            handleVoiceConfirmAttempt(text = text, token = pendingToken)
            return
        }

        _state.update {
            it.copy(
                isUploading = true,
                uploadSuccess = false,
                uploadError = null,
                confirmError = null,
                pendingConfirmToken = null,
                pendingConfirmMessage = null,
                isConfirming = false
            )
        }

        viewModelScope.launch(Dispatchers.IO) {
            try {
                // 使用 Smart Home API 上传文本
                val result = apiClient.parseSmartHome(
                    text = text,
                    useGlm = true,
                    sessionId = sessionId,
                    userId = userId
                )

                result.onSuccess { response ->
                    withContext(Dispatchers.Main) {
                        applyBackendResponse(response)
                        _state.update { it.copy(isUploading = false) }

                        // 3秒后隐藏成功提示
                        viewModelScope.launch(Dispatchers.Main) {
                            delay(3000)
                            _state.update { it.copy(uploadSuccess = false) }
                        }
                    }
                }.onFailure { err ->
                    withContext(Dispatchers.Main) {
                        _state.update {
                            it.copy(
                                isUploading = false,
                                uploadSuccess = false,
                                uploadError = err.message ?: "上传失败"
                            )
                        }
                    }
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    _state.update {
                        it.copy(
                            isUploading = false,
                            uploadSuccess = false,
                            uploadError = e.message ?: "上传失败"
                        )
                    }
                }
            }
        }
    }

    private fun handleVoiceConfirmAttempt(text: String, token: String) {
        val decision = parseVoiceConfirmDecision(text)
        if (decision == null) {
            _state.update {
                it.copy(
                    isUploading = false,
                    uploadSuccess = false,
                    confirmError = "检测到待确认操作，请说“确认执行”或“取消”。"
                )
            }
            return
        }

        submitPendingConfirmation(token = token, accept = decision)
    }

    private fun parseVoiceConfirmDecision(text: String): Boolean? {
        val normalized = text.trim().replace("\\s+".toRegex(), "")
        if (normalized.isEmpty()) return null

        // 安全优先：先匹配取消类表达，避免误执行高风险命令。
        val rejectPhrases = listOf(
            "取消执行", "取消操作", "取消", "不执行", "不要执行", "否", "算了", "不用了"
        )
        if (rejectPhrases.any { normalized.contains(it) }) {
            return false
        }

        val acceptPhrases = listOf(
            "确认执行", "确认操作", "确认", "继续执行", "继续", "同意", "是的", "可以执行"
        )
        if (acceptPhrases.any { normalized.contains(it) }) {
            return true
        }

        return null
    }

    private fun submitPendingConfirmation(token: String, accept: Boolean) {
        _state.update {
            it.copy(
                isConfirming = true,
                isUploading = false,
                uploadError = null,
                confirmError = null
            )
        }

        viewModelScope.launch(Dispatchers.IO) {
            val result = apiClient.confirmCommand(confirmToken = token, accept = accept)
            result.onSuccess { response ->
                withContext(Dispatchers.Main) {
                    applyBackendResponse(response)
                    _state.update {
                        it.copy(
                            isConfirming = false,
                            pendingConfirmToken = null,
                            pendingConfirmMessage = null
                        )
                    }
                }
            }.onFailure { err ->
                withContext(Dispatchers.Main) {
                    _state.update {
                        it.copy(
                            isConfirming = false,
                            confirmError = err.message ?: "确认提交失败"
                        )
                    }
                }
            }
        }
    }

    fun clearText() {
        stopTts()
        finalBuffer.clear()
        correctedBuffer.clear()
        sentenceIndex = 0
        _state.update {
            it.copy(
                finalText = "",
                correctedText = "",
                partialText = "",
                pendingCorrections = emptyMap(),
                detectedCommands = emptyList(),
                isUploading = false,
                uploadSuccess = false,
                uploadError = null,
                pendingConfirmToken = null,
                pendingConfirmMessage = null,
                isConfirming = false,
                confirmError = null,
                ttsError = null
            )
        }
    }

    fun speakFinalText() {
        speakText(_state.value.finalText)
    }

    fun speakCorrectedText() {
        speakText(_state.value.correctedText.ifBlank { _state.value.finalText })
    }

    fun stopTts() {
        ttsPlayer?.stop()
        _state.update { it.copy(isSpeakingTts = false) }
    }

    fun setNetworkAvailable(available: Boolean) {
        router?.setNetworkAvailable(available)
        _state.update { it.copy(networkAvailable = available) }
    }

    fun updateNetworkConfig(config: NetworkConfig) {
        // 重建路由器以使用新配置
        setupRouter()
    }

    // ── Private ───────────────────────────────────────────────────────────

    private fun setupRouter() {
        router = ResultRouter(
            scope = viewModelScope,
            // 新链路改为松手后统一调用 /api/v1/command，关闭旧纠错端点调用，避免重复请求。
            config = networkConfig.copy(enableCorrection = false),
            onImmediateResult = { result ->
                // 直接更新状态，不通过 channel（避免循环）
                when (result) {
                    is AsrImmediateResult.Partial -> {
                        if (speakingStartTime == 0L && result.text.isNotEmpty()) {
                            speakingStartTime = System.currentTimeMillis()
                        }
                        _state.update {
                            it.copy(partialText = result.text, isSpeaking = true)
                        }
                    }
                    is AsrImmediateResult.Final -> {
                        // 计算ASR识别延时
                        val asrLatency = if (speakingStartTime > 0) {
                            (System.currentTimeMillis() - speakingStartTime).toFloat()
                        } else {
                            0f
                        }
                        // 重置开始时间
                        speakingStartTime = 0L

                        // 更新 final buffer
                        if (result.text.isNotEmpty()) {
                            finalBuffer.append(result.text)
                        }
                        _state.update {
                            it.copy(
                                finalText   = finalBuffer.toString(),
                                partialText = "",
                                isSpeaking  = false,
                                asrLatencyMs = asrLatency,
                                totalLatencyMs = asrLatency
                            )
                        }
                    }
                }
            },
            onCorrectionResult = { correction ->
                resultChannel.trySend(AsrEvent.Correction(correction))
            }
        )
    }

    private fun loadOrCreateId(key: String, prefix: String): String {
        val existing = preferences.getString(key, null)
        if (!existing.isNullOrBlank()) {
            return existing
        }
        val created = "${prefix}_${UUID.randomUUID().toString().replace("-", "").take(12)}"
        preferences.edit().putString(key, created).apply()
        return created
    }

    private fun buildBackendDisplayText(response: SmartHomeResponse): String {
        val reply = response.filtered.trim()
        if (reply.isNotEmpty()) {
            return if (response.code == "OK") {
                reply
            } else {
                "[${response.code}] $reply"
            }
        }
        if (response.message.isNotBlank()) {
            return "[${response.code}] ${response.message}"
        }
        return "[${response.code}]"
    }

    private fun applyBackendResponse(response: SmartHomeResponse) {
        val displayText = buildBackendDisplayText(response)
        val parsedCommands = toIntentCommandList(response)
        val confirmToken = response.data.confirmToken
        val confirmMsg = if (response.code == "POLICY_CONFIRM_REQUIRED") {
            val base = response.data.replyText.ifBlank { "该指令风险较高，请确认后执行。" }
            "$base 可语音说“确认执行”或“取消”。"
        } else {
            null
        }

        _state.update {
            it.copy(
                correctedText = displayText,
                detectedCommands = parsedCommands,
                uploadSuccess = response.code == "OK",
                uploadError = if (response.code == "OK" || response.code == "POLICY_CONFIRM_REQUIRED") null else displayText,
                pendingConfirmToken = confirmToken,
                pendingConfirmMessage = confirmMsg
            )
        }
    }

    private fun toIntentCommandList(response: SmartHomeResponse): List<CommandInfo> {
        val intent = response.data.intent.trim()
        val subIntent = response.data.subIntent.trim()
        if (intent.isEmpty() && subIntent.isEmpty()) {
            return emptyList()
        }

        val actionValue = intent.ifBlank { "unknown" }
        val deviceValue = subIntent.ifBlank { response.data.status.ifBlank { "unknown" } }
        val description = buildString {
            append("intent=").append(actionValue)
            append(", sub_intent=").append(subIntent.ifBlank { "unknown" })
            if (response.data.status.isNotBlank()) {
                append(", status=").append(response.data.status)
            }
        }

        return listOf(
            CommandInfo(
                action = actionValue,
                device = deviceValue,
                description = description
            )
        )
    }

    private fun speakText(text: String) {
        val trimmed = text.trim()
        val currentState = _state.value

        if (trimmed.isEmpty()) {
            _state.update { it.copy(ttsError = "没有可播报的文本") }
            return
        }

        if (!currentState.isTtsEnabled) {
            _state.update { it.copy(ttsError = "TTS 未启用，请先在设置中打开") }
            return
        }

        if (currentState.isListening) {
            _state.update { it.copy(ttsError = "录音中无法播报") }
            return
        }

        _state.update { it.copy(ttsError = null) }

        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                val player = ensureTtsPlayer()
                player.speak(
                    text = trimmed,
                    sid = _state.value.ttsSpeakerId,
                    speed = _state.value.ttsSpeed,
                    startTime = System.currentTimeMillis()
                )
            }.onFailure { err ->
                _state.update {
                    it.copy(
                        isSpeakingTts = false,
                        ttsError = err.message ?: "TTS 初始化失败"
                    )
                }
            }
        }
    }

    private fun ensureTtsPlayer(): TtsPlayer {
        ttsPlayer?.let { return it }

        val tts = TtsModelLoader.createTts(getApplication())
        return TtsPlayer(
            context = getApplication(),
            tts = tts,
            onPlaybackStateChanged = { speaking ->
                _state.update { it.copy(isSpeakingTts = speaking) }
            },
            onError = { message ->
                _state.update {
                    it.copy(
                        isSpeakingTts = false,
                        ttsError = message
                    )
                }
            }
        ).also {
            ttsPlayer = it
        }
    }

    private fun warmUpTtsIfNeeded(force: Boolean) {
        if (!_state.value.isTtsEnabled) return
        if (!force && ttsPlayer != null) return
        if (ttsWarmupJob?.isActive == true) return

        ttsWarmupJob = viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                val warmupStartTime = System.currentTimeMillis()
                ensureTtsPlayer()
                android.util.Log.d(
                    "AsrViewModel",
                    "warmUpTtsIfNeeded: TTS 初始化耗时 ${System.currentTimeMillis() - warmupStartTime}ms"
                )
            }.onFailure { err ->
                android.util.Log.e("AsrViewModel", "warmUpTtsIfNeeded: 失败 - ${err.message}", err)
            }
        }
    }

    private fun loadTtsSettings() {
        val enabled = preferences.getBoolean("tts_enabled", false)
        if (!enabled) {
            ttsPlayer?.stop()
            ttsWarmupJob?.cancel()
        }
        _state.update {
            it.copy(
                isTtsEnabled = enabled,
                ttsSpeed = preferences.getFloat("tts_speed", 1.0f).coerceIn(0.5f, 2.0f),
                ttsSpeakerId = preferences.getInt("tts_speaker_id", 0).coerceAtLeast(0)
            )
        }
        if (enabled) {
            warmUpTtsIfNeeded(force = false)
        }
    }

    private fun consumeResults() {
        viewModelScope.launch {
            for (event in resultChannel) {
                withContext(Dispatchers.Main) {
                    when (event) {
                        is AsrEvent.Partial -> {
                            // 发送到 ResultRouter
                            router?.onAsrResult(com.example.asrapp.router.AsrResult.Partial(event.text))
                        }
                        is AsrEvent.Final   -> {
                            // 发送到 ResultRouter 进行后台纠错决策
                            router?.onAsrResult(com.example.asrapp.router.AsrResult.Final(event.text, event.index))
                        }
                        is AsrEvent.Correction -> {
                            handleCorrection(event.correction)
                        }
                    }
                }
            }
        }
    }

    private fun handleCorrection(correction: AsrCorrectionResult) {
        // 更新待处理纠错映射
        val sentenceCorrection = SentenceCorrection(
            index = correction.index,
            original = correction.original,
            corrected = correction.corrected,
            corrections = correction.corrections,
            commands = correction.commands,
            confidence = correction.confidence,
            processingTimeMs = correction.processingTimeMs
        )

        val updatedCorrections = _state.value.pendingCorrections.toMutableMap()
        updatedCorrections[correction.index] = sentenceCorrection

        // 重建纠正后的完整文本
        val newCorrectedBuffer = StringBuilder()
        var allCommands = mutableListOf<CommandInfo>()

        for (i in 0 until sentenceIndex) {
            val sc = updatedCorrections[i]
            if (sc != null) {
                newCorrectedBuffer.append(sc.corrected)
                allCommands.addAll(sc.commands.map { CommandInfo.fromNetworkCommand(it) })
            } else {
                // 没有纠错的句子使用原文
                // 这里需要从finalBuffer中提取对应句子
                // 简化处理：使用当前correctedBuffer
                newCorrectedBuffer.append(correctedBuffer.toString())
            }
        }

        correctedBuffer.clear()
        correctedBuffer.append(newCorrectedBuffer.toString())

        // 计算总延时 = ASR识别延时 + 纠错延时
        val totalLatency = _state.value.asrLatencyMs + correction.processingTimeMs

        _state.update {
            it.copy(
                correctedText = correctedBuffer.toString(),
                pendingCorrections = updatedCorrections,
                detectedCommands = allCommands,
                isCorrecting = false,
                correctionLatencyMs = correction.processingTimeMs,
                totalLatencyMs = totalLatency
            )
        }
    }

    override fun onCleared() {
        modelInitJob?.cancel()
        ttsWarmupJob?.cancel()
        NetworkMonitor.removeListener(networkListener)
        preferences.unregisterOnSharedPreferenceChangeListener(preferenceListener)
        mic?.release()
        pipeline?.release()
        router?.release()
        ttsPlayer?.release()
        resultChannel.close()
    }
}
