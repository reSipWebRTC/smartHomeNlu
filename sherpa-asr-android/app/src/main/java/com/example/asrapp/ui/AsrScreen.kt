package com.example.asrapp.ui

import android.Manifest
import android.annotation.SuppressLint
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.asrapp.AsrApplication
import com.example.asrapp.AsrViewModelFactory
import com.example.asrapp.ui.components.*
import com.example.asrapp.viewmodel.AsrViewModel
import com.example.asrapp.viewmodel.CommandInfo

@SuppressLint("MissingPermission")
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AsrScreen(
    vm: AsrViewModel = viewModel<AsrViewModel>(
        factory = AsrViewModelFactory(LocalContext.current.applicationContext as android.app.Application)
    ),
    onSettingsClick: () -> Unit = {}
) {
    val state by vm.state.collectAsStateWithLifecycle()

    // Load models on first composition
    LaunchedEffect(Unit) { vm.initModels() }

    // Permission launcher
    val permLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) vm.startListening()
    }

    Scaffold(
        topBar = {
            SmallTopAppBar(
                title = { Text("语音识别") },
                actions = {
                    // 设置按钮
                    IconButton(onClick = onSettingsClick) {
                        Icon(Icons.Default.Settings, contentDescription = "设置")
                    }
                }
            )
        },
        floatingActionButton = {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                // Upload status indicator
                if (state.isUploading) {
                    Surface(
                        color = MaterialTheme.colorScheme.tertiaryContainer,
                        shape = MaterialTheme.shapes.small,
                        modifier = Modifier.padding(bottom = 8.dp)
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(14.dp),
                                strokeWidth = 2.dp
                            )
                            Text(
                                text = "上传中...",
                                style = MaterialTheme.typography.labelSmall
                            )
                        }
                    }
                }
                // Upload success indicator
                if (state.uploadSuccess) {
                    Surface(
                        color = MaterialTheme.colorScheme.primaryContainer,
                        shape = MaterialTheme.shapes.small,
                        modifier = Modifier.padding(bottom = 8.dp)
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            Icon(
                                imageVector = Icons.Default.CheckCircle,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(16.dp)
                            )
                            Text(
                                text = "上传成功",
                                style = MaterialTheme.typography.labelSmall
                            )
                        }
                    }
                }
                // Clear button (visible when there is text)
                if ((state.finalText.isNotEmpty() || state.correctedText.isNotEmpty()) && !state.isListening) {
                    SmallFloatingActionButton(
                        onClick           = vm::clearText,
                        containerColor    = MaterialTheme.colorScheme.secondaryContainer,
                        modifier          = Modifier.padding(bottom = 8.dp)
                    ) {
                        Icon(Icons.Default.Clear, contentDescription = "清空")
                    }
                }
                // Main mic FAB - Press and hold to record, click to toggle
                FloatingActionButton(
                    onClick = {
                        when {
                            state.isListening -> {
                                // 点击关闭录音模式（允许TTS播报）
                                vm.closeRecordingMode()
                            }
                            !state.isLoading -> {
                                // 点击时请求权限（首次使用）
                                permLauncher.launch(Manifest.permission.RECORD_AUDIO)
                            }
                        }
                    },
                    modifier = Modifier.pointerInput(Unit) {
                        detectTapGestures(
                            onPress = { offset ->
                                // User pressed down - start listening immediately
                                if (!state.isLoading && !state.isListening) {
                                    vm.startListening()
                                }
                                // Wait for press to be released
                                val success = tryAwaitRelease()
                                // User released - stop listening and upload
                                if (success) {
                                    vm.stopListeningAndUpload()
                                }
                            }
                        )
                    },
                    containerColor = when {
                        state.isListening -> MaterialTheme.colorScheme.errorContainer
                        state.isLoading   -> MaterialTheme.colorScheme.surfaceVariant
                        else              -> MaterialTheme.colorScheme.primaryContainer
                    }
                ) {
                    if (state.isLoading) {
                        CircularProgressIndicator(
                            modifier  = Modifier.size(24.dp),
                            strokeWidth = 2.dp
                        )
                    } else if (state.isListening) {
                        Icon(
                            imageVector        = Icons.Default.Stop,
                            contentDescription = "点击关闭录音模式",
                            tint = MaterialTheme.colorScheme.error
                        )
                    } else {
                        Icon(
                            imageVector        = Icons.Default.Mic,
                            contentDescription = "按住录音，松开上传"
                        )
                    }
                }
                // Recording hint
                if (!state.isLoading) {
                    Text(
                        text = if (state.isListening) "点击关闭录音" else "按住说话",
                        style = MaterialTheme.typography.labelSmall,
                        color = if (state.isListening)
                            MaterialTheme.colorScheme.error
                        else
                            MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 4.dp)
                    )
                }
            }
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .padding(innerPadding)
                .padding(horizontal = 16.dp, vertical = 12.dp)
                .fillMaxSize()
        ) {
            // ── VAD / status indicator ───────────────────────────────────
            VadStatusRow(
                isListening = state.isListening,
                isSpeaking  = state.isSpeaking,
                isLoading   = state.isLoading
            )

            Spacer(Modifier.height(8.dp))

            // ── Correction status indicator ───────────────────────────────
            CorrectionStatusIndicator(
                isCorrecting = state.isCorrecting,
                correctionCount = state.pendingCorrections.size,
                processingTimeMs = 0f,  // 总体时间可以另外计算
                modifier = Modifier.fillMaxWidth()
            )

            Spacer(Modifier.height(8.dp))

            // ── Error banner ─────────────────────────────────────────────
            state.error?.let { err ->
                Surface(
                    color  = MaterialTheme.colorScheme.errorContainer,
                    shape  = MaterialTheme.shapes.small,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(
                        text     = err,
                        color    = MaterialTheme.colorScheme.onErrorContainer,
                        style    = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(8.dp)
                    )
                }
                Spacer(Modifier.height(8.dp))
            }

            // ── Upload error banner ──────────────────────────────────────
            state.uploadError?.let { err ->
                Surface(
                    color  = MaterialTheme.colorScheme.errorContainer,
                    shape  = MaterialTheme.shapes.small,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        modifier = Modifier.padding(8.dp),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Text(
                            text     = "上传失败: $err",
                            color    = MaterialTheme.colorScheme.onErrorContainer,
                            style    = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.weight(1f)
                        )
                        TextButton(
                            onClick = { vm.retryUpload() },
                            colors = ButtonDefaults.textButtonColors(
                                contentColor = MaterialTheme.colorScheme.onErrorContainer
                            )
                        ) {
                            Text("重试", style = MaterialTheme.typography.labelSmall)
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))
            }

            // ── Confirm required banner ──────────────────────────────────
            state.pendingConfirmToken?.let {
                Surface(
                    color = MaterialTheme.colorScheme.tertiaryContainer,
                    shape = MaterialTheme.shapes.small,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text(
                            text = state.pendingConfirmMessage ?: "该指令风险较高，请确认是否继续执行。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onTertiaryContainer
                        )

                        Spacer(Modifier.height(8.dp))

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.End
                        ) {
                            TextButton(
                                onClick = { vm.confirmPendingCommand(false) },
                                enabled = !state.isConfirming
                            ) {
                                Text("取消")
                            }
                            Spacer(Modifier.width(8.dp))
                            Button(
                                onClick = { vm.confirmPendingCommand(true) },
                                enabled = !state.isConfirming
                            ) {
                                if (state.isConfirming) {
                                    CircularProgressIndicator(
                                        modifier = Modifier.size(14.dp),
                                        strokeWidth = 2.dp
                                    )
                                } else {
                                    Text("确认执行")
                                }
                            }
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))
            }

            // ── Confirm error banner ─────────────────────────────────────
            state.confirmError?.let { err ->
                Surface(
                    color  = MaterialTheme.colorScheme.errorContainer,
                    shape  = MaterialTheme.shapes.small,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(
                        text     = "确认失败: $err",
                        color    = MaterialTheme.colorScheme.onErrorContainer,
                        style    = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(8.dp)
                    )
                }
                Spacer(Modifier.height(8.dp))
            }

            // ── Network status ───────────────────────────────────────────
            NetworkStatusIndicator(
                networkAvailable = state.networkAvailable,
                modifier = Modifier.fillMaxWidth()
            )

            Spacer(Modifier.height(8.dp))

            TtsStatusCard(
                enabled = state.isTtsEnabled,
                speaking = state.isSpeakingTts,
                error = state.ttsError,
                finalText = state.finalText,
                correctedText = state.correctedText,
                onSpeakOriginal = vm::speakFinalText,
                onSpeakCorrected = vm::speakCorrectedText,
                onStop = vm::stopTts,
                modifier = Modifier.fillMaxWidth()
            )

            Spacer(Modifier.height(8.dp))

            // ── Transcript area with tabs ────────────────────────────────
            TranscriptWithTabs(
                finalText = state.finalText,
                correctedText = state.correctedText,
                partialText = state.partialText,
                pendingCorrections = state.pendingCorrections,
                detectedCommands = state.detectedCommands,
                asrLatencyMs = state.asrLatencyMs,
                correctionLatencyMs = state.correctionLatencyMs,
                totalLatencyMs = state.totalLatencyMs,
                modifier = Modifier.weight(1f)
            )
        }
    }
}

