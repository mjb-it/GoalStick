package com.goalstick.android.wifi

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import androidx.core.app.ActivityCompat

class WifiHelper(private val context: Context) {

    companion object {
        private const val CALLBACK_TIMEOUT_MS = 2_000L
        private const val UNKNOWN_SSID = "<unknown ssid>"
    }

    private val wifiManager: WifiManager? by lazy {
        context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
    }

    private val connectivityManager: ConnectivityManager? by lazy {
        context.applicationContext.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
    }

    private fun hasLocationPermission(): Boolean =
        ActivityCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED

    private fun cleanSsid(raw: String?): String? =
        raw?.removeSurrounding("\"")?.takeIf { it.isNotEmpty() && it != UNKNOWN_SSID }

    /**
     * Deliver the SSID of the connected WiFi network, or null when not on WiFi,
     * when location permission is missing, or when the system withholds it.
     *
     * Android 12+ only reveals the SSID through a NetworkCallback registered
     * with FLAG_INCLUDE_LOCATION_INFO, so the result is asynchronous. The
     * callback always runs on the main thread, exactly once.
     */
    fun requestCurrentSsid(onResult: (String?) -> Unit) {
        if (!hasLocationPermission() || !isConnectedToWifi()) {
            onResult(null)
            return
        }

        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
            onResult(getCurrentSsidLegacy())
            return
        }

        val cm = connectivityManager ?: run { onResult(null); return }
        val mainHandler = Handler(Looper.getMainLooper())
        var delivered = false

        lateinit var callback: ConnectivityManager.NetworkCallback
        fun finish(ssid: String?) {
            if (delivered) return
            delivered = true
            try { cm.unregisterNetworkCallback(callback) } catch (e: Exception) { /* already gone */ }
            mainHandler.post { onResult(ssid) }
        }

        callback = object : ConnectivityManager.NetworkCallback(FLAG_INCLUDE_LOCATION_INFO) {
            override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) {
                val info = capabilities.transportInfo as? WifiInfo
                finish(cleanSsid(info?.ssid))
            }
            override fun onUnavailable() = finish(null)
        }

        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .build()
        try {
            cm.registerNetworkCallback(request, callback)
        } catch (e: Exception) {
            finish(null)
            return
        }
        mainHandler.postDelayed({ finish(null) }, CALLBACK_TIMEOUT_MS)
    }

    @Suppress("DEPRECATION")
    private fun getCurrentSsidLegacy(): String? {
        val wifiInfo = wifiManager?.connectionInfo ?: return null
        return cleanSsid(wifiInfo.ssid)
    }

    /**
     * Check if the device is currently connected to WiFi.
     */
    fun isConnectedToWifi(): Boolean {
        val cm = connectivityManager ?: return false
        val network = cm.activeNetwork ?: return false
        val capabilities = cm.getNetworkCapabilities(network) ?: return false
        return capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
    }
}
