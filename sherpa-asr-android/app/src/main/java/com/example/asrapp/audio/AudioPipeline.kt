package com.example.asrapp.audio

import android.util.Log
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import com.k2fsa.sherpa.onnx.OnlineStream
import com.k2fsa.sherpa.onnx.Vad
import com.example.asrapp.utils.FillerWordFilter

class AudioPipeline(
    private val recognizer: OnlineRecognizer,
    private val vad:        Vad,
    private val onPartial:  (String) -> Unit,
    private val onFinal:    (String) -> Unit,
) {
    private val TAG = "AudioPipeline"

    private var stream: OnlineStream = recognizer.createStream()
    private var isSpeaking   = false
    private var silenceCount = 0
    private var lastPartial  = ""

    // 32ms/frame，600ms 静音 ≈ 19 帧
    // TAIL_FRAMES: 尾部缓冲，防止结尾丢字（渐进增加：5→10→15）
    private val TAIL_FRAMES           = 10   // 320ms 尾部缓冲
    private val SILENCE_COMMIT_FRAMES = 19

    fun feedFrame(samples: FloatArray) {
        // 送入 VAD 环形缓冲
        vad.acceptWaveform(samples)

        // 取出所有 VAD 检测到的语音段
        // 注意：sherpa-onnx Vad 用 empty() 不是 isEmpty()
        while (!vad.empty()) {
            val segment = vad.front()
            vad.pop()
            if (segment.samples.isNotEmpty()) {
                isSpeaking   = true
                silenceCount = 0
                acceptAndDecode(segment.samples)
            }
        }

        // 语音结束后的静音追踪
        if (isSpeaking) {
            silenceCount++
            if (silenceCount <= TAIL_FRAMES) {
                acceptAndDecode(samples)
            }
            if (silenceCount >= SILENCE_COMMIT_FRAMES) {
                commitFinal()
            }
        }
    }

    private fun acceptAndDecode(samples: FloatArray) {
        stream.acceptWaveform(samples, sampleRate = MicRecorder.SAMPLE_RATE)
        while (recognizer.isReady(stream)) {
            recognizer.decode(stream)
        }
        val text = recognizer.getResult(stream).text.trim()
        if (text.isNotEmpty() && text != lastPartial) {
            lastPartial = text
            onPartial(text)
        }
        if (recognizer.isEndpoint(stream)) {
            commitFinal()
        }
    }

    private fun commitFinal() {
        val text = recognizer.getResult(stream).text.trim()
        if (text.isNotEmpty()) {
            onFinal(FillerWordFilter.clean(text))
        }
        resetStream()
    }

    private fun resetStream() {
        recognizer.reset(stream)
        stream.release()
        stream       = recognizer.createStream()
        isSpeaking   = false
        silenceCount = 0
        lastPartial  = ""
    }

    fun release() {
        stream.release()
        vad.release()
    }
}