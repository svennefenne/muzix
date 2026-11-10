package io.github.svennefenne.muzix

import androidx.media3.common.C
import androidx.media3.exoplayer.audio.TeeAudioProcessor
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.log10
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * The visualizer's spectrum (step 7 in docs/app-plan.md): the sound the player sends to the speaker
 * (a tee in its audio sink, PlaybackService), its frequencies as the page's analyser has them
 * (frontend/src/player/engine.ts: 256 bands, a byte each between -100 and -30 dB), the newest kept for
 * PlayerBridge to send while the page shows.
 */
object Spectrum : TeeAudioProcessor.AudioBufferSink {
    const val SIZE = 512                     // the analyser's fftSize: 256 bands
    private val window = DoubleArray(SIZE) { i ->      // Blackman, as the Web Audio analyser windows
        0.42 - 0.5 * cos(2 * PI * i / SIZE) + 0.08 * cos(4 * PI * i / SIZE)
    }
    private val ring = FloatArray(SIZE)
    private var at = 0
    private var filled = 0
    private var channels = 2
    private var encoding = C.ENCODING_PCM_16BIT
    private var sinceLast = 0
    private var every = 1470                 // frames between two looks: about 30 a second
    /** Only while the page shows: the screen off, nothing is worked out. */
    @Volatile var wanted = false
    @Volatile var bands: ByteArray? = null
        private set
    @Volatile var when_ = 0L
        private set

    override fun flush(sampleRateHz: Int, channelCount: Int, encoding: Int) {
        channels = channelCount.coerceAtLeast(1)
        this.encoding = encoding
        every = (sampleRateHz / 30).coerceAtLeast(256)
        filled = 0
    }

    override fun handleBuffer(buffer: ByteBuffer) {
        if (!wanted) return
        val b = buffer.duplicate().order(ByteOrder.nativeOrder())
        val float = encoding == C.ENCODING_PCM_FLOAT
        if (!float && encoding != C.ENCODING_PCM_16BIT) return
        val frameBytes = channels * if (float) 4 else 2
        while (b.remaining() >= frameBytes) {
            var sum = 0f
            repeat(channels) { sum += if (float) b.float else b.short / 32768f }
            ring[at] = sum / channels
            at = (at + 1) % SIZE
            if (filled < SIZE) filled++
            if (++sinceLast >= every && filled == SIZE) {
                sinceLast = 0
                analyse()
            }
        }
    }

    private fun analyse() {
        val re = DoubleArray(SIZE) { i -> ring[(at + i) % SIZE] * window[i] }
        val im = DoubleArray(SIZE)
        fft(re, im)
        val out = ByteArray(SIZE / 2)
        for (k in 0 until SIZE / 2) {
            val mag = sqrt(re[k] * re[k] + im[k] * im[k]) / SIZE
            val db = if (mag > 0) 20 * log10(mag) else -200.0
            out[k] = ((db + 100) / 70 * 255).coerceIn(0.0, 255.0).toInt().toByte()
        }
        bands = out
        when_ = System.currentTimeMillis()
    }

    /** In place, radix 2. */
    private fun fft(re: DoubleArray, im: DoubleArray) {
        val n = re.size
        var j = 0
        for (i in 1 until n) {
            var bit = n shr 1
            while (j and bit != 0) {
                j = j xor bit
                bit = bit shr 1
            }
            j = j xor bit
            if (i < j) {
                re[i] = re[j].also { re[j] = re[i] }
                im[i] = im[j].also { im[j] = im[i] }
            }
        }
        var len = 2
        while (len <= n) {
            val ang = -2 * PI / len
            for (i in 0 until n step len) {
                for (k in 0 until len / 2) {
                    val wr = cos(ang * k)
                    val wi = sin(ang * k)
                    val ur = re[i + k]
                    val ui = im[i + k]
                    val vr = re[i + k + len / 2] * wr - im[i + k + len / 2] * wi
                    val vi = re[i + k + len / 2] * wi + im[i + k + len / 2] * wr
                    re[i + k] = ur + vr
                    im[i + k] = ui + vi
                    re[i + k + len / 2] = ur - vr
                    im[i + k + len / 2] = ui - vi
                }
            }
            len = len shl 1
        }
    }
}
