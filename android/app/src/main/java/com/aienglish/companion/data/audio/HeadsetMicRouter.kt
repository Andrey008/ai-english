package com.aienglish.companion.data.audio

import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.util.Log

private const val TAG = "HeadsetMicRouter"

/** Switches a Bluetooth headset into its call profile (HFP/SCO) so its own
 * microphone can be used. Over the music profile (A2DP) a headset only
 * plays audio and the phone's built-in mic records. The call profile is
 * two-way but mono and narrower (16 kHz mSBC, or 8 kHz CVSD on older
 * headsets), for playback too. That is the price of not having to talk
 * into the phone (2026-11-11 phone test). */
class HeadsetMicRouter(private val context: Context) {
    private val audioManager: AudioManager
        get() = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager

    @Volatile private var active = false

    /** Returns the headset's name if it was selected as the communication
     * device, or `null` if no Bluetooth headset is connected (the phone
     * mic is then used as usual). */
    fun enable(): String? {
        val device = audioManager.availableCommunicationDevices.firstOrNull {
            it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO || it.type == AudioDeviceInfo.TYPE_BLE_HEADSET
        } ?: run {
            Log.i(TAG, "no Bluetooth headset available; using the phone mic")
            return null
        }
        audioManager.mode = AudioManager.MODE_IN_COMMUNICATION
        if (!audioManager.setCommunicationDevice(device)) {
            Log.w(TAG, "setCommunicationDevice refused for ${device.productName}")
            audioManager.mode = AudioManager.MODE_NORMAL
            return null
        }
        active = true
        Log.i(TAG, "headset mic selected: ${device.productName} (type ${device.type})")
        return device.productName.toString()
    }

    fun disable() {
        if (!active) return
        audioManager.clearCommunicationDevice()
        audioManager.mode = AudioManager.MODE_NORMAL
        active = false
    }
}
