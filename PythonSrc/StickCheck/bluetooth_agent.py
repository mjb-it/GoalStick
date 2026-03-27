"""
Bluetooth pairing agent that automatically accepts pairing requests without PIN.
This enables headless operation where no user interaction is needed on the Pi.
"""

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import logging
import threading

log = logging.getLogger(__name__)

AGENT_INTERFACE = "org.bluez.Agent1"
AGENT_PATH = "/com/goalstick/agent"


class AutoPairAgent(dbus.service.Object):
    """
    Bluetooth agent that automatically accepts all pairing requests.
    Uses NoInputNoOutput capability for PIN-less pairing.
    """
    
    def __init__(self, bus, path):
        super().__init__(bus, path)
        self.bus = bus
    
    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Release(self):
        log.info("Agent released")
    
    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        log.info(f"Authorizing service {uuid} for device {device}")
        return  # Auto-authorize all services
    
    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        log.info(f"RequestPinCode for {device}")
        return "0000"  # Default PIN if somehow requested
    
    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        log.info(f"RequestPasskey for {device}")
        return dbus.UInt32(0)  # Return 0 passkey
    
    @dbus.service.method(AGENT_INTERFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        log.info(f"DisplayPasskey: {passkey} for {device}")
    
    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        log.info(f"DisplayPinCode: {pincode} for {device}")
    
    @dbus.service.method(AGENT_INTERFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        log.info(f"Auto-confirming passkey {passkey} for {device}")
        return  # Auto-confirm by returning without error
    
    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        log.info(f"Auto-authorizing device {device}")
        return  # Auto-authorize
    
    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Cancel(self):
        log.info("Pairing cancelled")


class BluetoothAgentManager:
    """Manages the Bluetooth agent lifecycle."""
    
    def __init__(self):
        self._agent = None
        self._mainloop = None
        self._thread = None
        self._running = False
    
    def start(self):
        """Start the Bluetooth agent in a background thread."""
        if self._running:
            return

        self._running = True
        self._registered = threading.Event()
        self._thread = threading.Thread(target=self._run_agent, daemon=True)
        self._thread.start()
        # Wait up to 2s to confirm the agent actually registered
        if self._registered.wait(timeout=2.0):
            log.info("Bluetooth agent started")
        else:
            log.error("Bluetooth agent failed to start (registration timed out or errored)")
    
    def stop(self):
        """Stop the Bluetooth agent."""
        self._running = False
        if self._agent:
            try:
                # Unregister from BlueZ AgentManager
                bus = dbus.SystemBus()
                manager = dbus.Interface(
                    bus.get_object("org.bluez", "/org/bluez"),
                    "org.bluez.AgentManager1"
                )
                manager.UnregisterAgent(AGENT_PATH)
            except Exception as e:
                log.debug(f"Agent unregister from BlueZ: {e}")
            try:
                # Remove D-Bus object path so it can be re-registered next time
                self._agent.remove_from_connection()
            except Exception as e:
                log.debug(f"Agent remove_from_connection: {e}")
            self._agent = None
        if self._mainloop:
            self._mainloop.quit()
        log.info("Bluetooth agent stopped")
    
    def _run_agent(self):
        """Run the agent main loop."""
        try:
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            bus = dbus.SystemBus()
            
            # Create and register agent
            self._agent = AutoPairAgent(bus, AGENT_PATH)
            
            # Get AgentManager
            manager = dbus.Interface(
                bus.get_object("org.bluez", "/org/bluez"),
                "org.bluez.AgentManager1"
            )
            
            # Register agent with NoInputNoOutput capability
            manager.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
            manager.RequestDefaultAgent(AGENT_PATH)

            log.info("Bluetooth agent registered with NoInputNoOutput capability")
            self._registered.set()  # Signal that registration succeeded

            # Run main loop
            self._mainloop = GLib.MainLoop()
            self._mainloop.run()
            
        except Exception as e:
            log.error(f"Bluetooth agent error: {e}")
        finally:
            self._running = False


# Global agent manager instance
_agent_manager = None


def start_agent():
    """Start the global Bluetooth agent."""
    global _agent_manager
    if _agent_manager is None:
        _agent_manager = BluetoothAgentManager()
    _agent_manager.start()


def stop_agent():
    """Stop the global Bluetooth agent."""
    global _agent_manager
    if _agent_manager:
        _agent_manager.stop()
        _agent_manager = None
