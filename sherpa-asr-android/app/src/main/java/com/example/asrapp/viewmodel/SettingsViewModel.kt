package com.example.asrapp.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.asrapp.audio.TtsPlayer
import com.example.asrapp.model.TtsModelLoader
import com.example.asrapp.network.NetworkConfig
import com.example.asrapp.network.WordfillerApiClient
import com.example.asrapp.ui.ConnectionStatus
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 设置界面状态
 */
data class SettingsUiState(
    val serverUrl: String = NetworkConfig.DEFAULT_SERVER_URL,
    val timeoutMs: Long = NetworkConfig.DEFAULT_TIMEOUT,
    val enableCorrection: Boolean = true,
    val usePhoneticCorrection: Boolean = true,
    val useSmartHomeRules: Boolean = true,
    val ttsEnabled: Boolean = false,
    val ttsSpeed: Float = 1.0f,
    val ttsSpeakerId: Int = 0,
    val isTestingTts: Boolean = false,
    val isWarmingTts: Boolean = false,
    val ttsTestStatus: String? = null,
    val ttsWarmStatus: String? = null,
    val isTestingConnection: Boolean = false,
    val connectionStatus: ConnectionStatus? = null
)

/**
 * 设置ViewModel
 *
 * 管理应用配置和网络设置
 */
class SettingsViewModel(app: Application) : AndroidViewModel(app) {

    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()
    private var ttsPlayer: TtsPlayer? = null
    private var ttsWarmupJob: Job? = null

    private val preferences = getApplication<Application>().getSharedPreferences(
        "settings", android.content.Context.MODE_PRIVATE
    )

    init {
        loadSettings()
    }

    // ── Public API ────────────────────────────────────────────────────────

    fun updateServerUrl(url: String) {
        _uiState.update { it.copy(serverUrl = url) }
        saveSettings()
    }

    fun updateTimeout(timeout: Long) {
        _uiState.update { it.copy(timeoutMs = timeout.coerceAtLeast(1000)) }
        saveSettings()
    }

    fun updateEnableCorrection(enabled: Boolean) {
        _uiState.update { it.copy(enableCorrection = enabled) }
        saveSettings()
    }

    fun updateUsePhoneticCorrection(enabled: Boolean) {
        _uiState.update { it.copy(usePhoneticCorrection = enabled) }
        saveSettings()
    }

    fun updateUseSmartHomeRules(enabled: Boolean) {
        _uiState.update { it.copy(useSmartHomeRules = enabled) }
        saveSettings()
    }

    fun updateTtsEnabled(enabled: Boolean) {
        _uiState.update { it.copy(ttsEnabled = enabled) }
        if (!enabled) {
            ttsWarmupJob?.cancel()
            ttsPlayer?.stop()
            _uiState.update {
                it.copy(
                    isTestingTts = false,
                    isWarmingTts = false,
                    ttsTestStatus = null,
                    ttsWarmStatus = null
                )
            }
        } else {
            warmUpTtsIfNeeded(force = false)
        }
        saveSettings()
    }

    fun updateTtsSpeed(speed: Float) {
        _uiState.update { it.copy(ttsSpeed = speed.coerceIn(0.5f, 2.0f)) }
        saveSettings()
    }

    fun updateTtsSpeakerId(speakerId: Int) {
        _uiState.update { it.copy(ttsSpeakerId = speakerId.coerceAtLeast(0)) }
        saveSettings()
    }

