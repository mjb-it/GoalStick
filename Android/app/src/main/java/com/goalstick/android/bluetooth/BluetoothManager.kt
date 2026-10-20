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
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONException
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.util.UUID

/**
 * RFCOMM client for the GoalStick Pi.
 *
 * Protocol: one JSON object per message, newline terminated, in both
 * directions. Older Pi firmware replied without a newline, so the reader also
 * accepts a bare JSON object once it parses. Requests are serialized with a
 * mutex so a config fetch and a button tap can never interleave on the wire.
 */
class BluetoothManager(private val context: Context) {

    companion object {
        private const val TAG = "BluetoothManager"
        val SPP_UUID: UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")

        /** Channel the Pi listens on; used when SDP lookup fails. */
        private const val FALLBACK_RFCOMM_CHANNEL = 1

        private const val REQUEST_TIMEOUT_MS = 15_000L
        private const val MAX_RESPONSE_BYTES = 16 * 1024

        private const val PREFS = "goalstick"
        private const val PREF_LAST_DEVICE = "last_device_address"
    }

    /** Result of a request/response exchange. */
    data class CommandResult(val ok: Boolean, val message: String? = null, val json: JSONObject? = null)

    sealed class ConnectionState {
        object Disconnected : ConnectionState()
        object Scanning : ConnectionState()
        object Connecting : ConnectionState()
        object Connected : ConnectionState()
        data class Error(val message: String) : ConnectionState()
    }

    private val bluetoothManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
    private val bluetoothAdapter: BluetoothAdapter? = bluetoothManager.adapter
    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    private var bluetoothSocket: BluetoothSocket? = null
    private var outputStream: OutputStream? = null
    private var inputStream: InputStream? = null
    private val ioMutex = Mutex()
    private val pending = ByteArrayOutputStream()

    private val _connectionState = MutableStateFlow<ConnectionState>(ConnectionState.Disconnected)
    val connectionState: StateFlow<ConnectionState> = _connectionState.asStateFlow()

    private val _discoveredDevices = MutableStateFlow<List<BluetoothDevice>>(emptyList())
    val discoveredDevices: StateFlow<List<BluetoothDevice>> = _discoveredDevices.asStateFlow()

    // ------------------------------------------------------------------
    // Adapter state and permissions
    // ------------------------------------------------------------------

    fun isBluetoothSupported(): Boolean = bluetoothAdapter != null

    fun isBluetoothEnabled(): Boolean = bluetoothAdapter?.isEnabled == true

    fun isConnected(): Boolean = _connectionState.value is ConnectionState.Connected

    private fun hasPermission(permission: String): Boolean =
        ActivityCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

    private fun hasConnectPermission(): Boolean =
        android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.S ||
            hasPermission(Manifest.permission.BLUETOOTH_CONNECT)

    private fun hasScanPermission(): Boolean =
        android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.S ||
            hasPermission(Manifest.permission.BLUETOOTH_SCAN)

    /** Device name, or null when unknown or not permitted. */
    fun nameOf(device: BluetoothDevice): String? =
        if (hasConnectPermission()) {
            try { device.name } catch (e: SecurityException) { null }
        } else null

    fun looksLikeGoalStick(device: BluetoothDevice): Boolean {
        val name = nameOf(device) ?: return false
        return name.contains("goalstick", ignoreCase = true) || name.contains("goalpi", ignoreCase = true)
    }

    // ------------------------------------------------------------------
    // Remembered device
    // ------------------------------------------------------------------

    /**
     * The GoalStick we connected to last time. Insecure RFCOMM does not bond,
     * so the Pi never shows up in the paired list; remembering the address
     * lets us reconnect without a scan.
     */
    fun getRememberedDevice(): BluetoothDevice? {
        val address = prefs.getString(PREF_LAST_DEVICE, null) ?: return null
        return try {
            bluetoothAdapter?.getRemoteDevice(address)
        } catch (e: IllegalArgumentException) {
            prefs.edit().remove(PREF_LAST_DEVICE).apply()
            null
        }
    }

    fun forgetRememberedDevice() {
        prefs.edit().remove(PREF_LAST_DEVICE).apply()
    }

    fun getPairedDevices(): List<BluetoothDevice> {
        if (!hasConnectPermission()) return emptyList()
        return try {
            bluetoothAdapter?.bondedDevices?.toList() ?: emptyList()
        } catch (e: SecurityException) {
            emptyList()
        }
    }

    // ------------------------------------------------------------------
    // Discovery
    // ------------------------------------------------------------------

