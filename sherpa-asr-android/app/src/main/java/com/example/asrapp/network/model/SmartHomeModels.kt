package com.example.asrapp.network.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

/**
 * 智能家居解析数据模型
 * 与服务端 /api/v1/command 端点对应
 */

// ── 请求模型 ─────────────────────────────────────────────────────────────

@JsonClass(generateAdapter = true)
data class SmartHomeRequest(
    @param:Json(name = "session_id")
    val sessionId: String,

    @param:Json(name = "user_id")
    val userId: String,

    @param:Json(name = "text")
    val text: String,

    @param:Json(name = "user_role")
    val userRole: String? = null
)

@JsonClass(generateAdapter = true)
data class ConfirmRequest(
    @param:Json(name = "confirm_token")
    val confirmToken: String,

    @param:Json(name = "accept")
    val accept: Boolean = true
)

// ── 响应模型 ─────────────────────────────────────────────────────────────

@JsonClass(generateAdapter = true)
data class SmartHomeResponse(
    @param:Json(name = "trace_id")
    val traceId: String? = null,

    @param:Json(name = "code")
    val code: String = "INTERNAL_ERROR",

    @param:Json(name = "message")
    val message: String = "",

    @param:Json(name = "retryable")
    val retryable: Boolean = false,

    @param:Json(name = "data")
    val data: SmartHomeResponseData = SmartHomeResponseData()
) {
    val isSuccess: Boolean
        get() = code == "OK" || code == "POLICY_CONFIRM_REQUIRED"

    // 为兼容旧UI字段：当前展示服务端回复文案。
    val filtered: String
        get() = data.replyText.ifBlank { data.ttsText.ifBlank { message } }
}

@JsonClass(generateAdapter = true)
data class SmartHomeResponseData(
    @param:Json(name = "status")
    val status: String = "",

    @param:Json(name = "reply_text")
    val replyText: String = "",

    @param:Json(name = "tts_text")
    val ttsText: String = "",

    @param:Json(name = "intent")
    val intent: String = "",

    @param:Json(name = "sub_intent")
    val subIntent: String = "",

    @param:Json(name = "confirm_token")
    val confirmToken: String? = null,

    @param:Json(name = "expires_in_sec")
    val expiresInSec: Int? = null,

    @param:Json(name = "idempotent_hit")
    val idempotentHit: Boolean? = null
)

// ── 流式响应事件类型 ───────────────────────────────────────────────────────

@JsonClass(generateAdapter = true)
data class StreamEvent(
    @param:Json(name = "type")
    val type: EventType,

    @param:Json(name = "text")
    val text: String? = null,

    @param:Json(name = "delta")
    val delta: String? = null,

    @param:Json(name = "commands")
    val commands: List<CommandInfo>? = null,

    @param:Json(name = "confidence")
    val confidence: Float? = null,

    @param:Json(name = "latency_ms")
    val latencyMs: Float? = null,

    @param:Json(name = "glm_needed")
    val glmNeeded: Boolean? = null,

    @param:Json(name = "glm_used")
    val glmUsed: Boolean? = null,

    @param:Json(name = "is_final")
    val isFinal: Boolean? = null
)

enum class EventType {
    IMMEDIATE,
    TOKEN,
    DONE
}

// ── 智能补全模型 ─────────────────────────────────────────────────────────────

@JsonClass(generateAdapter = true)
data class CompletionRequest(
    @param:Json(name = "partial")
    val partial: String,

    @param:Json(name = "max_results")
    val maxResults: Int = 5
)

@JsonClass(generateAdapter = true)
data class CompletionCandidate(
    @param:Json(name = "completed")
    val completed: String,

    @param:Json(name = "confidence")
    val confidence: Float,

    @param:Json(name = "match_type")
    val matchType: String,

    @param:Json(name = "source")
    val source: String
)

@JsonClass(generateAdapter = true)
data class CompletionResponse(
    @param:Json(name = "partial")
    val partial: String,

    @param:Json(name = "completions")
    val completions: List<CompletionCandidate>? = null,

    @param:Json(name = "total_latency_ms")
    val totalLatencyMs: Float? = null
)
