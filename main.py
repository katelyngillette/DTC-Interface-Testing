import asyncio
import sys
import serial
import serial.tools.list_ports
import subprocess
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
    Cross-platform auto-discovery supporting Windows, macOS, and Linux.
    Matches devices by hardware serial IDs instead of platform-specific paths.
    """
    ports = list(serial.tools.list_ports.comports())
    normalized_ports = []
    
    for p in ports:
        port_path = p.device
        
        # Guard against virtual/debug ports
        if any(x in port_path for x in ["debug-console", "Bluetooth-Incoming", "bthdb"]):
            continue
            
        # macOS specific normalization if using legacy callout devices
        if sys.platform == "darwin" and "cu.usbserial" in port_path:
            port_path = port_path.replace("cu.usbserial", "tty.usbserial")
        
        # Consolidate all identifiers into a searchable metadata string
        # Windows uses hwid; macOS uses serial_number/description
        metadata = f"{p.description or ''} {p.serial_number or ''} {p.hwid or ''}"
        normalized_ports.append((port_path, metadata))

    modbus_port = None
    sdi12_port = None

    print(f"\n[Auto-Discovery] Initializing static map on platform: {sys.platform}...")

    # Step 1: Strict SDI-12 chip matching (Universal Serial Identifier)
    for path, info in normalized_ports:
        if "AQ00BEJS" in info:
            sdi12_port = path
            print(f" [✓] SDI-12 Interface Explicitly Mapped to {sdi12_port}")
            break

    if not sdi12_port:
        print("[System WARNING] Expected SDI-12 hardware adapter (AQ00BEJS) was not detected.")

    # Prevent Modbus scanning from touching the SDI-12 hardware
    remaining_ports = [(path, info) for path, info in normalized_ports if path != sdi12_port]

    # Step 2: Preferred Modbus chip matching
    preferred_modbus = [path for path, info in remaining_ports if "AB0JRCBJ" in info]
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
        except Exception:
            print(f" [!] Preferred adapter {target_port} connected but failed to answer Modbus queries.")

    # Step 3: Fallback sequential discovery scan
    if not modbus_port:
        print(" -> Preferred Modbus port unavailable. Scanning remaining physical adapters...")
        fallback_ports = [path for path, info in remaining_ports if "AB0JRCBJ" not in info]
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
            except Exception:
                continue

    
    # Exit or manual selection check
    if not modbus_port or not sdi12_port:
        print(f"\n[Auto-Discovery ERROR] Mapping failed. Status -> Modbus: {modbus_port}, SDI-12: {sdi12_port}")
        print("\n[Manual Selection] Please choose the correct ports from the list below:")
        
        all_paths = [path for path, info in normalized_ports]
        for idx, path in enumerate(all_paths):
            print(f"  [{idx}] {path}")
            
        # Manually pick Modbus if missing
        if not modbus_port:
            while True:
                try:
                    choice = input("Enter the number for the Modbus port: ").strip()
                    modbus_port = all_paths[int(choice)]
                    break
                except (ValueError, IndexError):
                    print("Invalid choice. Try again.")
                    
        # Manually pick SDI-12 if missing
        if not sdi12_port:
            while True:
                try:
                    choice = input("Enter the number for the SDI-12 port: ").strip()
                    sdi12_port = all_paths[int(choice)]
                    break
                except (ValueError, IndexError):
                    print("Invalid choice. Try again.")

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
        print(f"[Error] Invalid selection. Choose a number from 1 to {len(target_devices)}.")

async def main():
    import asyncio
import glob
import os
import subprocess

async def main():
    # --- PRE-TEST BOARD PROGRAMMING OPTION ---
    user_choice = input("To program the board the files must be located in the same folder as this program. \nPlease ensure you have the most updated firmware.\nWould you like to program the board first? (y/n): ").strip().lower()
    
    if user_choice in ['y', 'yes']:
        print("\n[Flash] Initializing board programming sequence...")
        
        # 1. Dynamically locate the signed hex file in the script's current directory
        script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
        search_pattern = os.path.join(script_dir, "*-zephyr.signed.hex")
        signed_files = glob.glob(search_pattern)
        
        if not signed_files:
            print("[Flash Error] Could not find a matching '*-zephyr.signed.hex' file in the directory.")
            print("[Flash Error] Skipping programming phase.\n")
        import asyncio
import glob
import os
import subprocess

async def main():
    # --- PRE-TEST BOARD PROGRAMMING OPTION ---
    user_choice = input("Would you like to program the board first? (y/n): ").strip().lower()
    
    if user_choice in ['y', 'yes']:
        print("\n[Flash] Searching for binary files...")
        
        # 1. Dynamically locate the signed hex file in the script's current directory
        script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
        search_pattern = os.path.join(script_dir, "*-zephyr.signed.hex")
        signed_files = glob.glob(search_pattern)
        
        if not signed_files:
            print("[Flash Error] Could not find a matching '*-zephyr.signed.hex' file in the directory.")
            print("[Flash Error] Skipping programming phase.\n")
        else:
            # Pick the first matching signed file found
            signed_hex = signed_files[0]
            filename = os.path.basename(signed_hex)
            
            # --- SECOND CONFIRMATION STEP ---
            print(f"\nFound file: {filename}")
            confirm_flash = input(f"Is '{filename}' the file you would like to flash? (y/n): ").strip().lower()
            
            if confirm_flash not in ['y', 'yes']:
                print("[Flash] Cancelled by user. Skipping programming phase.\n")
            else:
                try:
                    # 2. Run Command 1: Base zephyr erase & flash
                    print("\n[Flash] Executing chiperase & flashing base zephyr.hex...")
                    await asyncio.to_thread(
                        subprocess.run, 
                        ["nrfjprog", "--program", "zephyr.hex", "--chiperase", "--verify"], 
                        check=True
                    )
                    
                    # 3. Run Command 2: Version-controlled signed flash
                    print(f"[Flash] Executing sectorerase & flashing {filename}...")
                    await asyncio.to_thread(
                        subprocess.run, 
                        ["nrfjprog", "--program", signed_hex, "--sectorerase", "--verify"], 
                        check=True
                    )
                    await asyncio.sleep(2.0)

                    print("[Flash] Resetting the board...")
                    await asyncio.to_thread(
                        subprocess.run, 
                        ["nrfjprog", "--reset"], 
                        check=True
                    )

                    print("[Flash] Board programmed successfully!\n")
                    await asyncio.sleep(5.0)
                    
                except subprocess.CalledProcessError as e:
                    print(f"\n[Flash Error] nrfjprog failed with exit code {e.returncode}.")
                    print("[Flash Error] Aborting protocol tests for safety.\n")
                    return  # Halts the program if flashing fails
    else:
        print("\n[Flash] Skipping programming phase.")

    # Discover serial lines
    modbus_port, sdi12_port = auto_detect_serial_ports(slave_id=1)
    
    # Run and await the BLE search selection ---
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
    if target_ble_address:
        ble_check = await run_bluetooth_diagnostics(target_ble_address)
    else:
        print("[BLE SKIPPED] No target device was selected or found during scan.")
        ble_check = False

    # Final Summary
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
