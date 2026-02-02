package com.goalstick.android.wifi

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.Build
import androidx.core.app.ActivityCompat

class WifiHelper(private val context: Context) {
    
    private val wifiManager: WifiManager? by lazy {
        context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
    }
    
    private val connectivityManager: ConnectivityManager? by lazy {
        context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
    }
    
    /**
     * Get the SSID of the currently connected WiFi network.
     * Returns null if not connected to WiFi or permissions not granted.
     */
    fun getCurrentSsid(): String? {
        // Check location permission (required for WiFi SSID on Android 8.1+)
        if (ActivityCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) 
            != PackageManager.PERMISSION_GRANTED) {
            return null
        }
        
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            // Android 10+ - use ConnectivityManager
            getCurrentSsidApi29()
        } else {
            // Android 9 and below - use WifiManager
            getCurrentSsidLegacy()
        }
    }
    
    @Suppress("DEPRECATION")
    private fun getCurrentSsidLegacy(): String? {
        val wifiInfo = wifiManager?.connectionInfo ?: return null
        val ssid = wifiInfo.ssid
        
        // SSID is wrapped in quotes, remove them
        return ssid?.removeSurrounding("\"")?.takeIf { 
            it.isNotEmpty() && it != "<unknown ssid>" 
        }
    }
    
    private fun getCurrentSsidApi29(): String? {
        val network = connectivityManager?.activeNetwork ?: return null
        val capabilities = connectivityManager?.getNetworkCapabilities(network) ?: return null
        
        if (!capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) {
            return null
        }
        
        // On Android 10+, we need to use WifiManager with location permission
        @Suppress("DEPRECATION")
        val wifiInfo = wifiManager?.connectionInfo ?: return null
        val ssid = wifiInfo.ssid
        
        return ssid?.removeSurrounding("\"")?.takeIf { 
            it.isNotEmpty() && it != "<unknown ssid>" 
        }
    }
    
    /**
     * Check if the device is currently connected to WiFi.
     */
    fun isConnectedToWifi(): Boolean {
        val network = connectivityManager?.activeNetwork ?: return false
        val capabilities = connectivityManager?.getNetworkCapabilities(network) ?: return false
        return capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
    }
}