    /** Returns false if discovery could not be started. */
    fun startDiscovery(): Boolean {
        if (!hasScanPermission()) {
            _connectionState.value = ConnectionState.Error("Bluetooth scan permission not granted")
            return false
        }
        val adapter = bluetoothAdapter ?: return false

        _discoveredDevices.value = getPairedDevices().filter { looksLikeGoalStick(it) }
        return try {
            if (adapter.isDiscovering) adapter.cancelDiscovery()
            val started = adapter.startDiscovery()
            if (started) {
                _connectionState.value = ConnectionState.Scanning
            } else {
                _connectionState.value = ConnectionState.Error("Could not start Bluetooth scan")
            }
            started
        } catch (e: SecurityException) {
            _connectionState.value = ConnectionState.Error("Bluetooth scan permission not granted")
            false
        }
    }

    fun stopDiscovery() {
        if (!hasScanPermission()) return
        try {
            bluetoothAdapter?.cancelDiscovery()
        } catch (e: SecurityException) {
            // ignore
        }
    }

    /** Called by the activity when the system reports discovery has ended. */
    fun onDiscoveryFinished() {
        if (_connectionState.value is ConnectionState.Scanning) {
            _connectionState.value = ConnectionState.Disconnected
        }
    }

    fun addDiscoveredDevice(device: BluetoothDevice) {
        // Unnamed devices are never the GoalStick and only clutter the list.
        if (nameOf(device).isNullOrBlank()) return
        val current = _discoveredDevices.value
        val updated = if (current.any { it.address == device.address }) {
            current.map { if (it.address == device.address) device else it }
        } else {
            current + device
        }
        // GoalStick-looking devices first, then by name.
        _discoveredDevices.value = updated.sortedWith(
            compareByDescending<BluetoothDevice> { looksLikeGoalStick(it) }
                .thenBy { nameOf(it) ?: "" }
        )
    }

    // ------------------------------------------------------------------
    // Connection
    // ------------------------------------------------------------------

    suspend fun connect(device: BluetoothDevice): Boolean = withContext(Dispatchers.IO) {
        if (!hasConnectPermission()) {
            _connectionState.value = ConnectionState.Error("Bluetooth connect permission not granted")
            return@withContext false
        }
        if (_connectionState.value is ConnectionState.Connecting) {
            return@withContext false
        }

        _connectionState.value = ConnectionState.Connecting
        stopDiscovery()
        closeSocket()

        val socket = openSocket(device)
        if (socket == null) {
            // The background server is always listening; the button is only
            // for WiFi setup. Do not send people into pairing mode (or Android
            // settings) for a plain connection failure.
            _connectionState.value = ConnectionState.Error(
                "Couldn't reach GoalStick. Make sure it is powered on and nearby, then tap Reconnect or Scan."
            )
            return@withContext false
        }

        bluetoothSocket = socket
        outputStream = socket.outputStream
        inputStream = socket.inputStream
        pending.reset()
        prefs.edit().putString(PREF_LAST_DEVICE, device.address).apply()
        _connectionState.value = ConnectionState.Connected
        true
    }

    /**
     * Try the SDP-based socket first; if the Pi's SDP record is missing (sdptool
     * failed) fall back to the well-known channel.
     */
    private fun openSocket(device: BluetoothDevice): BluetoothSocket? {
        try {
            val socket = device.createInsecureRfcommSocketToServiceRecord(SPP_UUID)
            socket.connect()
            return socket
        } catch (e: Exception) {
            Log.w(TAG, "SDP connect failed: ${e.message}")
        }

        try {
            val method = device.javaClass.getMethod("createInsecureRfcommSocket", Int::class.javaPrimitiveType)
            val socket = method.invoke(device, FALLBACK_RFCOMM_CHANNEL) as BluetoothSocket
            socket.connect()
            Log.i(TAG, "Connected via fallback channel $FALLBACK_RFCOMM_CHANNEL")
            return socket
        } catch (e: Exception) {
            Log.e(TAG, "Fallback connect failed: ${e.message}")
        }
        return null
    }

    private fun closeSocket() {
        try { inputStream?.close() } catch (e: IOException) { /* ignore */ }
        try { outputStream?.close() } catch (e: IOException) { /* ignore */ }
        try { bluetoothSocket?.close() } catch (e: IOException) { /* ignore */ }
        inputStream = null
        outputStream = null
        bluetoothSocket = null
        pending.reset()
    }

    fun disconnect() {
        closeSocket()
        _connectionState.value = ConnectionState.Disconnected
    }

    private fun connectionLost(reason: String) {
        closeSocket()
        _connectionState.value = ConnectionState.Error(reason)
    }