@Composable
fun TtsStatusCard(
    enabled: Boolean,
    speaking: Boolean,
    error: String?,
    finalText: String,
    correctedText: String,
    onSpeakOriginal: () -> Unit,
    onSpeakCorrected: () -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier = modifier,
        shape = MaterialTheme.shapes.medium,
        tonalElevation = 1.dp
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "离线播报",
                    style = MaterialTheme.typography.titleSmall
                )
                Text(
                    text = when {
                        speaking -> "播报中"
                        enabled -> "已启用"
                        else -> "未启用"
                    },
                    style = MaterialTheme.typography.labelMedium,
                    color = when {
                        speaking -> MaterialTheme.colorScheme.primary
                        enabled -> MaterialTheme.colorScheme.secondary
                        else -> MaterialTheme.colorScheme.onSurfaceVariant
                    }
                )
            }

            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                OutlinedButton(
                    onClick = onSpeakOriginal,
                    enabled = enabled && finalText.isNotBlank() && !speaking
                ) {
                    Icon(Icons.Default.PlayArrow, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text(if (speaking) "原文播报中..." else "播报原文")
                }

                OutlinedButton(
                    onClick = onSpeakCorrected,
                    enabled = enabled && (correctedText.isNotBlank() || finalText.isNotBlank()) && !speaking
                ) {
                    Icon(Icons.Default.PlayArrow, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text(if (speaking) "纠正后播报中..." else "播报纠正后")
                }

                FilledTonalButton(
                    onClick = onStop,
                    enabled = enabled && speaking
                ) {
                    Icon(Icons.Default.Stop, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text("停止播报")
                }
            }

            if (!enabled) {
                Text(
                    text = "在设置页启用 TTS，并将模型放到 app/src/main/assets/tts/",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }

            error?.takeIf { it.isNotBlank() }?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error
                )
            }
        }
    }
}

