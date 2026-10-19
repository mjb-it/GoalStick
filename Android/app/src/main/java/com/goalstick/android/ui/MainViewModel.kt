package com.goalstick.android.ui

import android.app.Application
import android.bluetooth.BluetoothDevice
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.goalstick.android.bluetooth.BluetoothManager
import com.goalstick.android.data.GoalStickConfig
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class MainViewModel(application: Application) : AndroidViewModel(application) {

    val bluetoothManager = BluetoothManager(application)

    /** One-shot messages for the UI (toasts). A SharedFlow so repeats are delivered. */
    sealed class UiEvent {
        data class Info(val message: String) : UiEvent()
        data class Error(val message: String) : UiEvent()
    }

    private val _events = MutableSharedFlow<UiEvent>(extraBufferCapacity = 8)
    val events: SharedFlow<UiEvent> = _events.asSharedFlow()

    /** True while a request is in flight; the UI disables buttons. */
    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy.asStateFlow()

    private val _currentConfig = MutableStateFlow<GoalStickConfig?>(null)
    val currentConfig: StateFlow<GoalStickConfig?> = _currentConfig.asStateFlow()

    private var connectInFlight = false

    suspend fun connect(device: BluetoothDevice): Boolean {
        if (connectInFlight) return false
        connectInFlight = true
        try {
            return bluetoothManager.connect(device)
        } finally {
            connectInFlight = false
        }
    }

    fun isConnectInFlight(): Boolean = connectInFlight

    fun sendConfiguration(wifiSsid: String?, wifiPassword: String?, teamAbbr: String, celebrationDelaySeconds: Int) {
        if (_busy.value) return
        viewModelScope.launch {
            _busy.value = true
            try {
                val result = bluetoothManager.sendConfiguration(wifiSsid, wifiPassword, teamAbbr, celebrationDelaySeconds)
                if (result.ok) {
                    val wifi = result.json?.optString("wifi")
                    val note = when (wifi) {
                        "ok" -> " WiFi updated."
                        else -> ""
                    }
                    _events.emit(UiEvent.Info("Configuration saved.$note"))
                    fetchConfigInternal()
                } else {
                    _events.emit(UiEvent.Error(result.message ?: "Failed to send configuration"))
                }
            } finally {
                _busy.value = false
            }
        }
    }

    fun sendTestGoal() {
        if (_busy.value) return
        viewModelScope.launch {
            _busy.value = true
            try {
                val result = bluetoothManager.sendTestGoal()
                if (!result.ok) {
                    _events.emit(UiEvent.Error(result.message ?: "Failed to send test goal"))
                }
            } finally {
                _busy.value = false
            }
        }
    }

    fun fetchConfig() {
        if (_busy.value) return
        viewModelScope.launch {
            _busy.value = true
            try {
                fetchConfigInternal()
            } finally {
                _busy.value = false
            }
        }
    }

    private suspend fun fetchConfigInternal() {
        val config = bluetoothManager.getConfig()
        if (config != null) {
            _currentConfig.value = config
        }
    }

    fun disconnect() {
        bluetoothManager.disconnect()
        _currentConfig.value = null
    }

    override fun onCleared() {
        super.onCleared()
        bluetoothManager.disconnect()
    }
}