    fun testConnection() {
        val config = getCurrentConfig()
        if (!config.isValid()) {
            _uiState.update {
                it.copy(
                    connectionStatus = ConnectionStatus.Error("服务器地址无效")
                )
            }
            return
        }

        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isTestingConnection = true,
                    connectionStatus = ConnectionStatus.Testing
                )
            }

            try {
                val client = WordfillerApiClient(config)
                val startTime = System.currentTimeMillis()
                val success = client.testConnection()
                val latency = System.currentTimeMillis() - startTime

                _uiState.update {
                    it.copy(
                        isTestingConnection = false,
                        connectionStatus = if (success) {
                            ConnectionStatus.Success(latency)
                        } else {
                            ConnectionStatus.Error("无响应")
                        }
                    )
                }
            } catch (e: Exception) {
                _uiState.update {
                    it.copy(
                        isTestingConnection = false,
                        connectionStatus = ConnectionStatus.Error(e.message ?: "未知错误")
                    )
                }
            }
        }
    }

    fun testTts() {
        val state = _uiState.value
        if (!state.ttsEnabled) {
            _uiState.update { it.copy(ttsTestStatus = "请先启用离线 TTS") }
            return
        }

        val clickTime = System.currentTimeMillis()
        android.util.Log.d("TtsViewModel", "testTts: 用户点击测试播报按钮")

        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                val prepareStartTime = System.currentTimeMillis()
                android.util.Log.d("TtsViewModel", "testTts: 协程启动耗时 ${prepareStartTime - clickTime}ms")

                _uiState.update {
                    it.copy(
                        isTestingTts = true,
                        isWarmingTts = false,
                        ttsTestStatus = "正在播放测试语音..."
                    )
                }

                val ensurePlayerStartTime = System.currentTimeMillis()
                val player = ensureTtsPlayer()
                android.util.Log.d("TtsViewModel", "testTts: ensureTtsPlayer 耗时 ${System.currentTimeMillis() - ensurePlayerStartTime}ms")

                val testText = buildTestText(state.ttsSpeakerId)
                android.util.Log.d("TtsViewModel", "testTts: 测试文本: \"$testText\"")

                val speakStartTime = System.currentTimeMillis()
                player.speak(
                    text = testText,
                    sid = state.ttsSpeakerId,
                    speed = state.ttsSpeed,
                    startTime = speakStartTime
                )
                android.util.Log.d("TtsViewModel", "testTts: speak() 调用完成，总耗时 ${System.currentTimeMillis() - clickTime}ms")
            }.onFailure { err ->
                android.util.Log.e("TtsViewModel", "testTts: 失败 - ${err.message}", err)
                _uiState.update {
                    it.copy(
                        isTestingTts = false,
                        ttsTestStatus = err.message ?: "TTS 试听失败"
                    )
                }
            }
        }
    }

    fun stopTtsTest() {
        ttsPlayer?.stop()
        _uiState.update {
            it.copy(
                isTestingTts = false,
                ttsTestStatus = "已停止测试播报"
            )
        }
    }

    fun getCurrentConfig(): NetworkConfig {
        return with(_uiState.value) {
            NetworkConfig(
                serverUrl = serverUrl,
                timeoutMs = timeoutMs,
                enableCorrection = enableCorrection
            )
        }
    }

    // ── Private ───────────────────────────────────────────────────────────

    private fun loadSettings() {
        _uiState.update {
            it.copy(
                serverUrl = preferences.getString("server_url", NetworkConfig.DEFAULT_SERVER_URL)
                    ?: NetworkConfig.DEFAULT_SERVER_URL,
                timeoutMs = preferences.getLong("timeout_ms", NetworkConfig.DEFAULT_TIMEOUT),
                enableCorrection = preferences.getBoolean("enable_correction", true),
                usePhoneticCorrection = preferences.getBoolean("use_phonetic_correction", true),
                useSmartHomeRules = preferences.getBoolean("use_smart_home_rules", true),
                ttsEnabled = preferences.getBoolean("tts_enabled", false),
                ttsSpeed = preferences.getFloat("tts_speed", 1.0f),
                ttsSpeakerId = preferences.getInt("tts_speaker_id", 0)
            )
        }

        if (_uiState.value.ttsEnabled) {
            warmUpTtsIfNeeded(force = false)
        }
    }

    private fun saveSettings() {
        with(_uiState.value) {
            preferences.edit()
                .putString("server_url", serverUrl)
                .putLong("timeout_ms", timeoutMs)
                .putBoolean("enable_correction", enableCorrection)
                .putBoolean("use_phonetic_correction", usePhoneticCorrection)
                .putBoolean("use_smart_home_rules", useSmartHomeRules)
                .putBoolean("tts_enabled", ttsEnabled)
                .putFloat("tts_speed", ttsSpeed)
                .putInt("tts_speaker_id", ttsSpeakerId)
                .apply()
        }
    }

    private fun ensureTtsPlayer(): TtsPlayer {
        ttsPlayer?.let { return it }

        val tts = TtsModelLoader.createTts(getApplication())
        return TtsPlayer(
            context = getApplication(),
            tts = tts,
            onPlaybackStateChanged = { speaking ->
                _uiState.update {
                    it.copy(
                        isTestingTts = speaking,
                        ttsTestStatus = if (speaking) "正在播放测试语音..." else "测试播报完成"
                    )
                }
            },
            onError = { message ->
                _uiState.update {
                    it.copy(
                        isTestingTts = false,
                        ttsTestStatus = message
                    )
                }
            }
        ).also {
            ttsPlayer = it
        }
    }

    private fun warmUpTtsIfNeeded(force: Boolean) {
        if (!uiState.value.ttsEnabled) return
        if (!force && ttsPlayer != null) {
            _uiState.update {
                if (it.isTestingTts) it else it.copy(isWarmingTts = false, ttsWarmStatus = "TTS 已就绪")
            }
            return
        }
        if (ttsWarmupJob?.isActive == true) return

        ttsWarmupJob = viewModelScope.launch(Dispatchers.IO) {
            _uiState.update {
                if (it.isTestingTts) it else it.copy(isWarmingTts = true, ttsWarmStatus = "TTS 预热中...")
            }
            runCatching {
                ensureTtsPlayer()
            }.onSuccess {
                _uiState.update {
                    if (it.isTestingTts) it else it.copy(isWarmingTts = false, ttsWarmStatus = "TTS 已就绪")
                }
            }.onFailure { err ->
                _uiState.update {
                    if (it.isTestingTts) {
                        it
                    } else {
                        it.copy(
                            isWarmingTts = false,
                            ttsWarmStatus = err.message ?: "TTS 预热失败"
                        )
                    }
                }
            }
        }
    }

    private fun buildTestText(speakerId: Int): String {
        return when (TtsModelLoader.getInstalledTtsKind(getApplication())) {
            TtsModelLoader.InstalledTtsKind.MATCHA_ZH_EN ->
                "这是一个语音测试。"
            TtsModelLoader.InstalledTtsKind.VITS_ZH ->
                "这是一个语音测试。"
            TtsModelLoader.InstalledTtsKind.VITS_EN ->
                "Hello, this is a TTS test."
            TtsModelLoader.InstalledTtsKind.VITS_MULTI_SPEAKER ->
                "这是一个语音测试。"
            TtsModelLoader.InstalledTtsKind.UNKNOWN ->
                "这是一个语音测试。"
        }
    }

    override fun onCleared() {
        ttsWarmupJob?.cancel()
        ttsPlayer?.release()
        ttsPlayer = null
        super.onCleared()
    }
}