// ── VAD indicator ─────────────────────────────────────────────────────────────

@Composable
fun VadStatusRow(isListening: Boolean, isSpeaking: Boolean, isLoading: Boolean) {
    val dotColor by animateColorAsState(
        targetValue = when {
            isSpeaking  -> MaterialTheme.colorScheme.primary
            isListening -> MaterialTheme.colorScheme.outline
            else        -> MaterialTheme.colorScheme.outlineVariant
        },
        animationSpec = tween(200),
        label = "dot_color"
    )
    val dotScale by animateFloatAsState(
        targetValue   = if (isSpeaking) 1.3f else 1f,
        animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy),
        label         = "dot_scale"
    )
    val label = when {
        isLoading   -> "正在加载模型…"
        isSpeaking  -> "检测到人声"
        isListening -> "等待说话…"
        else        -> "未开始"
    }

    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier
                .scale(dotScale)
                .size(10.dp)
                .background(dotColor, CircleShape)
        )
        Spacer(Modifier.width(8.dp))
        Text(
            text  = label,
            style = MaterialTheme.typography.labelMedium,
            color = dotColor
        )
    }
}

// ── Network status indicator ───────────────────────────────────────────────────

@Composable
fun NetworkStatusIndicator(
    networkAvailable: Boolean,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier = modifier,
        shape = MaterialTheme.shapes.small,
        color = if (networkAvailable)
            MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.3f)
        else
            MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.3f)
    ) {
        Row(
            modifier = Modifier.padding(6.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = if (networkAvailable) "🌐 云纠错已启用" else "📴 仅端侧模式",
                style = MaterialTheme.typography.labelSmall,
                color = if (networkAvailable)
                    MaterialTheme.colorScheme.primary
                else
                    MaterialTheme.colorScheme.error
            )
        }
    }
}

