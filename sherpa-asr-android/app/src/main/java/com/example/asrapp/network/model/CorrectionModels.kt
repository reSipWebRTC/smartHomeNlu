package com.example.asrapp.network.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

/**
 * 端侧ASR纠错数据模型
 * 与服务端 asr_correction_models.py 对应
 */

// ── 请求模型 ─────────────────────────────────────────────────────────────

@JsonClass(generateAdapter = true)
data class CorrectionOptions(
    @Json(name = "use_phonetic_correction")
    val usePhoneticCorrection: Boolean = true,

    @Json(name = "use_smart_home_rules")
    val useSmartHomeRules: Boolean = true,

    @Json(name = "use_glm")
    val useGlm: Boolean = false,

    @Json(name = "return_commands")
    val returnCommands: Boolean = true,

    @Json(name = "return_diffs")
    val returnDiffs: Boolean = true
)

@JsonClass(generateAdapter = true)
data class CorrectionRequest(
    val text: String,

    @Json(name = "options")
    val options: CorrectionOptions? = CorrectionOptions()
)

// ── 响应模型 ─────────────────────────────────────────────────────────────

enum class DiffType {
    @Json(name = "phonetic")
    PHONETIC,

    @Json(name = "filler")
    FILLER,

    @Json(name = "grammar")
    GRAMMAR,

    @Json(name = "command")
    COMMAND
}

@JsonClass(generateAdapter = true)
data class DiffSpan(
    @Json(name = "start")
    val start: Int,

    @Json(name = "end")
    val end: Int,

    @Json(name = "original")
    val original: String,

    @Json(name = "corrected")
    val corrected: String,

    @Json(name = "type")
    val type: String  // DiffType as string for Moshi
)

@JsonClass(generateAdapter = true)
data class CommandInfo(
    @Json(name = "action")
    val action: String,

    @Json(name = "device")
    val device: String,

    @Json(name = "location")
    val location: String? = null,

    @Json(name = "parameter")
    val parameter: String? = null,

    @Json(name = "value")
    val value: String? = null,

    @Json(name = "raw")
    val raw: String
)

@JsonClass(generateAdapter = true)
data class CorrectionResponse(
    @Json(name = "original")
    val original: String,

    @Json(name = "corrected")
    val corrected: String,

    @Json(name = "commands")
    val commands: List<CommandInfo>? = null,

    @Json(name = "corrections")
    val corrections: List<DiffSpan>? = null,

    @Json(name = "confidence")
    val confidence: Float,

    @Json(name = "processing_time_ms")
    val processingTimeMs: Float,

    @Json(name = "rule_hit")
    val ruleHit: Boolean = false,

    @Json(name = "glm_used")
    val glmUsed: Boolean = false,

    @Json(name = "error")
    val error: String? = null
) {
    val isSuccess: Boolean
        get() = error == null

    val hasCorrections: Boolean
        get() = !corrections.isNullOrEmpty()

    val hasCommands: Boolean
        get() = !commands.isNullOrEmpty()
}
