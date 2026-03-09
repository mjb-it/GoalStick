package com.goalstick.android.ui

import android.app.Application
import android.bluetooth.BluetoothDevice
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.goalstick.android.bluetooth.BluetoothManager
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class MainViewModel(application: Application) : AndroidViewModel(application) {
    
    val bluetoothManager = BluetoothManager(application)
    
    private val _configSent = MutableStateFlow(false)
    val configSent: StateFlow<Boolean> = _configSent.asStateFlow()
    
    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()
    
    suspend fun connect(device: BluetoothDevice): Boolean {
        return bluetoothManager.connect(device)
    }
    
    fun sendConfiguration(wifiSsid: String, wifiPassword: String, teamAbbr: String, celebrationDelaySeconds: Int = 0) {
        viewModelScope.launch {
            val success = bluetoothManager.sendConfiguration(wifiSsid, wifiPassword, teamAbbr, celebrationDelaySeconds)
            if (success) {
                _configSent.value = true
            } else {
                _errorMessage.value = "Failed to send configuration"
            }
        }
    }
    
    fun clearError() {
        _errorMessage.value = null
    }
    
    fun sendTestGoal() {
        viewModelScope.launch {
            val success = bluetoothManager.sendTestGoal()
            if (success) {
                _errorMessage.value = null
            } else {
                _errorMessage.value = "Failed to send test goal"
            }
        }
    }
    
    private val _currentConfig = MutableStateFlow<BluetoothManager.GoalStickConfig?>(null)
    val currentConfig: StateFlow<BluetoothManager.GoalStickConfig?> = _currentConfig.asStateFlow()
    
    fun fetchConfig() {
        viewModelScope.launch {
            val config = bluetoothManager.getConfig()
            _currentConfig.value = config
        }
    }
    
    override fun onCleared() {
        super.onCleared()
        bluetoothManager.disconnect()
    }
}
