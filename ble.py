import asyncio
import struct
import random
import cbor2
import re
from bleak import BleakScanner, BleakClient

# MCUmgr Simple Management Protocol characteristic over BLE
SMP_CHAR_UUID = "da2e7828-fbce-4e01-ae9e-261174997c48"
DEVICE_ADDRESS = "F4495D63-4361-51FF-2367-6A92ADFB3142"

class MCUmgrShellClient:
    def __init__(self, client):
        self.client = client
        self._raw_buffer = bytearray()
        self._expected_length = 0
        self.received_text_chunks = []
        self.response_completed_event = asyncio.Event()

    def notification_handler(self, sender, data):
        """Assembles fragmented binary MCUmgr responses streaming from Zephyr."""
        try:
            if not self._raw_buffer:
                if len(data) < 8:
                    return
                op, flags, length, group, seq, msg_id = struct.unpack(">BBHHBB", data[:8])
                self._expected_length = length
                self._raw_buffer.extend(data[8:])
            else:
                self._raw_buffer.extend(data)

            if len(self._raw_buffer) >= self._expected_length:
                decoded_packet = cbor2.loads(self._raw_buffer)
                if "o" in decoded_packet:
                    self.received_text_chunks.append(decoded_packet["o"])
                self.response_completed_event.set()
        except Exception:
            self.response_completed_event.set()

    async def execute_shell_command(self, cmd_string, timeout=4.0):
        """Encapsulates a string command into an MCUmgr Group 9 (Shell) packet."""
        self._raw_buffer = bytearray()
        self._expected_length = 0
        self.received_text_chunks = []
        self.response_completed_event.clear()

        await self.client.start_notify(SMP_CHAR_UUID, self.notification_handler)

        argv_list = cmd_string.split()
        cbor_payload = cbor2.dumps({"argv": argv_list})
        payload_length = len(cbor_payload)
        seq_token = random.randint(1, 250)

        smp_header = struct.pack(">BBHHBB", 2, 0, payload_length, 9, seq_token, 0)
        full_packet = smp_header + cbor_payload

        await self.client.write_gatt_char(SMP_CHAR_UUID, full_packet, response=False)

        try:
            await asyncio.wait_for(self.response_completed_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            print(f"  [!] Command '{cmd_string}' timed out waiting for response.")
        finally:
            await self.client.stop_notify(SMP_CHAR_UUID)

        return "".join(self.received_text_chunks)


async def run_bluetooth_diagnostics(device_mac_or_uuid=None):
    target_address = device_mac_or_uuid if device_mac_or_uuid else DEVICE_ADDRESS
    print(f"\n🌐 [BLE Link] Connecting to Zephyr hardware over Bluetooth: {target_address}")
    
    try:
        async with BleakClient(target_address, timeout=10.0) as client:
            if not client.is_connected:
                print(" ❌ BLE Connection failed.")
                return False
                
            print(" [✓] Connected wirelessly! Syncing device attribute tables...")
            _ = client.services  # Cache services
            shell = MCUmgrShellClient(client)

            # =========================================================================
            # TASK 1: Check Power Configuration via dtc status
            # =========================================================================
            #print(" 🔍 Querying power rail constraints via Bluetooth Shell...")
            print("\n" + "="*45)
            print("         --- DTC Information ---       ")
            print("="*45)
            console_output = await shell.execute_shell_command("app version")
            print("\n --- Firmware ---")
            print(console_output.strip() if console_output else "[Empty Response]")
            print("\n")
            
            console_output = await shell.execute_shell_command("dtc status")

            print(console_output.strip() if console_output else "[Empty Response]")
            print("-----------------------------------------")

            expected_sensors = 0
            # --- FIX: Match your specific "DS18B20: X / 125" layout ---
            sensor_count_match = re.search(r'DS18B20:\s*(\d+)', console_output, re.IGNORECASE)
            
            if sensor_count_match:
                expected_sensors = int(sensor_count_match.group(1))
                print(f" [✓] Detected {expected_sensors} expected sensors from status.")
            else:
                print(" ⚠️ Warning: Could not parse expected sensor count from status text.")

            external_powered = True
            if console_output and "Parasitic" in console_output:
                print(" ⚠️ POWER WARNING: Running on Parasitic Draw (External 5V Line is BROKEN!)")
                external_powered = False
            elif console_output and ("External 5V" in console_output or "Normal" in console_output):
                print(" [✓] POWER VERIFICATION: Device is running safely on EXTERNAL 5V power.")
            else:
                print(" ⚠️ POWER WARNING: Could not parse power state from text response.")

            await asyncio.sleep(1.0)

            # =========================================================================
            # TASK 2: Automated Temp Array Validation
            # =========================================================================
            temps_output = await shell.execute_shell_command("dtc temps")
            print("\n" + "="*45)
            print("         --- DTC Temps ---       ")
            print("="*45)
            
            print(temps_output.strip() if temps_output else "[Empty Response]")
            print("------------------------------------")

            # Extract all numeric float readings from the output string
            # Uses a strict match to capture decimal structures like "24.78"
            parsed_floats = [float(val) for val in re.findall(r'temp:\s*([+-]?\d+\.\d+)', temps_output, re.IGNORECASE)]
            
            # Fallback filter if "temp: " isn't a direct prefix in all firmware variations
            if not parsed_floats:
                parsed_floats = [float(val) for val in re.findall(r'([+-]?\d+\.\d+)', temps_output)]

            # Filter out known hardware error indicators (85.0 and 99.0)
            valid_temps = [t for t in parsed_floats if t != 85.0 and t != 99.0]
            invalid_temps_count = len(parsed_floats) - len(valid_temps)

            if invalid_temps_count > 0:
                print(f" ├── Total temps: {len(parsed_floats)}")
                print(f" ├── ⚠️ Faulty sensors filtered out (85°C / 99°C errors): {invalid_temps_count}")
                print(f" └── Operational sensor count: {len(valid_temps)}")
            else: 
                print(f" └── Total temps: {len(parsed_floats)}")

            # Assert verification check against the topology layout
            temp_validation_success = True
            if expected_sensors > 0:
                if len(valid_temps) != expected_sensors:
                    print(f" ❌ Number of sensors: ({len(valid_temps)}) does not match expected ({expected_sensors}).")
                    temp_validation_success = False
                    
            else:
                if len(valid_temps) > 0:
                    print(f" ⚠️ Verified loosely (Captured {len(valid_temps)} data values, but expected count was missing).")
                else:
                    print(" ❌ VALIDATION FAILED: No data points captured.")
                    temp_validation_success = False

            await asyncio.sleep(1.0)

            # =========================================================================
            # TASK 3: Trigger Physical LED Test Sequence & Verify Colors
            # =========================================================================
            loop = asyncio.get_running_loop()
            #print("\n[Prompt] Next stage will trigger the physical LED test pattern.")
            
            while True:
                confirm = await loop.run_in_executor(
                    None, input, "Are you ready to run the led_test? (y/n): "
                )
                confirm = confirm.strip().lower()
                if confirm in ['y', 'yes', 'n', 'no']:
                    break
                print("[!] Invalid input. Please type 'y' or 'n'.")

            if confirm in ['y', 'yes']:
                led_output = await shell.execute_shell_command("led_test")
                if led_output:
                    print(f"{led_output.strip()}")
                
                #print(" [!] Execution command sent. Pausing 3 seconds for hardware color cycling...")
                await asyncio.sleep(3.25)
                
                while True:
                    colors_ok = await loop.run_in_executor(
                        None, input, "Did all colors (red, blue, green, white) display correctly? (y/n): "
                    )
                    colors_ok = colors_ok.strip().lower()
                    if colors_ok in ['y', 'yes', 'n', 'no']:
                        break
                    print("[!] Invalid input. Please type 'y' or 'n'.")

                if colors_ok in ['y', 'yes']:
                    print(" [✓] LED VISUAL CHECK: Passed.")
                    led_test_success = True
                else:
                    print(" ❌ LED VISUAL CHECK: Failed. Hardware component failure suspected.")
                    led_test_success = False
            else:
                print("[BLE Action] Skipping LED hardware test at user request.")
                led_test_success = False

            if(not temp_validation_success or not led_test_success or not external_powered):
                if(not temp_validation_success):
                    print(" ❌ Bluetooth Diagnostic Result: Temperature validation failed.")
                if(not led_test_success):
                    print(" ❌ Bluetooth Diagnostic Result: LED test failed.")
                if(not external_powered):
                    print(" ❌ Bluetooth Diagnostic Result: External power check failed.")
                return False
            else:
                print(" [✓] Bluetooth Diagnostic Result: All tests passed successfully.")
                return True
                

    except Exception as e:
        print(f" ❌ Bluetooth Diagnostic Error: {e}")
        return False



