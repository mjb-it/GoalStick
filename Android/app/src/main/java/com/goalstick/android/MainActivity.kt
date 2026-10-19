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
import android.widget.SeekBar
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.goalstick.android.bluetooth.BluetoothManager
import com.goalstick.android.data.TeamData
import com.goalstick.android.ui.DeviceAdapter
import com.goalstick.android.ui.MainViewModel
import com.goalstick.android.wifi.WifiHelper
import com.google.android.material.textfield.TextInputEditText
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var viewModel: MainViewModel
    private lateinit var deviceAdapter: DeviceAdapter

    // Discovery UI
    private lateinit var statusText: TextView
    private lateinit var ipAddressText: TextView
    private lateinit var scanButton: Button
    private lateinit var reconnectButton: Button
    private lateinit var devicesRecyclerView: RecyclerView
    private lateinit var discoveryProgressBar: ProgressBar

    // Configuration UI
    private lateinit var configLayout: View
    private lateinit var wifiSsidInput: TextInputEditText
    private lateinit var wifiPasswordInput: TextInputEditText
    private lateinit var teamSpinner: Spinner
    private lateinit var delaySeekBar: SeekBar
    private lateinit var delayValueText: TextView
    private lateinit var sendConfigButton: Button
    private lateinit var testGoalButton: Button
    private lateinit var disconnectButton: Button
    private lateinit var configProgressBar: ProgressBar

    private lateinit var wifiHelper: WifiHelper

    /** Set once we have tried the remembered device on this launch. */
    private var autoConnectAttempted = false
    /** Lets a Disconnected state read as "lost connection" rather than the idle hint. */
    private var wasConnected = false
    private var receiverRegistered = false

    private val bluetoothReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                BluetoothDevice.ACTION_FOUND -> {
                    @Suppress("DEPRECATION")
                    val device: BluetoothDevice? = intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
                    device?.let { viewModel.bluetoothManager.addDiscoveredDevice(it) }
                }
                BluetoothAdapter.ACTION_DISCOVERY_FINISHED -> {
                    discoveryProgressBar.visibility = View.GONE
                    scanButton.isEnabled = true
                    val wasScanning = viewModel.bluetoothManager.connectionState.value is BluetoothManager.ConnectionState.Scanning
                    viewModel.bluetoothManager.onDiscoveryFinished()
                    if (wasScanning && viewModel.bluetoothManager.discoveredDevices.value.isEmpty()) {
                        statusText.text = getString(R.string.status_no_devices)
                    } else if (wasScanning) {
                        statusText.text = getString(R.string.status_pick_device)
                    }
                }
            }
        }
    }

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val required = requiredBluetoothPermissions()
        val granted = required.all { permissions[it] == true || hasPermission(it) }
        if (granted) {
            startScan()
        } else {
            Toast.makeText(this, R.string.toast_bt_permissions, Toast.LENGTH_LONG).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        viewModel = ViewModelProvider(this)[MainViewModel::class.java]
        wifiHelper = WifiHelper(this)

        setupViews()
        setupRecyclerView()
        setupTeamSpinner()
        observeViewModel()
        registerBluetoothReceiver()
    }

    override fun onResume() {
        super.onResume()
        updateReconnectButton()
        // Try the last GoalStick once per launch, when idle.
        if (!autoConnectAttempted &&
            viewModel.bluetoothManager.connectionState.value is BluetoothManager.ConnectionState.Disconnected &&
            !viewModel.isConnectInFlight()
        ) {
            autoConnectAttempted = true
            val remembered = viewModel.bluetoothManager.getRememberedDevice()
            if (remembered != null && viewModel.bluetoothManager.isBluetoothEnabled()) {
                connectTo(remembered, autoScanOnFailure = false)
            } else {
                statusText.text = getString(R.string.status_idle)
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        if (receiverRegistered) {
            unregisterReceiver(bluetoothReceiver)
            receiverRegistered = false
        }
        viewModel.bluetoothManager.stopDiscovery()
    }

    // ------------------------------------------------------------------
    // Setup
    // ------------------------------------------------------------------

    private fun setupViews() {
        statusText = findViewById(R.id.statusText)
        ipAddressText = findViewById(R.id.ipAddressText)
        scanButton = findViewById(R.id.scanButton)
        reconnectButton = findViewById(R.id.reconnectButton)
        devicesRecyclerView = findViewById(R.id.devicesRecyclerView)
        discoveryProgressBar = findViewById(R.id.discoveryProgressBar)

        configLayout = findViewById(R.id.configLayout)
        wifiSsidInput = findViewById(R.id.wifiSsidInput)
        wifiPasswordInput = findViewById(R.id.wifiPasswordInput)
        teamSpinner = findViewById(R.id.teamSpinner)
        delaySeekBar = findViewById(R.id.delaySeekBar)
        delayValueText = findViewById(R.id.delayValueText)
        sendConfigButton = findViewById(R.id.sendConfigButton)
        testGoalButton = findViewById(R.id.testGoalButton)
        disconnectButton = findViewById(R.id.disconnectButton)
        configProgressBar = findViewById(R.id.configProgressBar)

        scanButton.setOnClickListener { checkPermissionsAndScan() }
        reconnectButton.setOnClickListener {
            viewModel.bluetoothManager.getRememberedDevice()?.let { connectTo(it, autoScanOnFailure = false) }
        }
        sendConfigButton.setOnClickListener { sendConfiguration() }
        testGoalButton.setOnClickListener { viewModel.sendTestGoal() }
        disconnectButton.setOnClickListener { viewModel.disconnect() }

        delaySeekBar.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: SeekBar?, progress: Int, fromUser: Boolean) {
                delayValueText.text = getString(R.string.delay_value, progress)
            }
            override fun onStartTrackingTouch(seekBar: SeekBar?) {}
            override fun onStopTrackingTouch(seekBar: SeekBar?) {}
        })
    }

    private fun setupRecyclerView() {
        deviceAdapter = DeviceAdapter(
            nameOf = { viewModel.bluetoothManager.nameOf(it) },
            onDeviceClick = { device -> connectTo(device, autoScanOnFailure = false) }
        )
        devicesRecyclerView.layoutManager = LinearLayoutManager(this)
        devicesRecyclerView.adapter = deviceAdapter
    }

    private fun setupTeamSpinner() {
        val teamNames = TeamData.teams.map { "${it.first} - ${it.second}" }
        val adapter = ArrayAdapter(this, R.layout.spinner_item, teamNames)
        adapter.setDropDownViewResource(R.layout.spinner_dropdown_item)
        teamSpinner.adapter = adapter
    }

    private fun updateReconnectButton() {
        val hasRemembered = viewModel.bluetoothManager.getRememberedDevice() != null
        val connected = viewModel.bluetoothManager.isConnected()
        reconnectButton.visibility = if (hasRemembered && !connected) View.VISIBLE else View.GONE
    }

    // ------------------------------------------------------------------
    // Observers
    // ------------------------------------------------------------------

    private fun observeViewModel() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                launch {
                    viewModel.bluetoothManager.connectionState.collectLatest { state -> renderConnectionState(state) }
                }
                launch {
                    viewModel.bluetoothManager.discoveredDevices.collectLatest { devices ->
                        deviceAdapter.submitList(devices)
                        val connected = viewModel.bluetoothManager.isConnected()
                        devicesRecyclerView.visibility = if (devices.isNotEmpty() && !connected) View.VISIBLE else View.GONE
                    }
                }
                launch {
                    viewModel.events.collect { event ->
                        when (event) {
                            is MainViewModel.UiEvent.Info ->
                                Toast.makeText(this@MainActivity, event.message, Toast.LENGTH_LONG).show()
                            is MainViewModel.UiEvent.Error ->
                                Toast.makeText(this@MainActivity, event.message, Toast.LENGTH_LONG).show()
                        }
                    }
                }
                launch {
                    viewModel.busy.collectLatest { busy ->
                        val connected = viewModel.bluetoothManager.isConnected()
                        configProgressBar.visibility = if (busy) View.VISIBLE else View.GONE
                        sendConfigButton.isEnabled = connected && !busy
                        testGoalButton.isEnabled = connected && !busy
                    }
                }
                launch {
                    viewModel.currentConfig.collectLatest { config -> renderConfig(config) }
                }
            }
        }
    }

    private fun renderConnectionState(state: BluetoothManager.ConnectionState) {
        when (state) {
            is BluetoothManager.ConnectionState.Disconnected -> {
                statusText.text = getString(
                    if (wasConnected) R.string.status_disconnected else R.string.status_idle
                )
                wasConnected = false
                discoveryProgressBar.visibility = View.GONE
                configLayout.visibility = View.GONE
                ipAddressText.visibility = View.GONE
                scanButton.isEnabled = true
                devicesRecyclerView.visibility =
                    if (viewModel.bluetoothManager.discoveredDevices.value.isNotEmpty()) View.VISIBLE else View.GONE
            }
            is BluetoothManager.ConnectionState.Scanning -> {
                statusText.text = getString(R.string.status_scanning)
                discoveryProgressBar.visibility = View.VISIBLE
                configLayout.visibility = View.GONE
            }
            is BluetoothManager.ConnectionState.Connecting -> {
                statusText.text = getString(R.string.status_connecting)
                discoveryProgressBar.visibility = View.VISIBLE
                scanButton.isEnabled = false
                reconnectButton.isEnabled = false
            }
            is BluetoothManager.ConnectionState.Connected -> {
                wasConnected = true
                statusText.text = getString(R.string.status_connected)
                discoveryProgressBar.visibility = View.GONE
                devicesRecyclerView.visibility = View.GONE
                configLayout.visibility = View.VISIBLE
                scanButton.isEnabled = true
                reconnectButton.isEnabled = true

                if (wifiSsidInput.text.isNullOrEmpty()) {
                    wifiHelper.requestCurrentSsid { ssid ->
                        if (ssid != null && wifiSsidInput.text.isNullOrEmpty()) wifiSsidInput.setText(ssid)
                    }
                }
                viewModel.fetchConfig()
            }
            is BluetoothManager.ConnectionState.Error -> {
                wasConnected = false
                statusText.text = state.message
                discoveryProgressBar.visibility = View.GONE
                configLayout.visibility = View.GONE
                ipAddressText.visibility = View.GONE
                scanButton.isEnabled = true
                reconnectButton.isEnabled = true
            }
        }
        updateReconnectButton()
        val connected = state is BluetoothManager.ConnectionState.Connected
        val busy = viewModel.busy.value
        sendConfigButton.isEnabled = connected && !busy
        testGoalButton.isEnabled = connected && !busy
    }

    private fun renderConfig(config: com.goalstick.android.data.GoalStickConfig?) {
        if (config == null) return
        config.teamAbbr?.let { teamAbbr ->
            val teamIndex = TeamData.teams.indexOfFirst { it.first == teamAbbr }
            if (teamIndex >= 0) teamSpinner.setSelection(teamIndex)
        }
        delaySeekBar.progress = config.celebrationDelaySeconds.coerceIn(0, delaySeekBar.max)
        delayValueText.text = getString(R.string.delay_value, delaySeekBar.progress)

        if (!config.ipAddress.isNullOrBlank()) {
            ipAddressText.text = getString(R.string.ip_address, config.ipAddress)
            ipAddressText.visibility = View.VISIBLE
        } else {
            ipAddressText.visibility = View.GONE
        }
    }

    // ------------------------------------------------------------------
    // Actions
    // ------------------------------------------------------------------

    private fun connectTo(device: BluetoothDevice, autoScanOnFailure: Boolean) {
        lifecycleScope.launch {
            val connected = viewModel.connect(device)
            if (!connected && autoScanOnFailure) {
                checkPermissionsAndScan()
            }
        }
    }

    private fun hasPermission(permission: String): Boolean =
        ActivityCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED

    private fun requiredBluetoothPermissions(): Array<String> =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        } else {
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
        }

    private fun checkPermissionsAndScan() {
        // Location is required for the SSID pre-fill and, before Android 12,
        // for Bluetooth discovery itself. Ask for everything in one dialog.
        val toRequest = (requiredBluetoothPermissions() + Manifest.permission.ACCESS_FINE_LOCATION)
            .distinct()
            .filterNot { hasPermission(it) }

        if (toRequest.isEmpty()) {
            startScan()
        } else {
            permissionLauncher.launch(toRequest.toTypedArray())
        }
    }

    private fun startScan() {
        val bt = viewModel.bluetoothManager
        if (!bt.isBluetoothSupported()) {
            Toast.makeText(this, R.string.toast_bt_unsupported, Toast.LENGTH_LONG).show()
            return
        }
        if (!bt.isBluetoothEnabled()) {
            Toast.makeText(this, R.string.toast_bt_disabled, Toast.LENGTH_LONG).show()
            return
        }

        scanButton.isEnabled = false
        if (!bt.startDiscovery()) {
            scanButton.isEnabled = true
            Toast.makeText(this, R.string.toast_scan_failed, Toast.LENGTH_LONG).show()
        }
    }

    private fun sendConfiguration() {
        val ssid = wifiSsidInput.text?.toString()?.trim().orEmpty()
        val password = wifiPasswordInput.text?.toString().orEmpty()
        val selectedPosition = teamSpinner.selectedItemPosition
        if (selectedPosition !in TeamData.teams.indices) return
        val teamAbbr = TeamData.teams[selectedPosition].first
        val delaySeconds = delaySeekBar.progress

        wifiSsidInput.error = null
        wifiPasswordInput.error = null

        val sendWifi = password.isNotEmpty()
        if (sendWifi) {
            if (ssid.isBlank()) {
                wifiSsidInput.error = getString(R.string.error_ssid_required)
                return
            }
            if (password.length !in 8..63 && !password.matches(Regex("^[0-9a-fA-F]{64}$"))) {
                wifiPasswordInput.error = getString(R.string.error_password_length)
                return
            }
        }

        viewModel.sendConfiguration(
            wifiSsid = if (sendWifi) ssid else null,
            wifiPassword = if (sendWifi) password else null,
            teamAbbr = teamAbbr,
            celebrationDelaySeconds = delaySeconds
        )
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
        receiverRegistered = true
    }
}
