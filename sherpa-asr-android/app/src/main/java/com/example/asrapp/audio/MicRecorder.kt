package com.example.asrapp.audio

import android.Manifest
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.annotation.RequiresPermission
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Continuously reads microphone audio and delivers Float32 PCM frames
 * at 16 kHz, mono, 512 samples (32 ms) per callback.
 *
 * AudioRecord is created lazily inside start() — after the caller has
 * already obtained RECORD_AUDIO permission — so Lint is satisfied and
 * no SecurityException can be thrown at construction time.
 */
class MicRecorder(
    private val onFrame: (FloatArray) -> Unit
) {
    companion object {
        const val SAMPLE_RATE   = 16_000
        const val FRAME_SAMPLES = 512        // 32 ms @ 16 kHz
    }

    private var audioRecord: AudioRecord? = null
    private var recordJob: Job? = null

    val isRecording: Boolean
        get() = audioRecord?.recordingState == AudioRecord.RECORDSTATE_RECORDING

    @RequiresPermission(Manifest.permission.RECORD_AUDIO)
    fun start(scope: CoroutineScope) {
        if (isRecording) return

        val minBufSize = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_FLOAT
        )

        // AudioRecord is created here, AFTER permission has been granted
        val record = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_FLOAT,
            maxOf(minBufSize, FRAME_SAMPLES * 4)
        )
        audioRecord = record
        record.startRecording()

        recordJob = scope.launch(Dispatchers.IO) {
            val frame = FloatArray(FRAME_SAMPLES)
            while (isActive) {
                val read = record.read(
                    frame, 0, FRAME_SAMPLES, AudioRecord.READ_BLOCKING
                )
                if (read == FRAME_SAMPLES) {
                    onFrame(frame.copyOf())
                }
            }
        }
    }

    fun stop() {
        recordJob?.cancel()
        recordJob = null
        audioRecord?.let {
            if (it.state == AudioRecord.STATE_INITIALIZED) {
                it.stop()
            }
        }
    }

    fun release() {
        stop()
        audioRecord?.release()
        audioRecord = null
    }
}