// ── Latency information row ────────────────────────────────────────────────────────

@Composable
fun LatencyInfoRow(
    asrLatencyMs: Float,
    correctionLatencyMs: Float,
    totalLatencyMs: Float
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.3f),
        shape = MaterialTheme.shapes.small
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            // ASR识别延时
            LatencyItem(
                label = "ASR识别",
                latencyMs = asrLatencyMs,
                color = MaterialTheme.colorScheme.primary
            )

            // 纠错延时
            if (correctionLatencyMs > 0) {
                LatencyItem(
                    label = "纠错",
                    latencyMs = correctionLatencyMs,
                    color = MaterialTheme.colorScheme.tertiary
                )
            }

            // 总延时
            LatencyItem(
                label = "总延时",
                latencyMs = totalLatencyMs,
                color = MaterialTheme.colorScheme.secondary
            )
        }
    }
}

@Composable
fun LatencyItem(
    label: String,
    latencyMs: Float,
    color: Color
) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            text = "${latencyMs.toInt()}",
            style = MaterialTheme.typography.titleMedium,
            color = color
        )
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Text(
            text = "ms",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
        )
    }
}

// ── Transcript with tabs (Original/Corrected/Commands) ───────────────────────────

@Composable
fun TranscriptWithTabs(
    finalText: String,
    correctedText: String,
    partialText: String,
    pendingCorrections: Map<Int, com.example.asrapp.viewmodel.SentenceCorrection>,
    detectedCommands: List<CommandInfo>,
    asrLatencyMs: Float = 0f,
    correctionLatencyMs: Float = 0f,
    totalLatencyMs: Float = 0f,
    modifier: Modifier = Modifier
) {
    var selectedTab by remember { mutableIntStateOf(0) }
    val tabs = listOf("原文", "纠正后", "命令")

    Column(modifier = modifier) {
        // Tab row
        TabRow(
            selectedTabIndex = selectedTab,
            containerColor = Color.Transparent
        ) {
            tabs.forEachIndexed { index, title ->
                Tab(
                    selected = selectedTab == index,
                    onClick = { selectedTab = index },
                    text = {
                        Text(
                            text = title,
                            style = if (selectedTab == index)
                                MaterialTheme.typography.titleSmall
                            else
                                MaterialTheme.typography.bodyMedium
                        )
                    }
                )
            }
        }

        Spacer(Modifier.height(8.dp))

        // 延时信息显示（有数据时显示）
        if (totalLatencyMs > 0) {
            LatencyInfoRow(
                asrLatencyMs = asrLatencyMs,
                correctionLatencyMs = correctionLatencyMs,
                totalLatencyMs = totalLatencyMs
            )
            Spacer(Modifier.height(8.dp))
        }

        // Content based on selected tab
        when (selectedTab) {
            0 -> OriginalTranscriptTab(
                finalText = finalText,
                partialText = partialText
            )
            1 -> CorrectedTranscriptTab(
                correctedText = correctedText,
                pendingCorrections = pendingCorrections
            )
            2 -> CommandsTab(
                commands = detectedCommands
            )
        }
    }
}

// ── Original transcript tab ─────────────────────────────────────────────────────

