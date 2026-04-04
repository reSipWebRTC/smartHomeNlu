package com.example.asrapp.router

import android.util.Log
import com.example.asrapp.network.CorrectionMode
import com.example.asrapp.network.FallbackStrategy
import com.example.asrapp.network.NetworkConfig
import com.example.asrapp.network.WordfillerApi
import com.example.asrapp.network.model.CorrectionResponse
import com.example.asrapp.network.model.DiffType
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * ASR结果路由器
 *
 * 职责：
 * 1. 决定结果是否需要发送服务端纠错
 * 2. 协调即时UI更新和后台纠错
 * 3. 管理纠错请求的生命周期
 */
class ResultRouter(
    private val scope: CoroutineScope,
    private val config: NetworkConfig = NetworkConfig(),
    private val onImmediateResult: (AsrImmediateResult) -> Unit,
    private val onCorrectionResult: (AsrCorrectionResult) -> Unit
) {
    private val TAG = "ResultRouter"

    private val apiClient = com.example.asrapp.network.WordfillerApi.getInstance(config)
    private val fallbackStrategy = FallbackStrategy(config)

    // 追踪正在进行的纠错请求
    private val pendingCorrections = mutableMapOf<String, CorrectionJob>()
    private var networkAvailable = true

    // 智能家居关键词检测
    private val smartHomeKeywords = listOf(
        "打开", "关闭", "开启", "停止", "启动",
        "灯", "空调", "窗帘", "电视", "插座",
        "客厅", "卧室", "书房", "二楼",
        "温度", "亮度", "调高", "调低"
    )

    /**
     * 处理ASR结果
     */
    fun onAsrResult(result: AsrResult) {
        when (result) {
            is AsrResult.Partial -> {
                // Partial结果立即显示，不发送服务端
                onImmediateResult(AsrImmediateResult.Partial(result.text))
            }

            is AsrResult.Final -> {
                // Final结果先立即显示
                onImmediateResult(AsrImmediateResult.Final(result.text, result.index))

                // 判断是否需要服务端纠错
                val mode = fallbackStrategy.decideMode(result.text, networkAvailable)
                Log.i(TAG, "ASR Final: text='${result.text}', networkAvailable=$networkAvailable, mode=$mode")
                handleCorrection(result.text, result.index, mode)
            }
        }
    }

    /**
     * 处理服务端纠错
     */
    private fun handleCorrection(text: String, index: Int, mode: CorrectionMode) {
        when (mode) {
            CorrectionMode.LOCAL_ONLY -> {
                Log.d(TAG, "Using local-only mode for: '$text'")
                // 不发送服务端，已经通过ImmediateResult显示了本地结果
            }

            CorrectionMode.HYBRID_ASYNC -> {
                Log.d(TAG, "Using hybrid async mode for: '$text'")
                sendCorrectionRequest(text, index, async = true)
            }

            CorrectionMode.HYBRID_SYNC -> {
                Log.d(TAG, "Using hybrid sync mode for: '$text'")
                sendCorrectionRequest(text, index, async = false)
            }
        }
    }

    /**
     * 发送纠错请求
     */
    private fun sendCorrectionRequest(text: String, index: Int, async: Boolean) {
        // 取消之前的同一位置纠错请求（如果有）
        pendingCorrections[index.toString()]?.job?.cancel()

        Log.i(TAG, "sendCorrectionRequest: text='$text', index=$index, async=$async, serverUrl=${config.serverUrl}")

        val job = scope.launch {
            // 添加小延迟，避免频繁请求
            if (async) {
                delay(50)
            }

            try {
                Log.d(TAG, "Calling apiClient.correct()...")
                val result = apiClient.correct(text)
                Log.d(TAG, "apiClient.correct() returned: ${result.isSuccess}")

                result
                    .getOrNull()
                    ?.let { response ->
                        Log.d(TAG, "Response: corrected='${response.corrected}', isSuccess=${response.isSuccess}, commands=${response.commands?.size}")
                        if (response.isSuccess && (response.corrected != text || !response.commands.isNullOrEmpty())) {
                            Log.i(TAG, "Correction received: '${response.corrected}'")
                            onCorrectionResult(AsrCorrectionResult(
                                index = index,
                                original = text,
                                corrected = response.corrected,
                                corrections = response.corrections ?: emptyList(),
                                commands = response.commands ?: emptyList(),
                                confidence = response.confidence,
                                processingTimeMs = response.processingTimeMs
                            ))
                        } else {
                            Log.d(TAG, "No correction needed or failed")
                        }
                    }
                    ?: Log.w(TAG, "Correction request failed: null result")
            } catch (e: Exception) {
                Log.e(TAG, "Correction request exception", e)
            } finally {
                pendingCorrections.remove(index.toString())
            }
        }

        pendingCorrections[index.toString()] = CorrectionJob(text, job)
    }

    /**
     * 设置网络可用性
     */
    fun setNetworkAvailable(available: Boolean) {
        networkAvailable = available
        Log.d(TAG, "Network availability changed: $available")
    }

    /**
     * 取消所有待处理的纠错请求
     */
    fun cancelAll() {
        pendingCorrections.values.forEach { it.job.cancel() }
        pendingCorrections.clear()
    }

    /**
     * 清理资源
     */
    fun release() {
        cancelAll()
    }
}

// ── 数据类 ─────────────────────────────────────────────────────────────

/**
 * ASR原始结果
 */
sealed class AsrResult {
    /** 临时结果（流式输出中） */
    data class Partial(val text: String) : AsrResult()

    /** 最终结果（句子结束） */
    data class Final(val text: String, val index: Int) : AsrResult()
}

/**
 * 即时显示结果
 */
sealed class AsrImmediateResult {
    /** 临时结果 */
    data class Partial(val text: String) : AsrImmediateResult()

    /** 最终结果（本地处理） */
    data class Final(val text: String, val index: Int) : AsrImmediateResult()
}

/**
 * 服务端纠错结果
 */
data class AsrCorrectionResult(
    val index: Int,                           // 句子索引
    val original: String,                     // 原始文本
    val corrected: String,                    // 纠正后文本
    val corrections: List<com.example.asrapp.network.model.DiffSpan>,  // 差异列表
    val commands: List<com.example.asrapp.network.model.CommandInfo>,  // 命令列表
    val confidence: Float,                    // 置信度
    val processingTimeMs: Float               // 处理耗时
) {
    /** 是否有纠正 */
    val hasCorrections: Boolean
        get() = corrections.isNotEmpty()

    /** 是否解析出命令 */
    val hasCommands: Boolean
        get() = commands.isNotEmpty()

    /** 获取拼音纠差异数 */
    val phoneticCorrections: List<com.example.asrapp.network.model.DiffSpan>
        get() = corrections.filter { it.type == DiffType.PHONETIC.name }

    /** 获取填充词删除差异数 */
    val fillerCorrections: List<com.example.asrapp.network.model.DiffSpan>
        get() = corrections.filter { it.type == DiffType.FILLER.name }
}

/**
 * 纠错任务
 */
private data class CorrectionJob(
    val text: String,
    val job: Job
)
