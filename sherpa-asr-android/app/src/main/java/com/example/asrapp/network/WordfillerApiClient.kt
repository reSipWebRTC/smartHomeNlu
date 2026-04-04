package com.example.asrapp.network

import android.util.Log
import com.example.asrapp.network.model.CorrectionResponse
import com.example.asrapp.network.model.CompletionResponse
import com.example.asrapp.network.model.ConfirmRequest
import com.example.asrapp.network.model.SmartHomeRequest
import com.example.asrapp.network.model.SmartHomeResponse
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.logging.HttpLoggingInterceptor
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Wordfiller服务端API客户端
 * 负责与 SmartHome NLU Runtime 通信
 */
class WordfillerApiClient(
    private val config: NetworkConfig = NetworkConfig()
) {
    companion object {
        const val DEFAULT_SESSION_ID = "sess_android_default"
        const val DEFAULT_USER_ID = "usr_android_default"
    }

    private val TAG = "WordfillerApiClient"

    private val moshi: Moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    private val client: OkHttpClient by lazy {
        val builder = OkHttpClient.Builder()
            .connectTimeout(config.timeoutMs, TimeUnit.MILLISECONDS)
            .readTimeout(config.timeoutMs, TimeUnit.MILLISECONDS)
            .writeTimeout(config.timeoutMs, TimeUnit.MILLISECONDS)

        // 添加日志拦截器（始终启用）
        val loggingInterceptor = HttpLoggingInterceptor { message ->
            Log.d(TAG, message)
        }.apply {
            level = HttpLoggingInterceptor.Level.BODY
        }
        builder.addInterceptor(loggingInterceptor)

        builder.build()
    }

    private val smartHomeRequestAdapter by lazy {
        moshi.adapter(SmartHomeRequest::class.java)
    }

    private val confirmRequestAdapter by lazy {
        moshi.adapter(ConfirmRequest::class.java)
    }

    private val smartHomeResponseAdapter by lazy {
        moshi.adapter(SmartHomeResponse::class.java)
    }

    private val jsonMediaType = "application/json".toMediaType()

    /**
     * 发送纠错请求
     *
     * @param text ASR识别的原始文本
     * @return CorrectionResponse 纠错结果
     */
    suspend fun correct(text: String): Result<CorrectionResponse> = withContext(Dispatchers.IO) {
        Log.w(TAG, "correct() is deprecated after migration to /api/v1/command")
        Result.failure(UnsupportedOperationException("Legacy correction endpoint has been removed"))
    }

    /**
     * 智能家居指令解析
     *
     * 使用 /api/v1/command 端点，返回意图识别与执行结果
     *
     * @param text 原始ASR文本
     * @param useGlm 兼容旧调用方参数（已不使用）
     * @param sessionId 会话ID
     * @param userId 用户ID
     * @param userRole 用户角色（可选）
     * @return SmartHomeResponse 解析结果
     */
    suspend fun parseSmartHome(
        text: String,
        useGlm: Boolean = true,
        sessionId: String = DEFAULT_SESSION_ID,
        userId: String = DEFAULT_USER_ID,
        userRole: String? = null
    ): Result<SmartHomeResponse> = withContext(Dispatchers.IO) {
        try {
            Log.d(
                TAG,
                "Parsing smart home command: text='$text', sessionId='$sessionId', userId='$userId', useGlm=$useGlm"
            )

            val request = SmartHomeRequest(
                sessionId = sessionId,
                userId = userId,
                text = text,
                userRole = userRole
            )
            val jsonBody = smartHomeRequestAdapter.toJson(request)

            val httpRequest: Request = Request.Builder()
                .url(config.getCommandEndpoint())
                .post(jsonBody.toRequestBody(jsonMediaType))
                .build()

            val response = client.newCall(httpRequest).execute()
            val responseBody = response.body?.string()
            if (responseBody == null) {
                Log.e(TAG, "Empty response body")
                return@withContext Result.failure(IOException("Empty response body"))
            }

            Log.d(TAG, "Smart home response: $responseBody")

            val smartHomeResponse = smartHomeResponseAdapter.fromJson(responseBody)
            if (smartHomeResponse == null) {
                Log.e(TAG, "Failed to parse smart home response")
                return@withContext Result.failure(IOException("Failed to parse response"))
            }

            if (!response.isSuccessful) {
                Log.w(TAG, "Server returned HTTP ${response.code}: ${response.message}, code=${smartHomeResponse.code}")
            }
            if (!smartHomeResponse.isSuccess) {
                Log.w(TAG, "Business result is not success: code=${smartHomeResponse.code}, message=${smartHomeResponse.message}")
            }

            Log.d(
                TAG,
                "Smart home parse done: code=${smartHomeResponse.code}, intent=${smartHomeResponse.data.intent}, sub_intent=${smartHomeResponse.data.subIntent}"
            )

            Result.success(smartHomeResponse)

        } catch (e: Exception) {
            Log.e(TAG, "Smart home parse failed", e)
            Result.failure(e)
        }
    }

    /**
     * 提交风险确认
     *
     * @param confirmToken /api/v1/command 返回的确认令牌
     * @param accept true=确认执行, false=取消
     */
    suspend fun confirmCommand(confirmToken: String, accept: Boolean): Result<SmartHomeResponse> = withContext(Dispatchers.IO) {
        try {
            val request = ConfirmRequest(confirmToken = confirmToken, accept = accept)
            val jsonBody = confirmRequestAdapter.toJson(request)

            val httpRequest: Request = Request.Builder()
                .url(config.getConfirmEndpoint())
                .post(jsonBody.toRequestBody(jsonMediaType))
                .build()

            val response = client.newCall(httpRequest).execute()
            val responseBody = response.body?.string()
            if (responseBody == null) {
                Log.e(TAG, "confirmCommand: Empty response body")
                return@withContext Result.failure(IOException("Empty response body"))
            }

            val parsed = smartHomeResponseAdapter.fromJson(responseBody)
            if (parsed == null) {
                Log.e(TAG, "confirmCommand: Failed to parse response: $responseBody")
                return@withContext Result.failure(IOException("Failed to parse response"))
            }

            if (!response.isSuccessful) {
                Log.w(TAG, "confirmCommand: HTTP ${response.code} ${response.message}, code=${parsed.code}")
            }

            Result.success(parsed)
        } catch (e: Exception) {
            Log.e(TAG, "confirmCommand failed", e)
            Result.failure(e)
        }
    }

    /**
     * 智能补全
     *
     * 根据部分输入推测完整意图
     *
     * @param partial 部分输入文本
     * @param maxResults 最多返回候选数（默认5）
     * @return CompletionResponse 补全结果
     */
    suspend fun complete(partial: String, maxResults: Int = 5): Result<CompletionResponse> = withContext(Dispatchers.IO) {
        Log.w(TAG, "complete() is deprecated after migration to /api/v1/command: partial='$partial', maxResults=$maxResults")
        Result.failure(UnsupportedOperationException("Legacy completion endpoint has been removed"))
    }

    /**
     * 测试服务端连接
     *
     * @return true 如果服务端可用
     */
    suspend fun testConnection(): Boolean = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url(config.getHealthEndpoint())
                .get()
                .build()

            val response = client.newCall(request).execute()
            response.isSuccessful
        } catch (e: Exception) {
            Log.e(TAG, "Connection test failed", e)
            false
        }
    }

    /**
     * 更新配置
     */
    fun updateConfig(newConfig: NetworkConfig) {
        Log.d(TAG, "updateConfig() called. Create a new WordfillerApiClient to apply: $newConfig")
    }
}

/**
 * API客户端单例
 */
object WordfillerApi {
    private var client: WordfillerApiClient? = null

    fun getInstance(config: NetworkConfig = NetworkConfig()): WordfillerApiClient {
        return client ?: WordfillerApiClient(config).also {
            client = it
        }
    }

    fun reset() {
        client = null
    }
}