    // ------------------------------------------------------------------
    // Request / response
    // ------------------------------------------------------------------

    private suspend fun request(json: JSONObject): CommandResult = withContext(Dispatchers.IO) {
        ioMutex.withLock {
            val out = outputStream
            val input = inputStream
            if (out == null || input == null) {
                return@withLock CommandResult(false, "Not connected")
            }

            try {
                out.write((json.toString() + "\n").toByteArray(Charsets.UTF_8))
                out.flush()
            } catch (e: IOException) {
                connectionLost("Connection lost")
                return@withLock CommandResult(false, "Connection lost")
            }

            val response = withTimeoutOrNull(REQUEST_TIMEOUT_MS) { readResponse(input) }
            when {
                response == null -> {
                    // The blocking read only returns when the socket closes.
                    connectionLost("GoalStick did not respond")
                    CommandResult(false, "GoalStick did not respond")
                }
                response.json == null -> {
                    connectionLost(response.message ?: "Connection lost")
                    CommandResult(false, response.message ?: "Connection lost")
                }
                else -> {
                    val status = response.json.optString("status")
                    val message = response.json.optString("message").takeIf { it.isNotBlank() }
                    CommandResult(status == "ok", message, response.json)
                }
            }
        }
    }

    /**
     * Read until a complete JSON object is available. Newline framing is
     * preferred; a bare object that parses is accepted for old firmware.
     */
    private fun readResponse(input: InputStream): CommandResult {
        val buffer = ByteArray(1024)
        while (true) {
            extractMessage()?.let { return it }

            val n = try {
                input.read(buffer)
            } catch (e: IOException) {
                return CommandResult(false, "Connection lost")
            }
            if (n < 0) return CommandResult(false, "GoalStick closed the connection")
            pending.write(buffer, 0, n)
            if (pending.size() > MAX_RESPONSE_BYTES) {
                return CommandResult(false, "Response too large")
            }
        }
    }

    private fun extractMessage(): CommandResult? {
        if (pending.size() == 0) return null
        val bytes = pending.toByteArray()
        val text = String(bytes, Charsets.UTF_8)

        val newline = text.indexOf('\n')
        if (newline >= 0) {
            val line = text.substring(0, newline).trim()
            val rest = text.substring(newline + 1)
            pending.reset()
            pending.write(rest.toByteArray(Charsets.UTF_8))
            if (line.isEmpty()) return extractMessage()
            return try {
                CommandResult(true, json = JSONObject(line))
            } catch (e: JSONException) {
                Log.w(TAG, "Ignoring non-JSON line from GoalStick")
                extractMessage()
            }
        }

        // No newline yet: legacy firmware sends a bare object.
        val trimmed = text.trim()
        if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
            return try {
                val obj = JSONObject(trimmed)
                pending.reset()
                CommandResult(true, json = obj)
            } catch (e: JSONException) {
                null // incomplete, keep reading
            }
        }
        return null
    }

    // ------------------------------------------------------------------
    // Commands
    // ------------------------------------------------------------------

    suspend fun ping(): CommandResult = request(JSONObject().put("type", "ping"))

    /**
     * Send team and delay, and WiFi credentials only when both are supplied.
     * WiFi changes are accepted by the Pi only in pairing mode.
     */
    suspend fun sendConfiguration(
        wifiSsid: String?,
        wifiPassword: String?,
        teamAbbr: String,
        celebrationDelaySeconds: Int = 0
    ): CommandResult {
        val json = JSONObject().apply {
            put("type", "config")
            put("team_abbr", teamAbbr)
            put("celebration_delay_seconds", celebrationDelaySeconds)
            if (!wifiSsid.isNullOrBlank() && !wifiPassword.isNullOrEmpty()) {
                put("wifi_ssid", wifiSsid)
                put("wifi_password", wifiPassword)
            }
        }
        return request(json)
    }

    suspend fun sendTestGoal(): CommandResult = request(JSONObject().put("type", "test_goal"))

    suspend fun getConfig(): GoalStickConfig? {
        val result = request(JSONObject().put("type", "get_config"))
        if (!result.ok) {
            Log.w(TAG, "get_config failed: ${result.message}")
            return null
        }
        val configJson = result.json?.optJSONObject("config") ?: return null
        return GoalStickConfig(
            teamAbbr = configJson.optString("team_abbr").takeIf { it.isNotBlank() },
            celebrationDelaySeconds = configJson.optInt("celebration_delay_seconds", 0),
            ipAddress = configJson.optString("ip_address").takeIf { it.isNotBlank() && it != "null" }
        )
    }
}
