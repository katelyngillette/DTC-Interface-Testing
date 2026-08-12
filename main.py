import asyncio
import sys
import serial
import serial.tools.list_ports
import modbus_tk
import modbus_tk.defines as cst
from modbus_tk import modbus_rtu
from bleak import BleakScanner, BleakClient

# Custom local protocol module imports
from modbus import run_modbus_test
from sdi12 import run_sdi12_test
from ble import run_bluetooth_diagnostics

def auto_detect_serial_ports(slave_id=1):
    """
    Maps Modbus to usbserial-AB0JRCBJ first (with dynamic backup scanning),
    and forces SDI-12 to map strictly to usbserial-AQ00BEJS.
    """
    ports = list(serial.tools.list_ports.comports())
    # Filter and normalize paths upfront for macOS/Linux compatibility
    normalized_ports = []
    for p in ports:
        port_path = p.device
        if "debug-console" in port_path or "Bluetooth-Incoming" in port_path:
            continue
        if sys.platform == "darwin" and "cu.usbserial" in port_path:
            port_path = port_path.replace("cu.usbserial", "tty.usbserial")
        normalized_ports.append(port_path)

    modbus_port = None
    sdi12_port = None

    print("\n[Auto-Discovery] Initializing static map and fallback scan...")

    # Step 1: Enforce the absolute mapping rule for SDI-12
    for port in normalized_ports:
        if "usbserial-AQ00BEJS" in port:
            sdi12_port = port
            print(f" [✓] SDI-12 Interface Explicitly Mapped to {sdi12_port}")
            break

    if not sdi12_port:
        print("[System WARNING] Expected SDI-12 hardware adapter (usbserial-AQ00BEJS) was not detected on the bus.")

    # Remove the assigned SDI-12 port so Modbus never accidentally steals it
    remaining_ports = [p for p in normalized_ports if p != sdi12_port]

    # Step 2: Try mapping Modbus to the preferred adapter string first
    preferred_modbus = [p for p in remaining_ports if "usbserial-AB0JRCBJ" in p]
    if preferred_modbus:
        target_port = preferred_modbus[0]
        try:
            with serial.Serial(port=target_port, baudrate=9600, bytesize=8, parity='N', stopbits=1, timeout=1.0) as ser:
                master = modbus_rtu.RtuMaster(ser)
                master.set_timeout(1.0)
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                master.execute(slave_id, cst.READ_INPUT_REGISTERS, 0, 1)
                print(f" [✓] Modbus Signature Found on preferred adapter: {target_port}!")
                modbus_port = target_port
        except (modbus_tk.modbus.ModbusError, serial.SerialException, Exception):
            print(f" [!] Preferred adapter {target_port} connected but failed to answer Modbus queries.")

    # Step 3: Fallback discovery if the preferred adapter isn't found or failed
    if not modbus_port:
        print(" -> Preferred Modbus port unavailable or failed. Scanning remaining adapters...")
        fallback_ports = [p for p in remaining_ports if "usbserial-AB0JRCBJ" not in p]
        for port in fallback_ports:
            print(f" -> Probing alternative port {port} for Modbus RTU signature...")
            try:
                with serial.Serial(port=port, baudrate=9600, bytesize=8, parity='N', stopbits=1, timeout=1.0) as ser:
                    master = modbus_rtu.RtuMaster(ser)
                    master.set_timeout(1.0)
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                    master.execute(slave_id, cst.READ_INPUT_REGISTERS, 0, 1)
                    print(f" [✓] Modbus Signature Found on fallback port {port}!")
                    modbus_port = port
                    break
            except (modbus_tk.modbus.ModbusError, serial.SerialException, Exception):
                continue

    # Final validation check
    if not modbus_port or not sdi12_port:
        print(f"\n[Auto-Discovery ERROR] Mapping failed. Status -> Modbus: {modbus_port}, SDI-12: {sdi12_port}")
        print("[System Hint] Verify device connections, power, and matching Slave IDs.")
        sys.exit(1)

    return modbus_port, sdi12_port

async def selective_ble_selection():
    print("\n[BLE Scan] Scanning for target hardware devices (5 seconds)...")
    devices = await BleakScanner.discover(timeout=5.0)
    target_devices = [d for d in devices if d.name and d.name.upper().startswith("BLK")]
    if not target_devices:
        print("[BLE Status] No hardware devices starting with 'BLK' were found.")
        return None
    if len(target_devices) == 1:
        selected_device = target_devices[0]
        print(f" [✓] BLE Auto-Selected (Single Match): {selected_device.name} ({selected_device.address})")
        return selected_device.address

    print(f"\n--- Discovered Multiple Matching BLE Devices ({len(target_devices)}) ---")
    for idx, d in enumerate(target_devices):
        # FIX 1: Display starting at 1 instead of 0
        print(f" [{idx + 1}] {d.name} ({d.address})")
    print(" -------------------------------------------------------------")
    
    loop = asyncio.get_running_loop()
    while True:
        # FIX 2: Update the interactive prompt helper string window
        user_input = await loop.run_in_executor(
            None, input, f"Select a device index (1-{len(target_devices)}) or press enter to skip: "
        )
        user_input = user_input.strip()
        if not user_input:
            print("[BLE SKIPPED] No device selected.")
            return None
        try:
            # FIX 3: Convert the 1-based user input down to a 0-based array index
            selection = int(user_input) - 1
            if 0 <= selection < len(target_devices):
                chosen = target_devices[selection]
                print(f" [✓] Selected: {chosen.name} ({chosen.address})")
                return chosen.address
        except ValueError:
            pass
        # FIX 4: Correct error response message limits
        print(f"[Error] Invalid selection. Choose a number from 1 to {len(target_devices)}.")

async def main():
    # Discover serial lines
    modbus_port, sdi12_port = auto_detect_serial_ports(slave_id=1)
    
    # --- FIX 1: Run and await the BLE search selection ---
    target_ble_address = await selective_ble_selection()

    print("\n" + "="*50)
    print(" --- Starting Protocol Tests --- ")
    print("="*50)

    # --- PROTOCOL 1: MODBUS ---
    print("\n>>> STEP 1: RUNNING MODBUS RS-485 TEST <<<")
    modbus_check = run_modbus_test(modbus_port, slave_id=1)
    await asyncio.sleep(1.0)

    # --- PROTOCOL 2: SDI-12 ---
    print("\n>>> STEP 2: RUNNING SDI-12 TEST <<<")
    sdi_check = run_sdi12_test(sdi12_port, sensor_address='0')
    await asyncio.sleep(1.0)

    # --- PROTOCOL 3: BLUETOOTH BLE ---
    print("\n>>> STEP 3: RUNNING BLUETOOTH TEST <<<")
    # --- FIX 2: Bind the runtime check to the dynamically scanned address ---
    if target_ble_address:
        ble_check = await run_bluetooth_diagnostics(target_ble_address)
    else:
        print("[BLE SKIPPED] No target device was selected or found during scan.")
        ble_check = False

    print("\n" + "="*50)
    if modbus_check and sdi_check and ble_check:
        print("[✓] All protocol tests completed successfully.")
    else:
        print("[X] Failure decected")
        if not modbus_check:
            print("[Modbus] One or more errors detected during the Modbus test.")
        if not sdi_check:
            print("[SDI-12] One or more errors detected during the SDI-12 test.")
        if not ble_check:
            print("[BLE] One or more errors detected during the Bluetooth test.")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(main())
