package com.example.asrapp.audio

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import com.k2fsa.sherpa.onnx.OfflineTts
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch

class TtsPlayer(
    context: Context,
    private val tts: OfflineTts,
    private val onPlaybackStateChanged: (Boolean) -> Unit,
    private val onError: (String) -> Unit,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val audioManager = context.getSystemService(AudioManager::class.java)
    private val audioFocusRequest = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
        .setAudioAttributes(
            AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ASSISTANCE_ACCESSIBILITY)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                .build()
        )
        .build()

    private var playbackJob: Job? = null
    @Volatile
    private var currentTrack: AudioTrack? = null

    fun speak(text: String, sid: Int, speed: Float, startTime: Long = System.currentTimeMillis()) {
        stop()

        val trimmed = text.trim()
        if (trimmed.isEmpty()) return

        android.util.Log.d("TtsPlayer", "speak: 开始，距点击 ${System.currentTimeMillis() - startTime}ms")

        playbackJob = scope.launch {
            val focusResult = audioManager.requestAudioFocus(audioFocusRequest)
            if (focusResult != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
                android.util.Log.e("TtsPlayer", "speak: 无法获取音频焦点")
                onError("无法获取音频焦点")
                return@launch
            }

            onPlaybackStateChanged(true)
            android.util.Log.d("TtsPlayer", "speak: 获取音频焦点成功，距点击 ${System.currentTimeMillis() - startTime}ms")

            try {
                splitIntoSentences(trimmed).forEachIndexed { index, sentence ->
                    ensureActive()
                    val genStartTime = System.currentTimeMillis()
                    android.util.Log.d("TtsPlayer", "speak: 开始生成第 ${index + 1} 句: \"$sentence\"，距点击 ${genStartTime - startTime}ms")

                    val generated = tts.generate(sentence, sid = sid, speed = speed)
                    val genDuration = System.currentTimeMillis() - genStartTime
                    android.util.Log.d("TtsPlayer", "speak: 第 ${index + 1} 句生成耗时 ${genDuration}ms，音频长度 ${generated.samples.size / generated.sampleRate.toFloat()}s，距点击 ${System.currentTimeMillis() - startTime}ms")

                    playSamples(generated.samples, generated.sampleRate, startTime)
                    android.util.Log.d("TtsPlayer", "speak: 第 ${index + 1} 句播放完成，距点击 ${System.currentTimeMillis() - startTime}ms")
                }
            } catch (_: CancellationException) {
                android.util.Log.d("TtsPlayer", "speak: 已取消")
                // Ignore cancellation during manual stop or ViewModel clear.
            } catch (e: Exception) {
                android.util.Log.e("TtsPlayer", "speak: 异常 - ${e.message}", e)
                onError(e.message ?: "TTS 播放失败")
            } finally {
                releaseTrack()
                audioManager.abandonAudioFocusRequest(audioFocusRequest)
                onPlaybackStateChanged(false)
                android.util.Log.d("TtsPlayer", "speak: 全部完成，总耗时 ${System.currentTimeMillis() - startTime}ms")
            }
        }
    }

    fun stop() {
        playbackJob?.cancel()
        playbackJob = null
        releaseTrack()
    }

    fun release() {
        stop()
        tts.release()
        scope.cancel()
    }

    private suspend fun playSamples(samples: FloatArray, sampleRate: Int, startTime: Long) {
        if (samples.isEmpty()) return

        val audioTrackStartTime = System.currentTimeMillis()

        val minBuffer = AudioTrack.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_FLOAT
        ).coerceAtLeast(samples.size * 4)

        val track = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANCE_ACCESSIBILITY)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_FLOAT)
                    .setSampleRate(sampleRate)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build()
            )
            .setBufferSizeInBytes(minBuffer)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()

        currentTrack = track
        android.util.Log.d("TtsPlayer", "playSamples: AudioTrack 创建耗时 ${System.currentTimeMillis() - audioTrackStartTime}ms，距点击 ${System.currentTimeMillis() - startTime}ms")

        track.play()
        android.util.Log.d("TtsPlayer", "playSamples: AudioTrack.play() 调用，距点击 ${System.currentTimeMillis() - startTime}ms")

        track.write(samples, 0, samples.size, AudioTrack.WRITE_BLOCKING)

        val estimatedDurationMs = (samples.size * 1000L / sampleRate) + 80L
        android.util.Log.d("TtsPlayer", "playSamples: 音频写入完成，预计播放时长 ${estimatedDurationMs}ms，距点击 ${System.currentTimeMillis() - startTime}ms")

        delay(estimatedDurationMs)
        releaseTrack(track)
    }

    private fun splitIntoSentences(text: String): List<String> {
        return text
            .split(Regex("(?<=[。！？!?；;\\n])"))
            .map(String::trim)
            .filter(String::isNotEmpty)
            .ifEmpty { listOf(text) }
    }

    private fun releaseTrack(track: AudioTrack? = currentTrack) {
        track?.runCatching {
            pause()
            flush()
            release()
        }
        if (currentTrack === track) {
            currentTrack = null
        }
    }
}
