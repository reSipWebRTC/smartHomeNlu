package com.example.asrapp.network

/**
 * 网络配置
 * 服务端连接参数
 */
data class NetworkConfig(
    val serverUrl: String = DEFAULT_SERVER_URL,
    val timeoutMs: Long = DEFAULT_TIMEOUT,
    val enableCorrection: Boolean = true,
    val cacheEnabled: Boolean = true,
    val retryCount: Int = DEFAULT_RETRY_COUNT
) {
    companion object {
        const val DEFAULT_SERVER_URL = "http://192.168.3.145:8001"
        const val DEFAULT_TIMEOUT = 3000L
        const val DEFAULT_RETRY_COUNT = 2
    }

    /**
     * 获取命令解析端点完整URL
     */
    fun getCommandEndpoint(): String = "$serverUrl/api/v1/command"

    /**
     * 获取健康检查端点完整URL
     */
    fun getHealthEndpoint(): String = "$serverUrl/api/v1/health"

    /**
     * 获取风险确认端点完整URL
     */
    fun getConfirmEndpoint(): String = "$serverUrl/api/v1/confirm"

    /**
     * 兼容旧调用方：统一路由到新命令端点
     */
    fun getCorrectionEndpoint(): String = getCommandEndpoint()

    /**
     * 兼容旧调用方：统一路由到新命令端点
     */
    fun getSmartHomeEndpoint(): String = getCommandEndpoint()

    /**
     * 兼容旧调用方：统一路由到新命令端点
     */
    fun getSmartHomeStreamEndpoint(): String = getCommandEndpoint()

    /**
     * 兼容旧调用方：统一路由到新命令端点
     */
    fun getCompletionEndpoint(): String = getCommandEndpoint()

    /**
     * 验证配置有效性
     */
    fun isValid(): Boolean {
        return serverUrl.isNotBlank() &&
               serverUrl.startsWith("http") &&
               timeoutMs > 0
    }
}

/**
 * 纠错模式
 */
enum class CorrectionMode {
    /** 仅端侧处理，不发送服务端 */
    LOCAL_ONLY,

    /** 先显示本地结果，后台异步纠错 */
    HYBRID_ASYNC,

    /** 等待服务端纠错结果（适用于重要命令） */
    HYBRID_SYNC
}

/**
 * 降级策略
 * 决定何时使用服务端纠错
 */
class FallbackStrategy(
    private val config: NetworkConfig
) {
    private val TAG = "FallbackStrategy"

    /**
     * 判断给定文本应该使用哪种纠错模式
     */
    fun decideMode(text: String, networkAvailable: Boolean): CorrectionMode {
        android.util.Log.d(TAG, "decideMode: text='$text', enableCorrection=${config.enableCorrection}, networkAvailable=$networkAvailable")

        if (!config.enableCorrection || !networkAvailable) {
            android.util.Log.d(TAG, "→ LOCAL_ONLY (correction disabled or no network)")
            return CorrectionMode.LOCAL_ONLY
        }

        // 紧急命令需要更快速响应，不等待服务端
        if (isUrgentCommand(text)) {
            android.util.Log.d(TAG, "→ HYBRID_ASYNC (urgent command)")
            return CorrectionMode.HYBRID_ASYNC
        }

        // 移除短文本限制 - 让智能家居命令也能发送后台
        // 已知同音字错误模式，建议使用服务端纠错
        if (hasKnownPhoneticErrors(text)) {
            android.util.Log.d(TAG, "→ HYBRID_ASYNC (has phonetic errors)")
            return CorrectionMode.HYBRID_ASYNC
        }

        // 检测到智能家居关键词，发送后台解析
        if (hasSmartHomeKeywords(text)) {
            android.util.Log.d(TAG, "→ HYBRID_ASYNC (smart home keywords)")
            return CorrectionMode.HYBRID_ASYNC
        }

        // 默认：先显示本地结果，后台纠错
        android.util.Log.d(TAG, "→ HYBRID_ASYNC (default)")
        return CorrectionMode.HYBRID_ASYNC
    }

    private fun isUrgentCommand(text: String): Boolean {
        val urgentKeywords = listOf("紧急", "马上", "立刻", "停止", "报警")
        return urgentKeywords.any { text.contains(it) }
    }

    private fun hasKnownPhoneticErrors(text: String): Boolean {
        val errorPatterns = listOf("社灯", "床帘", "叫掉", "调的", "森环")
        return errorPatterns.any { text.contains(it) }
    }

    private fun hasSmartHomeKeywords(text: String): Boolean {
        val keywords = listOf(
            "打开", "关闭", "开启", "启动", "停止",
            "灯", "空调", "窗帘", "电视", "插座",
            "客厅", "卧室", "书房", "二楼", "小孩",
            "温度", "亮度", "调高", "调低", "设置为"
        )
        return keywords.any { text.contains(it) }
    }
}
