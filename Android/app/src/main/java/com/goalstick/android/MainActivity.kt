package com.goalstick.android

import android.Manifest
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.ProgressBar
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.goalstick.android.bluetooth.BluetoothManager
import com.goalstick.android.data.TeamData
import com.goalstick.android.ui.DeviceAdapter
import com.goalstick.android.ui.MainViewModel
import com.google.android.material.textfield.TextInputEditText
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {
    
    private lateinit var viewModel: MainViewModel
    private lateinit var deviceAdapter: DeviceAdapter
    
    // Discovery UI
    private lateinit var statusText: TextView
    private lateinit var scanButton: Button
    private lateinit var devicesRecyclerView: RecyclerView
    private lateinit var discoveryProgressBar: ProgressBar
    
    // Configuration UI
    private lateinit var configLayout: View
    private lateinit var wifiSsidInput: TextInputEditText
    private lateinit var wifiPasswordInput: TextInputEditText
    private lateinit var teamSpinner: Spinner
    private lateinit var sendConfigButton: Button
    private lateinit var testGoalButton: Button
    private lateinit var configProgressBar: ProgressBar
    
    private val bluetoothReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                BluetoothDevice.ACTION_FOUND -> {
                    val device: BluetoothDevice? = intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
                    device?.let { viewModel.bluetoothManager.addDiscoveredDevice(it) }
                }
                BluetoothAdapter.ACTION_DISCOVERY_FINISHED -> {
                    discoveryProgressBar.visibility = View.GONE
                    scanButton.isEnabled = true
                }
            }
        }
    }
    
    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val allGranted = permissions.all { it.value }
        if (allGranted) {
            startScan()
        } else {
            Toast.makeText(this, "Bluetooth permissions required", Toast.LENGTH_LONG).show()
        }
    }
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        
        viewModel = ViewModelProvider(this)[MainViewModel::class.java]
        
        setupViews()
        setupRecyclerView()
        setupTeamSpinner()
        observeViewModel()
        registerBluetoothReceiver()
    }
    
    private fun setupViews() {
        // Discovery views
        statusText = findViewById(R.id.statusText)
        scanButton = findViewById(R.id.scanButton)
        devicesRecyclerView = findViewById(R.id.devicesRecyclerView)
        discoveryProgressBar = findViewById(R.id.discoveryProgressBar)
        
        // Configuration views
        configLayout = findViewById(R.id.configLayout)
        wifiSsidInput = findViewById(R.id.wifiSsidInput)
        wifiPasswordInput = findViewById(R.id.wifiPasswordInput)
        teamSpinner = findViewById(R.id.teamSpinner)
        sendConfigButton = findViewById(R.id.sendConfigButton)
        testGoalButton = findViewById(R.id.testGoalButton)
        configProgressBar = findViewById(R.id.configProgressBar)
        
        scanButton.setOnClickListener { checkPermissionsAndScan() }
        sendConfigButton.setOnClickListener { sendConfiguration() }
        testGoalButton.setOnClickListener { sendTestGoal() }
    }
    
    private fun setupRecyclerView() {
        deviceAdapter = DeviceAdapter { device ->
            viewModel.connect(device)
        }
        devicesRecyclerView.layoutManager = LinearLayoutManager(this)
        devicesRecyclerView.adapter = deviceAdapter
    }
    
    private fun setupTeamSpinner() {
        val teamNames = TeamData.teams.map { "${it.first} - ${it.second}" }
        val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, teamNames)
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        teamSpinner.adapter = adapter
    }
    
    private fun observeViewModel() {
        lifecycleScope.launch {
            viewModel.bluetoothManager.connectionState.collectLatest { state ->
                when (state) {
                    is BluetoothManager.ConnectionState.Disconnected -> {
                        statusText.text = "Tap scan to find your GoalStick device"
                        configLayout.visibility = View.GONE
                    }
                    is BluetoothManager.ConnectionState.Scanning -> {
                        statusText.text = "Scanning for devices..."
                        discoveryProgressBar.visibility = View.VISIBLE
                    }
                    is BluetoothManager.ConnectionState.Connecting -> {
                        statusText.text = "Connecting..."
                        discoveryProgressBar.visibility = View.VISIBLE
                    }
                    is BluetoothManager.ConnectionState.Connected -> {
                        statusText.text = "Connected! Configure your GoalStick below."
                        discoveryProgressBar.visibility = View.GONE
                        devicesRecyclerView.visibility = View.GONE
                        configLayout.visibility = View.VISIBLE
                        sendConfigButton.isEnabled = true
                        testGoalButton.isEnabled = true
                    }
                    is BluetoothManager.ConnectionState.Error -> {
                        statusText.text = "Error: ${state.message}"
                        discoveryProgressBar.visibility = View.GONE
                    }
                }
            }
        }
        
        lifecycleScope.launch {
            viewModel.bluetoothManager.discoveredDevices.collectLatest { devices ->
                deviceAdapter.submitList(devices)
                devicesRecyclerView.visibility = if (devices.isNotEmpty()) View.VISIBLE else View.GONE
            }
        }
        
        lifecycleScope.launch {
            viewModel.configSent.collectLatest { sent ->
                if (sent) {
                    Toast.makeText(this@MainActivity, "Configuration sent successfully!", Toast.LENGTH_LONG).show()
                    configProgressBar.visibility = View.GONE
                }
            }
        }
        
        lifecycleScope.launch {
            viewModel.errorMessage.collectLatest { error ->
                error?.let {
                    Toast.makeText(this@MainActivity, it, Toast.LENGTH_LONG).show()
                    configProgressBar.visibility = View.GONE
                    viewModel.clearError()
                }
            }
        }
    }
    
    private fun checkPermissionsAndScan() {
        val permissions = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            arrayOf(
                Manifest.permission.BLUETOOTH_SCAN,
                Manifest.permission.BLUETOOTH_CONNECT,
                Manifest.permission.ACCESS_FINE_LOCATION
            )
        } else {
            arrayOf(
                Manifest.permission.BLUETOOTH,
                Manifest.permission.BLUETOOTH_ADMIN,
                Manifest.permission.ACCESS_FINE_LOCATION
            )
        }
        
        val needsPermission = permissions.any {
            ActivityCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        
        if (needsPermission) {
            permissionLauncher.launch(permissions)
        } else {
            startScan()
        }
    }
    
    private fun startScan() {
        if (!viewModel.bluetoothManager.isBluetoothSupported()) {
            Toast.makeText(this, "Bluetooth not supported", Toast.LENGTH_LONG).show()
            return
        }
        
        if (!viewModel.bluetoothManager.isBluetoothEnabled()) {
            Toast.makeText(this, "Please enable Bluetooth", Toast.LENGTH_LONG).show()
            return
        }
        
        scanButton.isEnabled = false
        viewModel.bluetoothManager.startDiscovery()
    }
    
    private fun sendConfiguration() {
        val ssid = wifiSsidInput.text?.toString() ?: ""
        val password = wifiPasswordInput.text?.toString() ?: ""
        val selectedPosition = teamSpinner.selectedItemPosition
        val teamAbbr = TeamData.teams[selectedPosition].first
        
        if (ssid.isBlank()) {
            wifiSsidInput.error = "WiFi SSID required"
            return
        }
        
        configProgressBar.visibility = View.VISIBLE
        sendConfigButton.isEnabled = false
        viewModel.sendConfiguration(ssid, password, teamAbbr)
    }
    
    private fun sendTestGoal() {
        Toast.makeText(this, "Sending test goal...", Toast.LENGTH_SHORT).show()
        viewModel.sendTestGoal()
    }
    
    private fun registerBluetoothReceiver() {
        val filter = IntentFilter().apply {
            addAction(BluetoothDevice.ACTION_FOUND)
            addAction(BluetoothAdapter.ACTION_DISCOVERY_FINISHED)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(bluetoothReceiver, filter, RECEIVER_EXPORTED)
        } else {
            registerReceiver(bluetoothReceiver, filter)
        }
    }
    
    override fun onDestroy() {
        super.onDestroy()
        unregisterReceiver(bluetoothReceiver)
        viewModel.bluetoothManager.stopDiscovery()
    }
}
