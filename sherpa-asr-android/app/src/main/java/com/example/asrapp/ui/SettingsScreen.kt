package com.example.asrapp.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.asrapp.viewmodel.SettingsViewModel

/**
 * 设置界面
 *
 * 配置网络连接和纠错选项
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onBackClick: () -> Unit,
    viewModel: SettingsViewModel = viewModel()
) {
    val uiState by viewModel.uiState.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("设置") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            )
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .padding(innerPadding)
                .padding(16.dp)
                .fillMaxSize()
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // 服务器配置
            ServerConfigSection(
                serverUrl = uiState.serverUrl,
                timeoutMs = uiState.timeoutMs,
                onServerUrlChange = { viewModel.updateServerUrl(it) },
                onTimeoutChange = { viewModel.updateTimeout(it) }
            )

            HorizontalDivider()

            // 纠错选项
            CorrectionOptionsSection(
                enableCorrection = uiState.enableCorrection,
                usePhoneticCorrection = uiState.usePhoneticCorrection,
                useSmartHomeRules = uiState.useSmartHomeRules,
                onEnableCorrectionChange = { viewModel.updateEnableCorrection(it) },
                onUsePhoneticCorrectionChange = { viewModel.updateUsePhoneticCorrection(it) },
                onUseSmartHomeRulesChange = { viewModel.updateUseSmartHomeRules(it) }
            )

            HorizontalDivider()

            TtsOptionsSection(
                ttsEnabled = uiState.ttsEnabled,
                ttsSpeed = uiState.ttsSpeed,
                ttsSpeakerId = uiState.ttsSpeakerId,
                isTestingTts = uiState.isTestingTts,
                isWarmingTts = uiState.isWarmingTts,
                ttsTestStatus = uiState.ttsTestStatus,
                ttsWarmStatus = uiState.ttsWarmStatus,
                onTtsEnabledChange = { viewModel.updateTtsEnabled(it) },
                onTtsSpeedChange = { viewModel.updateTtsSpeed(it) },
                onTtsSpeakerIdChange = { viewModel.updateTtsSpeakerId(it) },
                onTestTtsClick = { viewModel.testTts() },
                onStopTtsClick = { viewModel.stopTtsTest() }
            )

            HorizontalDivider()

            // 连接测试
            ConnectionTestSection(
                isTesting = uiState.isTestingConnection,
                connectionStatus = uiState.connectionStatus,
                onTestClick = { viewModel.testConnection() }
            )

            HorizontalDivider()

            // 应用信息
            AppInfoSection()
        }
    }
}

@Composable
fun TtsOptionsSection(
    ttsEnabled: Boolean,
    ttsSpeed: Float,
    ttsSpeakerId: Int,
    isTestingTts: Boolean,
    isWarmingTts: Boolean,
    ttsTestStatus: String?,
    ttsWarmStatus: String?,
    onTtsEnabledChange: (Boolean) -> Unit,
    onTtsSpeedChange: (Float) -> Unit,
    onTtsSpeakerIdChange: (Int) -> Unit,
    onTestTtsClick: () -> Unit,
    onStopTtsClick: () -> Unit
) {
    Column(
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text(
            text = "语音播报",
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.primary
        )

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "启用离线 TTS",
                    style = MaterialTheme.typography.bodyLarge
                )
                Text(
                    text = "播报识别结果与纠错结果",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Switch(
                checked = ttsEnabled,
                onCheckedChange = onTtsEnabledChange
            )
        }

        var speedText by remember { mutableStateOf(ttsSpeed.toString()) }
        LaunchedEffect(ttsSpeed) {
            speedText = ttsSpeed.toString()
        }

        OutlinedTextField(
            value = speedText,
            onValueChange = {
                speedText = it
                it.toFloatOrNull()?.let(onTtsSpeedChange)
            },
            label = { Text("语速 (0.5 - 2.0)") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            enabled = ttsEnabled
        )

        var speakerIdText by remember { mutableStateOf(ttsSpeakerId.toString()) }
        LaunchedEffect(ttsSpeakerId) {
            speakerIdText = ttsSpeakerId.toString()
        }

        OutlinedTextField(
            value = speakerIdText,
            onValueChange = {
                speakerIdText = it
                it.toIntOrNull()?.let(onTtsSpeakerIdChange)
            },
            label = { Text("说话人 ID") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            enabled = ttsEnabled
        )

        if (!ttsWarmStatus.isNullOrBlank()) {
            Text(
                text = ttsWarmStatus,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            OutlinedButton(
                onClick = onTestTtsClick,
                enabled = ttsEnabled && !isTestingTts && !isWarmingTts
            ) {
                Text(
                    when {
                        isWarmingTts -> "模型预热中..."
                        isTestingTts -> "测试播报中..."
                        else -> "测试播报"
                    }
                )
            }

            OutlinedButton(
                onClick = onStopTtsClick,
                enabled = ttsEnabled && isTestingTts
            ) {
                Text("停止播报")
            }
        }

        if (!ttsTestStatus.isNullOrBlank()) {
            Text(
                text = ttsTestStatus,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

    }
}

// ── Server config section ────────────────────────────────────────────────

@Composable
fun ServerConfigSection(
    serverUrl: String,
    timeoutMs: Long,
    onServerUrlChange: (String) -> Unit,
    onTimeoutChange: (Long) -> Unit
) {
    Column(
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text(
            text = "服务器配置",
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.primary
        )

        // 服务器地址
        OutlinedTextField(
            value = serverUrl,
            onValueChange = onServerUrlChange,
            label = { Text("服务器地址") },
            placeholder = { Text("http://192.168.3.145:8001") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )

        // 超时时间
        var timeoutText by remember { mutableStateOf(timeoutMs.toString()) }
        LaunchedEffect(timeoutMs) {
            timeoutText = timeoutMs.toString()
        }

        OutlinedTextField(
            value = timeoutText,
            onValueChange = {
                timeoutText = it
                it.toLongOrNull()?.let { timeout -> onTimeoutChange(timeout) }
            },
            label = { Text("超时时间 (毫秒)") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )

        // 说明
        Text(
            text = "• 服务器运行在局域网内\n• 确保手机和服务器在同一网络\n• 默认地址: http://192.168.3.145:8001",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

// ── Correction options section ───────────────────────────────────────────

@Composable
fun CorrectionOptionsSection(
    enableCorrection: Boolean,
    usePhoneticCorrection: Boolean,
    useSmartHomeRules: Boolean,
    onEnableCorrectionChange: (Boolean) -> Unit,
    onUsePhoneticCorrectionChange: (Boolean) -> Unit,
    onUseSmartHomeRulesChange: (Boolean) -> Unit
) {
    Column(
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text(
            text = "纠错选项",
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.primary
        )

        // 启用云纠错
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "启用云纠错",
                    style = MaterialTheme.typography.bodyLarge
                )
                Text(
                    text = "使用服务端进行智能纠错",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Switch(
                checked = enableCorrection,
                onCheckedChange = onEnableCorrectionChange
            )
        }

        // 拼音纠错
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "拼音纠错",
                    style = MaterialTheme.typography.bodyMedium
                )
                Text(
                    text = "纠正ASR同音字错误",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Switch(
                checked = usePhoneticCorrection && enableCorrection,
                onCheckedChange = onUsePhoneticCorrectionChange,
                enabled = enableCorrection
            )
        }

        // 智能家居规则
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "智能家居规则",
                    style = MaterialTheme.typography.bodyMedium
                )
                Text(
                    text = "解析和格式化智能家居命令",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Switch(
                checked = useSmartHomeRules && enableCorrection,
                onCheckedChange = onUseSmartHomeRulesChange,
                enabled = enableCorrection
            )
        }
    }
}

// ── Connection test section ─────────────────────────────────────────────

@Composable
fun ConnectionTestSection(
    isTesting: Boolean,
    connectionStatus: ConnectionStatus?,
    onTestClick: () -> Unit
) {
    Column(
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text(
            text = "连接测试",
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.primary
        )

        Button(
            onClick = onTestClick,
            enabled = !isTesting,
            modifier = Modifier.fillMaxWidth()
        ) {
            if (isTesting) {
                CircularProgressIndicator(
                    modifier = Modifier.size(20.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimary
                )
                Spacer(Modifier.width(8.dp))
                Text("测试中...")
            } else {
                Text("测试连接")
            }
        }

        // 状态显示
        connectionStatus?.let { status ->
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = when (status) {
                    is ConnectionStatus.Success -> MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.3f)
                    is ConnectionStatus.Error -> MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.3f)
                    is ConnectionStatus.Testing -> MaterialTheme.colorScheme.surfaceVariant
                },
                shape = MaterialTheme.shapes.small
            ) {
                Row(
                    modifier = Modifier.padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = status.message,
                        style = MaterialTheme.typography.bodyMedium,
                        color = when (status) {
                            is ConnectionStatus.Success -> MaterialTheme.colorScheme.primary
                            is ConnectionStatus.Error -> MaterialTheme.colorScheme.error
                            is ConnectionStatus.Testing -> MaterialTheme.colorScheme.onSurfaceVariant
                        }
                    )
                }
            }
        }
    }
}

// ── App info section ─────────────────────────────────────────────────────

@Composable
fun AppInfoSection() {
    Column(
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Text(
            text = "应用信息",
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.primary
        )

        Text(
            text = """
                版本: 1.0.0
                ASR引擎: sherpa-onnx
                纠错服务: Wordfiller Server

                本应用完全本地运行语音识别，
                可选使用局域网服务进行智能纠错。
            """.trimIndent(),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

// ── Connection status ─────────────────────────────────────────────────────

sealed class ConnectionStatus {
    object Testing : ConnectionStatus() {
        override val message = "正在测试连接..."
    }

    data class Success(val latency: Long) : ConnectionStatus() {
        override val message = "连接成功 (${latency}ms)"
    }

    data class Error(val error: String) : ConnectionStatus() {
        override val message = "连接失败: $error"
    }

    abstract val message: String
}