@Composable
fun OriginalTranscriptTab(
    finalText: String,
    partialText: String,
    modifier: Modifier = Modifier
) {
    val scrollState = rememberScrollState()

    LaunchedEffect(finalText) {
        scrollState.animateScrollTo(scrollState.maxValue)
    }

    val isEmpty = finalText.isEmpty() && partialText.isEmpty()

    Surface(
        modifier      = modifier.fillMaxWidth(),
        shape         = MaterialTheme.shapes.medium,
        tonalElevation = 1.dp,
        shadowElevation = 0.dp
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp)
        ) {
            if (isEmpty) {
                Text(
                    text     = "点击麦克风按钮开始识别…",
                    style    = MaterialTheme.typography.bodyLarge,
                    color    = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                    modifier = Modifier.align(Alignment.Center)
                )
            } else {
                Text(
                    text = buildAnnotatedString {
                        // Final text
                        withStyle(
                            SpanStyle(color = MaterialTheme.colorScheme.onSurface)
                        ) {
                            append(finalText)
                        }
                        // Partial text
                        if (partialText.isNotEmpty()) {
                            withStyle(
                                SpanStyle(
                                    color     = MaterialTheme.colorScheme.onSurfaceVariant,
                                    fontStyle = FontStyle.Italic
                                )
                            ) {
                                if (finalText.isNotEmpty()) append(" ")
                                append(partialText)
                            }
                        }
                    },
                    style    = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.verticalScroll(scrollState)
                )
            }
        }
    }
}

// ── Corrected transcript tab ───────────────────────────────────────────────────

@Composable
fun CorrectedTranscriptTab(
    correctedText: String,
    pendingCorrections: Map<Int, com.example.asrapp.viewmodel.SentenceCorrection>,
    modifier: Modifier = Modifier
) {
    val scrollState = rememberScrollState()

    LaunchedEffect(correctedText) {
        scrollState.animateScrollTo(scrollState.maxValue)
    }

    Surface(
        modifier      = modifier.fillMaxWidth(),
        shape         = MaterialTheme.shapes.medium,
        tonalElevation = 1.dp,
        shadowElevation = 0.dp
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp)
        ) {
            if (correctedText.isEmpty()) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    modifier = Modifier.align(Alignment.Center)
                ) {
                    Text(
                        text     = "暂无纠错结果",
                        style    = MaterialTheme.typography.bodyLarge,
                        color    = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text     = "识别带有ASR错误的文本后会显示纠正内容",
                        style    = MaterialTheme.typography.bodySmall,
                        color    = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.3f)
                    )
                }
            } else {
                Column {
                    // 纠正后的文本
                    if (pendingCorrections.isNotEmpty()) {
                        // 按句子显示，每句带差异数据
                        pendingCorrections.values
                            .sortedBy { it.index }
                            .forEach { correction ->
                                Spacer(Modifier.height(4.dp))
                                CorrectedText(
                                    original = correction.original,
                                    corrected = correction.corrected,
                                    corrections = correction.corrections,
                                    modifier = Modifier.fillMaxWidth()
                                )
                            }
                    } else {
                        // 整体显示
                        Text(
                            text = correctedText,
                            style = MaterialTheme.typography.bodyLarge,
                            modifier = Modifier.verticalScroll(scrollState)
                        )
                    }

                    Spacer(Modifier.height(16.dp))

                    // 差异说明
                    DiffLegend()
                }
            }
        }
    }
}

// ── Commands tab ───────────────────────────────────────────────────────────────

@Composable
fun CommandsTab(
    commands: List<CommandInfo>,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier      = modifier.fillMaxWidth(),
        shape         = MaterialTheme.shapes.medium,
        tonalElevation = 1.dp,
        shadowElevation = 0.dp
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp)
        ) {
            if (commands.isEmpty()) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    modifier = Modifier.align(Alignment.Center)
                ) {
                    Text(
                        text     = "暂无检测到命令",
                        style    = MaterialTheme.typography.bodyLarge,
                        color    = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text     = "说出如「打开客厅的灯」等智能家居命令",
                        style    = MaterialTheme.typography.bodySmall,
                        color    = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.3f)
                    )
                }
            } else {
                Column(
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(
                        text = "📌 检测到 ${commands.size} 条命令",
                        style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.primary
                    )

                    commands.forEach { command ->
                        CommandItem(command = command)
                    }
                }
            }
        }
    }
}
