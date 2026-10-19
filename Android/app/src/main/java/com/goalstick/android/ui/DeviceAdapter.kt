package com.goalstick.android.ui

import android.bluetooth.BluetoothDevice
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.goalstick.android.R

class DeviceAdapter(
    private val nameOf: (BluetoothDevice) -> String?,
    private val onDeviceClick: (BluetoothDevice) -> Unit
) : ListAdapter<BluetoothDevice, DeviceAdapter.DeviceViewHolder>(DeviceDiffCallback(nameOf)) {

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): DeviceViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_device, parent, false)
        return DeviceViewHolder(view)
    }

    override fun onBindViewHolder(holder: DeviceViewHolder, position: Int) {
        holder.bind(getItem(position))
    }

    inner class DeviceViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val deviceName: TextView = itemView.findViewById(R.id.deviceName)
        private val deviceAddress: TextView = itemView.findViewById(R.id.deviceAddress)
        private val connectButton: Button = itemView.findViewById(R.id.connectButton)

        fun bind(device: BluetoothDevice) {
            deviceName.text = nameOf(device) ?: itemView.context.getString(R.string.unknown_device)
            deviceAddress.text = device.address
            connectButton.setOnClickListener { onDeviceClick(device) }
            itemView.setOnClickListener { onDeviceClick(device) }
        }
    }

    class DeviceDiffCallback(
        private val nameOf: (BluetoothDevice) -> String?
    ) : DiffUtil.ItemCallback<BluetoothDevice>() {
        override fun areItemsTheSame(oldItem: BluetoothDevice, newItem: BluetoothDevice): Boolean =
            oldItem.address == newItem.address

        // A device can be reported first without a name and again with one.
        override fun areContentsTheSame(oldItem: BluetoothDevice, newItem: BluetoothDevice): Boolean =
            oldItem.address == newItem.address && nameOf(oldItem) == nameOf(newItem)
    }
}
