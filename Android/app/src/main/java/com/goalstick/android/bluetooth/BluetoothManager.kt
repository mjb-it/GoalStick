package com.goalstick.android.bluetooth

import android.Manifest
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothSocket
import android.content.Context
import android.content.pm.PackageManager
import android.util.Log
import androidx.core.app.ActivityCompat
import com.goalstick.android.data.GoalStickConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.InputStream
import java.io.OutputStream
import java.util.UUID

class BluetoothManager(private val context: Context) {
    
    companion object {
        private const val TAG = "BluetoothManager"
        val SPP_UUID: UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
    }
    
    private val bluetoothManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
    private val bluetoothAdapter: BluetoothAdapter? = bluetoothManager.adapter
    
    private var bluetoothSocket: BluetoothSocket? = null
    private var outputStream: OutputStream? = null
    private var inputStream: InputStream? = null
    
    private val _connectionState = MutableStateFlow<ConnectionState>(ConnectionState.Disconnected)
    val connectionState: StateFlow<ConnectionState> = _connectionState.asStateFlow()
    
    private val _discoveredDevices = MutableStateFlow<List<BluetoothDevice>>(emptyList())
    val discoveredDevices: StateFlow<List<BluetoothDevice>> = _discoveredDevices.asStateFlow()
    
    sealed class ConnectionState {
        object Disconnected : ConnectionState()
        object Scanning : ConnectionState()
        object Connecting : ConnectionState()
        object Connected : ConnectionState()
        data class Error(val message: String) : ConnectionState()
    }
    
    fun isBluetoothSupported(): Boolean = bluetoothAdapter != null
    
    fun isBluetoothEnabled(): Boolean = bluetoothAdapter?.isEnabled == true
    
    fun getPairedDevices(): List<BluetoothDevice> {
        if (ActivityCompat.checkSelfPermission(context, Manifest.permission.BLUETOOTH_CONNECT) 
            != PackageManager.PERMISSION_GRANTED) {
            return emptyList()
        }
        return bluetoothAdapter?.bondedDevices?.toList() ?: emptyList()
    }
    
    fun startDiscovery() {
        if (ActivityCompat.checkSelfPermission(context, Manifest.permission.BLUETOOTH_SCAN) 
            != PackageManager.PERMISSION_GRANTED) {
            _connectionState.value = ConnectionState.Error("Bluetooth scan permission not granted")
            return
        }
        
        _connectionState.value = ConnectionState.Scanning
        _discoveredDevices.value = getPairedDevices()
        
        bluetoothAdapter?.let { adapter ->
            if (adapter.isDiscovering) {
                adapter.cancelDiscovery()
            }
            adapter.startDiscovery()
        }
    }
    
    fun stopDiscovery() {
        if (ActivityCompat.checkSelfPermission(context, Manifest.permission.BLUETOOTH_SCAN) 
            != PackageManager.PERMISSION_GRANTED) {
            return
        }
        bluetoothAdapter?.cancelDiscovery()
    }
    
    fun addDiscoveredDevice(device: BluetoothDevice) {
        val currentList = _discoveredDevices.value.toMutableList()
        if (!currentList.any { it.address == device.address }) {
            currentList.add(device)
            _discoveredDevices.value = currentList
        }
    }
    
    suspend fun connect(device: BluetoothDevice): Boolean = withContext(Dispatchers.IO) {
        try {
            _connectionState.value = ConnectionState.Connecting
            
            if (ActivityCompat.checkSelfPermission(context, Manifest.permission.BLUETOOTH_CONNECT) 
                != PackageManager.PERMISSION_GRANTED) {
                _connectionState.value = ConnectionState.Error("Bluetooth connect permission not granted")
                return@withContext false
            }
            
            stopDiscovery()
            
            bluetoothSocket = device.createRfcommSocketToServiceRecord(SPP_UUID)
            bluetoothSocket?.connect()
            
            outputStream = bluetoothSocket?.outputStream
            inputStream = bluetoothSocket?.inputStream
            
            _connectionState.value = ConnectionState.Connected
            true
        } catch (e: Exception) {
            Log.e(TAG, "Connection failed", e)
            val errorMsg = if (e.message?.contains("socket might closed") == true || 
                               e.message?.contains("Connection refused") == true ||
                               e.message?.contains("read failed") == true) {
                "GoalStick not ready. Make sure it's in pairing mode."
            } else {
                e.message ?: "Connection failed"
            }
            _connectionState.value = ConnectionState.Error(errorMsg)
            disconnect()
            false
        }
    }
    
    suspend fun sendConfiguration(wifiSsid: String, wifiPassword: String, teamAbbr: String, celebrationDelaySeconds: Int = 0): Boolean 
        = withContext(Dispatchers.IO) {
        try {
            val json = JSONObject().apply {
                put("type", "config")
                put("wifi_ssid", wifiSsid)
                put("wifi_password", wifiPassword)
                put("team_abbr", teamAbbr)
                put("celebration_delay_seconds", celebrationDelaySeconds)
            }
            
            outputStream?.write(json.toString().toByteArray())
            outputStream?.flush()
            
            // Wait for acknowledgment
            val buffer = ByteArray(1024)
            val bytesRead = inputStream?.read(buffer) ?: -1
            
            if (bytesRead > 0) {
                val response = String(buffer, 0, bytesRead)
                val responseJson = JSONObject(response)
                responseJson.getString("status") == "ok"
            } else {
                false
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to send configuration", e)
            false
        }
    }
    
    suspend fun sendTestGoal(): Boolean = withContext(Dispatchers.IO) {
        try {
            val json = JSONObject().apply {
                put("type", "test_goal")
            }
            
            outputStream?.write(json.toString().toByteArray())
            outputStream?.flush()
            
            // Wait for acknowledgment
            val buffer = ByteArray(1024)
            val bytesRead = inputStream?.read(buffer) ?: -1
            
            if (bytesRead > 0) {
                val response = String(buffer, 0, bytesRead)
                val responseJson = JSONObject(response)
                responseJson.getString("status") == "ok"
            } else {
                false
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to send test goal", e)
            false
        }
    }
    
    suspend fun getConfig(): GoalStickConfig? = withContext(Dispatchers.IO) {
        try {
            val json = JSONObject().apply {
                put("type", "get_config")
            }
            
            outputStream?.write(json.toString().toByteArray())
            outputStream?.flush()
            
            // Wait for response
            val buffer = ByteArray(1024)
            val bytesRead = inputStream?.read(buffer) ?: -1
            
            if (bytesRead > 0) {
                val response = String(buffer, 0, bytesRead)
                val responseJson = JSONObject(response)
                if (responseJson.getString("status") == "ok") {
                    val configJson = responseJson.optJSONObject("config")
                    GoalStickConfig(
                        teamAbbr = configJson?.optString("team_abbr"),
                        celebrationDelaySeconds = configJson?.optInt("celebration_delay_seconds", 0) ?: 0,
                        ipAddress = configJson?.optString("ip_address")
                    )
                } else {
                    null
                }
            } else {
                null
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to get config", e)
            null
        }
    }
    
    fun disconnect() {
        try {
            inputStream?.close()
            outputStream?.close()
            bluetoothSocket?.close()
        } catch (e: Exception) {
            Log.e(TAG, "Error closing connection", e)
        }
        inputStream = null
        outputStream = null
        bluetoothSocket = null
        _connectionState.value = ConnectionState.Disconnected
    }
}
